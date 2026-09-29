"""Deterministic fixture extractor used until the SAM2 runtime is available."""

import hashlib
import json
from pathlib import Path

from src.services.scene.bundle_consumer import ValidatedBundleView
from src.services.scene.extraction.models import BoundingBox, MaskObservation, MaskSet

_MODEL_VERSION = "real2sim.fixture-extractor.v1"
_CONFIG_CHECKSUM = "sha256:89a2606757a2e442be9db9d4d6d342a34cfbc191e85dbf883b8849429e07e3c6"


def extract_fixture_masks(view: ValidatedBundleView) -> MaskSet:
    """Emit stable mask metadata from validated fixture frame manifests."""
    frame_ids = _load_frame_ids(view.rgb_frames)
    masks = tuple(_mask_for_frame(frame_id, index, view) for index, frame_id in enumerate(frame_ids))
    return MaskSet(
        masks=masks,
        config_checksum=_CONFIG_CHECKSUM,
        model_version=_MODEL_VERSION,
        provenance={
            "mode": "deterministic_fixture",
            "sam2_runtime": "not_used",
            "bundle_checksum": view.bundle.artifact_checksum,
        },
    )


def _load_frame_ids(paths: tuple[Path, ...]) -> tuple[str, ...]:
    if not paths:
        raise ValueError("RGB frame refs are required for object extraction")
    frame_ids: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        frame_ids.extend(str(item) for item in payload.get("frame_ids", []))
    if not frame_ids:
        raise ValueError("RGB frame manifest has no frame_ids")
    return tuple(frame_ids)


def _mask_for_frame(frame_id: str, index: int, view: ValidatedBundleView) -> MaskObservation:
    hint = "fixture-object-001"
    seed = hashlib.sha256(f"{frame_id}:{hint}".encode("utf-8")).hexdigest()
    return MaskObservation(
        mask_id=f"mask-{index + 1:06d}",
        frame_id=frame_id,
        bbox=BoundingBox(x_min=8, y_min=8, x_max=72, y_max=72),
        confidence=0.75,
        source_frame_uri=view.bundle.rgb_frame_refs[0].artifact_uri,
        object_hint=hint,
        provenance={"extractor": _MODEL_VERSION, "deterministic_seed": seed},
    )
