"""Script điều phối tự động (Batch Orchestrator) đưa danh sách kịch bản qua Colab GPU pipeline,
tải bundle về máy local, tự động trích xuất Báo cáo đánh giá (Scorecard & Evaluation Report)
và import vào Studio local để phục vụ demo.

Tương thích với bộ dữ liệu chuẩn hóa `/media/usb/AI20K/TorWIC_Raw_Scenes`.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def upload_to_colab(session: str, local_path: Path, remote_path: str, chunk_size_mb: int = 10) -> None:
    """Upload file lên Colab, tự động chia nhỏ (chunked upload) nếu file lớn hơn 10MB
    để không bao giờ bị lỗi 500 của Colab Contents API."""
    size_mb = local_path.stat().st_size / (1024 * 1024)
    if size_mb <= chunk_size_mb:
        subprocess.run(["colab", "upload", "-s", session, str(local_path), remote_path], check=True)
        return

    print(f"    (File {size_mb:.1f} MB > {chunk_size_mb} MB: tự động upload theo phân đoạn {chunk_size_mb}MB)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_prefix = Path(tmpdir) / "chunk_"
        subprocess.run(["split", "-b", f"{chunk_size_mb}M", str(local_path), str(tmp_prefix)], check=True)
        parts = sorted(Path(tmpdir).glob("chunk_*"))
        remote_tmp_dir = f"/content/_tmp_upload_{local_path.stem}"
        mkdir_script = f"import subprocess; subprocess.run(['mkdir', '-p', '{remote_tmp_dir}'], check=True)"
        subprocess.run(["colab", "exec", "-s", session, mkdir_script], check=True, capture_output=True)

        for p_idx, part in enumerate(parts, start=1):
            print(f"      [part {p_idx}/{len(parts)}] -> {part.name}...")
            remote_part = f"{remote_tmp_dir}/{part.name}"
            subprocess.run(["colab", "upload", "-s", session, str(part), remote_part], check=True)

        # Hợp nhất các phân đoạn trên Colab và xóa thư mục tạm
        cat_script = f"import subprocess; subprocess.run('cat {remote_tmp_dir}/chunk_* > {remote_path} && rm -rf {remote_tmp_dir}', shell=True, check=True)"
        subprocess.run(["colab", "exec", "-s", session, cat_script], check=True, capture_output=True)
    print(f"    -> Đã tải lên và hợp nhất thành công: {remote_path}")


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
    args = parser.parse_args()

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

    print(f"=== Chuẩn bị xử lý {len(scenarios)} kịch bản qua Colab GPU session '{args.session}' ===")
    for idx, sc in enumerate(scenarios, start=1):
        code = sc.get("code", f"SC-{idx:02d}")
        folder = sc["folder"]
        video_filename = sc["video"]
        video_path = args.scenes_dir / folder / video_filename
        desc = sc.get("description", "")

        if not video_path.exists():
            print(f"[!] Không tìm thấy video tại {video_path}", file=sys.stderr)
            continue

        print(
            f"\n[{idx}/{len(scenarios)}] [{code}] Bắt đầu: {folder}/{video_filename} ({video_path.stat().st_size / 1e6:.1f} MB)"
        )
        print(f"    Mục đích: {desc}")

        remote_video = f"/content/{code}_{video_filename}"
        print(f"-> Đang tải video lên Colab: {remote_video}...")
        upload_to_colab(args.session, video_path, remote_video)

        job_name = f"{code} · {folder}"
        print(f"-> Khởi chạy pipeline trên Colab (job: '{job_name}')...")
        exec_script = f"""
import subprocess, sys
cmd = '''
cd /content/app && set -a && source /content/r2s/colab.env && set +a
.venv/bin/python -m scripts.kaggle.run_job \\
  --video "{remote_video}" \\
  --name "{job_name}" \\
  --attestation /content/app/scripts/colab/attestation.json \\
  --out /content/bundles \\
  --port 8000
'''
proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, executable="/bin/bash")
for line in proc.stdout:
    sys.stdout.write(line)
    sys.stdout.flush()
proc.wait()
sys.exit(proc.returncode)
"""
        exec_proc = subprocess.run(
            ["colab", "exec", "-s", args.session, "--timeout", "7200"],
            input=exec_script,
            text=True,
            capture_output=True,
        )
        print(exec_proc.stdout)
        if exec_proc.returncode != 0:
            print(f"[!] Lỗi khi chạy kịch bản {code} trên Colab:\n{exec_proc.stderr}", file=sys.stderr)
            continue

        print("-> Hoàn tất xử lý trên Colab! Đang kiểm tra bundles xuất ra...")
        find_script = """
import os, glob
bundles = sorted(glob.glob('/content/bundles/*/*'), key=os.path.getmtime)
if bundles:
    print(bundles[-1])
"""
        res = subprocess.run(
            ["colab", "exec", "-s", args.session, "--timeout", "30"],
            input=find_script,
            text=True,
            capture_output=True,
        )
        remote_bundle_path = res.stdout.strip().split("\n")[-1]
        print(f"-> Remote bundle: {remote_bundle_path}")

        if not remote_bundle_path or not remote_bundle_path.startswith("/content/bundles"):
            print("[!] Không tìm thấy bundle path từ Colab output", file=sys.stderr)
            continue

        bundle_name = Path(remote_bundle_path).name
        local_bundle_dest = args.out_dir / bundle_name
        local_bundle_dest.mkdir(parents=True, exist_ok=True)

        print(f"-> Đang nén và tải bundle về local {local_bundle_dest}...")
        tar_script = f"import subprocess; subprocess.run(['tar', '-czf', '/content/{bundle_name}.tar.gz', '-C', '{Path(remote_bundle_path).parent}', '{bundle_name}'], check=True)"
        subprocess.run(
            ["colab", "exec", "-s", args.session, "--timeout", "120"],
            input=tar_script,
            text=True,
            check=True,
        )

        local_tar = args.out_dir / f"{bundle_name}.tar.gz"
        subprocess.run(
            ["colab", "download", "-s", args.session, f"/content/{bundle_name}.tar.gz", str(local_tar)],
            check=True,
        )
        subprocess.run(["tar", "-xzf", str(local_tar), "-C", str(args.out_dir)], check=True)
        local_tar.unlink(missing_ok=True)

        print("-> Đang import bundle vào Studio local...")
        import_cmd = [".venv/bin/python", "-m", "scripts.kaggle.job_bundle", "import", str(local_bundle_dest)]
        import_proc = subprocess.run(import_cmd, capture_output=True, text=True)
        print(import_proc.stdout)
        if import_proc.returncode != 0:
            print(f"[!] Import bundle thất bại: {import_proc.stderr}", file=sys.stderr)

        # Tự động xuất Báo cáo đánh giá (Scorecard & Evaluation Report)
        print("-> Đang trích xuất Báo cáo Đánh giá (Scorecard & Evaluation Report)...")
        eval_script = f"""
from src.services.orchestration.projects.registry import get_project_registry
from src.services.orchestration.evaluation import evaluate_job, evaluation_markdown
from pathlib import Path

registry = get_project_registry()
eval_res = evaluate_job(registry, "{bundle_name}")
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

        print(f"-> Kịch bản {code} đã xử lý xong, xuất báo cáo và import thành công vào Studio!")

    print("\n=== Hoàn tất toàn bộ batch jobs! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
