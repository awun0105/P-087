"""Parse saved collision-clearance evidence without upgrading its claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, PositiveFloat, model_validator


class SavedClearanceRecord(BaseModel):
    """Normalized form of one historical collision-path JSONL row."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    benchmark: Literal["collision_path_clearance"]
    label: str = Field(min_length=1)
    measured_at: datetime
    status: str = Field(default="ok", min_length=1)
    resolution_m: PositiveFloat
    source: str | None = None
    cloud: str | None = None
    trajectory_origin: str | None = None
    robot_radius_m: PositiveFloat | None = None
    robot_height_m: PositiveFloat | None = None
    floor_band_m: FiniteFloat | None = Field(default=None, ge=0)
    min_range_m: FiniteFloat | None = Field(default=None, ge=0)
    alignment_median_m: FiniteFloat | None = Field(default=None, ge=0)
    blocked_positions: int | None = Field(default=None, ge=0)
    camera_positions: int | None = Field(default=None, ge=0)
    blocked_fraction: FiniteFloat | None = Field(default=None, ge=0, le=1)
    triangles: int | None = Field(default=None, ge=0)
    lidar_points: int | None = Field(default=None, ge=0)
    occupied_cells: int | None = Field(default=None, ge=0)
    source_geometry_checksum: str | None = None
    profile_checksum: str | None = None
    hardware_id: str | None = None

    @model_validator(mode="after")
    def _validate_measured_counts(self) -> SavedClearanceRecord:
        if self.status == "ok":
            if self.blocked_positions is None or self.camera_positions is None or self.camera_positions == 0:
                raise ValueError("successful clearance row requires non-empty camera position counts")
            if self.blocked_positions > self.camera_positions:
                raise ValueError("blocked_positions cannot exceed camera_positions")
            expected_fraction = self.blocked_positions / self.camera_positions
            if self.blocked_fraction is None or abs(self.blocked_fraction - expected_fraction) > 0.000051:
                raise ValueError("blocked_fraction does not match the measured counts")
        return self

    @property
    def evidence_class(
        self,
    ) -> Literal[
        "gt_assisted_free_space_proxy",
        "declared_trajectory_free_space_proxy",
        "origin_unrecorded_free_space_proxy",
    ]:
        """The saved path test is a free-space proxy, never obstacle-recall evidence."""
        if self.trajectory_origin == "ground_truth":
            return "gt_assisted_free_space_proxy"
        if self.trajectory_origin is None:
            return "origin_unrecorded_free_space_proxy"
        return "declared_trajectory_free_space_proxy"

    @property
    def missing_provenance(self) -> list[str]:
        """Required provenance absent from the historical record, without inference from labels."""
        fields = (
            "source",
            "source_geometry_checksum",
            "profile_checksum",
            "hardware_id",
            "robot_radius_m",
            "robot_height_m",
            "trajectory_origin",
        )
        return [field for field in fields if getattr(self, field) is None]

    @property
    def independent_obstacle_recall_measured(self) -> Literal[False]:
        """The clearance logs contain no independent obstacle reference measurement."""
        return False


class SavedClearanceEvidence(BaseModel):
    """File-level identity and parsed rows for an immutable saved JSONL log."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_name: str
    file_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    records: list[SavedClearanceRecord] = Field(min_length=1)


def parse_clearance_jsonl(path: Path) -> SavedClearanceEvidence:
    """Read historical rows and bind them to the exact saved file bytes."""
    content = path.read_bytes()
    file_checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
    records: list[SavedClearanceRecord] = []
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            records.append(SavedClearanceRecord.model_validate(payload))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid clearance record at {path}:{line_number}: {error}") from error
    return SavedClearanceEvidence(file_name=path.name, file_checksum=file_checksum, records=records)


def measure_sample_retention(
    reference_samples_m: np.ndarray,
    collision_samples_m: np.ndarray,
    tolerance_m: float,
) -> tuple[int, int, float]:
    """Measure sampled obstacle/support retention for deterministic synthetic fixtures."""
    reference = np.asarray(reference_samples_m, dtype=float)
    collision = np.asarray(collision_samples_m, dtype=float)
    if reference.ndim != 2 or reference.shape[1:] != (3,) or reference.shape[0] == 0:
        raise ValueError("fixture reference must contain at least one XYZ sample")
    if collision.ndim != 2 or collision.shape[1:] != (3,):
        raise ValueError("collision samples must have shape (N, 3)")
    if not np.isfinite(reference).all() or not np.isfinite(collision).all():
        raise ValueError("fixture samples must be finite metric coordinates")
    if not np.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("tolerance_m must be finite and positive")

    retained = 0
    if collision.shape[0]:
        tolerance_squared = tolerance_m * tolerance_m
        for start in range(0, len(reference), 1024):
            block = reference[start : start + 1024]
            distances_squared = np.sum((block[:, None, :] - collision[None, :, :]) ** 2, axis=2)
            retained += int(np.any(distances_squared <= tolerance_squared, axis=1).sum())
    expected = int(reference.shape[0])
    return expected, retained, retained / expected


def _record_summary(record: SavedClearanceRecord) -> dict[str, object]:
    summary = record.model_dump(mode="json")
    summary["evidence_class"] = record.evidence_class
    summary["independent_obstacle_recall_measured"] = record.independent_obstacle_recall_measured
    summary["missing_provenance"] = record.missing_provenance
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+", help="saved collision-clearance JSONL logs")
    args = parser.parse_args(argv)
    for path in args.logs:
        evidence = parse_clearance_jsonl(path)
        print(
            json.dumps(
                {
                    "file_name": evidence.file_name,
                    "file_checksum": evidence.file_checksum,
                    "records": [_record_summary(record) for record in evidence.records],
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
