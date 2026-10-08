"""Admission theo live headroom: giữ config, chờ và tự dispatch khi đủ tài nguyên.

Observation trong DB chỉ giải thích vì sao chờ, bind manifest checksum. Durable
queue/lifecycle vẫn là JobManifest, không tạo attempt/revision khi poll tài nguyên.

Worker được nhận job thì ghi **giữ chỗ** (một dòng mỗi worker). Số đo tức thời không
thấy được phần tài nguyên một job vừa được nhận sẽ chiếm vài phút sau (VRAM chỉ bị
chiếm khi tới bước train), nên worker khác phải trừ phần đã giữ chỗ ra. Gate và ghi
giữ chỗ nằm trong cùng một transaction có khoá để hai worker không cùng qua.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.config import Settings
from src.models.contracts.artifacts import Checksum
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction
from src.services.orchestration.jobs.workspace import reclaim_worker_scratch
from src.services.orchestration.processing import (
    JobProcessingConfig,
    is_presets_file,
    job_config_reference,
    load_presets,
)
from src.services.orchestration.processing.capability import (
    bound_gpu,
    measure_capacity,
    measure_live_headroom,
    worker_identity,
)
from src.services.orchestration.processing.observed import (
    exhausted_before,
    load_usages,
    numeric_params,
    observed_budget,
)
from src.services.orchestration.processing.procfs import process_alive, process_table, process_tree
from src.services.orchestration.processing.resources import estimate_gb

if TYPE_CHECKING:
    from src.services.orchestration.projects.registry import ProjectRegistry

logger = logging.getLogger(__name__)
Resource = Literal["vram", "ram", "disk"]
#: Vì sao một tài nguyên chưa đủ:
#: - busy: pipeline (worker khác) đang giữ, sẽ tự hết khi job đó xong;
#: - external: thứ khác trên máy đang dùng, pipeline không tự giải phóng được;
#: - exceeds_machine: cấu hình vượt tổng năng lực của máy worker này;
#: - unmeasured: không đo được trên máy worker này.
WaitReason = Literal["busy", "external", "exceeds_machine", "unmeasured"]
RESOURCES: tuple[Resource, ...] = ("vram", "ram", "disk")
OperationKind = Literal["reobjectify", "import_package", "isaac_validate"]
OperationParentKind = Literal["job", "import"]
#: Observation/giữ chỗ không được làm mới quá mức này coi như worker đã dừng (bằng TTL số đo máy).
STALE_AFTER = timedelta(minutes=15)
#: Khoảng nghỉ giữa hai lần dọn scratch khi thiếu đĩa; dọn là quét thư mục, không cần mỗi lượt poll.
RECLAIM_INTERVAL_SECONDS = 300.0
_LOCK_KEY = "real2sim.runtime.resource-reservations"


class ResourceWait(BaseModel):
    """Snapshot chờ của đúng job revision, không chứa path hoặc secret."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    job_manifest_checksum: str
    checked_at: datetime
    required_gb: dict[Resource, float]
    available_gb: dict[Resource, float | None]
    waiting_on: list[Resource]
    #: `measured`: VRAM/RAM cần lấy từ số đo các lượt chạy trước; `configured_preview`: ước lượng theo cấu hình.
    estimate_scope: Literal["configured_preview", "measured"] = "configured_preview"
    #: Mặc định rỗng để đọc được observation do bản worker trước ghi.
    reasons: dict[Resource, WaitReason] = Field(default_factory=dict)
    capacity_gb: dict[Resource, float | None] = Field(default_factory=dict)
    #: Chưa có số đo cho cấu hình này (hoặc lượt trước hết bộ nhớ): job phải chạy một mình trên GPU.
    needs_exclusive_gpu: bool = False


class Reservation(BaseModel):
    """Phần tài nguyên worker đã nhận; optional fields đọc được cả payload job cũ."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    worker_id: str
    host: str
    pid: int
    gpu_uuid: str | None
    job_id: str | None = None
    #: None với job chưa có mô hình ước lượng (legacy profile): vẫn đánh dấu máy đang bận.
    required_gb: dict[Resource, float] | None
    #: Job chạy một mình trên GPU này: chưa có số đo nên không ai được chạy chung.
    exclusive: bool = False
    #: Pha đang chạy (preview hoặc hoàn tất), để ước tính thời gian chờ của hàng đợi.
    phase: Literal["preview", "finalize"] | None = None
    reserved_at: datetime
    heartbeat_at: datetime
    #: CPU-only operation vẫn giữ RAM/đĩa nhưng không chiếm VRAM/GPU.
    gpu_required: bool = True
    operation_kind: OperationKind | None = None
    operation_id: str | None = Field(default=None, min_length=1)
    parent_kind: OperationParentKind | None = None
    parent_id: str | None = Field(default=None, min_length=1)
    input_checksum: Checksum | None = None
    config_checksum: Checksum | None = None
    lease_token: str | None = Field(default=None, min_length=1)
    lease_generation: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _identity(self) -> Reservation:
        has_job = self.job_id is not None
        is_operation = self.operation_id is not None
        if has_job == is_operation:
            raise ValueError("reservation must bind exactly one job or operation identity")
        operation_fields = (
            self.operation_kind,
            self.parent_kind,
            self.parent_id,
            self.input_checksum,
            self.config_checksum,
        )
        if is_operation and any(value is None for value in operation_fields):
            raise ValueError("operation reservation is missing identity or checksum fields")
        if not is_operation and any(value is not None for value in operation_fields):
            raise ValueError("job reservation cannot contain operation identity fields")
        if (self.lease_token is None) != (self.lease_generation is None):
            raise ValueError("operation lease token and generation must be provided together")
        if not is_operation and (self.lease_token is not None or self.lease_generation is not None):
            raise ValueError("job reservation cannot contain operation lease fields")
        return self


class OperationResourceProfile(BaseModel):
    """Nhu cầu operation; None nghĩa là chưa có estimate nên phải chờ."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    required_gb: dict[Resource, float | None]
    danger_ratio: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    measured: bool
    gpu_required: bool = True

    @model_validator(mode="after")
    def _resources(self) -> OperationResourceProfile:
        if set(self.required_gb) != set(RESOURCES):
            raise ValueError("operation resource profile must declare VRAM, RAM and disk")
        if any(value is not None and (not isfinite(value) or value < 0) for value in self.required_gb.values()):
            raise ValueError("operation resource demand must be finite and non-negative")
        if not self.gpu_required and self.required_gb["vram"] not in (None, 0, 0.0):
            raise ValueError("CPU-only operation cannot declare a VRAM requirement")
        return self


class OperationAdmissionRequest(BaseModel):
    """Identity bất biến của một operation cần xét admission; không giả lập JobManifest."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    operation_kind: OperationKind
    operation_id: str = Field(min_length=1)
    parent_kind: OperationParentKind
    parent_id: str = Field(min_length=1)
    input_checksum: Checksum
    config_checksum: Checksum
    resources: OperationResourceProfile
    requested_gpu_uuid: str | None = None
    #: Per-attempt fencing pair. None remains valid for legacy/direct callers.
    lease_token: str | None = Field(default=None, min_length=1)
    lease_generation: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _request_contract(self) -> OperationAdmissionRequest:
        expected_parent = "import" if self.operation_kind == "import_package" else "job"
        if self.parent_kind != expected_parent:
            article = "an" if expected_parent == "import" else "a"
            raise ValueError(f"{self.operation_kind} operation must bind {article} {expected_parent} parent")
        if self.requested_gpu_uuid is not None and not self.resources.gpu_required:
            raise ValueError("CPU-only operation cannot request GPU affinity")
        if (self.lease_token is None) != (self.lease_generation is None):
            raise ValueError("operation lease token and generation must be provided together")
        return self


class OperationAdmissionResult(BaseModel):
    """Kết quả admission có identity, lý do chờ và số đo thật, không có ETA giả."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    request: OperationAdmissionRequest
    status: Literal["admitted", "waiting_resources", "waiting_gpu_affinity", "worker_busy", "identity_conflict"]
    bound_gpu_uuid: str | None = None
    required_gb: dict[Resource, float | None]
    available_gb: dict[Resource, float | None]
    capacity_gb: dict[Resource, float | None]
    waiting_on: list[Resource] = Field(default_factory=list)
    reasons: dict[Resource, WaitReason] = Field(default_factory=dict)
    needs_exclusive_gpu: bool = False


@dataclass(frozen=True)
class _ResourceDecision:
    waiting_on: list[Resource]
    reasons: dict[Resource, WaitReason]
    available_gb: dict[Resource, float | None]
    capacity_gb: dict[Resource, float | None]
    exclusive: bool


def resource_wait(database: RuntimeDatabase, job: JobManifest) -> ResourceWait | None:
    """Bỏ observation stale/revision khác; không sửa job khi API đọc tiến trình."""
    with database.transaction() as tx:
        row = tx.execute("SELECT payload FROM r2s_resource_waits WHERE job_id=?", (job.job_id,)).fetchone()
    if row is None:
        return None
    wait = ResourceWait.model_validate_json(row[0])
    if wait.job_manifest_checksum != job.job_manifest_checksum or datetime.now(UTC) - wait.checked_at > STALE_AFTER:
        return None
    return wait


def job_reservation(database: RuntimeDatabase, job_id: str) -> Reservation | None:
    """Giữ chỗ còn hiệu lực (chưa stale) của worker đang phục vụ job_id này."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_resource_reservations").fetchall()
    now = datetime.now(UTC)
    for (payload,) in rows:
        try:
            reservation = Reservation.model_validate_json(payload)
            if reservation.job_id == job_id and now - reservation.heartbeat_at <= STALE_AFTER:
                return reservation
        except Exception:
            continue
    return None


def touch_job_reservation(database: RuntimeDatabase, job_id: str) -> None:
    """Làm mới heartbeat_at cho reservation của job_id để updated_at luôn tươi mới."""
    try:
        with database.transaction(write=True) as tx:
            rows = tx.execute("SELECT worker_id, payload FROM r2s_resource_reservations").fetchall()
            now = datetime.now(UTC)
            for worker_id, payload in rows:
                try:
                    reservation = Reservation.model_validate_json(payload)
                    if reservation.job_id == job_id:
                        updated = reservation.model_copy(update={"heartbeat_at": now})
                        tx.execute(
                            "UPDATE r2s_resource_reservations SET payload=? WHERE worker_id=?",
                            (updated.model_dump_json(), worker_id),
                        )
                except Exception:
                    continue
    except Exception as error:  # noqa: BLE001 - ghi heartbeat không được làm gián đoạn worker
        logger.debug("Không thể cập nhật heartbeat reservation cho job %s cause=%s", job_id, type(error).__name__)


Phase = Literal["preview", "finalize"]
#: Công cụ runner chạy trong mỗi lần nhận job; ngân sách đo được phải phủ hết các công cụ này.
PHASE_TOOLS: dict[Phase, tuple[str, ...]] = {"preview": ("preview",), "finalize": ("finalize", "scene_extract")}
#: Bước phụ trợ chạy cùng lần nhận job nhưng chỉ khi deployment bật (đề xuất tỉ lệ bằng MoGe-2).
PHASE_OPTIONAL_TOOLS: dict[Phase, tuple[str, ...]] = {"preview": ("metric_proposal",), "finalize": ()}


class Demand(BaseModel):
    """Nhu cầu tài nguyên của một lần nhận job và độ tin của nó."""

    model_config = ConfigDict(extra="forbid")

    required_gb: dict[Resource, float]
    danger_ratio: float
    #: True: VRAM/RAM lấy từ số đo → được chạy chung GPU. False: chỉ có ước lượng → phải chạy một mình.
    measured: bool
    #: Mặc định giữ tương thích mọi caller reconstruction job hiện tại.
    gpu_required: bool = True


def job_drivers(registry: ProjectRegistry, settings: Settings, job: JobManifest) -> dict[str, float] | None:
    """Thông số số học của cấu hình job (khoá tra số đo); None với job legacy hoặc cấu hình không đọc được."""
    path = settings.product_processing_config
    profile = registry.execution_profile
    if path is None or profile is None or job.config_checksum == profile.config_checksum or not is_presets_file(path):
        return None
    try:
        presets, _ = load_presets(path)
        config_path = registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
        config = JobProcessingConfig.model_validate_json(config_path.read_bytes())
        return numeric_params(presets.validate_params(config.params))
    except (ArtifactStoreError, OSError, ValueError):
        return None


class ResourceAdmission:
    """Gate của một worker; không hạ cấu hình.

    Quy tắc chạy chung GPU: job chỉ được chạy cùng job khác khi đã có **số đo** chứng minh nó
    vừa (`processing/observed.py`). Chưa có số đo — cấu hình mới, máy mới, job legacy, hoặc lượt
    trước của job chết vì hết bộ nhớ — thì job chạy một mình trên GPU; lượt đó tạo ra số đo cho
    các job sau. Khi chạy một mình, VRAM không bị so với ước lượng: ước lượng sai không được
    giữ job chờ vô hạn.

    Một instance cho mỗi tiến trình worker. `__call__` trả True thì worker đang giữ chỗ
    cho job đó tới khi `release()`; heartbeat gọi `touch()` để giữ chỗ không hết hạn.
    """

    def __init__(self, registry: ProjectRegistry, settings: Settings) -> None:
        if registry.persistence is None:
            raise ValueError("Resource admission cần durable registry")
        self.registry = registry
        self.settings = settings
        self.database = registry.persistence.database
        self.worker_id, self.host, self.pid = worker_identity()
        self._reserved = False
        self._last_reclaim: float | None = None
        self._disk_short = False
        settings.product_worker_root.mkdir(parents=True, exist_ok=True)

    # --- Ước lượng của job ---------------------------------------------------

    def _demand(self, job: JobManifest, phase: Phase, gpu_name: str | None) -> Demand | None:
        """Nhu cầu của job cho lần nhận này; None khi job chưa có mô hình ước lượng (legacy)."""
        path = self.settings.product_processing_config
        profile = self.registry.execution_profile
        if (
            path is None
            or profile is None
            or job.config_checksum == profile.config_checksum
            or not is_presets_file(path)
        ):
            # Legacy tool profile chưa có resource model; không bịa yêu cầu tối thiểu.
            logger.info("Resource admission chưa có estimate cho legacy profile")
            return None
        try:
            presets, _ = load_presets(path)
            config_path = self.registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
            config = JobProcessingConfig.model_validate_json(config_path.read_bytes())
            params = presets.validate_params(config.params)
            estimate = estimate_gb(presets.resource_model, params)
        except (ArtifactStoreError, OSError, ValueError) as error:
            # Cấu hình không đọc được là lỗi của job, không phải thiếu tài nguyên: cho qua để
            # runner báo lỗi theo đường có sẵn (ghi FAILED đúng stage), thay vì chờ vô hạn.
            logger.warning("Không đọc được cấu hình job để ước lượng cause=%s", type(error).__name__)
            return None
        usages = load_usages(self.database)
        budget = None
        if not exhausted_before(usages, job.job_id):
            budget = observed_budget(
                usages,
                tools=PHASE_TOOLS[phase],
                optional_tools=PHASE_OPTIONAL_TOOLS[phase],
                params=numeric_params(params),
                gpu_name=gpu_name,
                runtime_manifest_checksum=job.runtime_manifest_checksum,
            )
        if budget is None:
            return Demand(required_gb=estimate, danger_ratio=presets.resource_model.danger_ratio, measured=False)
        # Đĩa vẫn theo ước lượng: số đo scratch chỉ là phần trong workspace, chưa gồm artifact publish.
        required: dict[Resource, float] = {
            "vram": round(budget["vram"], 2),
            "ram": round(budget["ram"], 2),
            "disk": estimate["disk"],
        }
        return Demand(required_gb=required, danger_ratio=presets.resource_model.danger_ratio, measured=True)

    def operation_profile_for_job(self, job: JobManifest, *, gpu_required: bool) -> OperationResourceProfile:
        """Use the job's existing finalize resource model for a heavy scene operation.

        A missing estimate stays explicitly unknown. CPU-only operations keep their
        RAM/disk checks while declaring zero VRAM demand.
        """
        gpu = bound_gpu()
        demand = self._demand(job, "finalize", gpu.name if gpu is not None else None)
        if demand is None:
            return OperationResourceProfile(
                required_gb={"vram": None if gpu_required else 0.0, "ram": None, "disk": None},
                danger_ratio=None,
                measured=False,
                gpu_required=gpu_required,
            )
        required = dict(demand.required_gb)
        if not gpu_required:
            required["vram"] = 0.0
        return OperationResourceProfile(
            required_gb=required,
            danger_ratio=demand.danger_ratio,
            measured=demand.measured,
            gpu_required=gpu_required,
        )

    # --- Giữ chỗ -------------------------------------------------------------

    def _lock(self, tx: RuntimeTransaction) -> None:
        """PostgreSQL: khoá theo transaction; SQLite đã khoá ghi bằng BEGIN IMMEDIATE."""
        if tx.postgres:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (_LOCK_KEY,))

    def _alive(self, reservation: Reservation, now: datetime) -> bool:
        if now - reservation.heartbeat_at > STALE_AFTER:
            return False
        # Cùng host thì kiểm thẳng tiến trình: worker bị kill không kịp nhả giữ chỗ.
        return reservation.host != self.host or process_alive(reservation.pid)

    def _others(self, tx: RuntimeTransaction, now: datetime) -> list[Reservation]:
        """Giữ chỗ còn sống của worker khác; dòng đã chết được xoá tại chỗ."""
        alive: list[Reservation] = []
        for worker_id, payload in tx.execute("SELECT worker_id, payload FROM r2s_resource_reservations").fetchall():
            if worker_id == self.worker_id:
                continue
            reservation = Reservation.model_validate_json(payload)
            if self._alive(reservation, now):
                alive.append(reservation)
            else:
                tx.execute("DELETE FROM r2s_resource_reservations WHERE worker_id=?", (worker_id,))
        return alive

    def _reserve(
        self,
        tx: RuntimeTransaction,
        job: JobManifest,
        required: dict[Resource, float] | None,
        gpu_uuid: str | None,
        *,
        exclusive: bool,
        phase: Phase | None = None,
        gpu_required: bool = True,
    ) -> None:
        self._write_reservation(
            tx,
            required=required,
            gpu_uuid=gpu_uuid,
            exclusive=exclusive,
            phase=phase,
            gpu_required=gpu_required,
            job_id=job.job_id,
        )

    def _write_reservation(
        self,
        tx: RuntimeTransaction,
        *,
        required: dict[Resource, float] | None,
        gpu_uuid: str | None,
        exclusive: bool,
        phase: Phase | None,
        gpu_required: bool,
        job_id: str | None = None,
        operation: OperationAdmissionRequest | None = None,
    ) -> None:
        now = datetime.now(UTC)
        reservation = Reservation(
            worker_id=self.worker_id,
            host=self.host,
            pid=self.pid,
            gpu_uuid=gpu_uuid,
            job_id=job_id,
            required_gb=required,
            exclusive=exclusive,
            phase=phase,
            reserved_at=now,
            heartbeat_at=now,
            gpu_required=gpu_required,
            operation_kind=operation.operation_kind if operation is not None else None,
            operation_id=operation.operation_id if operation is not None else None,
            parent_kind=operation.parent_kind if operation is not None else None,
            parent_id=operation.parent_id if operation is not None else None,
            input_checksum=operation.input_checksum if operation is not None else None,
            config_checksum=operation.config_checksum if operation is not None else None,
            lease_token=operation.lease_token if operation is not None else None,
            lease_generation=operation.lease_generation if operation is not None else None,
        )
        tx.execute(
            "INSERT INTO r2s_resource_reservations(worker_id,payload) VALUES (?,?) "
            "ON CONFLICT(worker_id) DO UPDATE SET payload=excluded.payload",
            (
                self.worker_id,
                reservation.model_dump_json(
                    exclude={
                        "gpu_required",
                        "operation_kind",
                        "operation_id",
                        "parent_kind",
                        "parent_id",
                        "input_checksum",
                        "config_checksum",
                        "lease_token",
                        "lease_generation",
                    }
                    if job_id is not None
                    else None
                ),
            ),
        )
        self._reserved = True

    def discard_leftover_reservation(self) -> bool:
        """Xoá dòng giữ chỗ còn sót của lần chạy trước có cùng worker_id.

        Container restart giữ nguyên hostname và PID nên worker_id không đổi. Tại thời điểm worker
        khởi động nó chưa giữ gì, nên dòng này chỉ có thể do lần chạy trước bị kill để lại; nếu là
        giữ chỗ của một operation thì nó chặn mọi job và operation của chính worker này vĩnh viễn
        (`_others` không bao giờ xét dòng của chính mình là stale).
        """
        with self.database.transaction(write=True) as tx:
            self._lock(tx)
            deleted = tx.execute("DELETE FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)).rowcount
        self._reserved = False
        return bool(deleted)

    def release(self) -> None:
        """Nhả giữ chỗ của worker này; lỗi DB chỉ log (dòng sẽ tự hết hạn)."""
        if not self._reserved:
            return
        try:
            with self.database.transaction(write=True) as tx:
                tx.execute("DELETE FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,))
            self._reserved = False
        except Exception as error:  # noqa: BLE001 - ranh giới DB: không che kết quả job vừa chạy
            logger.warning("Không nhả được giữ chỗ tài nguyên cause=%s", type(error).__name__)

    def touch(self) -> None:
        """Làm mới giữ chỗ đang có (heartbeat gọi); job dài không bị coi là worker chết."""
        if not self._reserved:
            return
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)
            ).fetchone()
            if row is None:
                return
            reservation = Reservation.model_validate_json(row[0]).model_copy(update={"heartbeat_at": datetime.now(UTC)})
            tx.execute(
                "UPDATE r2s_resource_reservations SET payload=? WHERE worker_id=?",
                (reservation.model_dump_json(), self.worker_id),
            )

    def touch_operation(self, request: OperationAdmissionRequest) -> bool:
        """Heartbeat only the reservation owned by this exact operation lease."""
        try:
            with self.database.transaction(write=True) as tx:
                row = tx.execute(
                    "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)
                ).fetchone()
                if row is None:
                    return False
                reservation = Reservation.model_validate_json(row[0])
                if not self._same_operation_lease(reservation, request):
                    return False
                touched = reservation.model_copy(update={"heartbeat_at": datetime.now(UTC)})
                tx.execute(
                    "UPDATE r2s_resource_reservations SET payload=? WHERE worker_id=?",
                    (touched.model_dump_json(), self.worker_id),
                )
                return True
        except Exception as error:  # noqa: BLE001 - missed heartbeats are fenced by the lease and TTL
            logger.warning(
                "Operation reservation heartbeat lỗi operation=%s cause=%s",
                request.operation_id,
                type(error).__name__,
            )
            return False

    def operation_lease_is_current(self, tx: RuntimeTransaction, request: OperationAdmissionRequest) -> bool:
        """Check the exact reservation from the scene-head commit transaction."""
        row = tx.execute(
            "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?" + tx.lock_suffix(),
            (self.worker_id,),
        ).fetchone()
        if row is None:
            return False
        reservation = Reservation.model_validate_json(row[0])
        return self._same_operation_lease(reservation, request)

    def machine_idle(self) -> bool:
        """Pipeline không dùng máy này: worker không có tiến trình con, không ai giữ chỗ ở đây.

        Dùng để ghi mốc "máy rảnh" cho preset Maximum. Không kiểm được thì coi là bận.
        """
        table = process_table()
        if table is None or len(process_tree(table, {self.pid})) > 1:
            return False
        gpu = bound_gpu()
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            self._lock(tx)
            own = tx.execute("SELECT 1 FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)).fetchone()
            gpu_uuid = gpu.uuid if gpu is not None else None
            others = [
                item for item in self._others(tx, now) if any(self._shares(item, name, gpu_uuid) for name in RESOURCES)
            ]
        return own is None and not others

    def _shares(self, other: Reservation, resource: Resource, gpu_uuid: str | None) -> bool:
        """Worker kia có dùng chung tài nguyên này với worker này không (VRAM theo GPU, còn lại theo máy)."""
        if resource == "vram" and not other.gpu_required:
            return False
        if resource == "vram" and gpu_uuid is not None and other.gpu_uuid is not None:
            return other.gpu_uuid == gpu_uuid
        return other.host == self.host

    # --- Gate ----------------------------------------------------------------

    def _resource_snapshot(self) -> tuple[dict[Resource, float | None], dict[Resource, float | None]]:
        root = self.settings.product_worker_root
        live = measure_live_headroom(root)
        capacity = measure_capacity(root)
        free: dict[Resource, float | None] = {
            "vram": live["vram_free_gb"],
            "ram": live["ram_available_gb"],
            "disk": live["disk_free_gb"],
        }
        total: dict[Resource, float | None] = {name: capacity[name] for name in RESOURCES}
        return free, total

    def _assess(
        self,
        demand: Demand | OperationResourceProfile | None,
        gpu_uuid: str | None,
        others: list[Reservation],
        free: dict[Resource, float | None],
        total: dict[Resource, float | None],
        *,
        strict_unknown: bool,
    ) -> _ResourceDecision:
        """Dùng chung phép tính headroom cho job và operation, không ghi DB hoặc giả estimate."""
        gpu_required = demand is None or demand.gpu_required
        gpu_peers = [item for item in others if self._shares(item, "vram", gpu_uuid)] if gpu_required else []
        exclusive = demand is None or (gpu_required and not demand.measured)
        available: dict[Resource, float | None] = {}
        sharing: dict[Resource, bool] = {}
        for name in RESOURCES:
            if name == "vram" and not gpu_required:
                available[name] = None
                sharing[name] = False
                continue
            peers = gpu_peers if name == "vram" else [item for item in others if self._shares(item, name, gpu_uuid)]
            sharing[name] = bool(peers)
            held = sum(item.required_gb[name] for item in peers if item.required_gb is not None)
            value = free[name]
            if value is not None and held > 0 and total[name] is not None:
                value = max(0.0, min(value, total[name] - held))
            if name == "vram" and any(item.exclusive for item in peers):
                value = 0.0
            available[name] = value

        if demand is None:
            # Compatibility path: legacy job chưa có resource model chỉ yêu cầu GPU rảnh.
            waiting = ["vram"] if gpu_peers else []
            reasons: dict[Resource, WaitReason] = {"vram": "busy"} if gpu_peers else {}
            return _ResourceDecision(waiting, reasons, available, total, exclusive)

        waiting = []
        reasons = {}
        for name in RESOURCES:
            if name == "vram" and not gpu_required:
                continue
            have = available[name]
            need = demand.required_gb[name]
            danger_ratio = demand.danger_ratio
            if need is None or danger_ratio is None:
                waiting.append(name)
                reasons[name] = "unmeasured"
                continue
            if name == "vram" and exclusive:
                # Legacy jobs measure unknown configurations exclusively. Operations require a
                # concrete headroom reading before admission, even when they will run alone.
                if gpu_peers:
                    waiting.append(name)
                    reasons[name] = "busy"
                    continue
                if not strict_unknown:
                    continue
            if have is not None and need < have * danger_ratio:
                continue
            waiting.append(name)
            if have is None:
                reasons[name] = "unmeasured"
            elif total[name] is not None and need >= total[name] * danger_ratio:
                reasons[name] = "exceeds_machine"
            else:
                reasons[name] = "busy" if sharing[name] else "external"
        return _ResourceDecision(waiting, reasons, available, total, exclusive)

    def _decide(self, job: JobManifest, demand: Demand | None, gpu_uuid: str | None, phase: Phase) -> bool:
        """Đo, trừ phần worker khác đã giữ, rồi ghi giữ chỗ hoặc observation chờ trong một transaction."""
        free, total = self._resource_snapshot()
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            self._lock(tx)
            own = tx.execute(
                "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)
            ).fetchone()
            if own is not None and Reservation.model_validate_json(own[0]).operation_id is not None:
                return False
            others = self._others(tx, now)
            decision = self._assess(demand, gpu_uuid, others, free, total, strict_unknown=False)
            if demand is None and decision.waiting_on:
                # Giữ nguyên semantics lịch sử: legacy jobs chờ GPU nhưng không tạo ResourceWait giả.
                return False
            if decision.waiting_on:
                assert demand is not None
                observation = ResourceWait(
                    job_manifest_checksum=job.job_manifest_checksum,
                    checked_at=now,
                    required_gb=demand.required_gb,
                    available_gb=decision.available_gb,
                    waiting_on=decision.waiting_on,
                    estimate_scope="measured" if demand.measured else "configured_preview",
                    reasons=decision.reasons,
                    capacity_gb=decision.capacity_gb,
                    needs_exclusive_gpu=decision.exclusive,
                )
                tx.execute(
                    "INSERT INTO r2s_resource_waits(job_id,payload) VALUES (?,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload",
                    (job.job_id, observation.model_dump_json()),
                )
                tx.execute("DELETE FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,))
                self._reserved = False
                self._disk_short = "disk" in decision.waiting_on and decision.reasons["disk"] != "exceeds_machine"
            else:
                tx.execute("DELETE FROM r2s_resource_waits WHERE job_id=?", (job.job_id,))
                self._reserve(
                    tx,
                    job,
                    demand.required_gb if demand is not None else None,
                    gpu_uuid if demand is None or demand.gpu_required else None,
                    exclusive=decision.exclusive,
                    phase=phase,
                    gpu_required=demand is None or demand.gpu_required,
                )
                self._disk_short = False
        return not decision.waiting_on

    @staticmethod
    def _same_operation_identity(reservation: Reservation, request: OperationAdmissionRequest) -> bool:
        return (
            reservation.operation_kind == request.operation_kind
            and reservation.operation_id == request.operation_id
            and reservation.parent_kind == request.parent_kind
            and reservation.parent_id == request.parent_id
            and reservation.input_checksum == request.input_checksum
            and reservation.config_checksum == request.config_checksum
        )

    @staticmethod
    def _same_operation_lease(reservation: Reservation, request: OperationAdmissionRequest) -> bool:
        return (
            ResourceAdmission._same_operation_identity(reservation, request)
            and reservation.lease_token == request.lease_token
            and reservation.lease_generation == request.lease_generation
        )

    @staticmethod
    def _operation_result(
        request: OperationAdmissionRequest,
        status: Literal["admitted", "waiting_resources", "waiting_gpu_affinity", "worker_busy", "identity_conflict"],
        *,
        bound_gpu_uuid: str | None = None,
        available: dict[Resource, float | None] | None = None,
        capacity: dict[Resource, float | None] | None = None,
        decision: _ResourceDecision | None = None,
    ) -> OperationAdmissionResult:
        empty: dict[Resource, float | None] = {name: None for name in RESOURCES}
        return OperationAdmissionResult(
            request=request,
            status=status,
            bound_gpu_uuid=bound_gpu_uuid,
            required_gb=request.resources.required_gb,
            available_gb=decision.available_gb if decision is not None else available or empty,
            capacity_gb=decision.capacity_gb if decision is not None else capacity or empty,
            waiting_on=decision.waiting_on if decision is not None else [],
            reasons=decision.reasons if decision is not None else {},
            needs_exclusive_gpu=decision.exclusive if decision is not None else False,
        )

    def admit_operation(self, request: OperationAdmissionRequest) -> OperationAdmissionResult:
        """Reserve resource theo operation identity mà không dựng JobManifest giả.

        Estimate/headroom không biết được thì trả waiting_resources và giữ nguyên request;
        người gọi có thể persist đúng checksum/config trong queue của operation.
        """
        bound_gpu_uuid: str | None = None
        try:
            gpu = bound_gpu()
            bound_gpu_uuid = gpu.uuid if gpu is not None else None
            gpu_uuid = bound_gpu_uuid if request.resources.gpu_required else None
            if request.requested_gpu_uuid is not None and bound_gpu_uuid != request.requested_gpu_uuid:
                return self._operation_result(
                    request,
                    "waiting_gpu_affinity",
                    bound_gpu_uuid=bound_gpu_uuid,
                )
            free, total = self._resource_snapshot()
            now = datetime.now(UTC)
            with self.database.transaction(write=True) as tx:
                self._lock(tx)
                own = tx.execute(
                    "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)
                ).fetchone()
                if own is not None:
                    reservation = Reservation.model_validate_json(own[0])
                    if reservation.operation_id is not None:
                        if reservation.operation_id == request.operation_id and not self._same_operation_identity(
                            reservation, request
                        ):
                            return self._operation_result(
                                request,
                                "identity_conflict",
                                bound_gpu_uuid=bound_gpu_uuid,
                                available=free,
                                capacity=total,
                            )
                    return self._operation_result(
                        request,
                        "worker_busy",
                        bound_gpu_uuid=bound_gpu_uuid,
                        available=free,
                        capacity=total,
                    )

                others = self._others(tx, now)
                for reservation in others:
                    if reservation.operation_id != request.operation_id:
                        continue
                    status = (
                        "worker_busy" if self._same_operation_identity(reservation, request) else "identity_conflict"
                    )
                    return self._operation_result(
                        request,
                        status,
                        bound_gpu_uuid=bound_gpu_uuid,
                        available=free,
                        capacity=total,
                    )
                decision = self._assess(
                    request.resources,
                    gpu_uuid,
                    others,
                    free,
                    total,
                    strict_unknown=True,
                )
                if request.resources.gpu_required and gpu is None and "vram" not in decision.waiting_on:
                    decision.waiting_on.append("vram")
                    decision.reasons["vram"] = "unmeasured"
                if decision.waiting_on:
                    return self._operation_result(
                        request,
                        "waiting_resources",
                        bound_gpu_uuid=bound_gpu_uuid,
                        decision=decision,
                    )

                required = {name: float(request.resources.required_gb[name] or 0.0) for name in RESOURCES}
                self._write_reservation(
                    tx,
                    required=required,
                    gpu_uuid=gpu_uuid,
                    exclusive=decision.exclusive,
                    phase=None,
                    gpu_required=request.resources.gpu_required,
                    operation=request,
                )
                return self._operation_result(
                    request,
                    "admitted",
                    bound_gpu_uuid=bound_gpu_uuid,
                    decision=decision,
                )
        except Exception as error:  # noqa: BLE001 - gate failure must fail closed and preserve queue input
            logger.warning(
                "Operation resource admission lỗi operation=%s cause=%s",
                request.operation_id,
                type(error).__name__,
            )
            waiting = [name for name in RESOURCES if name != "vram" or request.resources.gpu_required]
            return OperationAdmissionResult(
                request=request,
                status="waiting_resources",
                bound_gpu_uuid=bound_gpu_uuid,
                required_gb=request.resources.required_gb,
                available_gb={name: None for name in RESOURCES},
                capacity_gb={name: None for name in RESOURCES},
                waiting_on=waiting,
                reasons={name: "unmeasured" for name in waiting},
                needs_exclusive_gpu=request.resources.gpu_required and not request.resources.measured,
            )

    def release_operation(self, request: OperationAdmissionRequest) -> bool:
        """Compare-and-delete operation reservation; repeated release is safe."""
        try:
            with self.database.transaction(write=True) as tx:
                self._lock(tx)
                row = tx.execute(
                    "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,)
                ).fetchone()
                if row is None:
                    self._reserved = False
                    return True
                reservation = Reservation.model_validate_json(row[0])
                if not self._same_operation_lease(reservation, request):
                    return False
                tx.execute("DELETE FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,))
                self._reserved = False
                return True
        except Exception as error:  # noqa: BLE001 - a failed compare-delete must not release another owner
            logger.warning(
                "Operation reservation release lỗi operation=%s cause=%s",
                request.operation_id,
                type(error).__name__,
            )
            return False

    def shares_gpu(self) -> bool | None:
        """Có worker khác đang giữ chỗ trên GPU của worker này không; None khi không kiểm được."""
        try:
            gpu = bound_gpu()
            with self.database.transaction(write=True) as tx:
                self._lock(tx)
                others = self._others(tx, datetime.now(UTC))
            return any(self._shares(item, "vram", gpu.uuid if gpu is not None else None) for item in others)
        except Exception as error:  # noqa: BLE001 - chỉ là nhãn của số đo, không được chặn job
            logger.warning("Không kiểm được GPU có chạy chung không cause=%s", type(error).__name__)
            return None

    def _reclaim_disk(self, job: JobManifest) -> bool:
        """Thiếu đĩa: dọn scratch không còn ai dùng và thùng rác quá hạn. Trả True nếu đã thử dọn."""
        now = time.monotonic()
        if self._last_reclaim is not None and now - self._last_reclaim < RECLAIM_INTERVAL_SECONDS:
            return False
        self._last_reclaim = now
        from src.services.orchestration.projects.deletion import context_from_settings, purge_expired

        with self.database.transaction(write=True) as tx:
            self._lock(tx)
            protected = {
                item.job_id if item.job_id is not None else item.parent_id
                for item in self._others(tx, datetime.now(UTC))
                if item.host == self.host
                and (item.job_id is not None or (item.parent_kind == "job" and item.parent_id is not None))
            }
        result = reclaim_worker_scratch(
            worker_root=self.settings.product_worker_root,
            artifact_root=self.registry.runtime_resolver.artifact_root,
            protected_jobs=protected,
        )
        purged = purge_expired(context_from_settings(self.settings))
        logger.info(
            "Thiếu đĩa cho job=%s: dọn scratch files=%s bytes=%s errors=%s, thùng rác quá hạn=%s",
            job.job_id,
            result.files_removed,
            result.bytes_removed,
            result.errors,
            len(purged),
        )
        return True

    def __call__(self, job: JobManifest, phase: Phase = "preview") -> bool:
        """True khi worker được nhận job (và đã giữ chỗ); ngược lại giữ nguyên queue/config và ghi diagnostic.

        Lỗi của chính gate (DB, quét thư mục) không được đổi trạng thái job: trả False để
        lượt poll sau thử lại.
        """
        try:
            gpu = bound_gpu()
            gpu_uuid = gpu.uuid if gpu is not None else None
            demand = self._demand(job, phase, gpu.name if gpu is not None else None)
            admitted = self._decide(job, demand, gpu_uuid, phase)
            if not admitted and self._disk_short and self._reclaim_disk(job):
                admitted = self._decide(job, demand, gpu_uuid, phase)
            return admitted
        except Exception as error:  # noqa: BLE001 - ranh giới gate: lỗi đo/ghi observation không phải lỗi của job
            logger.warning("Resource admission lỗi, thử lại lượt sau job=%s cause=%s", job.job_id, type(error).__name__)
            return False
