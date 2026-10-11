"""Path safety evidence must match the exact exported collider and candidate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionObservationState,
)
from src.models.contracts.scene import SceneEnvironment
from src.models.contracts.validation import (
    CollisionPathCoverageDiagnostic,
    CollisionPathSupportEvidence,
    ObservedPathResult,
    PathResult,
    RuleResult,
    ValidationCheck,
    ValidationReport,
)
from src.models.contracts.validation_run import ValidationConfig, ValidationPathPair
from src.services.orchestration.review.validation_gate import _collision_support_results
from tests.test_contracts.test_collision_quality import _report as make_quality_report
from tests.test_contracts.test_collision_quality import _selection

ZERO = "sha256:" + "0" * 64
CANDIDATE = "sha256:" + "e" * 64


def _ref(artifact_type: str, name: str, checksum: str, *, job_id: str = "job-001") -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/{name}",
        artifact_checksum=checksum,
        data_class="derived",
        producer_stage="ST-COLLIDER",
        job_id=job_id,
    )


class _Resolver:
    def __init__(self, artifacts: dict[str, object]) -> None:
        self.artifacts = artifacts

    def load_model(self, reference: ProductArtifactRef, model_type: type) -> object:
        value = self.artifacts[reference.artifact_uri]
        assert isinstance(value, model_type)
        return value


def _case(
    *,
    candidate_checksum: str = CANDIDATE,
    diagnostic_candidate_checksum: str | None = None,
    state: CollisionObservationState = CollisionObservationState.OBSERVED_STATIC,
    coverage: float = 1.0,
    quality_job_id: str = "job-001",
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, ValidationConfig, ValidationReport]:
    selection = _selection()
    selection_ref = _ref(
        "CollisionSourceSelection",
        "collision/selection.json",
        "sha256:" + "a" * 64,
    )
    quality = make_quality_report(selection, claim="verified")
    quality_ref = _ref(
        "CollisionQualityReport",
        "collision/quality.json",
        "sha256:" + "b" * 64,
        job_id=quality_job_id,
    )
    diagnostic = (
        CollisionPathCoverageDiagnostic(
            job_id=quality_job_id,
            candidate_checksum=diagnostic_candidate_checksum or candidate_checksum,
            effective_collision_ref=quality.effective_collision_ref,
            collision_quality_ref=quality_ref,
            pair_id="pair-1",
            state=state,
            observation_ids=["traversal-1"] if state == CollisionObservationState.OBSERVED_STATIC else [],
            coverage_fraction=coverage,
        )
        if quality_job_id == "job-001"
        else None
    )
    diagnostic_ref = (
        _ref(
            "CollisionPathCoverageDiagnostic",
            "collision/path-pair-1.json",
            "sha256:" + "c" * 64,
        )
        if diagnostic is not None
        else None
    )
    scene = SimpleNamespace(
        environment=SceneEnvironment(
            geometry_ref=selection.source_geometry_ref,
            collider_ref=quality.effective_collision_ref,
            collision_source_ref=selection.output_collision_ref,
            collision_selection_ref=selection_ref,
        )
    )
    candidate = SimpleNamespace(
        candidate_manifest=SimpleNamespace(
            collision_source_ref=selection.output_collision_ref,
            collision_selection_ref=selection_ref,
        ),
        candidate_checksum=candidate_checksum,
        colliders=[quality.effective_collision_ref],
    )
    config = ValidationConfig(
        schema_version="1.0",
        policy_id="collision-support-test-v1",
        required_check_ids=["scene_load"],
        warning_check_ids=[],
        path_pairs=[
            ValidationPathPair(
                pair_id="pair-1",
                start_xyz_m=(0.0, 0.0, 0.0),
                goal_xyz_m=(1.0, 0.0, 0.0),
                required=True,
            )
        ],
        config_checksum=ZERO,
    )
    report = ValidationReport(
        schema_version="1.0",
        candidate_checksum=candidate_checksum,
        validator_version="fixture-1",
        environment_versions={"isaac_sim": "fixture"},
        checks=[ValidationCheck(check_id="scene_load", result=RuleResult.PASS, evidence_refs=[])],
        path_results=[PathResult(pair_id="pair-1", result=ObservedPathResult.CLEAR, evidence_refs=[])],
        collision_quality_ref=quality_ref,
        collision_path_support=[
            CollisionPathSupportEvidence(
                pair_id="pair-1",
                state=state,
                observation_ids=["traversal-1"] if state == CollisionObservationState.OBSERVED_STATIC else [],
                coverage_fraction=coverage,
                diagnostic_ref=diagnostic_ref,
            )
        ],
        overall_result=RuleResult.PASS,
        report_checksum=ZERO,
    )
    artifacts = {
        selection_ref.artifact_uri: selection,
        quality_ref.artifact_uri: quality,
    }
    if diagnostic is not None and diagnostic_ref is not None:
        artifacts[diagnostic_ref.artifact_uri] = diagnostic
    registry = SimpleNamespace(runtime_resolver=_Resolver(artifacts))
    return registry, scene, candidate, config, report


def test_path_support_accepts_only_complete_static_evidence_for_exact_candidate() -> None:
    registry, scene, candidate, config, report = _case()

    blockers, warnings = _collision_support_results(registry, scene, candidate, config, report)

    assert blockers == []
    assert warnings == []


def test_path_support_rejects_quality_report_from_another_job() -> None:
    registry, scene, candidate, config, report = _case(
        quality_job_id="job-002",
        state=CollisionObservationState.UNOBSERVED,
        coverage=0.0,
    )

    blockers, warnings = _collision_support_results(registry, scene, candidate, config, report)

    assert blockers and "job khác" in blockers[0]
    assert warnings == []


def test_path_support_rejects_diagnostic_for_another_candidate() -> None:
    registry, scene, candidate, config, report = _case(
        diagnostic_candidate_checksum="sha256:" + "f" * 64,
    )

    blockers, warnings = _collision_support_results(registry, scene, candidate, config, report)

    assert len(blockers) == 1
    assert "path diagnostic" in blockers[0]
    assert warnings == []


@pytest.mark.parametrize(
    ("candidate_checksum", "state", "coverage"),
    [
        ("sha256:" + "f" * 64, CollisionObservationState.OBSERVED_STATIC, 1.0),
        (CANDIDATE, CollisionObservationState.MOTION_SUSPECTED, 0.0),
        (CANDIDATE, CollisionObservationState.OBSERVED_STATIC, 0.99),
    ],
)
def test_path_support_blocks_stale_motion_or_partial_coverage(
    candidate_checksum: str,
    state: CollisionObservationState,
    coverage: float,
) -> None:
    registry, scene, candidate, config, report = _case(
        candidate_checksum=candidate_checksum,
        state=state,
        coverage=coverage,
    )

    blockers, warnings = _collision_support_results(registry, scene, candidate, config, report)

    assert len(blockers) == 1
    assert "Collision support" in blockers[0]
    assert warnings == []
