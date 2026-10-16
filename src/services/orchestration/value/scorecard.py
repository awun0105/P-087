"""Bảng metric giá trị (architecture §15.1–§15.3): gom mọi nguồn thành `ValueScorecard` và xuất JSON / CSV / Markdown.

Phần tính toán là hàm thuần trên dữ liệu đã đọc (sự kiện, usage, ground truth, collision), để test không cần scene thật.
Mọi số thiếu dữ liệu là `unavailable` kèm lý do; không bao giờ ghi 0 giả.
"""

import csv
import io
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from src.config import Settings
from src.models.contracts.coordinates import MetricScaleStatus
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import RuleResult, ValidationReport
from src.models.contracts.validation_run import ValidationRunStatus
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.benchmark import BENCHMARK_KIND, PipelineRuntimeBenchmark
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.models import MachineCapability
from src.services.orchestration.processing.observed import (
    billed_usages,
    load_usages,
    processing_seconds,
    usage_vram,
)
from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.simulation_package import current_package
from src.services.orchestration.review.validation_runs import ValidationRunError, ValidationRunRepository
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.value.events import ValueEvent, list_events
from src.services.orchestration.value.ground_truth import BenchmarkTruth, StoredTruth, read_truth
from src.services.orchestration.value.measure import (
    CollisionWorld,
    DistanceResult,
    GapResult,
    MoveResult,
    collision_world,
    distance_error,
    gap_width,
    move_consistency,
)
from src.services.scene.geometry_state import object_geometry_state

Provenance = Literal["measured", "declared", "unavailable"]
DATA_SOURCE_LABELS = {"self_capture": "Tự quay", "hf_room": "HF room", "synthetic": "Tổng hợp"}
_PROVENANCE_LABEL = {"measured": "đo", "declared": "khai báo", "unavailable": "—"}
#: Lỗi đọc dữ liệu mà bảng vẫn phải trả được: khối đó thành `unavailable` kèm lý do, không làm hỏng cả bảng.
_READ_ERRORS = (SceneError, ValueError, ArtifactStoreError, ValidationRunError, OSError)


class Figure(BaseModel):
    value: float | int | str | None
    unit: str | None = None
    provenance: Provenance
    note: str | None = None


def measured(value: float | int | str, unit: str | None = None) -> Figure:
    return Figure(value=value, unit=unit, provenance="measured")


def declared(value: float | int | str, unit: str | None = None) -> Figure:
    return Figure(value=value, unit=unit, provenance="declared")


def unavailable(note: str, unit: str | None = None) -> Figure:
    return Figure(value=None, unit=unit, provenance="unavailable", note=note)


class NorthStar(BaseModel):
    hands_on_minutes: Figure
    hands_on_before_ready_minutes: Figure
    hands_on_after_ready_minutes: Figure
    machine_minutes: Figure
    #: gpu_name của lượt đo gần nhất; vram_gb / cpu_count / ram_gb từ snapshot máy trong benchmark của job (None nếu job
    #: chưa có snapshot); peak_* là đỉnh của job, gồm cả `scene.*`.
    hardware: dict[str, str | float | None]
    gpu_hours: Figure
    cost_usd: Figure
    #: operation → số lần (origin human); "request:<mode>" cho yêu cầu hàng đợi; "unknown" nếu có thao tác lạ.
    interventions: dict[str, int]
    #: Tổng can thiệp của người (không tính "unknown"); unavailable khi job chưa có sự kiện nào.
    interventions_total: Figure


class P2(BaseModel):
    gaps_checked: int
    gaps_agree: int
    missed_obstacles: int
    false_obstacles: int
    gap_results: list[GapResult]
    max_distance_error_cm: Figure
    distance_results: list[DistanceResult]
    key_obstacles_with_collider: str
    #: Lý do cả khối chưa đo được (vd. chưa có ground truth); None khi đã đo.
    unavailable_reason: str | None = None


class P3(BaseModel):
    edit_to_retest_minutes: Figure
    moves: list[MoveResult]
    consistent: bool | None
    unavailable_reason: str | None = None


class P4(BaseModel):
    level: Literal[0, 1, 2, 3, 4]
    reasons: list[str]


class ValueScorecard(BaseModel):
    job_id: str
    scene_name: str
    generated_at: datetime
    scene_revision: str | None
    data_source: str
    notes: str
    north_star: NorthStar
    p2: P2
    p3: P3
    p4: P4
    manual_baseline_minutes: Figure


class BenchmarkSummary(BaseModel):
    scenes: int
    hands_on_median_minutes: float | None
    hands_on_n: int
    machine_median_minutes_by_gpu: dict[str, float | None]
    machine_n_by_gpu: dict[str, int]
    gaps_agree_total: int
    gaps_total: int
    missed_total: int
    false_total: int
    scenes_at_least_l2: int
    scenes_at_least_l3: int
    manual_median_minutes: float | None
    manual_n: int


class BenchmarkResponse(BaseModel):
    rows: list[ValueScorecard]
    summary: BenchmarkSummary


# --- Thời gian máy, phần cứng, chi phí -------------------------------------------------------------------------------


def machine_minutes(usages: Iterable[ResourceUsage], job_id: str) -> Figure:
    """Phút máy theo `processing_seconds` (đã cộng các bước `scene.*`)."""
    total = processing_seconds(usage for usage in usages if usage.job_id == job_id).get(job_id)
    if total is None:
        return unavailable("job chưa có số đo thời gian máy", "phút")
    return measured(round(total / 60.0, 1), "phút")


def hardware_and_cost(
    usages: Sequence[ResourceUsage], rate_usd_per_hour: float | None, machine: MachineCapability | None = None
) -> tuple[dict[str, str | float | None], Figure, Figure]:
    completed = [usage for usage in usages if usage.outcome == "completed"]
    named = sorted((usage for usage in completed if usage.gpu_name), key=lambda usage: usage.completed_at)
    vram = [value for value in (usage_vram(usage) for usage in completed) if value is not None]
    ram = [usage.peak_ram_gb for usage in completed if usage.peak_ram_gb is not None]
    hardware: dict[str, str | float | None] = {
        "gpu_name": named[-1].gpu_name if named else (machine.gpu_name if machine is not None else None),
        "vram_gb": machine.vram_total_gb if machine is not None else None,
        "cpu_count": machine.cpu_count if machine is not None else None,
        "ram_gb": machine.ram_total_gb if machine is not None else None,
        "peak_vram_gb": round(max(vram), 2) if vram else None,
        "peak_ram_gb": round(max(ram), 2) if ram else None,
    }
    gpu_billed = [usage for usage in billed_usages(completed) if usage.gpu_name]
    if not gpu_billed:
        missing = "không có lượt chạy GPU"
        return hardware, unavailable(missing, "giờ"), unavailable(missing, "USD")
    gpu_hours = sum(usage.duration_seconds for usage in gpu_billed) / 3600.0
    gpu_figure = measured(round(gpu_hours, 4), "giờ")
    if rate_usd_per_hour is None:
        return hardware, gpu_figure, unavailable("chưa khai báo đơn giá GPU/giờ (benchmark_gpu_hourly_usd)", "USD")
    return hardware, gpu_figure, declared(round(gpu_hours * rate_usd_per_hour, 2), "USD")


# --- Công người và can thiệp ------------------------------------------------------------------------------------------


def hands_on(
    events: Sequence[ValueEvent], ready_at: datetime | None, currently_ready: bool | None
) -> tuple[Figure, Figure, Figure]:
    """Phút công người: tổng, trước và sau lần đầu object_geometry = ready (mốc theo `ended_at` của lô)."""
    batches = [
        (datetime.fromisoformat(str(event.payload["ended_at"])), float(event.payload.get("active_seconds", 0.0)) / 60.0)
        for event in events
        if event.kind == "operator_time"
    ]
    if not batches:
        missing = unavailable("job chưa có lô thời gian thao tác", "phút")
        return missing, missing, missing
    total = measured(round(sum(minutes for _, minutes in batches), 1), "phút")
    if ready_at is None:
        if currently_ready is False:
            # Chưa đạt ready: toàn bộ thời gian đã làm là trước ready, chưa có "sau ready".
            return (
                total,
                measured(round(sum(minutes for _, minutes in batches), 1), "phút"),
                unavailable("scene chưa đạt object_geometry = ready", "phút"),
            )
        unknown = unavailable("không xác định được lúc đạt ready", "phút")
        return total, unknown, unknown
    before = sum(minutes for ended, minutes in batches if ended < ready_at)
    after = sum(minutes for ended, minutes in batches if ended >= ready_at)
    return total, measured(round(before, 1), "phút"), measured(round(after, 1), "phút")


def interventions(events: Sequence[ValueEvent]) -> tuple[dict[str, int], Figure]:
    """Can thiệp = scene_edit origin human + scene_request origin human. Origin system không được đếm."""
    counts: dict[str, int] = {}
    seen = False
    for event in events:
        if event.kind == "scene_edit":
            seen = True
            origin = event.payload.get("origin")
            if origin == "human":
                key = str(event.payload.get("operation", "unknown"))
            elif origin == "unknown":
                key = "unknown"
            else:
                continue
        elif event.kind == "scene_request":
            seen = True
            if event.payload.get("origin") != "human":
                continue
            key = f"request:{event.payload.get('mode')}"
        else:
            continue
        counts[key] = counts.get(key, 0) + 1
    if not seen:
        return counts, unavailable("job chưa có sự kiện can thiệp", "lần")
    return counts, measured(sum(count for key, count in counts.items() if key != "unknown"), "lần")


def north_star_block(
    *,
    events: Sequence[ValueEvent],
    usages: Sequence[ResourceUsage],
    job_id: str,
    ready_at: datetime | None,
    currently_ready: bool | None,
    rate_usd_per_hour: float | None,
    machine: MachineCapability | None = None,
) -> NorthStar:
    total, before, after = hands_on(events, ready_at, currently_ready)
    hardware, gpu_hours, cost = hardware_and_cost(usages, rate_usd_per_hour, machine)
    counts, total_interventions = interventions(events)
    return NorthStar(
        hands_on_minutes=total,
        hands_on_before_ready_minutes=before,
        hands_on_after_ready_minutes=after,
        machine_minutes=machine_minutes(usages, job_id),
        hardware=hardware,
        gpu_hours=gpu_hours,
        cost_usd=cost,
        interventions=counts,
        interventions_total=total_interventions,
    )


# --- P2, P3, P4 -------------------------------------------------------------------------------------------------------


def unavailable_p2(reason: str) -> P2:
    return P2(
        gaps_checked=0,
        gaps_agree=0,
        missed_obstacles=0,
        false_obstacles=0,
        gap_results=[],
        max_distance_error_cm=unavailable(reason, "cm"),
        distance_results=[],
        key_obstacles_with_collider="—",
        unavailable_reason=reason,
    )


def compute_p2(
    truth: BenchmarkTruth, world_of: Callable[[str], CollisionWorld], key_with_collider: Sequence[bool]
) -> P2:
    """P2 từ ground truth. Mỗi khe đo trên collision của revision layout của nó (`world_of`)."""
    distances = [distance_error(item) for item in truth.distances]
    max_error = (
        declared(round(max(abs(item.error_m) for item in distances) * 100.0, 1), "cm")
        if distances
        else unavailable("chưa có đoạn đo thước", "cm")
    )
    gap_results: list[GapResult] = []
    if truth.gaps:
        if truth.robot is None:
            raise ValueError("chưa khai báo robot nên chưa đo được khe")
        for gap in truth.gaps:
            layout = truth.layouts.get(gap.layout)
            if layout is None:
                continue  # khe của layout chưa được gắn revision: không đo, không đếm
            gap_results.append(gap_width(world_of(layout.scene_revision), gap, truth.robot))
    kinds = [item.kind for item in gap_results]
    flagged = sum(1 for flag in key_with_collider if flag)
    total = len(key_with_collider)
    return P2(
        gaps_checked=len(gap_results),
        gaps_agree=sum(1 for item in gap_results if item.agree),
        missed_obstacles=kinds.count("missed_obstacle"),
        false_obstacles=kinds.count("false_obstacle"),
        gap_results=gap_results,
        max_distance_error_cm=max_error,
        distance_results=distances,
        key_obstacles_with_collider=f"{flagged}/{total}" if total else "chưa khai báo vật cản chính",
    )


def compute_p3(
    truth: BenchmarkTruth,
    first_human_edit_after: Callable[[datetime], datetime | None],
    walk_completed_after: Callable[[str, datetime], datetime | None],
    moves_of: Callable[[], list[MoveResult]],
) -> P3:
    layout_a = truth.layouts.get("A")
    layout_b = truth.layouts.get("B")
    if layout_a is None or layout_b is None:
        return P3(edit_to_retest_minutes=unavailable("cần đủ layout A và B", "phút"), moves=[], consistent=None)
    tagged = layout_a.tagged_at if layout_a.tagged_at.tzinfo else layout_a.tagged_at.replace(tzinfo=UTC)
    edited = first_human_edit_after(tagged)
    if edited is None:
        retest = unavailable("chưa có thao tác người sau khi gắn layout A", "phút")
    else:
        finished = walk_completed_after(layout_b.scene_revision, edited)
        if finished is None:
            retest = unavailable("chưa có walk hoàn tất trên layout B sau thao tác", "phút")
        else:
            retest = measured(round((finished - edited).total_seconds() / 60.0, 1), "phút")
    moves = moves_of()
    return P3(
        edit_to_retest_minutes=retest,
        moves=moves,
        consistent=all(item.passed for item in moves) if moves else None,
    )


@dataclass(frozen=True)
class Check:
    level: Literal[1, 2, 3, 4]
    ok: bool
    reason: str


def level_from_checks(checks: Sequence[Check]) -> P4:
    """Bậc = cao nhất mà mọi điều kiện của các bậc từ L1 đến đó đều đạt. `reasons` là điều kiện còn thiếu của bậc kế tiếp."""
    level = 0
    for candidate in (1, 2, 3, 4):
        missing = [check.reason for check in checks if check.level == candidate and not check.ok]
        if missing:
            return P4(level=level, reasons=missing)
        level = candidate
    return P4(level=4, reasons=[])


# --- Ghép bảng (đọc registry) -----------------------------------------------------------------------------------------


class _Worlds:
    """Collision của từng revision, dựng một lần cho cả bảng."""

    def __init__(self, registry: ProjectRegistry, job_id: str) -> None:
        self.registry = registry
        self.job_id = job_id
        self._cache: dict[str, CollisionWorld] = {}

    def get(self, scene_revision: str) -> CollisionWorld:
        if scene_revision not in self._cache:
            self._cache[scene_revision] = collision_world(self.registry, self.job_id, scene_revision)
        return self._cache[scene_revision]


def _revision_scene(registry: ProjectRegistry, job_id: str, scene_revision: str | None) -> SceneIR | None:
    if not scene_revision:
        return None
    try:
        revision = registry.scene.revision(job_id, scene_revision)
    except SceneError:
        return None
    return None if revision is None else revision.scene


def _current_scene(registry: ProjectRegistry, job_id: str) -> SceneIR | None:
    try:
        return registry.scene.current(job_id).scene
    except SceneError:
        return None


def _ready_at(registry: ProjectRegistry, job_id: str, events: Sequence[ValueEvent]) -> datetime | None:
    """Thời điểm revision ready đầu tiên được ghi (qua scene_edit)."""
    for event in events:
        if event.kind != "scene_edit":
            continue
        scene = _revision_scene(registry, job_id, event.payload.get("scene_revision"))
        if scene is not None and object_geometry_state(scene) == "ready":
            return event.at
    return None


def _p2_block(
    registry: ProjectRegistry,
    job_id: str,
    stored: StoredTruth,
    worlds: _Worlds,
    scene: SceneIR | None,
) -> P2:
    if stored.version == 0:
        return unavailable_p2("chưa có ground truth")
    truth = stored.truth
    by_id = {item.id: item for item in scene.objects} if scene is not None else {}
    flags = [
        by_id[identifier].collider is not None if identifier in by_id else False
        for identifier in truth.key_obstacle_ids
    ]
    try:
        return compute_p2(truth, worlds.get, flags)
    except _READ_ERRORS as error:
        return unavailable_p2(f"không đo được khe: {error}")


def first_human_change_after(events: Sequence[ValueEvent], moment: datetime) -> datetime | None:
    """Lúc người dùng bắt đầu đổi bố trí sau `moment`: thao tác sửa scene **hoặc** yêu cầu qua hàng đợi của người.

    Đổi bố trí trên scene Ready có thể chỉ đi qua hàng đợi (chỉnh vùng, Brush/Lasso), revision kết quả do worker publish
    là `system`, nên phải tính cả `scene_request` có origin human.
    """
    for event in events:
        if (
            event.kind in {"scene_edit", "scene_request"}
            and event.payload.get("origin") == "human"
            and event.at > moment
        ):
            return event.at
    return None


def _p3_block(
    registry: ProjectRegistry,
    job_id: str,
    stored: StoredTruth,
    events: Sequence[ValueEvent],
    worlds: _Worlds,
) -> P3:
    if stored.version == 0:
        reason = "chưa có ground truth"
        return P3(
            edit_to_retest_minutes=unavailable(reason, "phút"),
            moves=[],
            consistent=None,
            unavailable_reason=reason,
        )
    truth = stored.truth

    def first_human_edit_after(moment: datetime) -> datetime | None:
        return first_human_change_after(events, moment)

    def walk_completed_after(scene_revision: str, moment: datetime) -> datetime | None:
        for event in events:
            if (
                event.kind == "walk_session"
                and event.payload.get("outcome") == "completed"
                and event.payload.get("scene_revision") == scene_revision
                and event.at > moment
            ):
                return event.at
        return None

    def moves() -> list[MoveResult]:
        layout_a = truth.layouts.get("A")
        layout_b = truth.layouts.get("B")
        if layout_a is None or layout_b is None or truth.robot is None:
            return []
        scene_a = _revision_scene(registry, job_id, layout_a.scene_revision)
        scene_b = _revision_scene(registry, job_id, layout_b.scene_revision)
        if scene_a is None or scene_b is None:
            raise SceneError("không đọc được revision của layout A hoặc B")
        return move_consistency(
            worlds.get(layout_a.scene_revision),
            worlds.get(layout_b.scene_revision),
            scene_a,
            scene_b,
            truth.robot,
        )

    try:
        return compute_p3(truth, first_human_edit_after, walk_completed_after, moves)
    except _READ_ERRORS as error:
        reason = f"không đo được đổi bố trí: {error}"
        return P3(
            edit_to_retest_minutes=unavailable(reason, "phút"), moves=[], consistent=None, unavailable_reason=reason
        )


def _l3_checks(registry: ProjectRegistry, job_id: str, scene: SceneIR | None, database: RuntimeDatabase) -> list[Check]:
    """L3: gói mô phỏng của revision hiện tại có candidate, và lần validation được chọn cho candidate đó là COMPLETED với PASS."""
    if scene is None:
        return [Check(3, False, "chưa có scene")]
    try:
        package = current_package(registry, job_id)
        if package is None:
            return [Check(3, False, "chưa có gói mô phỏng cho revision hiện tại")]
        if package.candidate is None:
            return [Check(3, False, "gói mô phỏng chưa có candidate (đang bị chặn)")]
        repository = ValidationRunRepository(database, registry.runtime_resolver)
        selection = repository.get_selection_for_candidate(job_id, package.candidate.candidate_checksum)
        if selection is None:
            return [Check(3, False, "chưa có lần validation Isaac được chọn cho gói")]
        run = repository.get_run(selection.run_id)
        if run.scene_revision != scene.scene_revision:
            return [Check(3, False, "lần validation Isaac được chọn không thuộc revision hiện tại")]
        if run.status != ValidationRunStatus.COMPLETED:
            return [Check(3, False, f"validation Isaac chưa COMPLETED ({run.status.value})")]
        if run.report_ref is None:
            return [Check(3, False, "validation Isaac COMPLETED nhưng thiếu report")]
        report = registry.runtime_resolver.load_model(run.report_ref, ValidationReport)
    except _READ_ERRORS as error:
        return [Check(3, False, f"không đọc được validation Isaac: {error}")]
    if report.overall_result != RuleResult.PASS:
        return [Check(3, False, f"validation Isaac kết thúc {report.overall_result.value}, cần PASS")]
    return [Check(3, True, "")]


def _p4_block(
    registry: ProjectRegistry,
    job_id: str,
    stored: StoredTruth,
    scene: SceneIR | None,
    events: Sequence[ValueEvent],
    p2: P2,
    database: RuntimeDatabase,
) -> P4:
    checks: list[Check] = []
    if scene is None:
        checks.append(Check(1, False, "chưa có scene"))
    else:
        checks.append(
            Check(
                1,
                scene.metric_scale.status == MetricScaleStatus.CONFIRMED,
                "chưa xác nhận tỉ lệ mét cho revision hiện tại",
            )
        )
        checks.append(
            Check(
                1, object_geometry_state(scene) == "ready", "vật chưa được tạo mesh (object_geometry = awaiting_review)"
            )
        )
    truth = stored.truth
    if stored.version == 0:
        checks.append(Check(2, False, "chưa có ground truth"))
    else:
        if not truth.key_obstacle_ids:
            checks.append(Check(2, False, "chưa khai báo vật cản chính"))
        else:
            by_id = {item.id: item for item in scene.objects} if scene is not None else {}
            flagged = sum(
                1
                for identifier in truth.key_obstacle_ids
                if identifier in by_id and by_id[identifier].collider is not None
            )
            total = len(truth.key_obstacle_ids)
            checks.append(Check(2, flagged == total, f"vật cản chính chưa có collider ({flagged}/{total})"))
        walked = scene is not None and any(
            event.kind == "walk_session"
            and event.payload.get("outcome") == "completed"
            and event.payload.get("scene_revision") == scene.scene_revision
            for event in events
        )
        checks.append(Check(2, walked, "chưa có walk hoàn tất trên revision hiện tại"))
        if "A" not in truth.layouts:
            checks.append(Check(2, False, "chưa có layout A"))
        elif p2.unavailable_reason:
            checks.append(Check(2, False, "chưa đo được khe kiểm của layout A"))
        else:
            layout_of = {gap.id: gap.layout for gap in truth.gaps}
            results_a = [item for item in p2.gap_results if layout_of.get(item.gap_id) == "A"]
            if not results_a:
                checks.append(Check(2, False, "chưa có khe kiểm của layout A"))
            else:
                missed = sum(1 for item in results_a if item.kind == "missed_obstacle")
                checks.append(Check(2, missed == 0, f"layout A còn {missed} khe bỏ sót vật cản"))
    checks += _l3_checks(registry, job_id, scene, database)
    declaration = truth.l4 if stored.version > 0 else None
    if declaration is None:
        checks.append(Check(4, False, "chưa có khai báo tay bài thử robot A và B"))
    else:
        failed = [
            name
            for name, ok in (
                ("layout A", declaration.layout_a_passed),
                ("layout B", declaration.layout_b_passed),
                ("khớp đời thật", declaration.matches_reality),
            )
            if not ok
        ]
        checks.append(Check(4, not failed, "khai báo tay chưa đủ: " + ", ".join(failed)))
    return level_from_checks(checks)


def _job_machine(registry: ProjectRegistry, job_id: str) -> MachineCapability | None:
    """Snapshot cấu hình worker trong benchmark runtime của attempt mới nhất có snapshot (terminal trước, partial sau)."""
    try:
        attempts = registry.list_job_attempts(job_id)
    except (ValueError, OSError):
        return None
    for attempt in sorted({item.attempt for item in attempts}, reverse=True):
        for phase in ("terminal", "partial"):
            uri = f"artifact://jobs/{job_id}/benchmark/{BENCHMARK_KIND}/attempt-{attempt}-{phase}.json"
            try:
                path = registry.runtime_resolver.locate(uri)
                if path is None:
                    continue
                snapshot = PipelineRuntimeBenchmark.model_validate_json(path.read_bytes())
            except _READ_ERRORS:
                continue
            if snapshot.machine is not None:
                return snapshot.machine
    return None


def build_scorecard(registry: ProjectRegistry, settings: Settings, job_id: str) -> ValueScorecard:
    """Bảng metric của một job. Đọc dữ liệu, không ghi gì."""
    job = registry.get_job(job_id)
    project = registry.get_project(job.project_id)
    database = RuntimeDatabase(settings.database_url)
    events = list_events(database, job_id)
    usages = [usage for usage in load_usages(database) if usage.job_id == job_id]
    stored = read_truth(database, job_id)
    scene = _current_scene(registry, job_id)
    worlds = _Worlds(registry, job_id)
    north = north_star_block(
        events=events,
        usages=usages,
        job_id=job_id,
        ready_at=_ready_at(registry, job_id, events),
        currently_ready=None if scene is None else object_geometry_state(scene) == "ready",
        rate_usd_per_hour=settings.benchmark_gpu_hourly_usd,
        machine=_job_machine(registry, job_id),
    )
    p2 = _p2_block(registry, job_id, stored, worlds, scene)
    p3 = _p3_block(registry, job_id, stored, events, worlds)
    p4 = _p4_block(registry, job_id, stored, scene, events, p2, database)
    truth = stored.truth
    manual = (
        declared(truth.manual_baseline_minutes, "phút")
        if stored.version > 0 and truth.manual_baseline_minutes is not None
        else unavailable("chưa khai báo mốc làm tay", "phút")
    )
    return ValueScorecard(
        job_id=job_id,
        scene_name=project.name,
        generated_at=datetime.now(UTC),
        scene_revision=None if scene is None else scene.scene_revision,
        data_source=truth.data_source if stored.version > 0 else "unavailable",
        notes=truth.notes if stored.version > 0 else "",
        north_star=north,
        p2=p2,
        p3=p3,
        p4=p4,
        manual_baseline_minutes=manual,
    )


def benchmark_rows(registry: ProjectRegistry, settings: Settings) -> list[ValueScorecard]:
    """Job mới nhất của mỗi project có `include_in_benchmark`; project không có job nào như vậy thì bỏ qua."""
    database = RuntimeDatabase(settings.database_url)
    rows: list[ValueScorecard] = []
    for project in registry.list_projects():
        jobs = sorted(
            registry.list_jobs(project.project_id), key=lambda item: (item.started_at, item.job_id), reverse=True
        )
        for job in jobs:
            if read_truth(database, job.job_id).truth.include_in_benchmark:
                rows.append(build_scorecard(registry, settings, job.job_id))
                break
    return rows


# --- Tổng hợp và xuất -------------------------------------------------------------------------------------------------


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def benchmark_summary(rows: Sequence[ValueScorecard]) -> BenchmarkSummary:
    hands = [
        float(card.north_star.hands_on_minutes.value) for card in rows if _is_number(card.north_star.hands_on_minutes)
    ]
    manual = [float(card.manual_baseline_minutes.value) for card in rows if _is_number(card.manual_baseline_minutes)]
    by_gpu: dict[str, list[float]] = {}
    for card in rows:
        gpu = card.north_star.hardware.get("gpu_name")
        if gpu and _is_number(card.north_star.machine_minutes):
            by_gpu.setdefault(str(gpu), []).append(float(card.north_star.machine_minutes.value))  # type: ignore[arg-type]
    measured_p2 = [card.p2 for card in rows if not card.p2.unavailable_reason]
    return BenchmarkSummary(
        scenes=len(rows),
        hands_on_median_minutes=_median(hands),
        hands_on_n=len(hands),
        machine_median_minutes_by_gpu={gpu: _median(values) for gpu, values in sorted(by_gpu.items())},
        machine_n_by_gpu={gpu: len(values) for gpu, values in sorted(by_gpu.items())},
        gaps_agree_total=sum(p2.gaps_agree for p2 in measured_p2),
        gaps_total=sum(p2.gaps_checked for p2 in measured_p2),
        missed_total=sum(p2.missed_obstacles for p2 in measured_p2),
        false_total=sum(p2.false_obstacles for p2 in measured_p2),
        scenes_at_least_l2=sum(1 for card in rows if card.p4.level >= 2),
        scenes_at_least_l3=sum(1 for card in rows if card.p4.level >= 3),
        manual_median_minutes=_median(manual),
        manual_n=len(manual),
    )


def _is_number(figure: Figure) -> bool:
    return isinstance(figure.value, (int, float)) and not isinstance(figure.value, bool)


def _text(figure: Figure, digits: int = 1) -> str:
    if figure.value is None:
        return "—"
    if isinstance(figure.value, float):
        return f"{figure.value:.{digits}f}"
    return str(figure.value)


def _cell(figure: Figure) -> str:
    return "" if figure.value is None else _text(figure)


def _no_gap_measured(card: ValueScorecard) -> bool:
    """Chưa đo khe nào (chưa có ground truth, hoặc khe chưa gắn layout): không có số khe để ghi, kể cả 0/0."""
    return bool(card.p2.unavailable_reason) or card.p2.gaps_checked == 0


def _agree_text(card: ValueScorecard) -> str:
    return "—" if _no_gap_measured(card) else f"{card.p2.gaps_agree}/{card.p2.gaps_checked}"


def _missed_text(card: ValueScorecard) -> str:
    return "—" if _no_gap_measured(card) else f"{card.p2.missed_obstacles} / {card.p2.false_obstacles}"


def _md(text: str) -> str:
    """Chuỗi do người nhập (tên scene) trong ô bảng Markdown: không được làm vỡ bảng."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def scorecard_markdown(card: ValueScorecard) -> str:
    """Bảng 5 dòng ở đầu (Chính · P2 · P3 · P4 · Làm tay); chi tiết khe và vật dời ở dưới."""
    ns = card.north_star
    p2 = card.p2
    p3 = card.p3
    if p2.unavailable_reason:
        p2_value = f"— ({p2.unavailable_reason})"
    elif p2.gaps_checked == 0:
        p2_value = "chưa có khe kiểm nào được đo"
    else:
        p2_value = f"{_agree_text(card)} · {_missed_text(card)}"
    p2_source = "—" if _no_gap_measured(card) and p2.max_distance_error_cm.value is None else "đo, so với số thước"
    p3_consistent = "Đạt" if p3.consistent else "Không" if p3.consistent is False else "—"
    lines = [
        f"# Bảng metric giá trị · {_md(card.scene_name)}",
        "",
        f"Job `{card.job_id}` · revision `{card.scene_revision or '—'}` · nguồn dữ liệu: "
        f"{DATA_SOURCE_LABELS.get(card.data_source, '—')}",
        "",
        "| Metric | Giá trị | Nguồn |",
        "| --- | --- | --- |",
        f"| Chính: phút công · phút máy · chi phí | {_text(ns.hands_on_minutes)} phút công · "
        f"{_text(ns.machine_minutes)} phút máy · {_text(ns.cost_usd, 2)} {ns.cost_usd.unit or ''} | "
        f"{_PROVENANCE_LABEL[ns.hands_on_minutes.provenance]} |",
        f"| P2 khớp khe · bỏ sót / giả | {p2_value} | {p2_source} |",
        f"| P3 đổi → thử (phút) · nhất quán | {_text(p3.edit_to_retest_minutes)} · {p3_consistent} | "
        f"{_PROVENANCE_LABEL[p3.edit_to_retest_minutes.provenance]} |",
        f"| P4 bậc sẵn sàng | L{card.p4.level}{' (khai báo tay)' if card.p4.level == 4 else ''} | "
        f"{'khai báo' if card.p4.level == 4 else 'đo'} |",
        f"| Làm tay (mốc so sánh cho P1, phút) | {_text(card.manual_baseline_minutes)} | "
        f"{_PROVENANCE_LABEL[card.manual_baseline_minutes.provenance]} |",
        "",
        "## Khe kiểm",
        "",
        "| Khe | Mô phỏng (m) | Mô phỏng qua được | Thật qua được | Kết luận |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in p2.gap_results:
        lines.append(
            f"| {item.gap_id} | {item.sim_width_m:.3f} | {'Có' if item.sim_passable else 'Không'} | "
            f"{'Có' if item.real_passable else 'Không'} | {item.kind} |"
        )
    if not p2.gap_results:
        lines.append("| — | — | — | — | — |")
    lines += ["", "## Vật dời", "", "| Vật | Vết cũ đã khoét | Có collider mới | Đạt |", "| --- | --- | --- | --- |"]
    for move in p3.moves:
        lines.append(
            f"| {move.object_id} | {'Có' if move.old_cleared else 'Không'} | "
            f"{'Có' if move.new_present else 'Không'} | {'Đạt' if move.passed else 'Không'} |"
        )
    if not p3.moves:
        lines.append("| — | — | — | — |")
    if card.p4.reasons:
        lines += ["", "## Chưa lên bậc kế tiếp", ""] + [f"- {reason}" for reason in card.p4.reasons]
    return "\n".join(lines) + "\n"


CSV_HEADER = [
    "Scene",
    "Nguồn",
    "Phần cứng",
    "Máy (ph)",
    "Người (ph)",
    "Can thiệp",
    "Khe khớp",
    "Bỏ sót / Giả",
    "Sai số KT",
    "Đổi→thử (ph)",
    "Nhất quán",
    "Bậc",
    "Làm tay (ph)",
    "Ghi chú",
]


def _csv_row(card: ValueScorecard) -> list[str]:
    ns = card.north_star
    gpu = ns.hardware.get("gpu_name")
    consistent = "Đạt" if card.p3.consistent else "Không" if card.p3.consistent is False else ""
    return [
        card.scene_name,
        DATA_SOURCE_LABELS.get(card.data_source, ""),
        str(gpu) if gpu else "",
        _cell(ns.machine_minutes),
        _cell(ns.hands_on_minutes),
        "" if ns.interventions_total.value is None else str(ns.interventions_total.value),
        "" if _no_gap_measured(card) else f"{card.p2.gaps_agree}/{card.p2.gaps_checked}",
        "" if _no_gap_measured(card) else f"{card.p2.missed_obstacles} / {card.p2.false_obstacles}",
        _cell(card.p2.max_distance_error_cm),
        _cell(card.p3.edit_to_retest_minutes),
        consistent,
        f"L{card.p4.level}",
        _cell(card.manual_baseline_minutes),
        card.notes,
    ]


def csv_document(cards: Iterable[ValueScorecard]) -> str:
    """CSV UTF-8 có BOM, dấu phẩy, số dạng `.`; ô thiếu dữ liệu để trống (không ghi 0)."""
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for card in cards:
        writer.writerow(_csv_row(card))
    return buffer.getvalue()


def benchmark_markdown(rows: Sequence[ValueScorecard], summary: BenchmarkSummary) -> str:
    lines = [
        "# Bộ benchmark giá trị",
        "",
        f"Số scene: {summary.scenes} · trung vị phút công người: "
        f"{'—' if summary.hands_on_median_minutes is None else f'{summary.hands_on_median_minutes:.1f}'} "
        f"(n = {summary.hands_on_n}) · đạt ≥ L2: {summary.scenes_at_least_l2} · đạt ≥ L3: {summary.scenes_at_least_l3}",
        f"Khe khớp: {summary.gaps_agree_total}/{summary.gaps_total} · bỏ sót: {summary.missed_total} · giả: {summary.false_total}",
        "",
        "| Scene | Máy (ph) | Người (ph) | Khe khớp | Bỏ sót / Giả | Bậc |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for card in rows:
        lines.append(
            f"| {_md(card.scene_name)} | {_text(card.north_star.machine_minutes)} | {_text(card.north_star.hands_on_minutes)} | "
            f"{_agree_text(card)} | {_missed_text(card)} | L{card.p4.level} |"
        )
    return "\n".join(lines) + "\n"
