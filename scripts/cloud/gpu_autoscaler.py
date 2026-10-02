"""Tự bật GPU worker khi có việc và tắt khi rảnh (ADR 0003 §1), nhà cung cấp vast.ai.

Chạy thường trực ở nơi thấy được DB + kho file của deployment (vd tiến trình thứ hai trên máy API):

    python -m scripts.cloud.gpu_autoscaler                # vòng lặp
    python -m scripts.cloud.gpu_autoscaler --once --dry-run   # xem nó định làm gì, không gọi vast.ai

Mỗi chu kỳ: đếm việc đang chờ GPU trong DB (job trong hàng đợi, job vừa được xác nhận hệ mét, yêu cầu dựng lại
tập vật) và việc đang chạy; có việc chờ mà GPU chưa bật → bật; không còn việc quá `GPU_IDLE_MINUTES` → tắt.
Job đang **chờ người dùng** xác nhận hệ mét không tính là việc: GPU được tắt trong lúc chờ.

Hai cách dùng vast.ai, chọn bằng `VAST_MODE`:

- `instance` — bạn thuê sẵn một instance (`VAST_INSTANCE_ID`), lệnh này chỉ **start/stop** nó. Bật lại nhanh
  (đĩa còn nguyên, kể cả checkpoint train), nhưng instance đã stop vẫn tính tiền lưu trữ, và có thể không bật
  lại được ngay nếu GPU đó đang có người khác thuê.
- `rent` — mỗi lần cần thì **tìm offer rẻ nhất đạt yêu cầu, thuê mới**, xong thì **destroy**. Không tốn tiền
  lúc rảnh, nhưng mỗi lần bật phải kéo image (vài phút) và mất kho checkpoint cục bộ.

Biến môi trường (secret chỉ qua biến môi trường, không ghi vào file trong repo):

    VAST_API_KEY            khoá API vast.ai (bắt buộc)
    VAST_MODE               instance | rent                       (mặc định instance)
    VAST_INSTANCE_ID        id instance thuê sẵn                  (mode instance)
    VAST_IMAGE              image worker, vd user/real2sim-gpu:v2 (mode rent)
    VAST_MIN_GPU_RAM_GB     VRAM tối thiểu mỗi GPU                (mặc định 16)
    VAST_MAX_DPH            giá trần USD/giờ                      (mặc định 0.6)
    VAST_DISK_GB            ổ đĩa thuê                            (mặc định 60)
    VAST_MIN_RELIABILITY    độ tin cậy tối thiểu của máy          (mặc định 0.98)
    GPU_IDLE_MINUTES        rảnh bao lâu thì tắt                  (mặc định 10)
    GPU_POLL_SECONDS        chu kỳ kiểm                           (mặc định 30)

Ở mode `rent`, worker mới được cấp `DATABASE_URL` và `ARTIFACT_S3_*` của deployment qua biến môi trường của
instance — tức các secret này được gửi cho vast.ai/máy chủ thuê; chỉ dùng key có quyền vừa đủ.

CHƯA gọi API vast.ai thật (2026-10-01, chưa có tài khoản): endpoint theo tài liệu docs.vast.ai; dạng trường `env`
theo cách CLI `vastai` gửi (object). Lần đầu chạy thật hãy dùng `--once` và xem log.
"""

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

logger = logging.getLogger("gpu_autoscaler")

GpuState = Literal["absent", "stopped", "starting", "running"]
Action = Literal["start", "stop", "none"]
VAST_API = "https://console.vast.ai/api/v0"
WORKER_LABEL = "real2sim-worker"
#: Biến của deployment được chuyển cho worker thuê mới (mode rent).
WORKER_ENVIRONMENT = (
    "DATABASE_URL",
    "ARTIFACT_S3_BUCKET",
    "ARTIFACT_S3_ENDPOINT",
    "ARTIFACT_S3_REGION",
    "ARTIFACT_S3_ACCESS_KEY_ID",
    "ARTIFACT_S3_SECRET_ACCESS_KEY",
    "ARTIFACT_S3_PREFIX",
)


class AutoscalerError(RuntimeError):
    """Cấu hình thiếu hoặc nhà cung cấp trả lỗi; message không chứa secret."""


@dataclass(frozen=True)
class Workload:
    """Việc của GPU tại một thời điểm."""

    #: Việc đang chờ một worker nhận.
    waiting: int
    #: Việc một worker đang làm dở.
    running: int

    @property
    def active(self) -> bool:
        """Còn việc cần GPU (đang chờ hoặc đang chạy)."""
        return self.waiting + self.running > 0


class GpuProvider(Protocol):
    """Một nguồn GPU bật/tắt được."""

    def state(self) -> GpuState:
        """Trạng thái hiện tại của GPU worker."""

    def start(self) -> None:
        """Bật (hoặc thuê) GPU worker."""

    def stop(self) -> None:
        """Tắt (hoặc trả) GPU worker."""


def decide(workload: Workload, state: GpuState, idle_for: timedelta, idle_limit: timedelta) -> Action:
    """Quyết định thuần: bật khi có việc chờ mà GPU chưa bật; tắt khi GPU bật mà rảnh đủ lâu."""
    if workload.waiting > 0 and state in ("absent", "stopped"):
        return "start"
    if not workload.active and state in ("running", "starting") and idle_for >= idle_limit:
        return "stop"
    return "none"


# --- đếm việc trong DB -------------------------------------------------------


def measure_workload() -> Workload:
    """Đọc hàng đợi job và yêu cầu dựng lại tập vật từ DB của deployment."""
    from src.config import get_settings
    from src.models.contracts.manifests import JobStatus, StageId
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.jobs.progress import awaiting_finalize, metric_confirmation_stage
    from src.services.orchestration.projects.registry import get_project_registry

    registry = get_project_registry()
    if registry.persistence is None:
        raise AutoscalerError("Autoscaler cần registry bền vững (DATABASE_URL)")
    waiting = running = 0
    cursor = ""
    while page := registry.persistence.job_ids_after(cursor):
        for job_id in page:
            try:
                job = registry.get_job(job_id)
            except Exception as error:  # noqa: BLE001 - một manifest hỏng không được làm autoscaler dừng
                logger.warning("Bỏ qua job %s: %s", job_id, type(error).__name__)
                continue
            if job.status == JobStatus.QUEUED or awaiting_finalize(job):
                waiting += 1
            elif job.status == JobStatus.RUNNING:
                # RUNNING ở bước xác nhận mà chưa có bản xác nhận = đang chờ người dùng, không phải việc của GPU.
                parked = job.current_stage == StageId.METRIC_CANONICALIZE and metric_confirmation_stage(job) is None
                running += 0 if parked else 1
        cursor = page[-1]
    with RuntimeDatabase(get_settings().database_url).transaction() as tx:
        rows = tx.execute("SELECT status, COUNT(*) FROM r2s_scene_requests GROUP BY status").fetchall()
    counts = {str(status): int(count) for status, count in rows}
    return Workload(waiting + counts.get("queued", 0), running + counts.get("running", 0))


# --- vast.ai -----------------------------------------------------------------

Transport = Callable[[str, str, dict | None], dict]


def http_transport(api_key: str) -> Transport:
    """Gọi REST API vast.ai; lỗi HTTP → AutoscalerError (không kèm khoá API)."""

    def call(method: str, path: str, body: dict | None) -> dict:
        request = urllib.request.Request(
            VAST_API + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise AutoscalerError(f"vast.ai {method} {path} → {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise AutoscalerError(f"vast.ai {method} {path} không trả lời hợp lệ: {type(error).__name__}") from error

    return call


def _state_of(instance: dict) -> GpuState:
    actual, intended = instance.get("actual_status"), instance.get("intended_status")
    if actual == "running":
        return "running"
    if intended == "running":
        return "starting"  # đang kéo image / đang xếp lịch
    return "stopped"


class VastInstance:
    """Mode `instance`: start/stop một instance đã thuê sẵn."""

    def __init__(self, call: Transport, instance_id: str) -> None:
        self.call, self.instance_id = call, instance_id

    def state(self) -> GpuState:
        """Trạng thái instance; không tìm thấy instance là lỗi cấu hình (không tự thuê mới ở mode này)."""
        payload = self.call("GET", f"/instances/{self.instance_id}/", None)
        instance = payload.get("instances") or payload
        if not isinstance(instance, dict) or "actual_status" not in instance:
            raise AutoscalerError(f"Không đọc được instance {self.instance_id}; kiểm VAST_INSTANCE_ID")
        return _state_of(instance)

    def start(self) -> None:
        """Bật instance."""
        self.call("PUT", f"/instances/{self.instance_id}/", {"state": "running"})

    def stop(self) -> None:
        """Dừng instance (vẫn giữ đĩa)."""
        self.call("PUT", f"/instances/{self.instance_id}/", {"state": "stopped"})


@dataclass(frozen=True)
class RentSpec:
    """Yêu cầu khi thuê mới."""

    image: str
    min_gpu_ram_gb: float
    max_dph: float
    disk_gb: int
    min_reliability: float
    environment: dict[str, str]


class VastRental:
    """Mode `rent`: thuê offer rẻ nhất đạt yêu cầu khi cần, destroy khi rảnh. Nhận diện máy của mình bằng nhãn."""

    def __init__(self, call: Transport, spec: RentSpec) -> None:
        self.call, self.spec = call, spec

    def _mine(self) -> list[dict]:
        instances = self.call("GET", "/instances/", None).get("instances") or []
        return [item for item in instances if item.get("label") == WORKER_LABEL]

    def state(self) -> GpuState:
        """`absent` khi chưa thuê máy nào mang nhãn worker."""
        mine = self._mine()
        if not mine:
            return "absent"
        states = [_state_of(item) for item in mine]
        return "running" if "running" in states else ("starting" if "starting" in states else "stopped")

    def start(self) -> None:
        """Tìm offer rẻ nhất trong giá trần rồi thuê với image worker."""
        query = {
            "gpu_ram": {"gte": int(self.spec.min_gpu_ram_gb * 1024)},
            "num_gpus": {"gte": 1},
            "reliability": {"gte": self.spec.min_reliability},
            "dph_total": {"lte": self.spec.max_dph},
            "disk_space": {"gte": self.spec.disk_gb},
            "verified": {"eq": True},
            "rentable": {"eq": True},
            "type": "ondemand",
            "order": [["dph_total", "asc"]],
            "limit": 5,
        }
        offers = self.call("POST", "/bundles/", query).get("offers") or []
        offers = [offer for offer in offers if float(offer.get("dph_total", 1e9)) <= self.spec.max_dph]
        if not offers:
            raise AutoscalerError(
                f"Không có offer nào ≥ {self.spec.min_gpu_ram_gb:g} GB VRAM trong giá trần {self.spec.max_dph} USD/giờ"
            )
        offer = min(offers, key=lambda item: float(item["dph_total"]))
        body = {
            "image": self.spec.image,
            "disk": self.spec.disk_gb,
            "label": WORKER_LABEL,
            "runtype": "args",
            "args": ["worker"],
            "env": self.spec.environment,
            "target_state": "running",
            "cancel_unavail": True,
        }
        result = self.call("PUT", f"/asks/{offer['id']}/", body)
        if not result.get("success"):
            raise AutoscalerError("vast.ai không nhận yêu cầu thuê")
        logger.info(
            "Đã thuê instance %s (%s, %.3f USD/giờ)",
            result.get("new_contract"),
            offer.get("gpu_name"),
            offer["dph_total"],
        )

    def stop(self) -> None:
        """Destroy mọi instance mang nhãn worker."""
        for item in self._mine():
            self.call("DELETE", f"/instances/{item['id']}/", None)
            logger.info("Đã destroy instance %s", item["id"])


def provider_from_environment(environment: dict[str, str]) -> GpuProvider:
    """Dựng provider theo biến môi trường; thiếu biến bắt buộc → AutoscalerError nêu rõ tên biến."""
    api_key = environment.get("VAST_API_KEY")
    if not api_key:
        raise AutoscalerError("Thiếu VAST_API_KEY")
    call = http_transport(api_key)
    mode = environment.get("VAST_MODE", "instance")
    if mode == "instance":
        instance_id = environment.get("VAST_INSTANCE_ID")
        if not instance_id:
            raise AutoscalerError("VAST_MODE=instance cần VAST_INSTANCE_ID")
        return VastInstance(call, instance_id)
    if mode == "rent":
        image = environment.get("VAST_IMAGE")
        if not image:
            raise AutoscalerError("VAST_MODE=rent cần VAST_IMAGE")
        missing = [name for name in ("DATABASE_URL", "ARTIFACT_S3_BUCKET") if not environment.get(name)]
        if missing:
            raise AutoscalerError(f"Worker thuê mới cần DB + kho file chung; thiếu {', '.join(missing)}")
        return VastRental(
            call,
            RentSpec(
                image=image,
                min_gpu_ram_gb=float(environment.get("VAST_MIN_GPU_RAM_GB", "16")),
                max_dph=float(environment.get("VAST_MAX_DPH", "0.6")),
                disk_gb=int(environment.get("VAST_DISK_GB", "60")),
                min_reliability=float(environment.get("VAST_MIN_RELIABILITY", "0.98")),
                environment={name: environment[name] for name in WORKER_ENVIRONMENT if environment.get(name)},
            ),
        )
    raise AutoscalerError(f"VAST_MODE không hợp lệ: {mode}")


# --- vòng lặp ----------------------------------------------------------------


class Autoscaler:
    """Giữ mốc "lần cuối còn việc" giữa các chu kỳ; khởi động lại thì coi như vừa có việc (không tắt vội)."""

    def __init__(
        self,
        provider: GpuProvider,
        workload: Callable[[], Workload],
        idle_limit: timedelta,
        *,
        dry_run: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.provider, self.workload, self.idle_limit = provider, workload, idle_limit
        self.dry_run, self.clock = dry_run, clock
        self.last_active = clock()

    def tick(self) -> Action:
        """Một chu kỳ: đo việc, quyết định, gọi provider. Trả hành động đã chọn."""
        work = self.workload()
        now = self.clock()
        if work.active:
            self.last_active = now
        state = self.provider.state()
        action = decide(work, state, now - self.last_active, self.idle_limit)
        logger.info(
            "việc chờ=%d chạy=%d · GPU %s · rảnh %ds → %s%s",
            work.waiting,
            work.running,
            state,
            (now - self.last_active).total_seconds(),
            action,
            " (dry-run)" if self.dry_run and action != "none" else "",
        )
        if not self.dry_run:
            if action == "start":
                self.provider.start()
            elif action == "stop":
                self.provider.stop()
        return action


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="chạy một chu kỳ rồi thoát")
    parser.add_argument("--dry-run", action="store_true", help="chỉ ghi log quyết định, không bật/tắt gì")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        provider = provider_from_environment(dict(os.environ))
    except AutoscalerError as error:
        logger.error("%s", error)
        return 2
    scaler = Autoscaler(
        provider,
        measure_workload,
        timedelta(minutes=float(os.environ.get("GPU_IDLE_MINUTES", "10"))),
        dry_run=args.dry_run,
    )
    poll = float(os.environ.get("GPU_POLL_SECONDS", "30"))
    while True:
        try:
            scaler.tick()
        except AutoscalerError as error:
            # Lỗi nhà cung cấp/DB thoáng qua: ghi log, thử lại ở chu kỳ sau; không tự tắt GPU khi không chắc.
            logger.error("%s", error)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(poll)


if __name__ == "__main__":
    raise SystemExit(main())
