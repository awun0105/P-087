from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.input_assembly import (
    ArchiveMemberRef,
    CloudObservationState,
    DistanceUnit,
    EvidenceProvenance,
    InputAssemblySnapshot,
    InputAssetFormat,
    InputBinding,
    InputRecipe,
    InputRole,
    RecipeComponentVersion,
    RecipeGroup,
    StagedInputFile,
    TrajectoryOrigin,
    seal_input_assembly,
    seal_input_recipe,
)
from src.models.contracts.manifests import InputFile, StageId
from src.models.contracts.reconstruction import (
    EstimatedTrajectoryConsumerEvidence,
    EstimatedTrajectoryIngestBinding,
    EstimatedTrajectoryMapEvidence,
    EstimatedTrajectoryMapStats,
    EstimatedTrajectoryProductEvidence,
)
from src.models.contracts.rgb_lidar_registration import (
    RegistrationInputMode,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    seal_registration_profile,
    seal_registration_request,
)
from src.services.orchestration.artifacts import ArtifactChecksumError, ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.inputs.assembly import StoredInputAssembly
from src.services.orchestration.inputs.runs import InputAssemblyRunRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.registration_sources import (
    RegistrationSourceResolutionError,
    RegistrationSourceResolver,
    load_registration_source_points,
)
from src.services.orchestration.projects.persistence import ProjectPersistence
from src.services.reconstruction.inputs.input_probe import InputProbe

_ZERO = "sha256:" + "0" * 64
_PLY_HEADER = (
    b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
)
_PLY_BYTES = _PLY_HEADER + b"0 0 0\n"


def _checksum(payload: bytes | str) -> str:
    raw = payload.encode() if isinstance(payload, str) else payload
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _ref(job_id: str, artifact_type: str, checksum: str | None = None) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/registration/{artifact_type.lower()}.json",
        artifact_checksum=checksum or _checksum(artifact_type),
        data_class="derived",
        producer_stage=(StageId.OBJECT_EXTRACT if artifact_type == "FloorFitEvidence" else StageId.RGB_LIDAR_ALIGN),
        job_id=job_id,
    )


class _Assemblies:
    def __init__(self, stored: StoredInputAssembly) -> None:
        self.stored = stored
        self.verified_upload_ids: set[str] = set()

    def get_assembly(self, assembly_id: str, revision: int) -> StoredInputAssembly:
        assert (assembly_id, revision) == (self.stored.snapshot.assembly_id, self.stored.snapshot.revision)
        return self.stored

    def verify_upload_sources(self, stored: StoredInputAssembly, *, upload_ids: set[str] | None = None) -> None:
        assert stored is self.stored
        self.verified_upload_ids = upload_ids or set()


class _Resolver:
    def __init__(self, artifacts: ArtifactResolver, recipe: InputRecipe | None = None) -> None:
        self.artifacts = artifacts
        self.recipe = recipe

    def require_uri(self, artifact_uri: str, checksum: str) -> Path:
        return self.artifacts.require_uri(artifact_uri, checksum)

    def load_model(self, reference: ProductArtifactRef, model_type: type[InputRecipe]) -> InputRecipe:
        assert self.recipe is not None and model_type is InputRecipe
        assert reference.artifact_checksum == self.recipe.recipe_checksum
        return self.recipe


class _Projects:
    def __init__(
        self,
        resolver: _Resolver,
        run: InputAssemblyRunRecord | None = None,
        recipe_ref: ProductArtifactRef | None = None,
    ) -> None:
        self.resolver = resolver
        self.run = run
        self.recipe_ref = recipe_ref

    def input_run_for_job(self, job_id: str) -> InputAssemblyRunRecord | None:
        assert job_id == "job-registration-1"
        return self.run

    def get_project(self, project_id: str) -> SimpleNamespace:
        assert project_id == "project-registration-1"
        return SimpleNamespace(input_recipe_ref=self.recipe_ref)


def _fixture(
    tmp_path: Path,
    *,
    archived: bool = False,
    include_video: bool = False,
    payload: bytes = _PLY_BYTES,
    distance_unit: DistanceUnit = DistanceUnit.METER,
) -> tuple[StoredInputAssembly, ArtifactResolver, RegistrationRequest]:
    root = tmp_path / "artifacts"
    cloud_uri = "artifact://jobs/source-uploads/map.zip" if archived else "artifact://jobs/source-uploads/map.ply"
    if archived:
        archive_path = root / "jobs/source-uploads/map.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("maps/static/map.ply", payload)
        cloud_container = archive_path.read_bytes()
        cloud_checksum = _checksum(payload)
        source_checksum = _checksum(cloud_container)
        member = ArchiveMemberRef(
            container_checksum=source_checksum,
            member_path="maps/static/map.ply",
            member_checksum=cloud_checksum,
            uncompressed_size_bytes=len(payload),
        )
        probe_member_checksum = cloud_checksum
        source_format = InputAssetFormat.POINT_CLOUD_PLY
    else:
        cloud_path = root / "jobs/source-uploads/map.ply"
        cloud_path.parent.mkdir(parents=True, exist_ok=True)
        cloud_path.write_bytes(payload)
        cloud_checksum = _checksum(payload)
        source_checksum = cloud_checksum
        member = None
        probe_member_checksum = None
        source_format = InputAssetFormat.POINT_CLOUD_PLY

    source_file = InputFile(
        original_name="map.zip" if archived else "map.ply",
        media_type="application/octet-stream",
        size_bytes=len(cloud_container) if archived else len(payload),
        checksum=source_checksum,
        artifact_uri=cloud_uri,
        data_class="product_input",
    )
    staged = StagedInputFile(
        file_id="map-file-1",
        upload_id="map-upload-1",
        source_file=source_file,
        observed_format=source_format,
        archive_member=member,
    )
    files = [staged]
    probes = [
        InputProbe(
            file_id=staged.file_id,
            source_checksum=source_checksum,
            member_checksum=probe_member_checksum,
            observed_format=source_format,
        )
    ]
    bindings = [InputBinding(binding_id="map-binding", role=InputRole.STATIC_LIDAR_CLOUD, file_ids=[staged.file_id])]
    if include_video:
        video = InputFile(
            original_name="capture.mp4",
            media_type="video/mp4",
            size_bytes=4,
            checksum=_checksum(b"video"),
            artifact_uri="artifact://jobs/source-uploads/capture.mp4",
            data_class="product_input",
        )
        video_file = StagedInputFile(
            file_id="rgb-file-1",
            upload_id="rgb-upload-1",
            source_file=video,
            observed_format=InputAssetFormat.VIDEO_MP4,
        )
        files.append(video_file)
        probes.append(
            InputProbe(
                file_id=video_file.file_id,
                source_checksum=video.checksum,
                member_checksum=None,
                observed_format=video_file.observed_format,
            )
        )
        bindings.append(InputBinding(binding_id="rgb-binding", role=InputRole.RGB_VIDEO, file_ids=[video_file.file_id]))
    snapshot = seal_input_assembly(
        InputAssemblySnapshot(
            schema_version="1.0",
            assembly_id="assembly-registration-1",
            revision=1,
            owner_id="source-uploader",
            created_at=datetime(2026, 10, 9, tzinfo=UTC),
            files=files,
            bindings=bindings,
            declarations={
                "same_scene": {"value": True, "provenance": EvidenceProvenance.DECLARED},
                "cloud_state": {
                    "value": CloudObservationState.SINGLE_STATIC_CLOUD,
                    "provenance": EvidenceProvenance.DECLARED,
                },
                "coordinate_unit": {"value": distance_unit, "provenance": EvidenceProvenance.DECLARED},
                "lidar_frame_id": {"value": "lidar-map-frame", "provenance": EvidenceProvenance.DECLARED},
            },
            assembly_checksum=_ZERO,
        )
    )
    stored = StoredInputAssembly(snapshot=snapshot, probes=tuple(probes))
    profile = seal_registration_profile({"profile_id": "registration-test-profile", "profile_checksum": _ZERO})
    source = RegistrationSourceBinding(
        mode=RegistrationInputMode.STATIC_CLOUD,
        target_job_id="job-registration-1",
        authorized_project_id="project-registration-1",
        source_input_checksum=cloud_checksum,
        source_frame="lidar-map-frame",
        source_distance_unit=distance_unit,
        source_point_count=1,
        source_format=source_format,
        source_header_checksum=_checksum(_PLY_HEADER),
        source_role=InputRole.STATIC_LIDAR_CLOUD,
        input_assembly_id=snapshot.assembly_id,
        input_assembly_revision=snapshot.revision,
        input_assembly_checksum=snapshot.assembly_checksum,
        source_file_ids=[staged.file_id],
        same_scene_attestation=True,
    )
    request = seal_registration_request(
        {
            "request_id": "registration-request-1",
            "requested_by": "reviewer-a",
            "target_project_id": "project-registration-1",
            "target_job_id": "job-registration-1",
            "target_rgb_geometry_ref": ProductArtifactRef(
                artifact_type="RgbGeometry",
                schema_version="1.0",
                artifact_uri="artifact://jobs/job-registration-1/rgb/geometry.json",
                artifact_checksum=_checksum("rgb-geometry"),
                data_class="derived",
                producer_stage=StageId.RGB_GEOMETRY,
                job_id="job-registration-1",
            ),
            "expected_scene_revision": "scene-revision-1",
            "source": source,
            "metric_state": "confirmed",
            "metric_confirmation_ref": _ref("job-registration-1", "RGBMetricConfirmation"),
            "floor_state": "supported",
            "floor_model_refs": [_ref("job-registration-1", "FloorFitEvidence")],
            "target_roi_world": RegistrationROI(min_xyz_m=(-20, -20, -2), max_xyz_m=(20, 20, 8)),
            "profile": profile,
            "profile_checksum": profile.profile_checksum,
            "request_checksum": _ZERO,
        }
    )
    return stored, ArtifactResolver(root), request


def _estimated_map_source_fixture(
    root: Path,
) -> tuple[
    RegistrationSourceResolver,
    _Assemblies,
    InputAssemblySnapshot,
    ProductArtifactRef,
    ProductArtifactRef,
    list[str],
    list[str],
]:
    job_id = "job-registration-1"
    project_id = "project-registration-1"
    source_scan_file_ids = ["scan-2", "scan-1"]
    scan_checksums = [_checksum("scan-2-bytes"), _checksum("scan-1-bytes")]
    auxiliary = [
        ("rgb-file", "capture.mp4", InputRole.RGB_VIDEO, InputAssetFormat.VIDEO_MP4, b"rgb-video"),
        (
            "calibration-file",
            "calibration.json",
            InputRole.CAMERA_LIDAR_CALIBRATION,
            InputAssetFormat.CALIBRATION_JSON,
            b"calibration",
        ),
        (
            "rgb-times-file",
            "rgb-frame-times.txt",
            InputRole.RGB_FRAME_TIMES,
            InputAssetFormat.RGB_FRAME_TIMES,
            b"0.0\n0.1\n",
        ),
        (
            "lidar-times-file",
            "lidar-scan-times.txt",
            InputRole.LIDAR_SCAN_TIMES,
            InputAssetFormat.TIMESTAMP_ROWS,
            b"0.0\n0.1\n",
        ),
    ]
    staged: list[StagedInputFile] = []
    for index, file_id in enumerate(source_scan_file_ids):
        payload = f"{file_id}-bytes".encode()
        source_file = InputFile(
            original_name=f"scan-{index}.ply",
            media_type="application/octet-stream",
            size_bytes=len(payload),
            checksum=scan_checksums[index],
            artifact_uri=f"artifact://jobs/source-uploads/scan-{index}.ply",
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
        staged.append(
            StagedInputFile(
                file_id=file_id,
                upload_id="scan-archive-upload",
                source_file=source_file,
                observed_format=InputAssetFormat.POINT_CLOUD_PLY,
            )
        )
    for file_id, filename, role, observed_format, payload in auxiliary:
        source_file = InputFile(
            original_name=filename,
            media_type="video/mp4" if role == InputRole.RGB_VIDEO else "text/plain",
            size_bytes=len(payload),
            checksum=_checksum(payload),
            artifact_uri=f"artifact://jobs/source-uploads/{filename}",
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
        staged.append(
            StagedInputFile(
                file_id=file_id,
                upload_id="video-upload" if role == InputRole.RGB_VIDEO else "scan-archive-upload",
                source_file=source_file,
                observed_format=observed_format,
            )
        )
    bindings = [
        InputBinding(binding_id="ordered-scans", role=InputRole.LIDAR_SCAN, file_ids=source_scan_file_ids),
        InputBinding(binding_id="rgb", role=InputRole.RGB_VIDEO, file_ids=["rgb-file"]),
        InputBinding(binding_id="calibration", role=InputRole.CAMERA_LIDAR_CALIBRATION, file_ids=["calibration-file"]),
        InputBinding(binding_id="rgb-times", role=InputRole.RGB_FRAME_TIMES, file_ids=["rgb-times-file"]),
        InputBinding(binding_id="lidar-times", role=InputRole.LIDAR_SCAN_TIMES, file_ids=["lidar-times-file"]),
    ]
    snapshot = seal_input_assembly(
        InputAssemblySnapshot(
            schema_version="1.0",
            assembly_id="assembly-estimated-map",
            revision=1,
            owner_id="reviewer-a",
            created_at=datetime(2026, 10, 9, tzinfo=UTC),
            files=staged,
            bindings=bindings,
            declarations={
                "same_scene": {"value": True, "provenance": EvidenceProvenance.DECLARED},
                "cloud_state": {
                    "value": CloudObservationState.RAW_SCAN_SEQUENCE,
                    "provenance": EvidenceProvenance.DECLARED,
                },
                "coordinate_unit": {"value": DistanceUnit.METER, "provenance": EvidenceProvenance.DECLARED},
                "lidar_frame_id": {"value": "lidar-sensor", "provenance": EvidenceProvenance.DECLARED},
                "lidar_timestamp_unit": {"value": "seconds", "provenance": EvidenceProvenance.DECLARED},
                "clock_relation": {"value": "same_clock", "provenance": EvidenceProvenance.DECLARED},
                "rgb_timestamp_unit": {"value": "seconds", "provenance": EvidenceProvenance.DECLARED},
            },
            assembly_checksum=_ZERO,
        )
    )
    stored = StoredInputAssembly(
        snapshot=snapshot,
        probes=tuple(
            InputProbe(
                file_id=item.file_id,
                source_checksum=item.source_file.checksum,
                member_checksum=None,
                observed_format=item.observed_format,
            )
            for item in staged
        ),
    )
    recipe = seal_input_recipe(
        {
            "schema_version": "1.0",
            "recipe_id": "recipe-estimated-map",
            "assembly_id": snapshot.assembly_id,
            "assembly_revision": snapshot.revision,
            "assembly_checksum": snapshot.assembly_checksum,
            "resolution_checksum": _checksum("resolution"),
            "candidate_id": "candidate-r6-estimated",
            "recipe_group": RecipeGroup.SENSOR_GUIDED,
            "selected_by": "reviewer-a",
            "accepted_at": datetime(2026, 10, 9, tzinfo=UTC),
            "bindings": bindings,
            "trajectory_origin": TrajectoryOrigin.ESTIMATED,
            "component_versions": [RecipeComponentVersion(component_id="test-r6", version="1.0")],
            "config_checksum": _checksum("recipe-config"),
            "recipe_checksum": _ZERO,
        }
    )
    recipe_payload = recipe.model_dump_json(indent=2).encode("utf-8") + b"\n"
    resolver = ArtifactResolver(root / "artifacts")
    writer = FilesystemArtifactStore(resolver)
    recipe_ref = ProductArtifactRef(
        artifact_type="InputRecipe",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{project_id}/input/recipe.json",
        artifact_checksum=_checksum(recipe_payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=project_id,
    )
    writer.publish(recipe_ref, recipe_payload)

    resolution_checksum = recipe.resolution_checksum
    runtime_registry_checksum = _checksum("runtime-registry")
    accepted_assembly_ref = ProductArtifactRef(
        artifact_type="InputAssemblySnapshot",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{project_id}/input/assembly.json",
        artifact_checksum=snapshot.assembly_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=project_id,
    )
    accepted_resolution_ref = ProductArtifactRef(
        artifact_type="InputResolutionReport",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{project_id}/input/resolution.json",
        artifact_checksum=resolution_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=project_id,
    )
    accepted_runtime_ref = ProductArtifactRef(
        artifact_type="RuntimeQualificationRegistry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{project_id}/input/runtime.json",
        artifact_checksum=runtime_registry_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=project_id,
    )
    project = SimpleNamespace(
        input_assembly_ref=accepted_assembly_ref,
        input_resolution_ref=accepted_resolution_ref,
        input_runtime_registry_ref=accepted_runtime_ref,
        input_recipe_ref=recipe_ref,
    )
    run = InputAssemblyRunRecord(
        requester_id="reviewer-a",
        idempotency_key="r6-run",
        request_fingerprint=_checksum("request"),
        job_id=job_id,
        project_id=project_id,
        assembly_id=snapshot.assembly_id,
        assembly_revision=snapshot.revision,
        assembly_checksum=snapshot.assembly_checksum,
        resolution_checksum=recipe.resolution_checksum,
        candidate_id=recipe.candidate_id,
        recipe_checksum=recipe.recipe_checksum,
        recipe_ref=recipe_ref,
        accepted_at=datetime(2026, 10, 9, tzinfo=UTC),
    )

    attempt_prefix = f"artifact://jobs/{job_id}/attempts/attempt-1/lidar-odometry"
    timestamp_ref = ArtifactRef(
        artifact_type="InputAssemblyMember",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/attempts/attempt-1/inputs/lidar-scan-times.txt",
        artifact_checksum=_checksum("lidar-timestamp-member"),
        data_class=ArtifactDataClass.PRODUCT_INPUT,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=job_id,
    )
    trajectory_ref = ArtifactRef(
        artifact_type="EstimatedTrajectoryArtifact",
        schema_version="1.0",
        artifact_uri=f"{attempt_prefix}/trajectory.json",
        artifact_checksum=_checksum("trajectory"),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=job_id,
        source_provenance={
            "assembly_checksum": snapshot.assembly_checksum,
            "recipe_checksum": recipe.recipe_checksum,
            "timestamp_file_checksum": timestamp_ref.artifact_checksum,
        },
    )
    ingest_binding = EstimatedTrajectoryIngestBinding(
        trajectory_ref=trajectory_ref,
        timestamp_file_ref=timestamp_ref,
        assembly_checksum=snapshot.assembly_checksum,
        recipe_checksum=recipe.recipe_checksum,
        source_scan_file_ids=source_scan_file_ids,
        source_scan_checksums=scan_checksums,
        sensor_frame_id="lidar-sensor",
        odometry_map_frame_id="odometry-map",
    )
    fusion_profile_checksum = _checksum("fusion-profile")
    map_checksum = _checksum(_PLY_BYTES)
    map_ref = ProductArtifactRef(
        artifact_type="EstimatedTrajectoryMapCloud",
        schema_version="1.0",
        artifact_uri=f"{attempt_prefix}/estimated-map.ply",
        artifact_checksum=map_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=job_id,
        source_provenance={
            "assembly_checksum": snapshot.assembly_checksum,
            "recipe_checksum": recipe.recipe_checksum,
            "trajectory_checksum": trajectory_ref.artifact_checksum,
            "timestamp_file_checksum": timestamp_ref.artifact_checksum,
            "map_frame_id": "odometry-map",
            "fusion_profile_checksum": fusion_profile_checksum,
            "source_scan_file_ids": source_scan_file_ids,
            "source_scan_checksums": scan_checksums,
        },
    )
    evidence_refs = [
        ArtifactRef(
            artifact_type=reference.artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/attempts/attempt-1/input/{reference.artifact_type}.json",
            artifact_checksum=reference.artifact_checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.LIDAR_ODOMETRY,
            job_id=job_id,
        )
        for reference in (
            accepted_assembly_ref,
            accepted_resolution_ref,
            accepted_runtime_ref,
            recipe_ref,
        )
    ]
    consumer = EstimatedTrajectoryConsumerEvidence(
        job_id=job_id,
        recipe_group="R6",
        assembly_ref=evidence_refs[0],
        resolution_ref=evidence_refs[1],
        runtime_registry_ref=evidence_refs[2],
        recipe_ref=evidence_refs[3],
        trajectory_ref=trajectory_ref,
        ingest_binding=ingest_binding,
        lidar_scan_times_ref=timestamp_ref,
        camera_lidar_calibration_ref=ArtifactRef(
            artifact_type="InputAssemblyMember",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/attempts/attempt-1/inputs/calibration.json",
            artifact_checksum=_checksum("calibration"),
            data_class=ArtifactDataClass.PRODUCT_INPUT,
            producer_stage=StageId.LIDAR_ODOMETRY,
            job_id=job_id,
        ),
        rgb_frame_times_ref=ArtifactRef(
            artifact_type="InputAssemblyMember",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/attempts/attempt-1/inputs/rgb-frame-times.txt",
            artifact_checksum=_checksum("rgb-times"),
            data_class=ArtifactDataClass.PRODUCT_INPUT,
            producer_stage=StageId.LIDAR_ODOMETRY,
            job_id=job_id,
        ),
        odometry_runtime_id="kiss-icp-python",
        odometry_runtime_version="1.3.0",
        odometry_profile_checksum=_checksum("odometry-profile"),
        runtime_qualification_status="wired_unqualified",
        sensor_guided_runtime_id="qualified-r6",
        sensor_guided_runtime_version="1.0",
        sensor_guided_runtime_evidence_checksum=_checksum("sensor-guided-runtime"),
    )
    map_evidence = EstimatedTrajectoryMapEvidence(
        job_id=job_id,
        trajectory_ref=trajectory_ref,
        ingest_binding=ingest_binding,
        map_cloud_ref=map_ref,
        map_frame_id="odometry-map",
        map_status="ready",
        point_count=1,
        fusion_profile_checksum=fusion_profile_checksum,
        fusion_stats=EstimatedTrajectoryMapStats(
            scan_count=2,
            input_points=2,
            removed_points=1,
            point_count=1,
            bounds_min=(0.0, 0.0, 0.0),
            bounds_max=(1.0, 1.0, 1.0),
        ),
    )
    product = EstimatedTrajectoryProductEvidence(
        job_id=job_id,
        consumer_evidence=consumer,
        map_evidence=map_evidence,
    )
    product_payload = product.model_dump_json(indent=2).encode("utf-8") + b"\n"
    product_ref = ProductArtifactRef(
        artifact_type="EstimatedTrajectoryProductEvidence",
        schema_version="1.0",
        artifact_uri=f"{attempt_prefix}/product-evidence.json",
        artifact_checksum=_checksum(product_payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=job_id,
    )
    writer.publish(map_ref, _PLY_BYTES)
    writer.publish(product_ref, product_payload)
    projects = SimpleNamespace(
        resolver=resolver,
        input_run_for_job=lambda requested_job_id: run if requested_job_id == job_id else None,
        get_project=lambda requested_project_id: project if requested_project_id == project_id else None,
    )
    assemblies = _Assemblies(stored)
    return (
        RegistrationSourceResolver(assemblies, projects),
        assemblies,
        snapshot,
        product_ref,
        map_ref,
        source_scan_file_ids,
        scan_checksums,
    )


def test_inspect_estimated_map_verifies_receipt_and_exact_ordered_recipe_binding(tmp_path: Path) -> None:
    (
        source_resolver,
        assemblies,
        snapshot,
        product_ref,
        map_ref,
        scan_file_ids,
        _scan_checksums,
    ) = _estimated_map_source_fixture(tmp_path)
    inspection = source_resolver.inspect_estimated_trajectory_map(
        job_id="job-registration-1",
        project_id="project-registration-1",
        assembly_id=snapshot.assembly_id,
        assembly_revision=snapshot.revision,
        assembly_checksum=snapshot.assembly_checksum,
        source_scan_file_ids=scan_file_ids,
        source_distance_unit=DistanceUnit.METER,
        source_frame="odometry-map",
        same_scene_attestation=True,
        estimated_trajectory_product_ref=product_ref,
        estimated_map_cloud_ref=map_ref,
        odometry_runtime_qualification_status="wired_unqualified",
        workspace=tmp_path / "registration-workspace",
        max_source_points=100,
    )

    assert inspection.path.read_bytes() == _PLY_BYTES
    assert inspection.source_scan_file_ids == tuple(scan_file_ids)
    assert inspection.source_checksum == map_ref.artifact_checksum
    assert inspection.source_frame == "odometry-map"
    assert inspection.odometry_runtime_qualification_status == "wired_unqualified"
    assert assemblies.verified_upload_ids == {"scan-archive-upload"}

    with pytest.raises(RegistrationSourceResolutionError, match="scan order differs"):
        source_resolver.inspect_estimated_trajectory_map(
            job_id="job-registration-1",
            project_id="project-registration-1",
            assembly_id=snapshot.assembly_id,
            assembly_revision=snapshot.revision,
            assembly_checksum=snapshot.assembly_checksum,
            source_scan_file_ids=list(reversed(scan_file_ids)),
            source_distance_unit=DistanceUnit.METER,
            source_frame="odometry-map",
            same_scene_attestation=True,
            estimated_trajectory_product_ref=product_ref,
            estimated_map_cloud_ref=map_ref,
            odometry_runtime_qualification_status="wired_unqualified",
            workspace=tmp_path / "reversed-scan-workspace",
            max_source_points=100,
        )

    map_from_other_attempt = map_ref.model_copy(
        update={"artifact_uri": map_ref.artifact_uri.replace("attempt-1", "attempt-2")}
    )
    with pytest.raises(RegistrationSourceResolutionError, match="does not describe this pending R6 map"):
        source_resolver.inspect_estimated_trajectory_map(
            job_id="job-registration-1",
            project_id="project-registration-1",
            assembly_id=snapshot.assembly_id,
            assembly_revision=snapshot.revision,
            assembly_checksum=snapshot.assembly_checksum,
            source_scan_file_ids=scan_file_ids,
            source_distance_unit=DistanceUnit.METER,
            source_frame="odometry-map",
            same_scene_attestation=True,
            estimated_trajectory_product_ref=product_ref,
            estimated_map_cloud_ref=map_from_other_attempt,
            odometry_runtime_qualification_status="wired_unqualified",
            workspace=tmp_path / "wrong-attempt-workspace",
            max_source_points=100,
        )


def test_resolve_checks_exact_assembly_source_and_header(tmp_path: Path) -> None:
    stored, artifacts, request = _fixture(tmp_path)
    assemblies = _Assemblies(stored)
    projects = _Projects(_Resolver(artifacts))

    resolved = RegistrationSourceResolver(assemblies, projects).resolve(request, tmp_path / "worker")

    assert resolved.path.read_bytes() == _PLY_BYTES
    assert resolved.input_assembly_checksum == stored.snapshot.assembly_checksum
    assert resolved.header_checksum == _checksum(_PLY_HEADER)
    assert resolved.point_count == 1
    assert resolved.geometry_format == "ply"
    assert resolved.same_scene_lineage_verified is False
    assert assemblies.verified_upload_ids == {"map-upload-1"}


def test_load_registration_source_points_converts_declared_units_to_meters(tmp_path: Path) -> None:
    payload = _PLY_HEADER + b"100 250 -300\n"
    stored, artifacts, request = _fixture(tmp_path, payload=payload, distance_unit=DistanceUnit.CENTIMETER)
    source = RegistrationSourceResolver(_Assemblies(stored), _Projects(_Resolver(artifacts))).resolve(
        request, tmp_path / "worker"
    )

    points = load_registration_source_points(source, request.profile)

    assert points.tolist() == [[1.0, 2.5, -3.0]]


def test_load_registration_source_points_rejects_bytes_changed_after_resolution(tmp_path: Path) -> None:
    stored, artifacts, request = _fixture(tmp_path)
    source = RegistrationSourceResolver(_Assemblies(stored), _Projects(_Resolver(artifacts))).resolve(
        request, tmp_path / "worker"
    )
    source.path.write_bytes(_PLY_HEADER + b"1 2 3\n")

    with pytest.raises(ValueError, match="source checksum"):
        load_registration_source_points(source, request.profile)


def test_resolve_materializes_only_the_checksum_bound_archive_member(tmp_path: Path) -> None:
    stored, artifacts, request = _fixture(tmp_path, archived=True)
    resolved = RegistrationSourceResolver(_Assemblies(stored), _Projects(_Resolver(artifacts))).resolve(
        request, tmp_path / "worker"
    )

    assert resolved.path.read_bytes() == _PLY_BYTES
    assert resolved.source_checksum == stored.snapshot.files[0].archive_member.member_checksum
    assert resolved.header_checksum == request.source.source_header_checksum


def test_resolve_rejects_a_header_checksum_not_observed_from_source_bytes(tmp_path: Path) -> None:
    stored, artifacts, request = _fixture(tmp_path)
    source = request.source.model_copy(update={"source_header_checksum": _checksum(b"forged header")})
    forged = seal_registration_request({**request.model_dump(mode="python"), "source": source})

    with pytest.raises(RegistrationSourceResolutionError, match="header checksum"):
        RegistrationSourceResolver(_Assemblies(stored), _Projects(_Resolver(artifacts))).resolve(
            forged, tmp_path / "worker"
        )


def test_same_scene_lineage_requires_one_accepted_run_with_rgb_and_selected_lidar(tmp_path: Path) -> None:
    stored, artifacts, request = _fixture(tmp_path, include_video=True)
    project_id, job_id = request.target_project_id, request.target_job_id
    recipe = seal_input_recipe(
        {
            "schema_version": "1.0",
            "recipe_id": "recipe-registration-1",
            "assembly_id": stored.snapshot.assembly_id,
            "assembly_revision": stored.snapshot.revision,
            "assembly_checksum": stored.snapshot.assembly_checksum,
            "resolution_checksum": _checksum("resolution"),
            "candidate_id": "candidate-registration-1",
            "recipe_group": RecipeGroup.SINGLE_STATIC_CLOUD,
            "selected_by": "source-uploader",
            "accepted_at": datetime(2026, 10, 9, tzinfo=UTC),
            "bindings": [
                InputBinding(binding_id="recipe-rgb", role=InputRole.RGB_VIDEO, file_ids=["rgb-file-1"]),
                InputBinding(binding_id="recipe-map", role=InputRole.STATIC_LIDAR_CLOUD, file_ids=["map-file-1"]),
            ],
            "trajectory_origin": TrajectoryOrigin.NOT_REQUIRED,
            "component_versions": [RecipeComponentVersion(component_id="video-worker", version="1.0")],
            "config_checksum": _checksum("config"),
            "recipe_checksum": _ZERO,
        }
    )
    recipe_ref = ProductArtifactRef(
        artifact_type="InputRecipe",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{project_id}/inputs/recipe.json",
        artifact_checksum=recipe.recipe_checksum,
        data_class="derived",
        producer_stage=StageId.RGB_GEOMETRY,
        job_id=project_id,
    )
    run = InputAssemblyRunRecord(
        requester_id="source-uploader",
        idempotency_key="input-run-key",
        request_fingerprint=_checksum("fingerprint"),
        job_id=job_id,
        project_id=project_id,
        assembly_id=stored.snapshot.assembly_id,
        assembly_revision=stored.snapshot.revision,
        assembly_checksum=stored.snapshot.assembly_checksum,
        resolution_checksum=_checksum("resolution"),
        candidate_id="candidate-registration-1",
        recipe_checksum=recipe.recipe_checksum,
        recipe_ref=recipe_ref,
        accepted_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    resolver = _Resolver(artifacts, recipe)
    projects = _Projects(resolver, run, recipe_ref)

    resolved = RegistrationSourceResolver(_Assemblies(stored), projects).resolve(request, tmp_path / "worker")

    assert resolved.same_scene_lineage_verified is True


def test_input_run_for_job_returns_record_and_rejects_row_payload_drift(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.sqlite'}")
    resolver = ArtifactResolver(tmp_path / "artifacts")
    persistence = ProjectPersistence(database, resolver)
    recipe_ref = _ref("project-registration-1", "InputRecipe")
    run = InputAssemblyRunRecord(
        requester_id="user-a",
        idempotency_key="input-run-key",
        request_fingerprint=_checksum("fingerprint"),
        job_id="job-registration-1",
        project_id="project-registration-1",
        assembly_id="assembly-registration-1",
        assembly_revision=1,
        assembly_checksum=_checksum("assembly"),
        resolution_checksum=_checksum("resolution"),
        candidate_id="candidate-1",
        recipe_checksum=_checksum("recipe"),
        recipe_ref=recipe_ref,
        accepted_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    with database.transaction(write=True) as tx:
        tx.execute("INSERT INTO r2s_projects(project_id,payload) VALUES (?,?)", (run.project_id, "{}"))
        tx.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?)",
            (run.job_id, run.project_id, 1, f"artifact://jobs/{run.job_id}/manifest.json"),
        )
        tx.execute(
            "INSERT INTO r2s_input_assemblies(assembly_id,revision,owner_id,payload) VALUES (?,?,?,?)",
            (run.assembly_id, run.assembly_revision, run.requester_id, "{}"),
        )
        tx.execute(
            "INSERT INTO r2s_input_resolutions(report_checksum,assembly_id,revision,owner_id,payload) "
            "VALUES (?,?,?,?,?)",
            (run.resolution_checksum, run.assembly_id, run.assembly_revision, run.requester_id, "{}"),
        )
        tx.execute(
            "INSERT INTO r2s_input_runs(requester_id,idempotency_key,request_fingerprint,job_id,project_id,"
            "assembly_id,revision,report_checksum,recipe_checksum,recipe_ref,payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.requester_id,
                run.idempotency_key,
                run.request_fingerprint,
                run.job_id,
                run.project_id,
                run.assembly_id,
                run.assembly_revision,
                run.resolution_checksum,
                run.recipe_checksum,
                run.recipe_ref.model_dump_json(),
                run.model_dump_json(),
            ),
        )

    assert persistence.input_run_for_job(run.job_id) == run
    assert persistence.input_run_for_job("missing-job") is None
    with database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_input_runs SET recipe_checksum=? WHERE job_id=?",
            (_checksum("other-recipe"), run.job_id),
        )
    with pytest.raises(ArtifactChecksumError, match="columns differ"):
        persistence.input_run_for_job(run.job_id)


@pytest.mark.parametrize("archived", [False, True])
def test_inspect_staged_source_derives_exact_direct_or_archive_identity(tmp_path: Path, archived: bool) -> None:
    stored, artifacts, request = _fixture(tmp_path, archived=archived)
    assemblies = _Assemblies(stored)
    resolver = RegistrationSourceResolver(assemblies, _Projects(_Resolver(artifacts)))

    inspected = resolver.inspect_staged_source(
        mode=RegistrationInputMode.STATIC_CLOUD,
        assembly_id=stored.snapshot.assembly_id,
        assembly_revision=stored.snapshot.revision,
        source_role=InputRole.STATIC_LIDAR_CLOUD,
        source_file_id="map-file-1",
        distance_unit=DistanceUnit.METER,
        source_frame="lidar-map-frame",
        same_scene_attestation=True,
        workspace=tmp_path / "inspect",
        max_source_points=10,
        expected_assembly_checksum=stored.snapshot.assembly_checksum,
    )

    assert inspected.source_checksum == request.source.source_input_checksum
    assert inspected.header_checksum == request.source.source_header_checksum
    assert inspected.point_count == request.source.source_point_count == 1
    assert inspected.geometry_format == "ply"
    assert inspected.distance_unit == DistanceUnit.METER
    assert inspected.source_frame == "lidar-map-frame"
    assert inspected.same_scene_attestation is True
    assert inspected.path.read_bytes() == _PLY_BYTES
    assert assemblies.verified_upload_ids == {"map-upload-1"}


def test_inspect_staged_source_rejects_role_or_header_checksum_mismatch(tmp_path: Path) -> None:
    stored, artifacts, _ = _fixture(tmp_path)
    resolver = RegistrationSourceResolver(_Assemblies(stored), _Projects(_Resolver(artifacts)))
    parameters = {
        "mode": RegistrationInputMode.STATIC_CLOUD,
        "assembly_id": stored.snapshot.assembly_id,
        "assembly_revision": stored.snapshot.revision,
        "source_role": InputRole.STATIC_LIDAR_CLOUD,
        "source_file_id": "map-file-1",
        "distance_unit": DistanceUnit.METER,
        "source_frame": "lidar-map-frame",
        "same_scene_attestation": True,
        "workspace": tmp_path / "inspect",
        "max_source_points": 10,
    }

    with pytest.raises(RegistrationSourceResolutionError, match="source role does not match"):
        resolver.inspect_staged_source(**{**parameters, "source_role": InputRole.REGISTERED_LIDAR_MAP})
    with pytest.raises(RegistrationSourceResolutionError, match="header checksum"):
        resolver.inspect_staged_source(**{**parameters, "expected_header_checksum": _checksum("forged")})
