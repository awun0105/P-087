"""Ground truth của benchmark giá trị (architecture §15.2): số đo thước và khai báo của một scene.

Toạ độ là khung canonical của scene (mét, Z-up, sàn z = 0), cùng khung với SceneIR.
"""

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Identifier
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction

Vec3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]

#: Khe kiểm phải có bề rộng đo được trong khoảng này; ngoài khoảng là nhập nhầm điểm.
GAP_SPAN_MIN_M = 0.1
GAP_SPAN_MAX_M = 10.0


class RobotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_m: float = Field(gt=0.05, le=3)
    safety_margin_m: float = Field(ge=0, le=1)
    height_min_m: float = Field(ge=0, le=2)
    height_max_m: float = Field(gt=0, le=3)

    @model_validator(mode="after")
    def _height_range(self) -> Self:
        if self.height_min_m >= self.height_max_m:
            raise ValueError("height_min_m phải nhỏ hơn height_max_m")
        return self


class MeasuredDistance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    label: str = Field(max_length=80)
    a: Vec3
    b: Vec3
    real_m: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def _points_differ(self) -> Self:
        if self.a == self.b:
            raise ValueError(f"đoạn đo {self.id}: hai điểm a và b trùng nhau")
        return self


class GapCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    label: str = Field(max_length=80)
    layout: Literal["A", "B"]
    a: Vec3
    b: Vec3
    real_width_m: float | None = Field(default=None, gt=0, le=10)
    real_passable: bool

    @model_validator(mode="after")
    def _span_in_range(self) -> Self:
        span = math.dist(self.a, self.b)
        if not GAP_SPAN_MIN_M <= span <= GAP_SPAN_MAX_M:
            raise ValueError(
                f"khe kiểm {self.id}: |b−a| = {span:.3f} m nằm ngoài khoảng [{GAP_SPAN_MIN_M}, {GAP_SPAN_MAX_M}] m"
            )
        return self


class LayoutRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_revision: Identifier
    tagged_at: datetime


class L4Declaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layout_a_passed: bool
    layout_b_passed: bool
    matches_reality: bool
    evidence: str = Field(min_length=1, max_length=600)


class BenchmarkTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    include_in_benchmark: bool = False
    data_source: Literal["self_capture", "hf_room", "synthetic"] = "self_capture"
    robot: RobotProfile | None = None
    distances: list[MeasuredDistance] = Field(default_factory=list, max_length=32)
    gaps: list[GapCheck] = Field(default_factory=list, max_length=32)
    key_obstacle_ids: list[Identifier] = Field(default_factory=list, max_length=64)
    layouts: dict[Literal["A", "B"], LayoutRef] = Field(default_factory=dict)
    manual_baseline_minutes: float | None = Field(default=None, ge=0, le=10_000)
    l4: L4Declaration | None = None
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _ids_unique(self) -> Self:
        ids = [item.id for item in self.distances] + [item.id for item in self.gaps]
        duplicated = sorted({item for item in ids if ids.count(item) > 1})
        if duplicated:
            raise ValueError(f"id trùng trong distances/gaps: {', '.join(duplicated)}")
        if len(set(self.key_obstacle_ids)) != len(self.key_obstacle_ids):
            raise ValueError("key_obstacle_ids có id trùng")
        return self


class TruthVersionConflictError(RuntimeError):
    """Ghi với `expected_version` cũ: tài liệu đã được ghi bởi bên khác."""

    def __init__(self, expected_version: int, current_version: int) -> None:
        super().__init__(f"ground truth đã đổi: client giữ version {expected_version}, hiện tại là {current_version}")
        self.expected_version = expected_version
        self.current_version = current_version


@dataclass(frozen=True)
class StoredTruth:
    version: int
    truth: BenchmarkTruth
    updated_at: datetime | None


def read_truth(database: RuntimeDatabase, job_id: str) -> StoredTruth:
    """Tài liệu hiện có của job; chưa có thì version 0 và giá trị mặc định."""
    with database.transaction() as tx:
        row = tx.execute("SELECT version,payload FROM r2s_benchmark_truth WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return StoredTruth(version=0, truth=BenchmarkTruth(), updated_at=None)
    stored = json.loads(row[1])
    return StoredTruth(
        version=int(row[0]),
        truth=BenchmarkTruth.model_validate(stored["truth"]),
        updated_at=datetime.fromisoformat(stored["updated_at"]),
    )


def write_truth(database: RuntimeDatabase, job_id: str, expected_version: int, truth: BenchmarkTruth) -> StoredTruth:
    """Ghi CAS: chỉ ghi khi `expected_version` khớp; mỗi lần ghi thành công tăng version 1."""
    updated_at = datetime.now(UTC)
    payload = json.dumps({"truth": truth.model_dump(mode="json"), "updated_at": updated_at.isoformat()}, sort_keys=True)
    with database.transaction(write=True) as tx:
        current = _current_version(tx, job_id)
        if current != expected_version:
            raise TruthVersionConflictError(expected_version, current)
        if current == 0:
            # ON CONFLICT: trên PostgreSQL hai ghi tạo lần đầu cùng lúc không được làm lỗi 500.
            cursor = tx.execute(
                "INSERT INTO r2s_benchmark_truth(job_id,version,payload) VALUES (?,?,?) ON CONFLICT(job_id) DO NOTHING",
                (job_id, 1, payload),
            )
        else:
            cursor = tx.execute(
                "UPDATE r2s_benchmark_truth SET version=?,payload=? WHERE job_id=? AND version=?",
                (current + 1, payload, job_id, current),
            )
        if cursor.rowcount != 1:
            raise TruthVersionConflictError(expected_version, _current_version(tx, job_id))
    return StoredTruth(version=expected_version + 1, truth=truth, updated_at=updated_at)


def _current_version(tx: RuntimeTransaction, job_id: str) -> int:
    row = tx.execute(f"SELECT version FROM r2s_benchmark_truth WHERE job_id=?{tx.lock_suffix()}", (job_id,)).fetchone()
    return 0 if row is None else int(row[0])
