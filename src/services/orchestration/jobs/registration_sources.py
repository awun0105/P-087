"""Server-side verification of exact staged inputs for RGB–LiDAR registration."""

from __future__ import annotations

import hashlib
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.input_assembly import (
    ArchiveMemberRef,
    CloudObservationState,
    DistanceUnit,
    InputAssetFormat,
    InputRecipe,
    InputRole,
    verify_input_assembly_checksum,
    verify_input_recipe_checksum,
)
from src.models.contracts.rgb_lidar_registration import RegistrationInputMode, RegistrationProfile, RegistrationRequest
from src.services.orchestration.artifacts import ArtifactChecksumError
from src.services.orchestration.inputs.assembly import InputAssemblyService, StoredInputAssembly
from src.services.orchestration.projects.persistence import ProjectPersistence
from src.services.reconstruction.lidar.cloud_header import CloudHeader, read_header
from src.services.reconstruction.lidar.cloud_payload import load_registration_xyz_points


class RegistrationSourceResolutionError(ValueError):
    """The request's source binding does not match the stored assembly or bytes."""


@dataclass(frozen=True)
class VerifiedRegistrationSource:
    """Resolved source bytes and parsed header; the workspace owns any extracted member."""

    path: Path
    file_id: str
    input_assembly_id: str
    input_assembly_revision: int
    input_assembly_checksum: str
    source_checksum: str
    header_checksum: str
    point_count: int
    geometry_format: Literal["pcd", "ply"]
    distance_unit: Literal["m", "cm", "mm"]
    source_frame: str
    same_scene_lineage_verified: bool


@dataclass(frozen=True)
class InspectedRegistrationSource:
    """Observed identity for one source file, shared by preparation and worker checks."""

    path: Path
    file_id: str
    input_assembly_id: str
    input_assembly_revision: int
    input_assembly_checksum: str
    source_checksum: str
    header_checksum: str
    point_count: int
    input_format: InputAssetFormat
    geometry_format: Literal["pcd", "ply"]
    distance_unit: DistanceUnit | None
    source_frame: str | None
    same_scene_attestation: bool | None
    stored: StoredInputAssembly


def load_registration_source_points(source: VerifiedRegistrationSource, profile: RegistrationProfile) -> np.ndarray:
    """Load the exact verified payload, recheck its checksums, and normalize coordinates to meters."""
    return load_registration_xyz_points(
        source.path,
        max_points=profile.max_source_points,
        distance_unit=source.distance_unit,
        expected_source_checksum=source.source_checksum,
        expected_header_checksum=source.header_checksum,
        expected_point_count=source.point_count,
        expected_geometry_format=source.geometry_format,
    )


class RegistrationSourceResolver:
    """Re-resolve one exact PCD/PLY binding before a registration worker consumes it."""

    def __init__(self, assemblies: InputAssemblyService, projects: ProjectPersistence) -> None:
        self.assemblies = assemblies
        self.projects = projects
        self.resolver = projects.resolver

    def resolve(self, request: RegistrationRequest, workspace: Path) -> VerifiedRegistrationSource:
        """Verify request, immutable assembly, selected role, source bytes, and PCD/PLY header."""
        verify_content_checksum(request, "request_checksum")
        source = request.source
        if source.mode not in {RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD}:
            raise RegistrationSourceResolutionError(
                "only registered-map and static-cloud requests have one source file"
            )
        if source.input_assembly_id is None or source.input_assembly_revision is None:
            raise RegistrationSourceResolutionError("map registration requires an exact assembly revision")
        if source.input_assembly_checksum is None or len(source.source_file_ids) != 1:
            raise RegistrationSourceResolutionError("map registration requires one checksummed staged file")
        if source.source_format not in {InputAssetFormat.POINT_CLOUD_PCD, InputAssetFormat.POINT_CLOUD_PLY}:
            raise RegistrationSourceResolutionError("source format must be an observed PCD or PLY point cloud")
        if source.source_header_checksum is None or source.source_point_count is None:
            raise RegistrationSourceResolutionError("source header checksum and point count are required")
        if source.source_distance_unit is None or source.source_frame is None:
            raise RegistrationSourceResolutionError("source distance unit and coordinate frame are required")

        inspected = self.inspect_staged_source(
            mode=source.mode,
            assembly_id=source.input_assembly_id,
            assembly_revision=source.input_assembly_revision,
            source_role=source.source_role,
            source_file_id=source.source_file_ids[0],
            distance_unit=source.source_distance_unit,
            source_frame=source.source_frame,
            workspace=workspace,
            max_source_points=request.profile.max_source_points,
            expected_assembly_checksum=source.input_assembly_checksum,
            expected_source_checksum=source.source_input_checksum,
            expected_header_checksum=source.source_header_checksum,
            expected_point_count=source.source_point_count,
            expected_format=source.source_format,
            same_scene_attestation=source.same_scene_attestation,
        )
        verified = self._same_scene_lineage_verified(request, inspected.stored)
        return VerifiedRegistrationSource(
            path=inspected.path,
            file_id=inspected.file_id,
            input_assembly_id=inspected.input_assembly_id,
            input_assembly_revision=inspected.input_assembly_revision,
            input_assembly_checksum=inspected.input_assembly_checksum,
            source_checksum=inspected.source_checksum,
            header_checksum=inspected.header_checksum,
            point_count=inspected.point_count,
            geometry_format=inspected.geometry_format,
            distance_unit=source.source_distance_unit.value,
            source_frame=source.source_frame,
            same_scene_lineage_verified=verified,
        )

    def inspect_staged_source(
        self,
        *,
        mode: RegistrationInputMode,
        assembly_id: str,
        assembly_revision: int,
        source_role: InputRole,
        source_file_id: str,
        distance_unit: DistanceUnit | None,
        source_frame: str | None,
        workspace: Path,
        max_source_points: int,
        expected_assembly_checksum: str | None = None,
        expected_source_checksum: str | None = None,
        expected_header_checksum: str | None = None,
        expected_point_count: int | None = None,
        expected_format: InputAssetFormat | None = None,
        same_scene_attestation: bool | None = None,
    ) -> InspectedRegistrationSource:
        """Read the exact staged source identity without trusting client-reported header fields."""
        if mode not in {RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD}:
            raise RegistrationSourceResolutionError(
                "only registered-map and static-cloud requests have one source file"
            )
        expected_role, expected_cloud_state = {
            RegistrationInputMode.REGISTERED_MAP: (
                InputRole.REGISTERED_LIDAR_MAP,
                CloudObservationState.REGISTERED_MAP,
            ),
            RegistrationInputMode.STATIC_CLOUD: (
                InputRole.STATIC_LIDAR_CLOUD,
                CloudObservationState.SINGLE_STATIC_CLOUD,
            ),
        }[mode]
        if source_role != expected_role:
            raise RegistrationSourceResolutionError("source role does not match registration mode")

        stored = self.assemblies.get_assembly(assembly_id, assembly_revision)
        snapshot = stored.snapshot
        try:
            verify_input_assembly_checksum(snapshot)
        except ValueError as error:
            raise RegistrationSourceResolutionError("stored input assembly checksum is invalid") from error
        if (
            snapshot.assembly_id != assembly_id
            or snapshot.revision != assembly_revision
            or (expected_assembly_checksum is not None and snapshot.assembly_checksum != expected_assembly_checksum)
        ):
            raise RegistrationSourceResolutionError("request does not name the exact stored assembly revision")
        matching_bindings = [
            binding
            for binding in snapshot.bindings
            if binding.role == expected_role and binding.file_ids == [source_file_id]
        ]
        if len(matching_bindings) != 1:
            raise RegistrationSourceResolutionError("selected source file is not bound to the exact assembly role")

        staged_matches = [item for item in snapshot.files if item.file_id == source_file_id]
        if len(staged_matches) != 1:
            raise RegistrationSourceResolutionError("selected source file is absent or duplicated in the assembly")
        staged = staged_matches[0]
        probes = [item for item in stored.probes if item.file_id == staged.file_id]
        if len(probes) != 1:
            raise RegistrationSourceResolutionError("selected source file has no unique server-side upload probe")
        probe = probes[0]
        if probe.observed_format != staged.observed_format or (
            expected_format is not None and staged.observed_format != expected_format
        ):
            raise RegistrationSourceResolutionError("request format differs from the server-observed staged file")
        if probe.source_checksum != staged.source_file.checksum:
            raise RegistrationSourceResolutionError("upload probe does not match the immutable source checksum")

        if staged.archive_member is None:
            observed_source_checksum = staged.source_file.checksum
            if probe.member_checksum is not None:
                raise RegistrationSourceResolutionError("direct source unexpectedly carries an archive-member checksum")
        else:
            observed_source_checksum = staged.archive_member.member_checksum
            if (
                staged.archive_member.container_checksum != staged.source_file.checksum
                or probe.member_checksum != staged.archive_member.member_checksum
            ):
                raise RegistrationSourceResolutionError("archive member is not bound to the verified upload bytes")
        if expected_source_checksum is not None and expected_source_checksum != observed_source_checksum:
            raise RegistrationSourceResolutionError("request source checksum differs from the selected staged bytes")

        declarations = snapshot.declarations
        if declarations.cloud_state is None or declarations.cloud_state.value != expected_cloud_state:
            raise RegistrationSourceResolutionError("assembly cloud-state declaration does not match registration mode")
        declared_unit = declarations.coordinate_unit.value if declarations.coordinate_unit is not None else None
        declared_frame = declarations.lidar_frame_id.value if declarations.lidar_frame_id is not None else None
        declared_same_scene = declarations.same_scene.value if declarations.same_scene is not None else None
        if distance_unit is not None and declared_unit != distance_unit:
            raise RegistrationSourceResolutionError("request distance unit differs from the assembly declaration")
        if source_frame is not None and declared_frame != source_frame:
            raise RegistrationSourceResolutionError("request source frame differs from the assembly declaration")
        if same_scene_attestation is not None and declared_same_scene != same_scene_attestation:
            raise RegistrationSourceResolutionError("same-scene attestation differs from the immutable assembly")

        if staged.observed_format not in {InputAssetFormat.POINT_CLOUD_PCD, InputAssetFormat.POINT_CLOUD_PLY}:
            raise RegistrationSourceResolutionError("source format must be an observed PCD or PLY point cloud")
        self.assemblies.verify_upload_sources(stored, upload_ids={staged.upload_id})
        container_path = self.resolver.require_uri(staged.source_file.artifact_uri, staged.source_file.checksum)
        workspace.mkdir(parents=True, exist_ok=True)
        cloud_path = (
            self._extract_member(container_path, staged.archive_member, workspace, staged.observed_format)
            if staged.archive_member is not None
            else container_path
        )
        try:
            header = self._read_header(cloud_path)
        except RegistrationSourceResolutionError:
            self._remove_extracted_member(cloud_path, container_path)
            raise
        header_checksum = _sha256(header[1])
        parsed_header = header[0]
        expected_geometry_format = "pcd" if staged.observed_format == InputAssetFormat.POINT_CLOUD_PCD else "ply"
        if parsed_header.geometry_format != expected_geometry_format:
            self._remove_extracted_member(cloud_path, container_path)
            raise RegistrationSourceResolutionError("parsed point-cloud header format differs from the request")
        if expected_point_count is not None and parsed_header.point_count != expected_point_count:
            self._remove_extracted_member(cloud_path, container_path)
            raise RegistrationSourceResolutionError("parsed point count differs from the request")
        if parsed_header.point_count > max_source_points:
            self._remove_extracted_member(cloud_path, container_path)
            raise RegistrationSourceResolutionError("source point count exceeds the registration profile limit")
        if expected_header_checksum is not None and header_checksum != expected_header_checksum:
            self._remove_extracted_member(cloud_path, container_path)
            raise RegistrationSourceResolutionError("parsed point-cloud header checksum differs from the request")
        if expected_source_checksum is not None and observed_source_checksum != expected_source_checksum:
            self._remove_extracted_member(cloud_path, container_path)
            raise RegistrationSourceResolutionError("request source checksum differs from the selected staged bytes")

        return InspectedRegistrationSource(
            path=cloud_path,
            file_id=staged.file_id,
            input_assembly_id=snapshot.assembly_id,
            input_assembly_revision=snapshot.revision,
            input_assembly_checksum=snapshot.assembly_checksum,
            source_checksum=observed_source_checksum,
            header_checksum=header_checksum,
            point_count=parsed_header.point_count,
            input_format=staged.observed_format,
            geometry_format=parsed_header.geometry_format,
            distance_unit=declared_unit,
            source_frame=declared_frame,
            same_scene_attestation=declared_same_scene,
            stored=stored,
        )

    def _same_scene_lineage_verified(self, request: RegistrationRequest, stored: StoredInputAssembly) -> bool:
        """Verify the attestation is attached to the accepted RGB+LiDAR job recipe.

        This establishes job/input lineage only; it cannot prove that the uploaded
        RGB and LiDAR data depict the same physical place.
        """
        if request.source.same_scene_attestation is not True:
            return False
        declaration = stored.snapshot.declarations.same_scene
        if declaration is None or declaration.value is not True:
            return False
        run = self.projects.input_run_for_job(request.target_job_id)
        if run is None:
            return False
        if run.project_id != request.target_project_id:
            raise RegistrationSourceResolutionError("target project differs from the accepted job lineage")
        if (
            run.assembly_id != stored.snapshot.assembly_id
            or run.assembly_revision != stored.snapshot.revision
            or run.assembly_checksum != stored.snapshot.assembly_checksum
        ):
            return False

        project = self.projects.get_project(run.project_id)
        if project.input_recipe_ref != run.recipe_ref:
            raise ArtifactChecksumError("accepted job recipe reference differs from the durable input run")
        recipe = self.resolver.load_model(run.recipe_ref, InputRecipe)
        try:
            verify_input_recipe_checksum(recipe)
        except ValueError as error:
            raise ArtifactChecksumError("accepted job recipe checksum is invalid") from error
        if (
            recipe.assembly_id != run.assembly_id
            or recipe.assembly_revision != run.assembly_revision
            or recipe.assembly_checksum != run.assembly_checksum
            or recipe.resolution_checksum != run.resolution_checksum
            or recipe.candidate_id != run.candidate_id
            or recipe.recipe_checksum != run.recipe_checksum
        ):
            raise ArtifactChecksumError("accepted job recipe differs from the durable input run")
        source_role = request.source.source_role
        source_file_ids = set(request.source.source_file_ids)
        source_is_in_recipe = any(
            binding.role == source_role and set(binding.file_ids) == source_file_ids for binding in recipe.bindings
        )
        rgb_video_is_in_recipe = any(
            binding.role == InputRole.RGB_VIDEO and binding.file_ids for binding in recipe.bindings
        )
        return source_is_in_recipe and rgb_video_is_in_recipe

    @staticmethod
    def _read_header(path: Path) -> tuple[CloudHeader, bytes]:
        try:
            with path.open("rb") as stream:
                header = read_header(stream)
                header_size = stream.tell()
                stream.seek(0)
                raw_header = stream.read(header_size)
        except (OSError, ValueError) as error:
            raise RegistrationSourceResolutionError("selected source has an invalid PCD/PLY header") from error
        if not raw_header or header_size > 128 * 1024:
            raise RegistrationSourceResolutionError("selected source header is empty or exceeds its byte limit")
        return header, raw_header

    @staticmethod
    def _extract_member(
        container_path: Path, member: ArchiveMemberRef, workspace: Path, source_format: InputAssetFormat
    ) -> Path:
        """Materialize one staged archive member without trusting its uploaded path as a destination."""
        member_path = member.member_path
        destination = workspace / f"registration-source-{uuid4().hex}.{_extension(source_format)}"
        try:
            with zipfile.ZipFile(container_path) as archive:
                matches = [info for info in archive.infolist() if info.filename == member_path]
                if len(matches) != 1:
                    raise RegistrationSourceResolutionError("archive member is missing or has a duplicate path")
                info = matches[0]
                if (
                    info.is_dir()
                    or info.file_size != member.uncompressed_size_bytes
                    or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
                    or info.flag_bits & 0x1
                ):
                    raise RegistrationSourceResolutionError(
                        "archive member size or type differs from the staged record"
                    )
                digest = hashlib.sha256()
                total = 0
                with archive.open(info) as source, destination.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > member.uncompressed_size_bytes:
                            raise RegistrationSourceResolutionError("archive member exceeds its staged size")
                        digest.update(chunk)
                        output.write(chunk)
                checksum = "sha256:" + digest.hexdigest()
                if total != member.uncompressed_size_bytes or checksum != member.member_checksum:
                    raise RegistrationSourceResolutionError("archive member bytes differ from their staged checksum")
        except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error) as error:
            destination.unlink(missing_ok=True)
            raise RegistrationSourceResolutionError("could not safely read the selected archive member") from error
        except RegistrationSourceResolutionError:
            destination.unlink(missing_ok=True)
            raise
        return destination

    @staticmethod
    def _remove_extracted_member(path: Path, container_path: Path) -> None:
        if path != container_path:
            path.unlink(missing_ok=True)


def _extension(source_format: InputAssetFormat) -> str:
    return "pcd" if source_format == InputAssetFormat.POINT_CLOUD_PCD else "ply"


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
