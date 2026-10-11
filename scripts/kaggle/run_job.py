"""Chạy pipeline cho một video mà không cần giao diện web, rồi xuất gói job (Kaggle / GPU thuê).

Lệnh này **không** có logic pipeline riêng: nó bật đúng API + worker của stack trên máy này, gọi các
endpoint như Studio vẫn gọi, chờ job chạy, rồi dùng `job_bundle` để xuất (và đẩy lên Hugging Face).

    set -a; source <file env>; set +a
    # Lượt 1 — dựng 3DGS, dừng ở bước chờ xác nhận hệ mét:
    python -m scripts.kaggle.run_job --video v.mp4 --name "Kho A" --attestation attestation.json \\
        --out /kaggle/working/bundles --hf-repo <user>/real2sim-artifacts
    # Lượt 2 — có điểm đo (file JSON đúng dạng `UserMetricInput`): chạy tiếp tới scene theo vật.
    python -m scripts.kaggle.run_job --job-id job-abc --metric-input metric.json \\
        --out /kaggle/working/bundles --hf-repo <user>/real2sim-artifacts

Nhiều video một lượt: `--video a.mp4 b.mp4 c.mp4` (mỗi video một job). Số worker và GPU của từng worker do
`scripts/gpu/gpu_plan.py` chia theo VRAM trống của từng GPU (`--workers auto`, mặc định), hoặc đặt tay tổng số
worker (`--workers 2`); các job còn lại xếp hàng.

Truyền cả `--video` và `--metric-input` thì chạy một mạch — chỉ đúng khi điểm đo được lấy trên chính
3DGS của lần chạy này (hệ SfM đổi theo từng lần dựng), nên bình thường phải đi hai lượt.

`attestation.json` là lời khai nguồn dữ liệu của người chạy (`SourceRightsAttestation`); lệnh không
tự điền thay. Điểm đo sai lệch quá ngưỡng (`check_passed=false`) thì dừng, không xác nhận.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.gpu.gpu_plan import plan_for_machine
from scripts.gpu.run_workers import WORKER_COMMAND
from scripts.kaggle.job_bundle import BundleError, export_bundle, push_bundle, runtime

_METRIC_STAGE = "ST-METRIC-CANONICALIZE"
_POLL_SECONDS = 15.0


class RunError(RuntimeError):
    """Pipeline không đi tiếp được; message nói rõ bước và lý do."""


class Api:
    """Client HTTP tối thiểu tới API của stack trên localhost."""

    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method: str, path: str, body: object | None = None, timeout: float = 600.0) -> dict:
        """Gọi JSON; lỗi HTTP → RunError kèm chi tiết API trả về."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers={"content-type": "application/json"}
        )
        return self._send(request, timeout)

    def upload_file(self, path: Path, content_type: str = "application/octet-stream") -> dict:
        """Gửi bytes file theo luồng (không nạp cả file vào RAM)."""
        query = urllib.parse.urlencode({"filename": path.name})
        with path.open("rb") as stream:
            request = urllib.request.Request(
                f"{self.base}/api/v1/uploads?{query}",
                data=stream,
                method="POST",
                headers={"content-type": content_type, "content-length": str(path.stat().st_size)},
            )
            return self._send(request, 3600.0)

    def upload(self, video: Path) -> dict:
        """Gửi bytes video theo luồng (không nạp cả file vào RAM)."""
        return self.upload_file(video, "video/mp4")

    @staticmethod
    def _send(request: urllib.request.Request, timeout: float) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:600]
            raise RunError(f"{request.get_method()} {request.full_url} → {error.code}: {detail}") from error


class Stack:
    """API + worker chạy nền trong lúc lệnh này làm việc; log ghi ra thư mục `log_dir`."""

    def __init__(self, port: int, log_dir: Path, worker_environments: list[dict[str, str]] | None = None) -> None:
        self.port, self.log_dir = port, log_dir
        #: Một phần tử cho mỗi worker: biến môi trường ghim worker đó vào một GPU (rỗng = mặc định).
        self.worker_environments = worker_environments or [{}]
        self.api = Api(port)
        self.processes: list[subprocess.Popen[bytes]] = []

    def __enter__(self) -> "Stack":
        self.log_dir.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "APP_PORT": str(self.port), "AUTH_REQUIRED": "false"}
        api = [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(self.port)]
        self._start("api", api, environment)
        # Nhiều worker cùng đọc một hàng đợi: mỗi job chỉ một worker nhận được (claim bằng CAS trong DB).
        for index, pinned in enumerate(self.worker_environments):
            self._start(f"worker-{index}", WORKER_COMMAND, {**environment, **pinned})
        for _ in range(120):
            self.require_alive()
            try:
                urllib.request.urlopen(f"{self.api.base}/health", timeout=2).close()
                return self
            except (urllib.error.URLError, OSError):
                time.sleep(1.0)
        raise RunError(f"API không lên sau 120 giây; xem {self.log_dir}/api.log")

    def _start(self, name: str, command: list[str], environment: dict[str, str]) -> None:
        log = (self.log_dir / f"{name}.log").open("ab")
        self.processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment))

    def require_alive(self) -> None:
        """API hoặc worker chết giữa chừng thì dừng ngay thay vì chờ vô hạn."""
        for process in self.processes:
            if process.poll() is not None:
                raise RunError(f"API/worker thoát sớm (exit {process.returncode}); xem log trong {self.log_dir}")

    def __exit__(self, *_: object) -> None:
        for process in self.processes:
            process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()


def _stage_states(progress: dict) -> dict[str, str]:
    return {stage["stage_id"]: stage["state"] for stage in progress["stages"]}


def wait_for_pause(stack: Stack, job_ids: list[str]) -> dict[str, dict]:
    """Chờ tới khi mọi job dừng: xong, lỗi, hoặc đang chờ người xác nhận hệ mét. In tiến trình khi đổi stage."""
    seen: dict[str, tuple[str, str]] = {}
    paused: dict[str, dict] = {}
    while True:
        stack.require_alive()
        for job_id in job_ids:
            if job_id in paused:
                continue
            progress = stack.api.call("GET", f"/api/v1/jobs/{job_id}/progress")
            marker = (progress["status"], progress["current_stage"])
            if marker != seen.get(job_id):
                print(f"[{time.strftime('%H:%M:%S')}] {job_id} {marker[0]} · {marker[1]}", flush=True)
                seen[job_id] = marker
            waiting = _stage_states(progress).get(_METRIC_STAGE) == "waiting"
            if progress["status"] not in ("RUNNING", "QUEUED") or waiting:
                paused[job_id] = progress
        if len(paused) == len(job_ids):
            return paused
        time.sleep(_POLL_SECONDS)


def confirm_metric(api: Api, job_id: str, metric_input: dict) -> None:
    """Xem trước rồi xác nhận đúng bản xem trước đó; đoạn kiểm không đạt thì dừng."""
    preview = api.call("POST", f"/api/v1/jobs/{job_id}/metric/preview", metric_input)
    print(
        f"hệ mét: {preview['scale_m_per_sfm_unit']:.4f} m/đơn vị SfM · sai số đoạn kiểm "
        f"{preview['check_error_m']:.4f} m (ngưỡng {preview['check_tolerance_m']:.4f})"
    )
    if not preview["check_passed"]:
        raise RunError("Đoạn kiểm không đạt ngưỡng; không xác nhận hệ mét. Kiểm lại điểm đo.")
    api.call(
        "POST",
        f"/api/v1/jobs/{job_id}/metric/confirm",
        {"input": metric_input, "preview_checksum": preview["preview_checksum"]},
    )


_PRESET_BOUNDS = {
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}


def fit_video_dimensions(display_w: int, display_h: int, preset: str = "1080p") -> tuple[int, int]:
    """Tính kích thước vừa preset mà không upscale và đảm bảo số chẵn (giống Web Studio)."""
    if preset not in _PRESET_BOUNDS:
        raise ValueError(f"Preset không hợp lệ: {preset}. Chọn một trong: {list(_PRESET_BOUNDS.keys())}")
    max_long, max_short = _PRESET_BOUNDS[preset]
    long_edge = max(display_w, display_h)
    short_edge = min(display_w, display_h)
    scale = min(1.0, max_long / long_edge, max_short / short_edge)
    width = int(display_w * scale) // 2 * 2
    height = int(display_h * scale) // 2 * 2
    return max(2, width), max(2, height)


def normalize_video(
    video: Path,
    output: Path | None = None,
    preset: str = "1080p",
    max_fps: float = 30.0,
    force: bool = False,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> Path:
    """Chuẩn hóa video đầu vào theo quy chuẩn Video Normalization Profile v1 của Web Studio.

    - Giảm độ phân giải về preset (1080p/720p/480p) mà không phóng to (no upscale).
    - Giới hạn tốc độ khung hình trần tối đa 30 FPS.
    - Xoay pixel về 0 độ (bake displaymatrix/rotation vào pixel).
    - Loại bỏ track audio.
    - Xuất video MP4 mới (H.264 yuv420p).
    """
    if not video.is_file():
        raise RunError(f"Video không tồn tại: {video}")

    if output is None:
        if video.stem.endswith("_normalized") and not force:
            return video
        output = video.with_name(f"{video.stem}_normalized.mp4")

    if not force and output.is_file() and output.stat().st_mtime >= video.stat().st_mtime and output.stat().st_size > 0:
        print(f"Sử dụng video đã chuẩn hóa sẵn có: {output.name} ({output.stat().st_size / (1024 * 1024):.1f} MB)")
        return output

    probe_cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate",
        "-show_entries",
        "stream_tags=rotate",
        "-show_entries",
        "stream_side_data=rotation",
        "-of",
        "json",
        str(video),
    ]
    try:
        proc = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
        info = json.loads(proc.stdout)
        streams = info.get("streams", [])
        if not streams:
            raise RunError(f"File không chứa stream video: {video}")
        stream = streams[0]
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as err:
        raise RunError(f"Lỗi khi probe video {video}: {err}") from err

    raw_w = int(stream["width"])
    raw_h = int(stream["height"])

    rotation = 0
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            try:
                rotation = int(float(side["rotation"]))
            except (ValueError, TypeError):
                pass
    if rotation == 0:
        rotate_tag = stream.get("tags", {}).get("rotate")
        if rotate_tag:
            try:
                rotation = int(float(rotate_tag))
            except (ValueError, TypeError):
                pass

    if abs(rotation) in (90, 270):
        disp_w, disp_h = raw_h, raw_w
    else:
        disp_w, disp_h = raw_w, raw_h

    target_w, target_h = fit_video_dimensions(disp_w, disp_h, preset)

    src_fps = 30.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = stream.get(key, "")
        if "/" in val:
            num, den = val.split("/", 1)
            try:
                n, d = float(num), float(den)
                if d > 0:
                    src_fps = n / d
                    break
            except (ValueError, ZeroDivisionError):
                pass
        elif val:
            try:
                src_fps = float(val)
                break
            except ValueError:
                pass

    target_fps = min(max_fps, src_fps)
    target_fps_str = "30" if abs(target_fps - 30.0) < 0.05 else f"{target_fps:.2f}"

    print(
        f"Chuẩn hóa video: {video.name} ({disp_w}x{disp_h} @ {src_fps:.1f} fps, rot={rotation}°) "
        f"→ {output.name} ({target_w}x{target_h} @ {target_fps_str} fps, preset={preset})..."
    )

    temp_output = output.with_name(f"{output.name}.tmp.{os.getpid()}.mp4")
    encode_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"scale={target_w}:{target_h},fps={target_fps_str}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-metadata:s:v:0",
        "rotate=0",
        "-an",
        str(temp_output),
    ]
    try:
        subprocess.run(encode_cmd, check=True)
        temp_output.replace(output)
    except Exception as err:
        temp_output.unlink(missing_ok=True)
        raise RunError(f"Lỗi khi mã hóa chuẩn hóa video bằng ffmpeg: {err}") from err

    print(f"Đã tạo video chuẩn hóa: {output.name} ({output.stat().st_size / (1024 * 1024):.1f} MB)")
    return output


def create_job(
    api: Api,
    video: Path,
    name: str,
    attestation: dict,
    processing: dict | None,
    lidar: Path | None = None,
) -> str:
    """Upload video (và lidar nếu có) và tạo scene; trả job_id của lần chạy đầu."""
    upload = api.upload(video)
    body = {"upload_id": upload["upload_id"], "name": name, "attestation": attestation}
    if lidar is not None:
        lidar_upload = api.upload_file(lidar, "application/zip")
        body["lidar"] = {
            "upload_id": lidar_upload["upload_id"],
            "trajectory_origin": "ground_truth",
            "same_scene_confirmed": True,
        }
    if processing is not None:
        body["processing"] = processing
    return str(api.call("POST", "/api/v1/scenes/from-upload", body)["job"]["job_id"])


def report_scene(api: Api, job_id: str) -> None:
    """In kết quả tách vật; nói rõ khi pipeline đã lùi về đường hộp."""
    response = api.call("GET", f"/api/v1/jobs/{job_id}/scene")
    scene = response.get("scene", response)
    method = str(scene.get("provenance", {}).get("object_extraction", "?"))
    print(f"scene {scene['scene_revision']}: {len(scene['objects'])} vật · phương pháp {method}")
    if not method.startswith("objectify"):
        note = scene.get("provenance", {}).get("note", "")
        print(f"[!] Tách theo vật KHÔNG chạy; scene dùng đường hộp. {note}", file=sys.stderr)


def _json_file(path: Path | None) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path is not None else None


def run(args: argparse.Namespace) -> int:
    """Điều phối một lượt chạy; trả exit code (0 = mọi job dừng ở trạng thái mong đợi và đã xuất gói)."""
    metrics = [_json_file(path) for path in args.metric_input]
    processing = _json_file(args.processing)
    count = len(args.video or args.job_id)
    if len(metrics) not in (0, count):
        raise RunError("--metric-input phải bỏ trống hoặc đủ một file cho mỗi job, theo đúng thứ tự")
    gpus, plan = plan_for_machine(
        count if args.workers == "auto" else min(count, max(1, int(args.workers))), processing
    )
    print(f"{len(gpus)} GPU, {len(plan.slots)} worker song song — {plan.reason}")
    for slot in plan.slots:
        print(f"  worker {slot.worker} → GPU {slot.gpu_index}")
    with Stack(args.port, args.out / "logs", [slot.environment for slot in plan.slots]) as stack:
        api = stack.api
        job_ids = list(args.job_id or [])
        if args.video:
            if getattr(args, "lidar", None) and not args.video:
                raise RunError("--lidar chỉ áp dụng khi tạo job mới từ --video")
            attestation = _json_file(args.attestation)
            if attestation is None:
                raise RunError("Tạo job mới cần --attestation (lời khai nguồn dữ liệu)")
            prepared_videos: list[Path] = []
            for video in args.video:
                if getattr(args, "no_normalize", False):
                    prepared_videos.append(video)
                else:
                    norm = normalize_video(
                        video,
                        preset=getattr(args, "video_preset", "1080p"),
                        force=getattr(args, "force_normalize", False),
                    )
                    prepared_videos.append(norm)

            lidars: list[Path | None] = (
                list(args.lidar) if getattr(args, "lidar", None) else [None] * len(prepared_videos)
            )
            if len(lidars) != len(prepared_videos):
                raise RunError("Số lượng file --lidar phải bằng số lượng video, hoặc bỏ trống hoàn toàn")

            for orig_video, video, lidar_path in zip(args.video, prepared_videos, lidars, strict=True):
                stem = orig_video.stem if count > 1 else args.name
                name = args.name if count == 1 else f"{args.name} · {stem}"
                job_ids.append(create_job(api, video, name, attestation, processing, lidar=lidar_path))
                lidar_info = f" + lidar: {lidar_path.name}" if lidar_path else ""
                if video != orig_video:
                    print(f"job: {job_ids[-1]} ← {video.name} (gốc: {orig_video.name}){lidar_info}")
                else:
                    print(f"job: {job_ids[-1]} ← {video.name}{lidar_info}")
        paused = wait_for_pause(stack, job_ids)
        if metrics:
            confirmed = []
            for job_id, metric in zip(job_ids, metrics, strict=True):
                if paused[job_id]["status"] == "RUNNING" and metric is not None:
                    confirm_metric(api, job_id, metric)
                    confirmed.append(job_id)
            paused.update(wait_for_pause(stack, confirmed))
        elif getattr(args, "auto_confirm_proposal", False):
            confirmed = []
            for job_id in job_ids:
                if paused[job_id]["status"] == "RUNNING":
                    try:
                        proposal = api.call("GET", f"/api/v1/jobs/{job_id}/metric/proposal")
                        if proposal and proposal.get("segments") and proposal.get("floor"):
                            seg = proposal["segments"]
                            flr = proposal["floor"]
                            source = (
                                "lidar_trajectory"
                                if proposal.get("method") == "lidar_trajectory_alignment"
                                else "ai_estimated"
                            )
                            metric_input = {
                                "point_a": seg["point_a"],
                                "point_b": seg["point_b"],
                                "distance_m": seg["distance_m"],
                                "check_a": seg["check_a"],
                                "check_b": seg["check_b"],
                                "check_distance_m": seg["check_distance_m"],
                                "distance_source": source,
                                "floor_points": flr["points"],
                            }
                            print(
                                f"[{job_id}] Tự động xác nhận hệ mét từ đề xuất ({source}, "
                                f"scale={proposal['scale_m_per_sfm_unit']:.4f})..."
                            )
                            confirm_metric(api, job_id, metric_input)
                            confirmed.append(job_id)
                    except Exception as err:
                        print(f"[{job_id}] Không thể tự động xác nhận đề xuất hệ mét: {err}")
            if confirmed:
                paused.update(wait_for_pause(stack, confirmed))
        for job_id in job_ids:
            progress = paused[job_id]
            if progress["status"] == "SUCCEEDED":
                report_scene(api, job_id)
            elif progress["status"] == "RUNNING":
                print(
                    f"{job_id}: chờ xác nhận hệ mét — nạp gói vào Studio để chọn điểm, hoặc chạy lượt 2 với --metric-input."
                )
            else:
                failed = [stage for stage in progress["stages"] if stage.get("error")]
                print(
                    f"[!] {job_id} {progress['status']}: {failed[-1]['error'] if failed else 'không rõ'}",
                    file=sys.stderr,
                )
    # Xuất sau khi API/worker đã dừng để không chụp DB giữa lúc đang ghi.
    database, jobs_root = runtime()
    out = args.out / time.strftime("%Y%m%d-%H%M%S")
    for job_id in job_ids:
        bundle = export_bundle(database, jobs_root, job_id, out)
        print(f"gói: {bundle}")
        if args.hf_repo:
            print(f"đã đẩy: {push_bundle(bundle, args.hf_repo)}")
    return 0 if all(paused[job_id]["status"] in ("SUCCEEDED", "RUNNING") for job_id in job_ids) else 1


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path, nargs="+", help="một hoặc nhiều video đầu vào (mỗi video một job)")
    source.add_argument("--job-id", nargs="+", help="job đã có trên máy này (vd. vừa nạp từ gói) để chạy tiếp")
    parser.add_argument("--name", default="Scene từ Kaggle")
    parser.add_argument("--attestation", type=Path, help="JSON SourceRightsAttestation (bắt buộc khi tạo job)")
    parser.add_argument(
        "--lidar",
        type=Path,
        nargs="*",
        default=[],
        help="Gói ZIP LiDAR (.zip gồm đám mây hoặc scan, quỹ đạo, calibration, thời điểm frame)",
    )
    parser.add_argument("--processing", type=Path, help="JSON thông số xử lý; bỏ trống = preset mặc định")
    parser.add_argument(
        "--metric-input",
        type=Path,
        nargs="*",
        default=[],
        help="JSON UserMetricInput, một file cho mỗi job theo thứ tự",
    )
    parser.add_argument(
        "--auto-confirm-proposal",
        action="store_true",
        help="Tự động xác nhận đề xuất hệ mét (AI Auto-Scale MoGe hoặc LiDAR) khi có",
    )
    parser.add_argument(
        "--video-preset",
        choices=["1080p", "720p", "480p"],
        default="1080p",
        help="Độ phân giải chuẩn hóa video tương tự Web Studio (mặc định 1080p)",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Bỏ qua bước chuẩn hóa video, giữ nguyên file gốc (không khuyến nghị cho video 4K/60fps)",
    )
    parser.add_argument(
        "--force-normalize",
        action="store_true",
        help="Bắt buộc chuẩn hóa lại video kể cả khi file normalized đã tồn tại",
    )
    parser.add_argument("--workers", default="auto", help="tổng số worker, hoặc `auto` theo VRAM trống từng GPU")
    parser.add_argument("--out", type=Path, required=True, help="thư mục chứa gói xuất ra và log")
    parser.add_argument("--hf-repo", help="dataset repo Hugging Face để đẩy gói (cần HF_TOKEN)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (RunError, BundleError) as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
