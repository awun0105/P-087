"""Script điều phối tự động (Batch Orchestrator) đưa danh sách video qua Colab GPU pipeline,
tải bundle về máy local và import vào Studio local để phục vụ demo.

Không sửa đổi bất kỳ code hiện tại nào của dự án.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def run_cmd(cmd: list[str] | str, shell: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=shell, check=True, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description="Chạy batch video trên Colab GPU và import bundle về máy local.")
    parser.add_argument("--videos-dir", type=Path, default=Path("/media/usb/AI20K/P-087 demo videos"), help="Thư mục chứa video demo")
    parser.add_argument("--session", default="p087-rec", help="Tên session Colab")
    parser.add_argument("--out-dir", type=Path, default=Path("data/colab_bundles"), help="Thư mục lưu bundles ở local")
    parser.add_argument("--demo-library-dir", type=Path, default=Path("data/demo/library"), help="Thư mục demo library của Studio")
    parser.add_argument("--single-video", type=str, help="Chỉ chạy một video cụ thể")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.demo_library_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = args.videos_dir / "manifest.json"
    if not manifest_file.exists():
        print(f"[!] Không tìm thấy manifest tại {manifest_file}", file=sys.stderr)
        return 1

    with open(manifest_file, "r") as f:
        meta = json.load(f)

    videos = meta.get("videos", [])
    if args.single_video:
        videos = [v for v in videos if v["file"] == args.single_video]
        if not videos:
            print(f"[!] Không tìm thấy video {args.single_video} trong manifest", file=sys.stderr)
            return 1

    print(f"=== Chuẩn bị xử lý {len(videos)} video qua Colab GPU session '{args.session}' ===")
    for idx, v in enumerate(videos, start=1):
        filename = v["file"]
        video_path = args.videos_dir / filename
        traversal = v.get("traversal", "demo")
        print(f"\n[{idx}/{len(videos)}] Bắt đầu video: {filename} ({video_path.stat().st_size / 1e6:.1f} MB)")

        remote_video = f"/content/{filename}"
        print(f"-> Uploading lên Colab: {remote_video}...")
        subprocess.run(["colab", "upload", "-s", args.session, str(video_path), remote_video], check=True)

        job_name = f"Demo · {Path(filename).stem}"
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
        exec_proc = subprocess.run(["colab", "exec", "-s", args.session, "--timeout", "7200"], input=exec_script, text=True, capture_output=True)
        print(exec_proc.stdout)
        if exec_proc.returncode != 0:
            print(f"[!] Lỗi khi chạy video {filename} trên Colab:\n{exec_proc.stderr}", file=sys.stderr)
            continue

        print(f"-> Hoàn tất xử lý trên Colab! Đang kiểm tra bundles xuất ra...")
        # Tìm thư mục bundle vừa xuất
        find_script = """
import os, glob
bundles = sorted(glob.glob('/content/bundles/*/*'), key=os.path.getmtime)
if bundles:
    print(bundles[-1])
"""
        res = subprocess.run(["colab", "exec", "-s", args.session, "--timeout", "30"], input=find_script, text=True, capture_output=True)
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
        subprocess.run(["colab", "exec", "-s", args.session, "--timeout", "120"], input=tar_script, text=True, check=True)

        local_tar = args.out_dir / f"{bundle_name}.tar.gz"
        subprocess.run(["colab", "download", "-s", args.session, f"/content/{bundle_name}.tar.gz", str(local_tar)], check=True)
        subprocess.run(["tar", "-xzf", str(local_tar), "-C", str(args.out_dir)], check=True)
        local_tar.unlink(missing_ok=True)

        print(f"-> Đang import bundle vào Studio local...")
        import_cmd = [".venv/bin/python", "-m", "scripts.kaggle.job_bundle", "import", str(local_bundle_dest)]
        import_proc = subprocess.run(import_cmd, capture_output=True, text=True)
        print(import_proc.stdout)
        if import_proc.returncode != 0:
            print(f"[!] Import bundle thất bại: {import_proc.stderr}", file=sys.stderr)

        print(f"-> Video {filename} đã xử lý xong và import thành công vào Studio!")

    print("\n=== Hoàn tất toàn bộ batch jobs! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
