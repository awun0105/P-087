"""Mask metadata owned by EX-SCENE before candidate association."""

from dataclasses import dataclass

from src.models.contracts.artifacts import JsonObject


@dataclass(frozen=True)
class BoundingBox:
    """Pixel-space box in xyxy order."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    def __post_init__(self) -> None:
        if self.x_min < 0 or self.y_min < 0:
            raise ValueError("bbox coordinates must be non-negative")
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("bbox must have positive area")


@dataclass(frozen=True)
class MaskObservation:
    """One extracted object mask with enough provenance for association."""

    mask_id: str
    frame_id: str
    bbox: BoundingBox
    confidence: float
    source_frame_uri: str
    object_hint: str
    provenance: JsonObject

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("mask confidence must be in [0, 1]")
        if not self.mask_id or not self.frame_id or not self.object_hint:
            raise ValueError("mask_id, frame_id and object_hint are required")


@dataclass(frozen=True)
class MaskSet:
    """Extraction output passed to multi-view association."""

    masks: tuple[MaskObservation, ...]
    config_checksum: str
    model_version: str
    provenance: JsonObject

    def __post_init__(self) -> None:
        if not self.masks:
            raise ValueError("mask set must contain at least one observation")
