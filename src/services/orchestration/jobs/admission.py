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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings
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
    """Phần tài nguyên một worker đã nhận trách nhiệm dùng cho job đang chạy."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    worker_id: str
    host: str
    pid: int
    gpu_uuid: str | None
    job_id: str
    #: None với job chưa có mô hình ước lượng (legacy profile): vẫn đánh dấu máy đang bận.
    required_gb: dict[Resource, float] | None
    #: Job chạy một mình trên GPU này: chưa có số đo nên không ai được chạy chung.
    exclusive: bool = False
    #: Pha đang chạy (preview hoặc hoàn tất), để ước tính thời gian chờ của hàng đợi.
    phase: Literal["preview", "finalize"] | None = None
    reserved_at: datetime
    heartbeat_at: datetime


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
    ) -> None:
        now = datetime.now(UTC)
        reservation = Reservation(
            worker_id=self.worker_id,
            host=self.host,
            pid=self.pid,
            gpu_uuid=gpu_uuid,
            job_id=job.job_id,
            required_gb=required,
            exclusive=exclusive,
            phase=phase,
            reserved_at=now,
            heartbeat_at=now,
        )
        tx.execute(
            "INSERT INTO r2s_resource_reservations(worker_id,payload) VALUES (?,?) "
            "ON CONFLICT(worker_id) DO UPDATE SET payload=excluded.payload",
            (self.worker_id, reservation.model_dump_json()),
        )
        self._reserved = True

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
        if resource == "vram" and gpu_uuid is not None and other.gpu_uuid is not None:
            return other.gpu_uuid == gpu_uuid
        return other.host == self.host

    # --- Gate ----------------------------------------------------------------

    def _decide(self, job: JobManifest, demand: Demand | None, gpu_uuid: str | None, phase: Phase) -> bool:
        """Đo, trừ phần worker khác đã giữ, rồi ghi giữ chỗ hoặc observation chờ trong một transaction.

        `demand` None (job legacy) hoặc `measured=False` nghĩa là chưa biết job dùng bao nhiêu:
        chỉ nhận khi không worker nào khác đang dùng GPU này, và giữ cả GPU cho nó.
        """
        root = self.settings.product_worker_root
        live = measure_live_headroom(root)
        capacity = measure_capacity(root)
        free: dict[Resource, float | None] = {
            "vram": live["vram_free_gb"],
            "ram": live["ram_available_gb"],
            "disk": live["disk_free_gb"],
        }
        total: dict[Resource, float | None] = {name: capacity[name] for name in RESOURCES}
        exclusive = demand is None or not demand.measured
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            self._lock(tx)
            others = self._others(tx, now)
            gpu_peers = [item for item in others if self._shares(item, "vram", gpu_uuid)]
            if demand is None:
                # Job legacy: không có con số nào để so; chỉ cần GPU không có ai.
                if gpu_peers:
                    return False
                self._reserve(tx, job, None, gpu_uuid, exclusive=True, phase=phase)
                return True
            required, danger_ratio = demand.required_gb, demand.danger_ratio
            available: dict[Resource, float | None] = {}
            sharing: dict[Resource, bool] = {}
            for name in RESOURCES:
                # VRAM chia theo GPU; RAM và đĩa chia theo máy.
                peers = gpu_peers if name == "vram" else [item for item in others if self._shares(item, name, gpu_uuid)]
                sharing[name] = bool(peers)
                held = sum(item.required_gb[name] for item in peers if item.required_gb is not None)
                value = free[name]
                if value is not None and held > 0 and total[name] is not None:
                    # Job vừa được nhận chưa chiếm hết phần của nó: không tính phần đó là còn trống.
                    value = max(0.0, min(value, total[name] - held))
                if name == "vram" and any(item.exclusive for item in peers):
                    value = 0.0  # Job kia đang chạy một mình để đo: không ai được chạy chung.
                available[name] = value
            waiting: list[Resource] = []
            reasons: dict[Resource, WaitReason] = {}
            for name in RESOURCES:
                have = available[name]
                if name == "vram" and exclusive:
                    # Chưa có số đo: không so VRAM với ước lượng (ước lượng sai sẽ giữ job chờ vô hạn);
                    # điều kiện duy nhất là GPU không có job nào khác của pipeline.
                    if gpu_peers:
                        waiting.append(name)
                        reasons[name] = "busy"
                    continue
                if have is not None and required[name] < have * danger_ratio:
                    continue
                waiting.append(name)
                if have is None:
                    reasons[name] = "unmeasured"
                elif total[name] is not None and required[name] >= total[name] * danger_ratio:
                    reasons[name] = "exceeds_machine"
                else:
                    reasons[name] = "busy" if sharing[name] else "external"
            if waiting:
                observation = ResourceWait(
                    job_manifest_checksum=job.job_manifest_checksum,
                    checked_at=now,
                    required_gb=required,
                    available_gb=available,
                    waiting_on=waiting,
                    estimate_scope="measured" if demand.measured else "configured_preview",
                    reasons=reasons,
                    capacity_gb=total,
                    needs_exclusive_gpu=exclusive,
                )
                tx.execute(
                    "INSERT INTO r2s_resource_waits(job_id,payload) VALUES (?,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload",
                    (job.job_id, observation.model_dump_json()),
                )
                tx.execute("DELETE FROM r2s_resource_reservations WHERE worker_id=?", (self.worker_id,))
                self._reserved = False
                self._disk_short = "disk" in waiting and reasons["disk"] != "exceeds_machine"
            else:
                tx.execute("DELETE FROM r2s_resource_waits WHERE job_id=?", (job.job_id,))
                self._reserve(tx, job, required, gpu_uuid, exclusive=exclusive, phase=phase)
                self._disk_short = False
        return not waiting

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
            protected = {item.job_id for item in self._others(tx, datetime.now(UTC)) if item.host == self.host}
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
