from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.input_assembly import (
    CloudObservationState,
    DistanceUnit,
    EvidenceProvenance,
    InputAssemblySnapshot,
    InputAssetFormat,
    InputBinding,
    InputRole,
    RecipeComponentVersion,
    RecipeGroup,
    StagedInputFile,
    TrajectoryOrigin,
    seal_input_assembly,
    seal_input_recipe,
)
from src.models.contracts.manifests import InputFile, StageId
from src.models.contracts.rgb_lidar_registration import RegistrationInputMode
from src.services.orchestration.inputs.assembly import StoredInputAssembly
from src.services.orchestration.jobs.registration_preparation import (
    RegistrationRequestPreparer,
    RegistrationSceneRevisionConflictError,
)
from src.services.orchestration.jobs.registration_sources import InspectedRegistrationSource
from src.services.reconstruction.inputs.input_probe import InputProbe

_ZERO = "sha256:" + "0" * 64
_JOB = "job-preparation"
_PROJECT = "project-preparation"


def _checksum(value: str) -> str:
    return "sha256:" + sha256(value.encode()).hexdigest()


@pytest.mark.parametrize(
    ("recipe_group", "cloud_state", "role", "mode"),
    [
        (
            RecipeGroup.REGISTERED_MAP,
            CloudObservationState.REGISTERED_MAP,
            InputRole.REGISTERED_LIDAR_MAP,
            RegistrationInputMode.REGISTERED_MAP,
        ),
        (
            RecipeGroup.SINGLE_STATIC_CLOUD,
            CloudObservationState.SINGLE_STATIC_CLOUD,
            InputRole.STATIC_LIDAR_CLOUD,
            RegistrationInputMode.STATIC_CLOUD,
        ),
        (
            RecipeGroup.SENSOR_GUIDED,
            CloudObservationState.RAW_SCAN_SEQUENCE,
            InputRole.LIDAR_SCAN,
            RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP,
        ),
    ],
)
def test_preparer_seals_request_from_exact_accepted_map_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recipe_group: RecipeGroup,
    cloud_state: CloudObservationState,
    role: InputRole,
    mode: RegistrationInputMode,
) -> None:
    assembly_id = "assembly-preparation"
    estimated_map = mode == RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP
    source_file_ids = ["lidar-scan-1", "lidar-scan-2"] if estimated_map else ["lidar-file"]
    staged_sources: list[StagedInputFile] = []
    for index, file_id in enumerate(source_file_ids, start=1):
        source_ref = InputFile(
            original_name=f"{'scan' if estimated_map else 'registered-map'}-{index}.ply",
            media_type="application/octet-stream",
            size_bytes=64,
            checksum=_checksum(f"source-bytes-{index}"),
            artifact_uri=f"artifact://jobs/source-uploads/lidar-{index}.ply",
            data_class="product_input",
        )
        staged_sources.append(
            StagedInputFile(
                file_id=file_id,
                upload_id=f"lidar-upload-{index}",
                source_file=source_ref,
                observed_format=InputAssetFormat.POINT_CLOUD_PLY,
            )
        )
    staged = staged_sources[0]
    rgb_ref = InputFile(
        original_name="capture.mp4",
        media_type="video/mp4",
        size_bytes=16,
        checksum=_checksum("rgb-bytes"),
        artifact_uri="artifact://jobs/source-uploads/capture.mp4",
        data_class="product_input",
    )
    staged_rgb = StagedInputFile(
        file_id="rgb-file",
        upload_id="rgb-upload",
        source_file=rgb_ref,
        observed_format=InputAssetFormat.VIDEO_MP4,
    )
    auxiliary_inputs: list[tuple[InputRole, StagedInputFile]] = []
    if estimated_map:
        auxiliary_specs = [
            (InputRole.CAMERA_LIDAR_CALIBRATION, InputAssetFormat.CALIBRATION_JSON),
            (InputRole.RGB_FRAME_TIMES, InputAssetFormat.RGB_FRAME_TIMES),
            (InputRole.LIDAR_SCAN_TIMES, InputAssetFormat.TIMESTAMP_ROWS),
        ]
        for index, (input_role, observed_format) in enumerate(auxiliary_specs, start=1):
            source_ref = InputFile(
                original_name=f"{input_role.value}.txt",
                media_type="text/plain",
                size_bytes=16,
                checksum=_checksum(input_role.value),
                artifact_uri=f"artifact://jobs/source-uploads/{input_role.value}.txt",
                data_class="product_input",
            )
            auxiliary_inputs.append(
                (
                    input_role,
                    StagedInputFile(
                        file_id=f"aux-file-{index}",
                        upload_id=f"aux-upload-{index}",
                        source_file=source_ref,
                        observed_format=observed_format,
                    ),
                )
            )
    source_binding = InputBinding(binding_id="map", role=role, file_ids=source_file_ids)
    rgb_binding = InputBinding(binding_id="rgb", role=InputRole.RGB_VIDEO, file_ids=[staged_rgb.file_id])
    auxiliary_bindings = [
        InputBinding(binding_id=f"aux-{index}", role=input_role, file_ids=[input_file.file_id])
        for index, (input_role, input_file) in enumerate(auxiliary_inputs, start=1)
    ]
    all_staged_files = [*staged_sources, staged_rgb, *(item for _, item in auxiliary_inputs)]
    snapshot = seal_input_assembly(
        InputAssemblySnapshot(
            schema_version="1.0",
            assembly_id=assembly_id,
            revision=1,
            owner_id="guest-owner",
            created_at=datetime(2026, 10, 9, tzinfo=UTC),
            files=all_staged_files,
            bindings=[source_binding, rgb_binding, *auxiliary_bindings],
            declarations={
                "same_scene": {"value": True, "provenance": EvidenceProvenance.DECLARED},
                "cloud_state": {"value": cloud_state, "provenance": EvidenceProvenance.DECLARED},
                "coordinate_unit": {"value": DistanceUnit.METER, "provenance": EvidenceProvenance.DECLARED},
                "lidar_frame_id": {"value": "lidar-map-frame", "provenance": EvidenceProvenance.DECLARED},
            },
            assembly_checksum=_ZERO,
        )
    )
    probes = [
        InputProbe(
            file_id=item.file_id,
            source_checksum=item.source_file.checksum,
            member_checksum=None,
            observed_format=item.observed_format,
        )
        for item in all_staged_files
    ]
    stored = StoredInputAssembly(snapshot=snapshot, probes=tuple(probes))
    recipe = seal_input_recipe(
        {
            "schema_version": "1.0",
            "recipe_id": "recipe-preparation",
            "assembly_id": snapshot.assembly_id,
            "assembly_revision": snapshot.revision,
            "assembly_checksum": snapshot.assembly_checksum,
            "resolution_checksum": _checksum("resolution"),
            "candidate_id": f"candidate-{recipe_group.value.lower()}",
            "recipe_group": recipe_group,
            "selected_by": "guest-owner",
            "accepted_at": datetime(2026, 10, 9, tzinfo=UTC),
            "bindings": [source_binding, rgb_binding, *auxiliary_bindings],
            "trajectory_origin": TrajectoryOrigin.ESTIMATED if estimated_map else TrajectoryOrigin.NOT_REQUIRED,
            "component_versions": [RecipeComponentVersion(component_id="test-adapter", version="1.0")],
            "config_checksum": _checksum("config"),
            "recipe_checksum": _ZERO,
        }
    )
    recipe_ref = ProductArtifactRef(
        artifact_type="InputRecipe",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_PROJECT}/input/recipe.json",
        artifact_checksum=recipe.recipe_checksum,
        data_class="derived",
        producer_stage=StageId.RGB_GEOMETRY,
        job_id=_PROJECT,
    )
    run = SimpleNamespace(
        recipe_ref=recipe_ref,
        project_id=_PROJECT,
        assembly_id=snapshot.assembly_id,
        assembly_revision=snapshot.revision,
        assembly_checksum=snapshot.assembly_checksum,
        resolution_checksum=recipe.resolution_checksum,
        candidate_id=recipe.candidate_id,
        recipe_checksum=recipe.recipe_checksum,
    )

    metric_ref = ProductArtifactRef(
        artifact_type="RGBMetricConfirmation",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/metric/confirmation.json",
        artifact_checksum=_checksum("metric"),
        data_class="derived",
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=_JOB,
    )
    master_ref = ProductArtifactRef(
        artifact_type="GaussianPLY",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/visual/master.ply",
        artifact_checksum=_checksum("master"),
        data_class="derived",
        producer_stage=StageId.VISUAL_RECON,
        job_id=_JOB,
    )
    geometry_ref = ProductArtifactRef(
        artifact_type="RgbGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/geometry/collision.glb",
        artifact_checksum=_checksum("geometry"),
        data_class="derived",
        producer_stage=StageId.RGB_GEOMETRY,
        job_id=_JOB,
        source_provenance={
            "metric_confirmation_ref": metric_ref.model_dump(mode="json"),
            "preprocessing_provenance": {"details": {"master": master_ref.model_dump(mode="json")}},
        },
    )
    floor_ref = ProductArtifactRef(
        artifact_type="FloorFitEvidence",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/floor/floor-fit.json",
        artifact_checksum=_checksum("floor"),
        data_class="derived",
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=_JOB,
    )
    scene = SimpleNamespace(
        scene_revision="scene-revision-1",
        environment=SimpleNamespace(geometry_ref=geometry_ref),
        provenance={"floor_fit": {"artifact_ref": floor_ref.model_dump(mode="json")}},
    )
    runtime_resolver = SimpleNamespace(load_model=lambda _ref, _model: recipe)
    persistence = SimpleNamespace(
        resolver=runtime_resolver,
        input_run_for_job=lambda job_id: run if job_id == _JOB else None,
    )
    registry = SimpleNamespace(
        persistence=persistence,
        runtime_resolver=runtime_resolver,
        scene=SimpleNamespace(current=lambda _job_id: SimpleNamespace(scene=scene)),
        get_project=lambda _project_id: SimpleNamespace(input_recipe_ref=recipe_ref),
        resolve_artifact=lambda _job_id, _ref: tmp_path / "fixture-artifact",
    )
    assemblies = SimpleNamespace(get_assembly=lambda _assembly_id, _revision: stored)
    preparer = RegistrationRequestPreparer(
        registry,  # type: ignore[arg-type]
        assemblies,  # type: ignore[arg-type]
        max_collision_glb_bytes=1024 * 1024,
    )
    if estimated_map:
        product_ref = ProductArtifactRef(
            artifact_type="EstimatedTrajectoryProductEvidence",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{_JOB}/attempts/1/stages/lidar-odometry/product-evidence.json",
            artifact_checksum=_checksum("odometry-product"),
            data_class="derived",
            producer_stage=StageId.LIDAR_ODOMETRY,
            job_id=_JOB,
        )
        map_ref = ProductArtifactRef(
            artifact_type="EstimatedTrajectoryMapCloud",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{_JOB}/attempts/1/stages/lidar-odometry/estimated-map.ply",
            artifact_checksum=_checksum("estimated-map"),
            data_class="derived",
            producer_stage=StageId.LIDAR_ODOMETRY,
            job_id=_JOB,
            source_provenance={"map_frame_id": "odometry-map-frame"},
        )
        inspected_estimated = SimpleNamespace(
            source_checksum=map_ref.artifact_checksum,
            header_checksum=_checksum("estimated-map-header"),
            point_count=12,
            source_frame="odometry-map-frame",
            same_scene_attestation=True,
            input_assembly_id=snapshot.assembly_id,
            input_assembly_revision=snapshot.revision,
            input_assembly_checksum=snapshot.assembly_checksum,
        )
        monkeypatch.setattr(preparer, "_latest_estimated_map_refs", lambda _job: (product_ref, map_ref))
        monkeypatch.setattr(preparer, "_estimated_runtime_status", lambda _ref: "wired_unqualified")
        monkeypatch.setattr(preparer, "_estimated_map_frame", lambda _ref: "odometry-map-frame")
        monkeypatch.setattr(
            preparer.source_resolver,
            "inspect_estimated_trajectory_map",
            lambda **_kwargs: inspected_estimated,
        )
    else:
        inspected = InspectedRegistrationSource(
            path=tmp_path / "source.ply",
            file_id=staged.file_id,
            input_assembly_id=snapshot.assembly_id,
            input_assembly_revision=snapshot.revision,
            input_assembly_checksum=snapshot.assembly_checksum,
            source_checksum=staged.source_file.checksum,
            header_checksum=_checksum("ply-header"),
            point_count=12,
            input_format=InputAssetFormat.POINT_CLOUD_PLY,
            geometry_format="ply",
            distance_unit=DistanceUnit.METER,
            source_frame="lidar-map-frame",
            same_scene_attestation=True,
            stored=stored,
        )
        monkeypatch.setattr(preparer.source_resolver, "inspect_staged_source", lambda **_kwargs: inspected)
    monkeypatch.setattr(
        preparer.source_resolver,
        "resolve",
        lambda _request, _workspace: SimpleNamespace(same_scene_lineage_verified=True),
    )
    monkeypatch.setattr(preparer.target_resolver, "resolve", lambda _request: None)
    monkeypatch.setattr(
        "src.services.orchestration.jobs.registration_preparation.load_floor_fit_evidence",
        lambda _ref, _resolve: SimpleNamespace(
            job_id=_JOB,
            floor_model=SimpleNamespace(status="supported", prior=object()),
        ),
    )
    monkeypatch.setattr(
        "src.services.orchestration.jobs.registration_preparation.read_collision_glb",
        lambda _path: SimpleNamespace(positions=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 4.0))),
    )
    (tmp_path / "fixture-artifact").write_bytes(b"{}")

    prepared = preparer.prepare(
        SimpleNamespace(job_id=_JOB, project_id=_PROJECT),  # type: ignore[arg-type]
        requested_by="guest-owner",
        expected_scene_revision="scene-revision-1",
    )

    verify_content_checksum(prepared.request, "request_checksum")
    assert prepared.request.source.mode == mode
    assert prepared.request.source.source_role == role
    assert prepared.request.source.source_file_ids == source_file_ids
    assert prepared.request.source.input_assembly_checksum == snapshot.assembly_checksum
    assert prepared.request.source.same_scene_attestation is True
    assert prepared.request.expected_scene_revision == "scene-revision-1"
    assert prepared.request.target_rgb_geometry_ref == geometry_ref
    assert prepared.request.metric_confirmation_ref == metric_ref
    assert prepared.request.floor_model_refs == [floor_ref]
    assert prepared.request.profile.qualification_state == "provisional"
    if estimated_map:
        assert "UNQUALIFIED_PROFILE" in {finding.value for finding in prepared.preflight.findings}
    else:
        assert prepared.preflight.state.value == "READY"


def test_preparer_rejects_stale_scene_before_reading_input_run() -> None:
    registry = SimpleNamespace(
        scene=SimpleNamespace(current=lambda _job_id: SimpleNamespace(scene=SimpleNamespace(scene_revision="new")))
    )
    preparer = RegistrationRequestPreparer.__new__(RegistrationRequestPreparer)
    preparer.registry = registry

    with pytest.raises(RegistrationSceneRevisionConflictError):
        preparer.prepare(
            SimpleNamespace(job_id=_JOB),  # type: ignore[arg-type]
            requested_by="guest-owner",
            expected_scene_revision="old",
        )
