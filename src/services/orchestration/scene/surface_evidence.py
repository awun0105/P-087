"""Publish surface inspection artifacts before collider/scene success, including rejected meshes."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId


def publish_surface_artifacts(
    job_id: str, object_id: str, item: dict, publish: Callable[[ProductArtifactRef, bytes], ProductArtifactRef]
) -> dict:
    quality = json.loads(Path(item["quality_report_path"]).read_bytes())
    repair = json.loads(Path(item["repair_report_path"]).read_bytes())
    if (
        quality.get("object_id") != object_id
        or quality.get("passed") is not item["quality_passed"]
        or any(
            report.get("object_id") != object_id
            or report.get("source_checksum") != item["raw_checksum"]
            or report.get("result_checksum") != item["checksum"]
            for report in (quality, repair)
        )
    ):
        raise ValueError("surface reports do not bind the object, source and result checksums")
    refs = {}
    kinds = {
        "raw": "ObjectSurfaceRawMesh",
        "quality_report": "ObjectSurfaceQualityReport",
        "repair_report": "ObjectSurfaceRepairReport",
        "support": "ObjectSurfaceDepthSupport",
        "surface": "ObjectSurfaceMesh" if item["quality_passed"] else "ObjectSurfaceCandidateMesh",
    }
    for key, artifact_type in kinds.items():
        path_key, checksum_key = ("path", "checksum") if key == "surface" else (key + "_path", key + "_checksum")
        if path_key not in item:
            if key == "support":
                continue
            raise ValueError("missing required surface evidence: " + key)
        payload = Path(item[path_key]).read_bytes()
        checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
        if checksum != item[checksum_key]:
            raise ValueError("surface evidence checksum mismatch: " + key)
        suffix = ".json" if key.endswith("report") else ".npz" if key == "support" else ".glb"
        reference = ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            job_id=job_id,
            artifact_uri=f"artifact://jobs/{job_id}/scene/objectgs/surface-evidence/{key}/{checksum[7:]}{suffix}",
            artifact_checksum=checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.SCENE_DECOMPOSE,
            source_provenance={
                **item.get("producer_provenance", {}),
                "object_id": object_id,
                "quality_passed": item["quality_passed"],
                **({"surface_evidence": dict(refs)} if key == "surface" else {}),
            },
        )
        stored = publish(reference, payload)
        if stored != reference:
            raise ValueError("surface evidence publisher changed identity")
        refs[key] = reference.model_dump(mode="json")
    return refs
