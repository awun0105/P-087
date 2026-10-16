"""Ground truth của benchmark giá trị (architecture §15.2): số đo thước và khai báo của một scene.

Toạ độ là khung canonical của scene (mét, Z-up, sàn z = 0), cùng khung với SceneIR.
"""

import math
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Identifier

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
