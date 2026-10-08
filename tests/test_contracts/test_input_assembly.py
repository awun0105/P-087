from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.input_assembly import (
    ArchiveMemberRef,
    CandidateState,
    EvidenceProvenance,
    EvidenceValue,
    GaussianViewCandidate,
    GaussianViewFormat,
    GaussianViewImportIntent,
    InputAssemblySnapshot,
    InputAssetFormat,
    InputBinding,
    InputRecipe,
    InputResolutionReport,
    InputResolutionState,
    InputRole,
    InputRoleEvidence,
    MissingInputFact,
    RecipeComponentVersion,
    RecipeGroup,
    RuntimeCapabilityKey,
    RuntimeCapabilityRecord,
    RuntimeQualificationRegistry,
    RuntimeQualificationStatus,
    StagedInputFile,
    TimestampUnit,
    TrajectoryOrigin,
    VideoRecipeCandidate,
    seal_gaussian_view_intent,
    seal_input_assembly,
    seal_input_recipe,
    seal_input_resolution,
    seal_runtime_registry,
    verify_gaussian_view_intent_checksum,
    verify_input_assembly_checksum,
    verify_input_recipe_checksum,
    verify_input_resolution_checksum,
    verify_runtime_registry_checksum,
)
from src.models.contracts.manifests import InputFile, InputManifest

ROOT = Path(__file__).parents[2]
MATRIX_PATH = ROOT / "fixtures/contracts/input_assembly_binding_matrix.json"
LEGACY_MANIFEST_PATH = ROOT / "fixtures/mock_job/input_manifest.json"
ZERO_CHECKSUM = "sha256:" + "0" * 64


def _input_file(upload_id: str, original_name: str, media_type: str = "application/zip") -> InputFile:
    return InputFile(
        original_name=original_name,
        media_type=media_type,
        size_bytes=256,
        checksum=ZERO_CHECKSUM,
        artifact_uri=f"artifact://jobs/{upload_id}/source/{original_name.replace('.', '_')}",
        data_class="product_input",
    )


def _staged(file_id: str, role: InputRole, *, upload_id: str | None = None) -> StagedInputFile:
    actual_upload_id = upload_id or file_id
    is_video = role == InputRole.RGB_VIDEO
    return StagedInputFile(
        file_id=file_id,
        upload_id=actual_upload_id,
        source_file=_input_file(
            actual_upload_id,
            "capture.mp4" if is_video else f"{file_id}.zip",
            "video/mp4" if is_video else "application/zip",
        ),
        observed_format=InputAssetFormat.VIDEO_MP4 if is_video else InputAssetFormat.ZIP_UNKNOWN,
        role_evidence=[InputRoleEvidence(role=role, provenance=EvidenceProvenance.OBSERVED, method="test_probe")],
    )


def _binding(role: InputRole, file_id: str, *, binding_id: str | None = None) -> InputBinding:
    return InputBinding(binding_id=binding_id or f"bind-{role.value}", role=role, file_ids=[file_id])


def _runtime(
    key: RuntimeCapabilityKey,
    status: RuntimeQualificationStatus = RuntimeQualificationStatus.WIRED_UNQUALIFIED,
) -> RuntimeCapabilityRecord:
    if status == RuntimeQualificationStatus.QUALIFIED:
        return RuntimeCapabilityRecord(
            capability_key=key,
            status=status,
            runtime_id="worker-rgb-v1",
            runtime_version="1.0.0",
            qualification_evidence_checksum=ZERO_CHECKSUM,
        )
    return RuntimeCapabilityRecord(
        capability_key=key,
        status=status,
        runtime_id="worker-rgb-v1" if status == RuntimeQualificationStatus.WIRED_UNQUALIFIED else None,
        runtime_version="1.0.0" if status == RuntimeQualificationStatus.WIRED_UNQUALIFIED else None,
        reason_codes=["qualification_pending"]
        if status == RuntimeQualificationStatus.WIRED_UNQUALIFIED
        else ["runtime_not_qualified"],
    )


def _assembly() -> InputAssemblySnapshot:
    return seal_input_assembly(
        InputAssemblySnapshot(
            schema_version="1.0",
            assembly_id="assembly-1",
            revision=1,
            owner_id="user-1",
            created_at=datetime(2026, 10, 8, tzinfo=UTC),
            files=[_staged("rgb-1", InputRole.RGB_VIDEO), _staged("map-1", InputRole.REGISTERED_LIDAR_MAP)],
            bindings=[_binding(InputRole.RGB_VIDEO, "rgb-1"), _binding(InputRole.REGISTERED_LIDAR_MAP, "map-1")],
            declarations={
                "same_scene": {"value": True, "provenance": "declared"},
                "cloud_state": {"value": "registered_map", "provenance": "declared"},
                "coordinate_unit": {"value": "m", "provenance": "declared"},
                "lidar_frame_id": {"value": "lidar_map", "provenance": "declared"},
            },
            assembly_checksum=ZERO_CHECKSUM,
        )
    )


def test_sealed_assembly_binds_files_bindings_and_declared_evidence() -> None:
    assembly = _assembly()
    verify_input_assembly_checksum(assembly)

    assert assembly.revision == 1
    assert assembly.bindings[1].role == InputRole.REGISTERED_LIDAR_MAP
    assert assembly.declarations.same_scene == EvidenceValue[bool](value=True, provenance="declared")

    tampered = assembly.model_copy(update={"owner_id": "user-2"})
    with pytest.raises(ValueError, match="checksum"):
        verify_input_assembly_checksum(tampered)


def test_optional_timestamp_unit_preserves_legacy_snapshot_checksums() -> None:
    assembly = _assembly()
    assert "timestamp_unit" not in assembly.declarations.model_dump(mode="json")
    assert "rgb_timestamp_unit" not in assembly.declarations.model_dump(mode="json")
    assert "lidar_timestamp_unit" not in assembly.declarations.model_dump(mode="json")
    verify_input_assembly_checksum(assembly)

    updated = assembly.model_copy(
        update={
            "declarations": assembly.declarations.model_copy(
                update={
                    "timestamp_unit": EvidenceValue[TimestampUnit](
                        value=TimestampUnit.MILLISECONDS, provenance=EvidenceProvenance.DECLARED
                    )
                }
            ),
            "assembly_checksum": ZERO_CHECKSUM,
        }
    )
    sealed = seal_input_assembly(updated)
    assert sealed.declarations.timestamp_unit is not None
    assert sealed.declarations.timestamp_unit.value == TimestampUnit.MILLISECONDS


def test_assembly_rejects_unknown_file_bindings_and_ambiguous_duplicate_roles() -> None:
    base = _assembly().model_dump(mode="json")
    base["assembly_checksum"] = ZERO_CHECKSUM
    base["bindings"][0]["file_ids"] = ["missing-file"]
    with pytest.raises(ValidationError, match="outside this revision"):
        InputAssemblySnapshot.model_validate(base)

    base = _assembly().model_dump(mode="json")
    base["assembly_checksum"] = ZERO_CHECKSUM
    base["bindings"].append(_binding(InputRole.RGB_VIDEO, "rgb-1", binding_id="another-rgb").model_dump(mode="json"))
    with pytest.raises(ValidationError, match="one selected binding per role"):
        InputAssemblySnapshot.model_validate(base)


def test_registered_map_recipe_does_not_require_calibration_or_trajectory() -> None:
    candidate = VideoRecipeCandidate(
        candidate_kind="video_recipe",
        candidate_id="candidate-r2",
        recipe_group=RecipeGroup.REGISTERED_MAP,
        state=CandidateState.PENDING_VERIFICATION,
        bindings=[
            _binding(InputRole.RGB_VIDEO, "rgb-1"),
            _binding(InputRole.REGISTERED_LIDAR_MAP, "map-1"),
        ],
        trajectory_origin=TrajectoryOrigin.NOT_REQUIRED,
        runtime=_runtime(RuntimeCapabilityKey.R2),
    )
    assert candidate.recipe_group == RecipeGroup.REGISTERED_MAP


def test_scan_sequence_binding_preserves_user_selected_order() -> None:
    binding = InputBinding(
        binding_id="scan-sequence",
        role=InputRole.LIDAR_SCAN,
        file_ids=["scan-03", "scan-04", "scan-05"],
    )
    assert binding.file_ids == ["scan-03", "scan-04", "scan-05"]


def test_runtime_registry_records_capability_identity_and_verification() -> None:
    registry = seal_runtime_registry(
        RuntimeQualificationRegistry(
            schema_version="1.0",
            registry_version="runtime-set-1",
            capabilities=[_runtime(RuntimeCapabilityKey.R1, RuntimeQualificationStatus.QUALIFIED)],
            registry_checksum=ZERO_CHECKSUM,
        )
    )
    verify_runtime_registry_checksum(registry)

    with pytest.raises(ValidationError, match="unique"):
        RuntimeQualificationRegistry(
            schema_version="1.0",
            registry_version="runtime-set-1",
            capabilities=[
                _runtime(RuntimeCapabilityKey.R1, RuntimeQualificationStatus.QUALIFIED),
                _runtime(RuntimeCapabilityKey.R1, RuntimeQualificationStatus.QUALIFIED),
            ],
            registry_checksum=ZERO_CHECKSUM,
        )


def test_calibration_cannot_substitute_for_sensor_trajectory_or_rgb_frame_times() -> None:
    with pytest.raises(ValidationError, match="missing required role bindings"):
        VideoRecipeCandidate(
            candidate_kind="video_recipe",
            candidate_id="candidate-r6",
            recipe_group=RecipeGroup.SENSOR_GUIDED,
            state=CandidateState.PENDING_VERIFICATION,
            bindings=[
                _binding(InputRole.RGB_VIDEO, "rgb-1"),
                _binding(InputRole.LIDAR_SCAN, "scan-1"),
                _binding(InputRole.CAMERA_LIDAR_CALIBRATION, "calib-1"),
                _binding(InputRole.CAMERA_TRAJECTORY, "camera-tum"),
            ],
            trajectory_origin=TrajectoryOrigin.SUPPLIED,
            runtime=_runtime(RuntimeCapabilityKey.R6),
        )


def test_supplied_trajectory_recipe_requires_sensor_trajectory_binding() -> None:
    common = {
        "candidate_kind": "video_recipe",
        "candidate_id": "candidate-r4",
        "recipe_group": RecipeGroup.SUPPLIED_TRAJECTORY,
        "state": CandidateState.PENDING_VERIFICATION,
        "trajectory_origin": TrajectoryOrigin.SUPPLIED,
        "runtime": _runtime(RuntimeCapabilityKey.R4),
    }
    with pytest.raises(ValidationError, match="missing required role bindings"):
        VideoRecipeCandidate(
            **common,
            bindings=[
                _binding(InputRole.RGB_VIDEO, "rgb-1"),
                _binding(InputRole.LIDAR_SCAN, "scan-1"),
            ],
        )

    candidate = VideoRecipeCandidate(
        **common,
        bindings=[
            _binding(InputRole.RGB_VIDEO, "rgb-1"),
            _binding(InputRole.LIDAR_SCAN, "scan-1"),
            _binding(InputRole.SENSOR_TRAJECTORY, "sensor-tum"),
        ],
    )
    assert candidate.recipe_group == RecipeGroup.SUPPLIED_TRAJECTORY


def test_estimated_trajectory_candidate_requires_lidar_timestamp_binding() -> None:
    common = {
        "candidate_kind": "video_recipe",
        "candidate_id": "candidate-r5",
        "recipe_group": RecipeGroup.ESTIMATED_TRAJECTORY,
        "trajectory_origin": TrajectoryOrigin.ESTIMATED,
        "runtime": _runtime(RuntimeCapabilityKey.R5),
    }
    base_bindings = [
        _binding(InputRole.RGB_VIDEO, "rgb-1"),
        _binding(InputRole.LIDAR_SCAN, "scan-1"),
    ]
    with pytest.raises(ValidationError, match="missing required role bindings"):
        VideoRecipeCandidate(state=CandidateState.PENDING_VERIFICATION, bindings=base_bindings, **common)

    needs_timestamp = VideoRecipeCandidate(
        state=CandidateState.NEEDS_INPUT,
        bindings=base_bindings,
        required_facts=[
            MissingInputFact(
                code="LIDAR_SCAN_TIMESTAMPS_REQUIRED",
                description="Bind one timestamp row per scan.",
            )
        ],
        **common,
    )
    assert needs_timestamp.state == CandidateState.NEEDS_INPUT

    candidate = VideoRecipeCandidate(
        state=CandidateState.PENDING_VERIFICATION,
        bindings=[*base_bindings, _binding(InputRole.LIDAR_SCAN_TIMES, "scan-times")],
        **common,
    )
    assert candidate.recipe_group == RecipeGroup.ESTIMATED_TRAJECTORY


def test_ready_resolution_requires_qualified_runtime_and_exact_candidate() -> None:
    candidate = VideoRecipeCandidate(
        candidate_kind="video_recipe",
        candidate_id="candidate-r1",
        recipe_group=RecipeGroup.RGB_ONLY,
        state=CandidateState.READY,
        bindings=[_binding(InputRole.RGB_VIDEO, "rgb-1")],
        trajectory_origin=TrajectoryOrigin.NOT_REQUIRED,
        runtime=_runtime(RuntimeCapabilityKey.R1, RuntimeQualificationStatus.QUALIFIED),
    )
    report = seal_input_resolution(
        InputResolutionReport(
            schema_version="1.0",
            assembly_id="assembly-1",
            assembly_revision=1,
            assembly_checksum=ZERO_CHECKSUM,
            resolver_version="resolver-1",
            runtime_registry_checksum=ZERO_CHECKSUM,
            state=InputResolutionState.READY,
            candidates=[candidate],
            recommended_candidate_id="candidate-r1",
            report_checksum=ZERO_CHECKSUM,
        )
    )
    verify_input_resolution_checksum(report)

    tampered = report.model_copy(update={"resolver_version": "resolver-2"})
    with pytest.raises(ValueError, match="checksum"):
        verify_input_resolution_checksum(tampered)


def test_ready_candidate_rejects_unqualified_runtime() -> None:
    with pytest.raises(ValidationError, match="qualified runtime"):
        VideoRecipeCandidate(
            candidate_kind="video_recipe",
            candidate_id="candidate-r1",
            recipe_group=RecipeGroup.RGB_ONLY,
            state=CandidateState.READY,
            bindings=[_binding(InputRole.RGB_VIDEO, "rgb-1")],
            trajectory_origin=TrajectoryOrigin.NOT_REQUIRED,
            runtime=_runtime(RuntimeCapabilityKey.R1),
        )


def test_accepted_recipe_is_checksum_bound_to_selected_route_versions_and_exclusions() -> None:
    recipe = seal_input_recipe(
        InputRecipe(
            schema_version="1.0",
            recipe_id="recipe-1",
            assembly_id="assembly-1",
            assembly_revision=3,
            assembly_checksum=ZERO_CHECKSUM,
            resolution_checksum=ZERO_CHECKSUM,
            candidate_id="candidate-r1",
            recipe_group=RecipeGroup.RGB_ONLY,
            selected_by="user-1",
            accepted_at=datetime(2026, 10, 8, tzinfo=UTC),
            bindings=[_binding(InputRole.RGB_VIDEO, "rgb-1")],
            excluded_file_ids=["unselected-sidecar"],
            trajectory_origin=TrajectoryOrigin.NOT_REQUIRED,
            component_versions=[RecipeComponentVersion(component_id="rgb_reconstruction", version="2.1")],
            config_checksum=ZERO_CHECKSUM,
            recipe_checksum=ZERO_CHECKSUM,
        )
    )
    verify_input_recipe_checksum(recipe)
    assert recipe.excluded_file_ids == ["unselected-sidecar"]


def test_gaussian_sog_view_intent_is_separate_from_video_recipe() -> None:
    candidate = GaussianViewCandidate(
        candidate_kind="gaussian_view_import",
        candidate_id="candidate-sog",
        source_file_id="sog-1",
        source_format=GaussianViewFormat.SOG,
        state=CandidateState.UNSUPPORTED,
        runtime=_runtime(RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW, RuntimeQualificationStatus.UNAVAILABLE),
    )
    assert candidate.candidate_kind == "gaussian_view_import"

    intent = seal_gaussian_view_intent(
        GaussianViewImportIntent(
            schema_version="1.0",
            intent_id="view-1",
            assembly_id="assembly-1",
            assembly_revision=1,
            assembly_checksum=ZERO_CHECKSUM,
            resolution_checksum=ZERO_CHECKSUM,
            candidate_id=candidate.candidate_id,
            source_file_id=candidate.source_file_id,
            source_format=candidate.source_format,
            source_checksum=ZERO_CHECKSUM,
            selected_by="user-1",
            selected_at=datetime(2026, 10, 8, tzinfo=UTC),
            intent_checksum=ZERO_CHECKSUM,
        )
    )
    verify_gaussian_view_intent_checksum(intent)
    assert intent.source_format == GaussianViewFormat.SOG


def test_verified_declarations_and_archive_members_need_bound_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence checksum"):
        InputRoleEvidence(role=InputRole.SENSOR_TRAJECTORY, provenance=EvidenceProvenance.VERIFIED)

    with pytest.raises(ValidationError, match="normalized relative POSIX path"):
        ArchiveMemberRef(
            container_checksum=ZERO_CHECKSUM,
            member_path="../trajectory.tum",
            member_checksum=ZERO_CHECKSUM,
            uncompressed_size_bytes=32,
        )


def test_owner_binding_matrix_covers_all_seven_combinations_without_claiming_runtime_acceptance() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    cases = matrix["cases"]

    assert matrix["schema_version"] == "1.0"
    assert len(cases) == 7
    assert {item["case_id"] for item in cases} == {
        f"owner-{index:02d}-" + suffix
        for index, suffix in [
            (1, "rgb-only"),
            (2, "registered-lidar"),
            (3, "single-raw-cloud"),
            (4, "lidar-and-calibration"),
            (5, "calibration-tum-and-rgb-frame-times"),
            (6, "calibration-and-rgb-frame-times-without-tum"),
            (7, "calibration-and-tum-without-rgb-frame-times"),
        ]
    }
    assert {group for case in cases for group in case["conditional_recipe_groups"]} == {
        item.value for item in RecipeGroup
    }
    assert cases[3]["requires_user_choice"] is True
    assert "trajectory" in cases[3]["notes"].lower()
    assert "rgb_clock_relation" in cases[4]["required_facts"]
    assert "R5" in cases[5]["conditional_recipe_groups"]
    assert "R6" not in cases[6]["conditional_recipe_groups"]


def test_legacy_input_manifest_checksum_and_payload_remain_unchanged() -> None:
    payload = json.loads(LEGACY_MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest = InputManifest.model_validate(payload)
    verify_content_checksum(manifest, "input_manifest_checksum")

    assert "assembly_checksum" not in manifest.model_dump(mode="json")
