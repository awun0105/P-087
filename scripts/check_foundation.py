"""Read-only Integration Foundation readiness checker."""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.models.contracts.identity import (
    verify_candidate_inventory,
    verify_candidate_lineage,
    verify_content_checksum,
)
from src.models.contracts.manifests import InputFile, InputManifest, JobManifest, RuntimeManifest, StageArtifact
from src.models.contracts.reconstruction import (
    AlignmentRecord,
    LiDARGeometryArtifact,
    ReconstructionBundle,
    VisualArtifact,
)
from src.models.contracts.release import ApprovalRecord, SceneRevisionRecord
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import CandidatePackage, ValidationReport
from src.services.orchestration.artifacts import ArtifactResolver, sha256_file

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures"
RESOLVER = ArtifactResolver(FIXTURES / "artifact_store")


def _validate_fixture(model: type[BaseModel], relative_path: str) -> BaseModel:
    path = FIXTURES / relative_path
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _check_contract_fixtures() -> None:
    for model in _foundation_models():
        checksum_field = _logical_checksum_field(model)
        if checksum_field is not None:
            verify_content_checksum(model, checksum_field)
    verify_candidate_inventory(_validate_fixture(CandidatePackage, "candidate/candidate_package.json"))
    snapshots = json.loads((FIXTURES / "mock_job/scene_revision_states.json").read_text(encoding="utf-8"))
    for snapshot in snapshots:
        SceneRevisionRecord.model_validate(snapshot)


def _foundation_models() -> list[BaseModel]:
    """List every committed, contract-shaped Foundation fixture."""
    entries: list[tuple[type[BaseModel], str]] = [
        (InputManifest, "mock_job/input_manifest.json"),
        (JobManifest, "mock_job/job_manifest.json"),
        (RuntimeManifest, "mock_job/runtime_manifest.json"),
        (VisualArtifact, "reconstruction_bundle/visual_artifact.json"),
        (LiDARGeometryArtifact, "reconstruction_bundle/lidar_artifact.json"),
        (ReconstructionBundle, "reconstruction_bundle/manifest.json"),
        (ReconstructionBundle, "reconstruction_bundle/rgb_depth_manifest.json"),
        (ReconstructionBundle, "reconstruction_bundle/mixed_manifest.json"),
        (SceneIR, "scene_ir/scene.json"),
        (SceneIR, "scene_ir/edited_scene.json"),
        (CandidatePackage, "candidate/candidate_package.json"),
        (ValidationReport, "validation_report/validation_report.json"),
        (ValidationReport, "validation_report/failed_validation_report.json"),
        (ApprovalRecord, "mock_job/approval_record.json"),
        (ArtifactRef, "evaluation/ground_truth_ref.json"),
    ]
    return [_validate_fixture(model, path) for model, path in entries]


def _logical_checksum_field(model: BaseModel) -> str | None:
    """Only self-describing content fields use canonical JSON identity."""
    names = {
        InputManifest: "input_manifest_checksum",
        JobManifest: "job_manifest_checksum",
        RuntimeManifest: "runtime_manifest_checksum",
        ReconstructionBundle: "artifact_checksum",
        SceneIR: "scene_ir_checksum",
        CandidatePackage: "candidate_checksum",
        ValidationReport: "report_checksum",
        ApprovalRecord: "record_checksum",
    }
    return names.get(type(model))


def _iter_references(value: object) -> list[ArtifactRef]:
    """Visit typed refs, including optional and nested evidence paths."""
    if isinstance(value, ArtifactRef):
        return [value]
    if isinstance(value, BaseModel):
        return [ref for name in type(value).model_fields for ref in _iter_references(getattr(value, name))]
    if isinstance(value, (list, tuple)):
        return [ref for item in value for ref in _iter_references(item)]
    return []


def _direct_references(model: BaseModel) -> list[ArtifactRef]:
    """Wrap URI/checksum pairs that predate the shared ArtifactRef field shape."""
    if isinstance(model, InputManifest):
        return [_direct_ref(item) for item in model.files]
    if isinstance(model, JobManifest):
        references: list[ArtifactRef] = []
        for item in model.stage_artifacts:
            if item.artifact_uri is None:
                continue
            references.append(_direct_ref(item))
        return references
    if isinstance(model, (VisualArtifact, LiDARGeometryArtifact)):
        return [_direct_ref(model)]
    if isinstance(model, ReconstructionBundle) and model.alignment_record is not None:
        return [_direct_ref(model.alignment_record)]
    return []


def _direct_ref(
    item: InputFile | StageArtifact | VisualArtifact | LiDARGeometryArtifact | AlignmentRecord,
) -> ArtifactRef:
    """Preserve the declared byte identity of a direct manifest URI."""
    if isinstance(item, InputFile):
        uri, checksum, data_class, artifact_type, stage = (
            item.artifact_uri,
            item.checksum,
            item.data_class,
            "InputFile",
            "ST-INPUT-VALIDATE",
        )
    elif isinstance(item, StageArtifact):
        if (
            item.artifact_uri is None
            or item.artifact_checksum is None
            or item.data_class is None
            or item.artifact_type is None
        ):
            raise ValueError("stage artifact URI requires type, checksum and data class")
        uri, checksum, data_class, artifact_type, stage = (
            item.artifact_uri,
            item.artifact_checksum,
            item.data_class,
            item.artifact_type,
            item.stage_id,
        )
    else:
        uri, checksum, data_class, artifact_type, stage = (
            item.artifact_uri,
            item.artifact_checksum,
            ArtifactDataClass.DERIVED,
            item.artifact_type,
            item.producer_stage,
        )
    return ArtifactRef.model_validate(
        {
            "artifact_type": artifact_type,
            "schema_version": "1.0",
            "artifact_uri": uri,
            "artifact_checksum": checksum,
            "data_class": data_class,
            "producer_stage": stage,
        }
    )


def verify_fixture_references(models: list[BaseModel], resolver: ArtifactResolver) -> None:
    """Resolve and SHA-256-check every typed/direct fixture byte reference."""
    for model in models:
        for reference in [*_iter_references(model), *_direct_references(model)]:
            resolver.require(reference)


def _check_resolvable_references() -> None:
    verify_fixture_references(_foundation_models(), RESOLVER)


def _check_handoff_lineage() -> None:
    """Check the synthetic producer-to-release-facing identity chain."""
    input_manifest = _validate_fixture(InputManifest, "mock_job/input_manifest.json")
    job = _validate_fixture(JobManifest, "mock_job/job_manifest.json")
    bundle = _validate_fixture(ReconstructionBundle, "reconstruction_bundle/mixed_manifest.json")
    scene = _validate_fixture(SceneIR, "scene_ir/scene.json")
    edited = _validate_fixture(SceneIR, "scene_ir/edited_scene.json")
    candidate = _validate_fixture(CandidatePackage, "candidate/candidate_package.json")
    report = _validate_fixture(ValidationReport, "validation_report/validation_report.json")
    approval = _validate_fixture(ApprovalRecord, "mock_job/approval_record.json")
    snapshots = json.loads((FIXTURES / "mock_job/scene_revision_states.json").read_text(encoding="utf-8"))
    approved = SceneRevisionRecord.model_validate(snapshots[3])
    draft = SceneRevisionRecord.model_validate(snapshots[4])
    _check_source_bindings(input_manifest, job, bundle)
    if scene.provenance.get("reconstruction_bundle_checksum") != bundle.artifact_checksum:
        raise ValueError("SceneIR reconstruction lineage mismatch")
    _check_candidate_source(job, scene, candidate)
    verify_candidate_lineage(candidate, report, approved)
    if approval.record_checksum != approved.approval_record_checksum:
        raise ValueError("approved revision record identity mismatch")
    if approval.candidate_checksum != candidate.candidate_checksum:
        raise ValueError("approval candidate identity mismatch")
    if approval.validation_report_checksum != report.report_checksum:
        raise ValueError("approval validation identity mismatch")
    if draft.scene_ir_checksum != edited.scene_ir_checksum or draft.candidate_checksum is not None:
        raise ValueError("edited SceneIR revision retained stale candidate identity")


def _check_source_bindings(input_manifest: InputManifest, job: JobManifest, bundle: ReconstructionBundle) -> None:
    """Bind input bytes/config to the reconstruction and scene revisions."""
    if sha256_file(FIXTURES / "mock_job/processing_config.json") != job.config_checksum:
        raise ValueError("JobManifest processing config byte checksum mismatch")
    for input_file in input_manifest.files:
        if RESOLVER.resolve(input_file.artifact_uri).stat().st_size != input_file.size_bytes:
            raise ValueError("InputManifest input byte size mismatch")
    if job.input_manifest_checksum != input_manifest.input_manifest_checksum:
        raise ValueError("JobManifest input identity mismatch")
    if bundle.source_input_checksum != input_manifest.input_manifest_checksum:
        raise ValueError("ReconstructionBundle input identity mismatch")


def _check_candidate_source(job: JobManifest, scene: SceneIR, candidate: CandidatePackage) -> None:
    """Bind package inventory/validation/approval to one exact scene."""
    if candidate.candidate_manifest.scene_ir_checksum != scene.scene_ir_checksum:
        raise ValueError("CandidateManifest scene identity mismatch")
    if candidate.candidate_manifest.job_manifest_checksum != job.job_manifest_checksum:
        raise ValueError("CandidateManifest job identity mismatch")
    if candidate.candidate_manifest.scene_revision != scene.scene_revision:
        raise ValueError("CandidateManifest scene revision mismatch")
    if candidate.candidate_manifest.build_config_checksum != job.config_checksum:
        raise ValueError("CandidateManifest build config identity mismatch")


def _check_negative_fixtures() -> None:
    invalid = [
        (ReconstructionBundle, "invalid/mixed_bundle_missing_alignment.json"),
        (SceneIR, "invalid/scene_missing_local_frame.json"),
        (ValidationReport, "invalid/validation_with_expected_label.json"),
    ]
    for model, relative_path in invalid:
        try:
            _validate_fixture(model, relative_path)
        except ValidationError:
            continue
        raise RuntimeError(f"negative fixture was accepted: {relative_path}")


def _check_document_projection() -> None:
    required = {
        "docs/execution/TEAM_EXECUTION_CONTRACT.md": ["REC-02A", "parent_from_local"],
        "docs/execution/TRACK_IMPLEMENTATION_GUIDE.md": ["REC-02A"],
        "docs/execution/tracks/ex_rec/TRACK.md": ["REC-02A"],
        "docs/execution/tracks/ex_rec/tasks/REC-02A.md": ["ST-FRAME-EXTRACT"],
    }
    for relative_path, needles in required.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        missing = [needle for needle in needles if needle not in text]
        if missing:
            raise RuntimeError(f"{relative_path} is missing: {', '.join(missing)}")


def _run_check(label: str, check: Callable[[], None]) -> bool:
    try:
        check()
    except (OSError, RuntimeError, ValidationError, ValueError) as error:
        print(f"[FAIL] {label}: {error}")
        return False
    print(f"[PASS] {label}")
    return True


def main() -> int:
    """Run every read-only Foundation gate and return a shell-compatible code."""
    checks = [
        ("typed contract fixtures", _check_contract_fixtures),
        ("artifact existence and SHA-256", _check_resolvable_references),
        ("synthetic handoff lineage", _check_handoff_lineage),
        ("negative fixtures rejected", _check_negative_fixtures),
        ("stage/task documentation projection", _check_document_projection),
    ]
    passed = [_run_check(label, check) for label, check in checks]
    if all(passed):
        print("Foundation fixture readiness: READY (M0 freeze also requires CI and common commit SHA)")
        return 0
    print("Foundation readiness: NOT READY")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
