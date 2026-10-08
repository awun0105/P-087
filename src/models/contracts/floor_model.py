"""Versioned contracts for metric floor fitting and per-point classification."""

from __future__ import annotations

import hashlib
import math
from enum import IntEnum
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel
from src.models.contracts.identity import canonical_json_bytes

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
FloorFitStatus = Literal["supported", "confirmed_prior_fallback", "uncertain"]
FloorFitFallbackReason = Literal[
    "missing_floor_prior",
    "invalid_point_shape",
    "non_finite_points",
    "insufficient_points",
    "degenerate_points",
    "no_floor_near_prior",
    "insufficient_inliers",
    "low_inlier_ratio",
    "insufficient_coverage",
    "excessive_noise",
    "ambiguous_multiple_planes",
]


class FloorPointClass(IntEnum):
    """Compact label values returned by ``classify_floor_points``."""

    UNKNOWN = 0
    FLOOR = 1
    ABOVE_FLOOR = 2
    BELOW_FLOOR = 3


class FloorPrior(ContractModel):
    """Confirmed floor point and up direction in canonical world meters."""

    schema_version: Literal["1.0"] = "1.0"
    frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"
    up_direction_world: Vector3
    point_on_floor_world: Vector3

    @model_validator(mode="after")
    def _up_is_normalized(self) -> Self:
        norm = math.sqrt(sum(component * component for component in self.up_direction_world))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("floor up direction must be normalized")
        return self


class FloorFitProfile(ContractModel):
    """Frozen limits for deterministic, prior-constrained RANSAC plane fitting."""

    schema_version: Literal["1.0"] = "1.0"
    algorithm: Literal["constrained_ransac_plane_v1"] = "constrained_ransac_plane_v1"
    distance_unit: Literal["m"] = "m"
    seed: int = Field(default=0, ge=0, le=4_294_967_295, strict=True)
    iterations: int = Field(default=512, ge=32, le=4096, strict=True)
    max_fit_points: int = Field(default=50_000, ge=30, le=100_000, strict=True)
    ransac_threshold_m: FiniteFloat = Field(default=0.04, gt=0, le=0.25)
    min_floor_band_m: FiniteFloat = Field(default=0.005, gt=0, le=0.1)
    max_floor_band_m: FiniteFloat = Field(default=0.09, gt=0, le=0.25)
    noise_sigma_multiplier: FiniteFloat = Field(default=3.0, ge=1, le=8)
    max_noise_sigma_m: FiniteFloat = Field(default=0.03, gt=0, le=0.1)
    max_tilt_degrees: FiniteFloat = Field(default=30.0, ge=0, le=45)
    prior_band_m: FiniteFloat = Field(default=0.15, gt=0, le=2)
    min_inliers: int = Field(default=30, ge=3, le=100_000, strict=True)
    min_inlier_ratio: FiniteFloat = Field(default=0.05, gt=0, le=1)
    min_coverage_area_m2: FiniteFloat = Field(default=0.25, ge=0, le=10_000)
    ambiguity_support_ratio: FiniteFloat = Field(default=0.7, ge=0.5, le=1)
    ambiguity_angle_degrees: FiniteFloat = Field(default=5.0, gt=0, le=45)
    ambiguity_offset_m: FiniteFloat = Field(default=0.12, gt=0, le=2)

    @model_validator(mode="after")
    def _profile_bounds(self) -> Self:
        if self.min_floor_band_m > self.max_floor_band_m:
            raise ValueError("minimum floor band cannot exceed maximum floor band")
        if self.min_inliers > self.max_fit_points:
            raise ValueError("minimum inliers cannot exceed the fit point limit")
        return self

    def checksum(self) -> Checksum:
        """Stable identity for the exact fit policy and random seed."""
        digest = hashlib.sha256(canonical_json_bytes(self)).hexdigest()
        return f"sha256:{digest}"


class FloorModel(ContractModel):
    """Measured plane or explicit canonical-prior fallback; uncertain fits cannot filter points."""

    schema_version: Literal["1.0", "1.1"] = "1.0"
    artifact_type: Literal["FloorModel"] = "FloorModel"
    algorithm: Literal["constrained_ransac_plane_v1"] = "constrained_ransac_plane_v1"
    frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"
    status: FloorFitStatus
    fallback_reason: FloorFitFallbackReason | None = None
    source_checksum: Checksum
    profile_checksum: Checksum
    profile: FloorFitProfile
    prior: FloorPrior | None
    point_count: int = Field(ge=0, strict=True)
    fit_point_count: int = Field(ge=0, strict=True)
    inlier_count: int = Field(ge=0, strict=True)
    inlier_ratio: FiniteFloat = Field(ge=0, le=1)
    coverage_area_m2: FiniteFloat = Field(ge=0)
    median_abs_residual_m: FiniteFloat | None = Field(default=None, ge=0)
    robust_noise_sigma_m: FiniteFloat | None = Field(default=None, ge=0)
    floor_band_m: FiniteFloat | None = Field(default=None, gt=0)
    plane_normal_world: Vector3 | None = None
    plane_offset_m: FiniteFloat | None = None

    @model_validator(mode="after")
    def _result_consistency(self) -> Self:
        if self.profile_checksum != self.profile.checksum():
            raise ValueError("profile checksum must match the embedded floor fit profile")
        if self.fit_point_count > self.point_count or self.inlier_count > self.fit_point_count:
            raise ValueError("floor fit counts are inconsistent")
        expected_ratio = self.inlier_count / self.fit_point_count if self.fit_point_count else 0.0
        if not math.isclose(self.inlier_ratio, expected_ratio, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("inlier ratio must match the recorded counts")
        if (self.plane_normal_world is None) != (self.plane_offset_m is None):
            raise ValueError("plane normal and offset must be present together")
        if self.plane_normal_world is not None:
            norm = math.sqrt(sum(component * component for component in self.plane_normal_world))
            if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError("floor plane normal must be normalized")
            if (
                self.prior is None
                or sum(a * b for a, b in zip(self.plane_normal_world, self.prior.up_direction_world, strict=True)) <= 0
            ):
                raise ValueError("floor plane normal must point along the confirmed up direction")
        if self.status == "supported":
            if self.fallback_reason is not None or self.prior is None or self.plane_normal_world is None:
                raise ValueError("supported floor model requires a prior, plane, and no fallback reason")
            if self.floor_band_m is None or self.robust_noise_sigma_m is None:
                raise ValueError("supported floor model requires measured noise and classification band")
            if self.fit_point_count > self.profile.max_fit_points:
                raise ValueError("supported floor fit exceeds the embedded point limit")
            if self.inlier_count < self.profile.min_inliers or self.inlier_ratio < self.profile.min_inlier_ratio:
                raise ValueError("supported floor model does not meet the embedded support threshold")
            if self.coverage_area_m2 < self.profile.min_coverage_area_m2:
                raise ValueError("supported floor model does not meet the embedded coverage threshold")
            if self.robust_noise_sigma_m > self.profile.max_noise_sigma_m:
                raise ValueError("supported floor model exceeds the embedded noise threshold")
            if not self.profile.min_floor_band_m <= self.floor_band_m <= self.profile.max_floor_band_m:
                raise ValueError("floor classification band exceeds the embedded profile")
            up = self.prior.up_direction_world
            cosine = sum(a * b for a, b in zip(self.plane_normal_world, up, strict=True))
            if cosine < math.cos(math.radians(self.profile.max_tilt_degrees)) - 1e-6:
                raise ValueError("supported floor model exceeds the embedded tilt threshold")
            signed_prior_distance = (
                sum(a * b for a, b in zip(self.plane_normal_world, self.prior.point_on_floor_world, strict=True))
                + self.plane_offset_m
            )
            if abs(signed_prior_distance) > self.profile.prior_band_m:
                raise ValueError("supported floor model exceeds the embedded prior distance")
        elif self.status == "confirmed_prior_fallback":
            if self.schema_version != "1.1":
                raise ValueError("confirmed prior fallback requires FloorModel schema 1.1")
            if self.fallback_reason is None or self.prior is None or self.plane_normal_world is None:
                raise ValueError("confirmed prior fallback requires its prior, plane, and fit reason")
            if self.floor_band_m is None or self.robust_noise_sigma_m is not None:
                raise ValueError("confirmed prior fallback requires a bounded band without claiming measured noise")
            if not self.profile.min_floor_band_m <= self.floor_band_m <= self.profile.max_floor_band_m:
                raise ValueError("confirmed prior fallback band exceeds the embedded profile")
            if any(
                not math.isclose(normal, up, rel_tol=0.0, abs_tol=1e-6)
                for normal, up in zip(self.plane_normal_world, self.prior.up_direction_world, strict=True)
            ):
                raise ValueError("confirmed prior fallback plane must use the confirmed up direction")
            prior_distance = (
                sum(a * b for a, b in zip(self.plane_normal_world, self.prior.point_on_floor_world, strict=True))
                + self.plane_offset_m
            )
            if not math.isclose(prior_distance, 0.0, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError("confirmed prior fallback plane must pass through the confirmed floor point")
        elif self.fallback_reason is None:
            raise ValueError("uncertain floor model requires an explicit fallback reason")
        return self
