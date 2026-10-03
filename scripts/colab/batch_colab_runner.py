"""Script điều phối tự động (Batch Orchestrator) đưa danh sách kịch bản qua Colab GPU pipeline,
tải bundle về máy local, tự động trích xuất Báo cáo đánh giá (Scorecard & Evaluation Report)
và import vào Studio local để phục vụ demo.

Tương thích với bộ dữ liệu chuẩn hóa `/media/usb/AI20K/TorWIC_Raw_Scenes`.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _transfer(command: list[str]) -> None:
    """Retry thao tác ghi cùng file khi kết nối Colab bị ngắt; không retry tạo job."""
    for attempt in range(1, 5):
        try:
            result = subprocess.run(command, check=True, timeout=600, capture_output=True, text=True)
            print(_redact(result.stdout), end="", flush=True)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 4:
                raise
            print(f"    Kết nối lỗi; thử lại transfer ({attempt}/4)...", flush=True)
            time.sleep(5)


def _redact(text: str) -> str:
    """CLI lỗi HTTP có thể in proxy token trong URL; bỏ token trước khi ghi log."""
    return re.sub(r"(colab-runtime-proxy-token=)[^&\s]+", r"\1[REDACTED]", text)


def _remote_idempotent(session: str, code: str, marker: str) -> str:
    """Xác nhận kết quả remote bằng marker, kể cả khi CLI không truyền exit code."""
    for attempt in range(1, 5):
        try:
            result = subprocess.run(
                ["colab", "exec", "-s", session, "--timeout", "90"],
                input=code,
                text=True,
                capture_output=True,
                timeout=180,
            )
            if result.returncode == 0 and any(line.startswith(marker) for line in result.stdout.splitlines()):
                return result.stdout
            detail = _redact(result.stdout + result.stderr)[-1000:]
        except subprocess.TimeoutExpired:
            detail = "CLI timeout; thao tác idempotent có thể đã chạy trên VM"
        if attempt == 4:
            raise RuntimeError(f"Colab chưa xác nhận {marker}: {detail}")
        print(f"    Chưa nhận xác nhận remote; thử lại ({attempt}/4)...", flush=True)
        time.sleep(5)
    raise RuntimeError("Không nhận được xác nhận remote")


def _run_detached(session: str, code: str, remote_video: str, job_name: str, log_path: Path) -> str:
    """Resume cùng process remote; polling mất kết nối không tạo lại job."""
    state = f"/content/p087-batch/{code}"
    command = (
        "cd /content/app && set -a && source /content/r2s/colab.env && set +a && "
        ".venv/bin/python -u -m scripts.kaggle.run_job "
        f"--video {shlex.quote(remote_video)} --name {shlex.quote(job_name)} "
        "--attestation /content/app/scripts/colab/attestation.json --auto-confirm-proposal "
        f"--out {shlex.quote('/content/bundles/' + code)} --port 8000; "
        f"result=$?; printf '%s' \"$result\" > {shlex.quote(state + '/exit-code')}"
    )
    launch = f"""
import subprocess
from pathlib import Path
state = Path({state!r})
state.mkdir(parents=True, exist_ok=True)
if not (state / 'pid').exists():
    with (state / 'run.log').open('w') as log:
        proc = subprocess.Popen(['bash', '-lc', {command!r}], stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    (state / 'pid').write_text(str(proc.pid))
print('BATCH_LAUNCH_OK')
"""
    _remote_idempotent(session, launch, "BATCH_LAUNCH_OK")
    snapshot = f"""
import json, os
from pathlib import Path
state = Path({state!r})
pid = int((state / 'pid').read_text())
alive = Path(f'/proc/{{pid}}').exists()
exit_code = int((state / 'exit-code').read_text()) if (state / 'exit-code').exists() else None
print('BATCH_SNAPSHOT ' + json.dumps(dict(alive=alive, exit_code=exit_code, log=(state / 'run.log').read_text())))
"""
    previous = ""
    while True:
        output = _remote_idempotent(session, snapshot, "BATCH_SNAPSHOT ")
        row = next(line for line in output.splitlines() if line.startswith("BATCH_SNAPSHOT "))
        progress = json.loads(row.removeprefix("BATCH_SNAPSHOT "))
        text = progress["log"]
        log_path.write_text(text, encoding="utf-8")
        if text != previous:
            print(text[len(previous) :] if text.startswith(previous) else text, flush=True)
            previous = text
        if progress["exit_code"] is not None:
            return text + f"\nP087_REMOTE_EXIT={progress['exit_code']}\n"
        if not progress["alive"]:
            raise RuntimeError(f"Process {code} đã mất, chưa có exit-code; giữ artifact để recovery")
        time.sleep(30)


def upload_to_colab(
    session: str,
    local_path: Path,
    remote_path: str,
    chunk_size_mb: int = 5,
    *,
    skip_parts: int = 0,
    preparing_pid: int | None = None,
) -> None:
    """Chia nhỏ input, retry kết nối và kiểm SHA-256 trước khi dùng file remote."""
    size_mb = local_path.stat().st_size / (1024 * 1024)
    with local_path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    probe = f"""
import hashlib, shutil
from pathlib import Path
target = Path({remote_path!r})
valid = False
if target.is_file():
    with target.open('rb') as source:
        valid = hashlib.file_digest(source, 'sha256').hexdigest() == {digest!r}
if not valid:
    for candidate in Path('/content').glob('SC-*_' + {local_path.name!r}):
        if candidate == target or candidate.stat().st_size != {local_path.stat().st_size}:
            continue
        with candidate.open('rb') as source:
            matches = hashlib.file_digest(source, 'sha256').hexdigest() == {digest!r}
        if matches:
            shutil.copyfile(candidate, target)
            valid = True
            break
print('INPUT_PROBE_MATCH' if valid else 'INPUT_PROBE_MISSING')
"""
    while True:
        if "INPUT_PROBE_MATCH" in _remote_idempotent(session, probe, "INPUT_PROBE_").splitlines():
            print("    Input remote đã khớp SHA-256; dùng lại file.", flush=True)
            return
        if preparing_pid is None:
            break
        try:
            os.kill(preparing_pid, 0)
        except ProcessLookupError:
            break
        print("    Đang chờ process chuẩn bị input; chưa upload trùng file.", flush=True)
        time.sleep(30)
    if size_mb <= chunk_size_mb:
        _transfer(["colab", "upload", "-s", session, str(local_path), remote_path])
        return

    print(f"    (File {size_mb:.1f} MB > {chunk_size_mb} MB: tự động upload theo phân đoạn {chunk_size_mb}MB)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_prefix = Path(tmpdir) / "chunk_"
        subprocess.run(["split", "-b", f"{chunk_size_mb}M", str(local_path), str(tmp_prefix)], check=True)
        parts = sorted(Path(tmpdir).glob("chunk_*"))
        remote_tmp_dir = f"/content/_tmp_upload_{Path(remote_path).stem}"
        if skip_parts == 0:
            mkdir_script = (
                f"from pathlib import Path; Path({remote_tmp_dir!r}).mkdir(parents=True, exist_ok=True); "
                "print('UPLOAD_DIRECTORY_OK')"
            )
            _remote_idempotent(session, mkdir_script, "UPLOAD_DIRECTORY_OK")

        for p_idx, part in enumerate(parts, start=1):
            if p_idx <= skip_parts:
                continue
            print(f"      [part {p_idx}/{len(parts)}] -> {part.name}...")
            remote_part = f"{remote_tmp_dir}/{part.name}"
            _transfer(["colab", "upload", "-s", session, str(part), remote_part])

        # Chỉ bỏ phần tạm sau khi file ghép khớp checksum của toàn bộ input.
        cat_script = f"""
import hashlib, shutil
from pathlib import Path
parts = [Path({remote_tmp_dir!r}) / name for name in {[part.name for part in parts]!r}]
target = Path({remote_path!r})
valid = False
if target.is_file():
    with target.open('rb') as source:
        valid = hashlib.file_digest(source, 'sha256').hexdigest() == {digest!r}
if not valid:
    with target.open('wb') as output:
        for part in parts:
            with part.open('rb') as source:
                shutil.copyfileobj(source, output)
with open({remote_path!r}, 'rb') as source:
    assert hashlib.file_digest(source, 'sha256').hexdigest() == {digest!r}, 'Input checksum mismatch'
if Path({remote_tmp_dir!r}).exists():
    shutil.rmtree({remote_tmp_dir!r})
print('UPLOAD_CHECKSUM_OK')
"""
        _remote_idempotent(session, cat_script, "UPLOAD_CHECKSUM_OK")
    print(f"    -> Đã tải lên và hợp nhất thành công: {remote_path}")


def _download_bundle(session: str, remote_bundle: str, out_dir: Path) -> Path:
    """Tải archive theo phần có checksum; giữ phần đã tải để resume khi đứt mạng."""
    bundle_name = Path(remote_bundle).name
    transfer_dir = f"/content/transfers/{bundle_name}"
    pack = f"""
import hashlib, json, tarfile
from pathlib import Path
root = Path({transfer_dir!r})
root.mkdir(parents=True, exist_ok=True)
manifest = root / 'transfer.json'
if not manifest.exists():
    archive = root / 'bundle.tar.gz'
    with tarfile.open(archive, 'w:gz', compresslevel=1) as tar:
        tar.add({remote_bundle!r}, arcname={bundle_name!r})
    parts = []
    with archive.open('rb') as source:
        while block := source.read(5 * 1024 * 1024):
            name = f'part-{{len(parts):05d}}'
            (root / name).write_bytes(block)
            parts.append(dict(name=name, sha256=hashlib.sha256(block).hexdigest(), size=len(block)))
    with archive.open('rb') as source:
        checksum = hashlib.file_digest(source, 'sha256').hexdigest()
    manifest.write_text(json.dumps(dict(parts=parts, sha256=checksum)))
print('BUNDLE_TRANSFER ' + manifest.read_text())
"""
    output = _remote_idempotent(session, pack, "BUNDLE_TRANSFER ")
    row = next(line for line in output.splitlines() if line.startswith("BUNDLE_TRANSFER "))
    manifest = json.loads(row.removeprefix("BUNDLE_TRANSFER "))
    local_parts = out_dir / f"{bundle_name}.transfer"
    local_parts.mkdir(parents=True, exist_ok=True)
    (local_parts / "transfer.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    paths: list[Path] = []
    for idx, item in enumerate(manifest["parts"], start=1):
        name = item["name"]
        if Path(name).name != name or not name.startswith("part-"):
            raise RuntimeError("Tên transfer part không hợp lệ")
        path = local_parts / name
        valid = False
        if path.is_file():
            with path.open("rb") as source:
                valid = hashlib.file_digest(source, "sha256").hexdigest() == item["sha256"]
        if not valid:
            print(f"    Download part {idx}/{len(manifest['parts'])}", flush=True)
            _transfer(["colab", "download", "-s", session, f"{transfer_dir}/{name}", str(path)])
        with path.open("rb") as source:
            if (
                path.stat().st_size != item["size"]
                or hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]
            ):
                raise RuntimeError(f"Transfer part sai checksum: {name}")
        paths.append(path)
    archive = local_parts / "bundle.tar.gz"
    with archive.open("wb") as target:
        for path in paths:
            with path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    target.write(block)
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != manifest["sha256"]:
            raise RuntimeError("Bundle archive sai checksum")
    from scripts.kaggle.job_bundle import load_bundle

    staging = local_parts / "extracted"
    staging.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        if any(Path(member.name).parts[0] != bundle_name for member in tar.getmembers()):
            raise RuntimeError("Archive chứa file ngoài bundle được yêu cầu")
        tar.extractall(staging, filter="data")
    incoming = staging / bundle_name
    incoming_manifest = load_bundle(incoming)
    destination = out_dir / bundle_name
    if destination.exists():
        if load_bundle(destination) != incoming_manifest:
            raise RuntimeError("Bundle local đã tồn tại với nội dung khác; không ghi đè")
    else:
        incoming.rename(destination)
    return destination


def _capture_runtime(session: str, out_dir: Path) -> Path:
    """Giữ runtime manifest thật của Colab để demo export không gán GPU local."""
    from src.models.contracts.identity import verify_content_checksum
    from src.models.contracts.manifests import RuntimeManifest

    temporary = out_dir / "colab-runtime-download.json"
    _transfer(["colab", "download", "-s", session, "/content/r2s/runtime_manifest.json", str(temporary)])
    manifest = RuntimeManifest.model_validate_json(temporary.read_bytes())
    verify_content_checksum(manifest, "runtime_manifest_checksum")
    checksum = manifest.runtime_manifest_checksum.removeprefix("sha256:")
    destination = out_dir / f"runtime-{checksum}.json"
    if not destination.exists():
        temporary.rename(destination)
    else:
        previous = RuntimeManifest.model_validate_json(destination.read_bytes())
        verify_content_checksum(previous, "runtime_manifest_checksum")
        if previous != manifest:
            raise RuntimeError("Runtime manifest local khác nội dung, không ghi đè")
    return destination


def _capture_logs(session: str, code: str, job_id: str, out_dir: Path) -> None:
    """Thu log API/worker và process log còn tồn tại, kể cả job FAILED."""
    snapshot = f"""
import hashlib, json
from pathlib import Path
paths = list(Path({f"/content/bundles/{code}/logs"!r}).glob('*.log'))
paths += list(Path({f"/content/r2s/workers/{job_id}"!r}).rglob('*.log'))
rows = []
for path in paths:
    with path.open('rb') as source:
        checksum = hashlib.file_digest(source, 'sha256').hexdigest()
    rows.append(dict(path=str(path), relative=str(path.relative_to('/content')), sha256=checksum))
print('DIAGNOSTIC_LOGS ' + json.dumps(rows))
"""
    output = _remote_idempotent(session, snapshot, "DIAGNOSTIC_LOGS ")
    row = next(line for line in output.splitlines() if line.startswith("DIAGNOSTIC_LOGS "))
    logs = json.loads(row.removeprefix("DIAGNOSTIC_LOGS "))
    destination = out_dir / f"{code}-diagnostics"
    destination.mkdir(exist_ok=True)
    for item in logs:
        relative = Path(item["relative"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Diagnostic log path không hợp lệ")
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _transfer(["colab", "download", "-s", session, item["path"], str(path)])
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                raise RuntimeError("Diagnostic log thay đổi sau snapshot; chưa thu log ổn định")
    (destination / "logs.json").write_text(json.dumps(logs, indent=2), encoding="utf-8")


def _collect_scenario(
    args: argparse.Namespace,
    code: str,
    folder: str,
    job_name: str,
    desc: str,
    remote_output: str,
    runtime_path: Path,
) -> bool:
    """Thu artifact/report trong một worker local; không chiếm lượt chạy GPU kế tiếp."""
    incomplete: list[str] = []
    remote_failed = "P087_REMOTE_EXIT=0" not in remote_output.splitlines()
    if remote_failed:
        incomplete.append(code)
        print(f"[!] {code} chưa thành công; vẫn thu hồi bundle chẩn đoán.")

    bundle_lines = [
        line.removeprefix("gói: ").strip() for line in remote_output.splitlines() if line.startswith("gói: ")
    ]
    remote_bundle_path = bundle_lines[-1] if bundle_lines else ""
    if not remote_bundle_path:
        match = re.search(r"^job: (job-[a-zA-Z0-9_-]+) ←", remote_output, re.MULTILINE)
        if match:
            job_id = match.group(1)
            recovery_root = f"/content/bundles/{code}/recovery"
            export_command = (
                "cd /content/app && set -a && source /content/r2s/colab.env && set +a && "
                f".venv/bin/python -m scripts.kaggle.job_bundle export {shlex.quote(job_id)} "
                f"--out {shlex.quote(recovery_root)}"
            )
            recovery = f"""
import subprocess
from pathlib import Path
bundle = Path({recovery_root!r}) / {job_id!r}
if not (bundle / 'bundle.json').is_file():
    subprocess.run(['bash', '-lc', {export_command!r}], check=True)
print('RECOVERY_BUNDLE ' + str(bundle))
"""
            recovered = _remote_idempotent(args.session, recovery, "RECOVERY_BUNDLE ")
            remote_bundle_path = next(
                line.removeprefix("RECOVERY_BUNDLE ")
                for line in recovered.splitlines()
                if line.startswith("RECOVERY_BUNDLE ")
            )
    print(f"-> Remote bundle: {remote_bundle_path}")

    if not remote_bundle_path or not remote_bundle_path.startswith("/content/bundles"):
        print("[!] Không tìm thấy bundle path từ Colab output", file=sys.stderr)
        incomplete.append(code)
        return False

    bundle_name = Path(remote_bundle_path).name
    _capture_logs(args.session, code, bundle_name, args.out_dir)
    print(f"-> Đang nén và tải bundle về local {args.out_dir / bundle_name}...")
    local_bundle_dest = _download_bundle(args.session, remote_bundle_path, args.out_dir)

    print("-> Đang import bundle vào Studio local...")
    import_cmd = [".venv/bin/python", "-m", "scripts.kaggle.job_bundle", "import", str(local_bundle_dest)]
    import_proc = subprocess.run(import_cmd, capture_output=True, text=True)
    print(import_proc.stdout)
    if import_proc.returncode != 0:
        print(f"[!] Import bundle thất bại: {import_proc.stderr}", file=sys.stderr)
        incomplete.append(code)
        return False

    # Tự động xuất Báo cáo đánh giá (Scorecard & Evaluation Report)
    print("-> Đang trích xuất Báo cáo Đánh giá (Scorecard & Evaluation Report)...")
    eval_script = f"""
from src.services.orchestration.projects.registry import get_project_registry
from src.services.orchestration.evaluation import evaluate_job, evaluation_markdown
from pathlib import Path
import json

registry = get_project_registry()
eval_res = evaluate_job(registry, "{bundle_name}")
print(f"P087_JOB_STATUS={{eval_res.job_status}}")
job = registry.get_job("{bundle_name}")
runtime = json.loads(Path({str(runtime_path)!r}).read_text())
print('P087_JOB_RUNTIME_OK' if job.runtime_manifest_checksum == runtime['runtime_manifest_checksum'] else 'P087_JOB_RUNTIME_MISMATCH')
json_path = Path("{local_bundle_dest}/evaluation.json")
md_path = Path("{local_bundle_dest}/evaluation-report.md")
json_path.write_text(eval_res.model_dump_json(indent=2), encoding="utf-8")
md_path.write_text(evaluation_markdown(eval_res), encoding="utf-8")
print(f"[v] Đã lưu {{json_path.name}} và {{md_path.name}} tại {{json_path.parent}}")
"""
    eval_proc = subprocess.run([".venv/bin/python", "-c", eval_script], capture_output=True, text=True)
    print(eval_proc.stdout)
    if eval_proc.returncode != 0:
        print(f"[!] Trích xuất đánh giá: {eval_proc.stderr}", file=sys.stderr)
        incomplete.append(code)
        return False

    if "P087_JOB_STATUS=SUCCEEDED" not in eval_proc.stdout.splitlines():
        incomplete.append(code)
        print(f"[!] {code}: trạng thái job chưa SUCCEEDED; report giữ nguyên các bước pending/failed.")

    if remote_failed:
        print(f"-> {code}: bundle chẩn đoán và report đã lưu; pipeline chưa hoàn tất.")
        return False
    if "P087_JOB_RUNTIME_OK" not in eval_proc.stdout.splitlines():
        incomplete.append(code)
        print(f"[!] {code}: runtime checksum khác manifest Colab hiện tại; không export demo sai máy.")
        return False
    demo_proc = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "scripts.demo.export_demo_bundle",
            "--demo-id",
            code.lower(),
            "--title",
            job_name,
            "--description",
            desc,
            "--sequence",
            folder,
            "--out",
            str(args.demo_library_dir / code.lower()),
            "job",
            "--job-id",
            bundle_name,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PRODUCT_RUNTIME_MANIFEST": str(runtime_path.resolve())},
    )
    if demo_proc.returncode != 0:
        print(f"[!] Demo export chưa hoàn tất: {demo_proc.stderr}", file=sys.stderr)
        incomplete.append(code)
        return False
    print(demo_proc.stdout)
    print(f"-> {code}: đã lưu/import bundle, report và demo; xem trạng thái job thật trong manifest.")

    return not incomplete


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy kịch bản video trên Colab GPU và import bundle về máy local.")
    parser.add_argument(
        "--scenes-dir",
        type=Path,
        default=Path("/media/usb/AI20K/TorWIC_Raw_Scenes"),
        help="Thư mục chứa các kịch bản chuẩn hóa",
    )
    parser.add_argument("--session", default="p087-rec", help="Tên session Colab")
    parser.add_argument("--out-dir", type=Path, default=Path("data/colab_bundles"), help="Thư mục lưu bundles ở local")
    parser.add_argument(
        "--demo-library-dir",
        type=Path,
        default=Path("data/demo/library"),
        help="Thư mục demo library của Studio",
    )
    parser.add_argument("--scenario", type=str, help="Chỉ chạy một mã kịch bản cụ thể (ví dụ: SC-01, SC-02)")
    parser.add_argument(
        "--preparing-pid", type=int, help="Chờ process đang upload trước input; không truyền PID remote"
    )
    parser.add_argument(
        "--video-only-experiments",
        action="store_true",
        help="Thử mọi video qua pipeline camera đơn; không claim LiDAR/stereo support",
    )
    parser.add_argument("--start-at", help="Resume từ mã scenario trong manifest, giữ kết quả các lượt trước")
    args = parser.parse_args()
    if args.scenario and args.start_at:
        parser.error("--scenario và --start-at không dùng cùng nhau")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.demo_library_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = args.scenes_dir / "manifest.json"
    if not manifest_file.exists():
        print(f"[!] Không tìm thấy manifest tại {manifest_file}", file=sys.stderr)
        return 1

    with open(manifest_file, encoding="utf-8") as f:
        meta = json.load(f)

    scenarios = meta.get("scenarios", [])
    if args.scenario:
        scenarios = [s for s in scenarios if s.get("code") == args.scenario]
        if not scenarios:
            print(f"[!] Không tìm thấy kịch bản {args.scenario} trong manifest", file=sys.stderr)
            return 1

    if args.start_at:
        indexes = [i for i, scene in enumerate(scenarios) if scene.get("code") == args.start_at]
        if not indexes:
            parser.error("--start-at không tồn tại trong manifest")
        scenarios = scenarios[indexes[0] :]

    print(f"=== Chuẩn bị xử lý {len(scenarios)} kịch bản qua Colab GPU session '{args.session}' ===")
    runtime_path = _capture_runtime(args.session, args.out_dir)
    incomplete: list[str] = []
    collections = []
    with ThreadPoolExecutor(max_workers=1) as collector:
        for idx, sc in enumerate(scenarios, start=1):
            code = sc.get("code", f"SC-{idx:02d}")
            folder = sc["folder"]
            video_filename = sc["video"]
            video_path = args.scenes_dir / folder / video_filename
            desc = sc.get("description", "")
            experimental = sc.get("sensor") != "Chỉ Video"
            if experimental and not args.video_only_experiments:
                print(f"[!] {code}: chưa có adapter LiDAR/stereo trong runner; giữ kịch bản pending.")
                incomplete.append(code)
                continue
            execution_note = "Input thực tế: video qua pipeline camera đơn."
            if experimental:
                execution_note += " LiDAR không được attach; stereo ghép không phải reconstruction hai camera."
                print(f"[EXPERIMENT] {code}: {execution_note}")
                desc = f"{execution_note} Mục đích dự kiến: {desc}"
            (args.out_dir / f"{code}-execution.json").write_text(
                json.dumps(
                    {
                        "scenario": code,
                        "requested_sensor": sc.get("sensor"),
                        "actual_inputs": ["video"],
                        "camera_pipeline": "single_camera",
                        "experimental": experimental,
                        "note": execution_note,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            if not video_path.exists():
                print(f"[!] Không tìm thấy video tại {video_path}", file=sys.stderr)
                incomplete.append(code)
                continue

            print(
                f"\n[{idx}/{len(scenarios)}] [{code}] Bắt đầu: {folder}/{video_filename} ({video_path.stat().st_size / 1e6:.1f} MB)"
            )
            print(f"    Mục đích: {desc}")

            remote_video = f"/content/{code}_{video_filename}"
            print(f"-> Đang tải video lên Colab: {remote_video}...")
            upload_to_colab(
                args.session,
                video_path,
                remote_video,
                preparing_pid=None if experimental else args.preparing_pid,
            )

            job_name = f"{code} · {folder}"
            print(f"-> Khởi chạy pipeline trên Colab (job: '{job_name}')...")
            remote_output = _run_detached(
                args.session,
                code,
                remote_video,
                job_name,
                args.out_dir / f"{code}-remote.log",
            )
            collections.append(
                (
                    code,
                    collector.submit(
                        _collect_scenario, args, code, folder, job_name, desc, remote_output, runtime_path
                    ),
                )
            )
            print(f"-> {code}: đang thu artifact; tiếp tục lượt xử lý kế tiếp.", flush=True)

        for code, future in collections:
            try:
                if not future.result():
                    incomplete.append(code)
            except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
                incomplete.append(code)
                print(f"[!] Thu artifact {code} chưa hoàn tất: {_redact(str(error))}", file=sys.stderr)

    print(f"\n=== Batch kết thúc; còn pending/failed: {', '.join(dict.fromkeys(incomplete)) or 'không'} ===")
    return 1 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
