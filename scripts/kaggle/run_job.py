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

    def upload(self, video: Path) -> dict:
        """Gửi bytes video theo luồng (không nạp cả file vào RAM)."""
        query = urllib.parse.urlencode({"filename": video.name})
        with video.open("rb") as stream:
            request = urllib.request.Request(
                f"{self.base}/api/v1/uploads?{query}",
                data=stream,
                method="POST",
                headers={"content-type": "video/mp4", "content-length": str(video.stat().st_size)},
            )
            return self._send(request, 3600.0)

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
        environment = {**os.environ, "APP_PORT": str(self.port)}
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


def create_job(api: Api, video: Path, name: str, attestation: dict, processing: dict | None) -> str:
    """Upload video và tạo scene; trả job_id của lần chạy đầu."""
    upload = api.upload(video)
    body = {"upload_id": upload["upload_id"], "name": name, "attestation": attestation}
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
            attestation = _json_file(args.attestation)
            if attestation is None:
                raise RunError("Tạo job mới cần --attestation (lời khai nguồn dữ liệu)")
            for video in args.video:
                name = args.name if count == 1 else f"{args.name} · {video.stem}"
                job_ids.append(create_job(api, video, name, attestation, processing))
                print(f"job: {job_ids[-1]} ← {video.name}")
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
