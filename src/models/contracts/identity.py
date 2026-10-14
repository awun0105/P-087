"""Deterministic logical identities shared by artifact producers and consumers."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from src.models.contracts.release import ReleaseManifest, SceneRevisionRecord
from src.models.contracts.validation import CandidatePackage, ValidationReport


def canonical_json_bytes(value: BaseModel | dict[str, Any], exclude_field: str | None = None) -> bytes:
    """Canonical UTF-8 JSON; exclude only the top-level self-checksum field."""
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    if exclude_field is not None:
        if exclude_field not in data:
            raise ValueError(f"missing checksum field: {exclude_field}")
        data.pop(exclude_field)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_content_checksum(value: BaseModel | dict[str, Any], checksum_field: str) -> str:
    """Hash logical model content without its own checksum to avoid recursion."""
    digest = hashlib.sha256(canonical_json_bytes(value, checksum_field)).hexdigest()
    return f"sha256:{digest}"


def artifact_model_payload(value: BaseModel) -> bytes:
    """Serialize one contract using the deterministic JSON representation stored as an artifact."""
    return value.model_dump_json(indent=2).encode("utf-8") + b"\n"


def artifact_model_checksum(value: BaseModel) -> str:
    """Hash the exact pretty-printed JSON bytes used by model artifact publication."""
    return f"sha256:{hashlib.sha256(artifact_model_payload(value)).hexdigest()}"


def verify_content_checksum(value: BaseModel, checksum_field: str) -> None:
    """Reject stale logical identities while leaving byte refs to the resolver."""
    expected = canonical_content_checksum(value, checksum_field)
    if getattr(value, checksum_field) != expected:
        raise ValueError(f"{type(value).__name__}.{checksum_field} does not match canonical content")


def verify_candidate_lineage(
    candidate: CandidatePackage,
    report: ValidationReport,
    release: ReleaseManifest | SceneRevisionRecord,
) -> None:
    """Bind one immutable package to its validation and release-facing identity."""
    verify_candidate_inventory(candidate)
    verify_content_checksum(candidate, "candidate_checksum")
    verify_content_checksum(report, "report_checksum")
    if isinstance(release, ReleaseManifest):
        verify_content_checksum(release, "release_manifest_checksum")
    if report.candidate_checksum != candidate.candidate_checksum:
        raise ValueError("ValidationReport candidate identity mismatch")
    if release.candidate_checksum != candidate.candidate_checksum:
        raise ValueError("release candidate identity mismatch")
    if release.validation_report_checksum != report.report_checksum:
        raise ValueError("release validation report identity mismatch")


def verify_candidate_inventory(candidate: CandidatePackage) -> None:
    """Require the manifest inventory to cover exactly the package byte refs."""
    refs = [candidate.entrypoint_usd, *candidate.assets, *candidate.geometry, *candidate.colliders]
    collision_source_ref = candidate.candidate_manifest.collision_source_ref
    collision_selection_ref = candidate.candidate_manifest.collision_selection_ref
    if collision_source_ref is not None and collision_source_ref not in candidate.colliders:
        raise ValueError("CandidateManifest collision_source_ref is missing from package collider refs")
    if collision_selection_ref is not None:
        refs.append(collision_selection_ref)
    checksums = [ref.artifact_checksum for ref in refs]
    if candidate.candidate_manifest.artifact_checksums != checksums:
        raise ValueError("CandidateManifest artifact_checksums do not match package refs")
    if candidate.candidate_manifest.asset_refs != candidate.assets:
        raise ValueError("CandidateManifest asset_refs do not match package assets")
    if candidate.candidate_manifest.collider_refs != candidate.colliders:
        raise ValueError("CandidateManifest collider_refs do not match package colliders")
