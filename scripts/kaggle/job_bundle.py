"""Gói một job (bản ghi DB + artifact) để chuyển giữa các máy, lưu trên Hugging Face dataset repo.

Dùng cho đường chạy Kaggle/GPU thuê "chỉ để lấy artifact": máy GPU chạy pipeline rồi `export` + `push`;
máy có Studio `pull` + `import` để xem/sửa scene và xuất USD. Gói mang đúng trạng thái job tại lúc xuất
(kể cả job đang chờ xác nhận hệ mét), nên cũng dùng để chuyển job từ máy này sang máy khác chạy tiếp.

    python -m scripts.kaggle.job_bundle export job-abc --out /tmp/bundles
    python -m scripts.kaggle.job_bundle push   /tmp/bundles/job-abc --repo <user>/real2sim-artifacts
    python -m scripts.kaggle.job_bundle pull   job-abc --repo <user>/real2sim-artifacts --out /tmp/bundles
    python -m scripts.kaggle.job_bundle import /tmp/bundles/job-abc

Cấu hình (DATABASE_URL, ARTIFACT_ROOT) lấy từ `Settings` như stack; token Hugging Face lấy từ biến môi
trường `HF_TOKEN` (hoặc `hf auth login`), không truyền qua tham số. Sau `import` phải khởi động lại
API/worker đang chạy vì registry giữ trạng thái trong bộ nhớ.

Bố cục gói: `<job_id>/bundle.json` + `<job_id>/artifacts/jobs/<id>/...` (job, project, upload). Artifact
giữ nguyên URI `artifact://jobs/...` nên không phải sửa nội dung khi chuyển máy.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.jobs.database import RuntimeDatabase

BUNDLE_SCHEMA = "1.0"
_MANIFEST = "bundle.json"
_CHUNK = 1 << 20


class BundleError(RuntimeError):
    """Gói hỏng hoặc không nạp được vào máy này; message hiển thị được cho người chạy lệnh."""


class BundleFile(BaseModel):
    """Một file artifact trong gói (đường dẫn tương đối tính từ thư mục `artifacts/`)."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int
    sha256: str


class JobBundle(BaseModel):
    """Nội dung `bundle.json`: các dòng DB của job và danh sách file kèm checksum."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = BUNDLE_SCHEMA
    job_id: str
    project_id: str
    job_version: int
    manifest_ref: str
    project_payload: str
    #: `version → payload` của `r2s_job_events`, đủ từ đầu tới `job_version`.
    events: dict[int, str]
    #: `upload_id → payload` của các upload thuộc project.
    uploads: dict[str, str]
    files: list[BundleFile]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _place(source: Path, target: Path) -> None:
    """Hardlink khi cùng ổ đĩa (không tốn thêm chỗ), khác ổ thì copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _rows(database: RuntimeDatabase, job_id: str) -> tuple[str, int, str, str, dict[int, str], dict[str, str]]:
    with database.transaction() as tx:
        job = tx.execute("SELECT project_id, version, manifest_ref FROM r2s_jobs WHERE job_id=?", (job_id,)).fetchone()
        if job is None:
            raise BundleError(f"Không có job {job_id} trong DB runtime")
        project_id, version, manifest_ref = str(job[0]), int(job[1]), str(job[2])
        project = tx.execute("SELECT payload FROM r2s_projects WHERE project_id=?", (project_id,)).fetchone()
        if project is None:
            raise BundleError(f"Job {job_id} trỏ tới project {project_id} không tồn tại")
        events = {
            int(row[0]): str(row[1])
            for row in tx.execute(
                "SELECT version, payload FROM r2s_job_events WHERE job_id=? ORDER BY version", (job_id,)
            ).fetchall()
        }
        uploads = {}
        for row in tx.execute("SELECT upload_id, payload FROM r2s_uploads").fetchall():
            if project_id in (json.loads(row[1]).get("project_ids") or []):
                uploads[str(row[0])] = str(row[1])
    return project_id, version, manifest_ref, str(project[0]), events, uploads


def export_bundle(database: RuntimeDatabase, jobs_root: Path, job_id: str, out: Path) -> Path:
    """Xuất job thành thư mục `<out>/<job_id>`; `jobs_root` là thư mục chứa `job-*`, `project-*`, `upload-*`.

    Không ghi đè gói đã có: xuất lại cùng job sau khi nó chạy tiếp thì dùng thư mục `out` khác hoặc xoá gói cũ.
    """
    project_id, version, manifest_ref, project_payload, events, uploads = _rows(database, job_id)
    target = out / job_id
    if target.exists():
        raise BundleError(f"Đã có gói tại {target}; xoá hoặc chọn thư mục --out khác")
    files: list[BundleFile] = []
    for owner in (job_id, project_id, *sorted(uploads)):
        source_dir = jobs_root / owner
        if not source_dir.is_dir():
            raise BundleError(f"Thiếu thư mục artifact {source_dir}")
        for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = Path("jobs") / owner / source.relative_to(source_dir)
            _place(source, target / "artifacts" / relative)
            files.append(BundleFile(path=relative.as_posix(), size_bytes=source.stat().st_size, sha256=_sha256(source)))
    bundle = JobBundle(
        job_id=job_id,
        project_id=project_id,
        job_version=version,
        manifest_ref=manifest_ref,
        project_payload=project_payload,
        events=events,
        uploads=uploads,
        files=files,
    )
    (target / _MANIFEST).write_text(bundle.model_dump_json(indent=1), encoding="utf-8")
    return target


def load_bundle(source: Path) -> JobBundle:
    """Đọc `bundle.json` và kiểm đủ file, đúng checksum trước khi đụng tới DB/artifact của máy này."""
    manifest = source / _MANIFEST
    if not manifest.is_file():
        raise BundleError(f"{source} không phải gói job (thiếu {_MANIFEST})")
    bundle = JobBundle.model_validate_json(manifest.read_text(encoding="utf-8"))
    if bundle.schema_version != BUNDLE_SCHEMA:
        raise BundleError(f"Gói schema {bundle.schema_version}, lệnh này đọc {BUNDLE_SCHEMA}")
    for item in bundle.files:
        if ".." in Path(item.path).parts or Path(item.path).is_absolute():
            raise BundleError(f"Đường dẫn không hợp lệ trong gói: {item.path}")
        path = source / "artifacts" / item.path
        if not path.is_file() or path.stat().st_size != item.size_bytes or _sha256(path) != item.sha256:
            raise BundleError(f"File trong gói thiếu hoặc sai checksum: {item.path}")
    return bundle


def _copy_artifacts(bundle: JobBundle, source: Path, jobs_root: Path) -> int:
    """Chép file còn thiếu; file đã có phải trùng checksum (artifact bất biến theo nội dung)."""
    copied = 0
    for item in bundle.files:
        target = jobs_root.parent / item.path
        if target.is_file():
            # JobManifest/scene revision là file mới mỗi lần đổi nên file trùng tên mà khác nội dung nghĩa
            # là hai máy đã chạy job này theo hai hướng khác nhau.
            if _sha256(target) != item.sha256:
                raise BundleError(f"Artifact đã có trên máy này nhưng khác nội dung: {item.path}")
            continue
        _place(source / "artifacts" / item.path, target)
        copied += 1
    return copied


def import_bundle(database: RuntimeDatabase, jobs_root: Path, source: Path) -> str:
    """Nạp gói vào máy này; trả mô tả ngắn việc đã làm.

    Job chưa có → thêm mới. Job đã có và gói là **bản chạy tiếp** của nó (mọi event chung trùng nhau, gói
    dài hơn) → tiến lên trạng thái của gói. Hai bên rẽ nhánh khác nhau → từ chối, không ghi gì vào DB.
    """
    bundle = load_bundle(source)
    with database.transaction() as tx:
        local_events = {
            int(row[0]): str(row[1])
            for row in tx.execute(
                "SELECT version, payload FROM r2s_job_events WHERE job_id=? ORDER BY version", (bundle.job_id,)
            ).fetchall()
        }
    shared = set(local_events) & set(bundle.events)
    if any(local_events[version] != bundle.events[version] for version in shared):
        raise BundleError(f"Job {bundle.job_id} trên máy này đã rẽ nhánh khác với gói; không nạp")
    if local_events and max(local_events) > bundle.job_version:
        raise BundleError(
            f"Job {bundle.job_id} trên máy này mới hơn gói (v{max(local_events)} > v{bundle.job_version})"
        )
    copied = _copy_artifacts(bundle, source, jobs_root)
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_projects(project_id,payload) VALUES (?,?) ON CONFLICT(project_id) DO NOTHING",
            (bundle.project_id, bundle.project_payload),
        )
        for upload_id, payload in bundle.uploads.items():
            tx.execute(
                "INSERT INTO r2s_uploads(upload_id,payload) VALUES (?,?) ON CONFLICT(upload_id) DO NOTHING",
                (upload_id, payload),
            )
        tx.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?) "
            "ON CONFLICT(job_id) DO NOTHING",
            (bundle.job_id, bundle.project_id, bundle.job_version, bundle.manifest_ref),
        )
        tx.execute(
            "UPDATE r2s_jobs SET version=?, manifest_ref=? WHERE job_id=?",
            (bundle.job_version, bundle.manifest_ref, bundle.job_id),
        )
        new_events = sorted(set(bundle.events) - set(local_events))
        for version in new_events:
            tx.execute(
                "INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)",
                (bundle.job_id, version, bundle.events[version]),
            )
    state = "thêm mới" if not local_events else ("đã cập nhật" if new_events else "không đổi")
    return f"{bundle.job_id}: {state} (v{bundle.job_version}), chép {copied}/{len(bundle.files)} file"


def _hub():  # noqa: ANN202 - kiểu của thư viện ngoài, chỉ import khi cần
    try:
        import huggingface_hub
    except ImportError as error:
        raise BundleError("Cần gói `huggingface_hub` (pip install huggingface_hub) để đẩy/kéo gói") from error
    return huggingface_hub


def push_bundle(source: Path, repo_id: str) -> str:
    """Đẩy gói lên dataset repo **private** tại `jobs/<job_id>/`; file trùng nội dung không tải lại."""
    bundle = load_bundle(source)
    hub = _hub()
    api = hub.HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(source),
        path_in_repo=f"jobs/{bundle.job_id}",
        commit_message=f"{bundle.job_id} v{bundle.job_version}",
    )
    return f"hf://datasets/{repo_id}/jobs/{bundle.job_id}"


def pull_bundle(job_id: str, repo_id: str, out: Path) -> Path:
    """Kéo gói của một job về `<out>/<job_id>` rồi kiểm checksum."""
    hub = _hub()
    hub.snapshot_download(
        repo_id=repo_id, repo_type="dataset", allow_patterns=[f"jobs/{job_id}/**"], local_dir=str(out / ".hf")
    )
    downloaded = out / ".hf" / "jobs" / job_id
    if not downloaded.is_dir():
        raise BundleError(f"Repo {repo_id} không có gói jobs/{job_id}")
    target = out / job_id
    if target.exists():
        raise BundleError(f"Đã có gói tại {target}; xoá hoặc chọn thư mục --out khác")
    shutil.move(str(downloaded), str(target))
    load_bundle(target)
    return target


def runtime() -> tuple[RuntimeDatabase, Path]:
    """DB runtime và thư mục `jobs/` của artifact store theo Settings của máy này."""
    from src.config import get_settings
    from src.services.orchestration.storage import runtime_resolver

    settings = get_settings()
    probe = runtime_resolver(settings).resolve("artifact://jobs/probe/x")
    return RuntimeDatabase(settings.database_url), probe.parent.parent


def main(argv: list[str] | None = None) -> int:
    """CLI: export / import / push / pull; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="xuất job trên máy này thành gói")
    export.add_argument("job_id")
    export.add_argument("--out", type=Path, required=True)
    load = commands.add_parser("import", help="nạp gói vào máy này")
    load.add_argument("bundle", type=Path)
    push = commands.add_parser("push", help="đẩy gói lên Hugging Face dataset repo (private)")
    push.add_argument("bundle", type=Path)
    push.add_argument("--repo", required=True)
    pull = commands.add_parser("pull", help="kéo gói của một job từ Hugging Face")
    pull.add_argument("job_id")
    pull.add_argument("--repo", required=True)
    pull.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            database, jobs_root = runtime()
            print(export_bundle(database, jobs_root, args.job_id, args.out))
        elif args.command == "import":
            database, jobs_root = runtime()
            print(import_bundle(database, jobs_root, args.bundle))
            print("Khởi động lại API/worker đang chạy để thấy job vừa nạp.")
        elif args.command == "push":
            print(push_bundle(args.bundle, args.repo))
        else:
            print(pull_bundle(args.job_id, args.repo, args.out))
    except BundleError as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
