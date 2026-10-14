"""Isolated host-side process boundary for one exact Isaac validation attempt."""

import json
import stat
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, Identifier, ProductArtifactRef
from src.models.contracts.identity import verify_candidate_inventory, verify_content_checksum
from src.models.contracts.manifests import RuntimeManifest
from src.models.contracts.validation import CandidateManifest, CandidatePackage, ObservedPathResult, RuleResult
from src.models.contracts.validation_run import (
    IsaacValidationRuntimeProfile,
    ValidationConfig,
    ValidationRunOrigin,
    ValidationRunRecord,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError, sha256_file
from src.services.process_control import ProcessCancelledError, ProcessTimeoutError, run_cancellable_process

_MAX_RESULT_BYTES = 16 * 1024 * 1024
_MAX_PACKAGE_ARCHIVE_BYTES = 8 * 1024**3
_MAX_PACKAGE_UNCOMPRESSED_BYTES = 16 * 1024**3
_MAX_PACKAGE_ENTRIES = 100_000


class IsaacValidationProcessError(ValueError):
    """A validation subprocess failed before producing trustworthy observations."""

    def __init__(self, error_code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class IsaacValidationRequest(BaseModel):
    """Exact persisted candidate, package, policy and runtime inputs for one attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ValidationRunRecord
    candidate: CandidatePackage
    candidate_package_ref: ProductArtifactRef
    config: ValidationConfig
    profile: IsaacValidationRuntimeProfile


class IsaacCheckObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: Identifier
    result: RuleResult
    message: str | None = None


class IsaacPathObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: Identifier
    result: ObservedPathResult
    message: str | None = None
    sample_count: int = Field(ge=0)
    collision_prim_paths: list[str] = Field(default_factory=list)


class IsaacExecutionObservations(BaseModel):
    """Unpublished runtime output; S3 serializes this into trusted report artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    run_id: Identifier
    candidate_checksum: Checksum
    config_checksum: Checksum
    profile_checksum: Checksum
    runtime_identity: Identifier
    runtime_versions: dict[Identifier, str]
    checks: list[IsaacCheckObservation] = Field(min_length=1)
    path_results: list[IsaacPathObservation]
    #: None means the runtime did not expose a trustworthy penetration-depth measurement.
    max_penetration_m: FiniteFloat | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _unique_observations(self) -> "IsaacExecutionObservations":
        check_ids = [item.check_id for item in self.checks]
        pair_ids = [item.pair_id for item in self.path_results]
        if len(check_ids) != len(set(check_ids)) or len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Isaac execution observation IDs must be unique")
        return self


class IsaacValidationProcess:
    """Run the bundled headless evaluator through a deployment-owned Isaac launcher."""

    def __init__(self, command: Sequence[str] | None, *, runner_script: Path | None = None) -> None:
        if command is not None and (not command or any(not argument for argument in command)):
            raise ValueError("Isaac runtime command must be a non-empty argv prefix")
        self.command = tuple(command) if command is not None else None
        self.runner_script = (
            runner_script or Path(__file__).resolve().parents[4] / "scripts/isaac/validate_candidate.py"
        )

    def run(
        self,
        request: IsaacValidationRequest,
        resolver: ArtifactResolver,
        workspace: Path,
        *,
        cancel_event: Event | None = None,
    ) -> IsaacExecutionObservations:
        """Verify all bound inputs, run in a private process group and validate output identity."""
        if self.command is None:
            raise IsaacValidationProcessError(
                "ISAAC_RUNTIME_NOT_CONFIGURED", "Isaac Sim validation runtime is not configured"
            )
        self._verify_inputs(request, resolver)
        if not self.runner_script.is_file():
            raise IsaacValidationProcessError(
                "ISAAC_RUNNER_MISSING", "The bundled Isaac validation entrypoint is missing"
            )

        attempt = workspace.expanduser().resolve()
        attempt.mkdir(parents=True, exist_ok=True)
        request_path = attempt / "isaac_request.json"
        result_path = attempt / "isaac_observations.json"
        log_path = attempt / "isaac_execution.log"
        try:
            candidate_usd_path = self._materialize_candidate_package(request, resolver, attempt / "candidate_package")
        except (ArtifactStoreError, OSError, ValueError, zipfile.BadZipFile) as error:
            raise IsaacValidationProcessError(
                "ISAAC_CANDIDATE_PACKAGE_INVALID", "The exact simulation-package archive could not be verified"
            ) from error
        payload = self._child_payload(request, resolver, candidate_usd_path)
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > _MAX_RESULT_BYTES:
            raise IsaacValidationProcessError("ISAAC_REQUEST_TOO_LARGE", "Isaac Sim request exceeded the size limit")
        try:
            with request_path.open("x", encoding="utf-8") as stream:
                stream.write(payload_bytes.decode("utf-8"))
                stream.write("\n")
            command = (
                *self.command,
                str(self.runner_script.resolve()),
                "--request",
                str(request_path),
                "--output",
                str(result_path),
            )
            with log_path.open("x", encoding="utf-8") as log:
                return_code = run_cancellable_process(
                    command,
                    cwd=attempt,
                    timeout_seconds=request.profile.timeout_seconds,
                    output=log,
                    cancel_event=cancel_event,
                )
        except ProcessCancelledError:
            raise
        except ProcessTimeoutError as error:
            raise IsaacValidationProcessError(
                "ISAAC_RUNTIME_TIMEOUT", "Isaac Sim exceeded the bound runtime timeout", retryable=True
            ) from error
        except OSError as error:
            raise IsaacValidationProcessError(
                "ISAAC_RUNTIME_LAUNCH_FAILED", "Isaac Sim could not be launched", retryable=True
            ) from error

        if return_code != 0:
            raise IsaacValidationProcessError(
                "ISAAC_RUNTIME_FAILED", "Isaac Sim exited without a successful observation result", retryable=True
            )
        if result_path.is_symlink() or not result_path.is_file():
            raise IsaacValidationProcessError("ISAAC_RESULT_MISSING", "Isaac Sim did not publish its result file")
        if result_path.stat().st_size > _MAX_RESULT_BYTES:
            raise IsaacValidationProcessError("ISAAC_RESULT_TOO_LARGE", "Isaac Sim result exceeded the size limit")
        try:
            observations = IsaacExecutionObservations.model_validate_json(result_path.read_bytes())
        except ValueError as error:
            raise IsaacValidationProcessError(
                "ISAAC_RESULT_INVALID", "Isaac Sim returned an invalid result contract"
            ) from error
        self._verify_observations(request, observations)
        return observations

    @staticmethod
    def _verify_inputs(request: IsaacValidationRequest, resolver: ArtifactResolver) -> None:
        run, candidate, config, profile = request.run, request.candidate, request.config, request.profile
        if run.origin != ValidationRunOrigin.WORKER or run.status != ValidationRunStatus.RUNNING:
            raise IsaacValidationProcessError("ISAAC_RUN_NOT_RUNNING", "Only a leased worker run may invoke Isaac Sim")
        if run.candidate_checksum != candidate.candidate_checksum:
            raise IsaacValidationProcessError(
                "ISAAC_CANDIDATE_MISMATCH", "Validation run and candidate checksums differ"
            )
        if run.validation_config_checksum != config.config_checksum:
            raise IsaacValidationProcessError("ISAAC_CONFIG_MISMATCH", "Validation run and policy checksums differ")
        try:
            verify_candidate_inventory(candidate)
            verify_content_checksum(candidate, "candidate_checksum")
            verify_content_checksum(config, "config_checksum")
            verify_content_checksum(profile, "profile_checksum")
            stored_config = ValidationConfig.model_validate_json(
                resolver.require(run.validation_config_ref).read_bytes()
            )
            verify_content_checksum(stored_config, "config_checksum")
            if stored_config != config:
                raise ValueError("validation config differs from the immutable run input")
            profile_ref = config.runtime_profile_ref
            if profile_ref is None:
                raise ValueError("validation config has no qualified runtime profile")
            stored_profile = IsaacValidationRuntimeProfile.model_validate_json(
                resolver.require(profile_ref).read_bytes()
            )
            verify_content_checksum(stored_profile, "profile_checksum")
            if stored_profile != profile:
                raise ValueError("runtime profile differs from the immutable config input")
            if (
                request.candidate_package_ref.artifact_type != "SimulationPackageArchive"
                or request.candidate_package_ref.job_id != run.job_id
                or candidate.entrypoint_usd.job_id != run.job_id
            ):
                raise ValueError("candidate package archive and entrypoint must be bound to this job")
            resolver.require(request.candidate_package_ref)
            runtime = RuntimeManifest.model_validate_json(resolver.require(profile.runtime_manifest_ref).read_bytes())
            verify_content_checksum(runtime, "runtime_manifest_checksum")
            component = runtime.components.get("isaac_sim")
            if (
                component is None
                or component.status.value != "VERIFIED"
                or component.version != profile.runtime_identity
            ):
                raise ValueError("runtime profile is not bound to a verified Isaac runtime manifest")
            for reference in (
                candidate.entrypoint_usd,
                *candidate.assets,
                *candidate.geometry,
                *candidate.colliders,
            ):
                resolver.require(reference)
            if candidate.candidate_manifest.object_aware_collision_ref is not None:
                resolver.require(candidate.candidate_manifest.object_aware_collision_ref)
            robot_path = resolver.require(profile.robot_asset_ref)
            if not robot_path.is_file():
                raise ValueError("configured robot asset is missing")
        except (ArtifactStoreError, OSError, ValueError) as error:
            raise IsaacValidationProcessError(
                "ISAAC_INPUT_INVALID", "A bound validation input failed verification"
            ) from error

    @staticmethod
    def _materialize_candidate_package(
        request: IsaacValidationRequest,
        resolver: ArtifactResolver,
        package_root: Path,
    ) -> Path:
        archive_path = resolver.require(request.candidate_package_ref)
        if archive_path.stat().st_size > _MAX_PACKAGE_ARCHIVE_BYTES:
            raise ValueError("simulation package archive exceeds the configured compressed-size limit")
        package_root.mkdir(mode=0o700)
        total_size = 0
        try:
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if len(entries) > _MAX_PACKAGE_ENTRIES:
                    raise ValueError("simulation package archive has too many members")
                names: set[str] = set()
                for info in entries:
                    name = info.filename
                    member = PurePosixPath(name)
                    mode = info.external_attr >> 16
                    if (
                        not name
                        or "\\" in name
                        or member.is_absolute()
                        or any(part in {"", ".", ".."} for part in member.parts)
                        or member.as_posix() != name.rstrip("/")
                        or stat.S_ISLNK(mode)
                    ):
                        raise ValueError("simulation package archive contains an unsafe member path or symlink")
                    if not info.is_dir() and stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                        raise ValueError("simulation package archive contains a non-regular file")
                    normalized = member.as_posix()
                    if normalized in names:
                        raise ValueError("simulation package archive contains duplicate members")
                    names.add(normalized)
                    total_size += info.file_size
                    if total_size > _MAX_PACKAGE_UNCOMPRESSED_BYTES:
                        raise ValueError("simulation package archive exceeds the configured expanded-size limit")
                    if info.is_dir():
                        (package_root / Path(*member.parts)).mkdir(parents=True, exist_ok=True)
                        continue
                    destination = package_root / Path(*member.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination.open("xb") as target:
                        copied = 0
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                            copied += len(chunk)
                        if copied != info.file_size:
                            raise ValueError("simulation package member size differs from the archive inventory")
        except zipfile.BadZipFile:
            raise

        package_path = package_root / "candidate_package.json"
        manifest_path = package_root / "candidate_manifest.json"
        candidate_usd_path = package_root / "scene.usda"
        if any(path.is_symlink() or not path.is_file() for path in (package_path, manifest_path, candidate_usd_path)):
            raise ValueError("simulation package archive is missing a required candidate member")
        stored_candidate = CandidatePackage.model_validate_json(package_path.read_bytes())
        verify_candidate_inventory(stored_candidate)
        verify_content_checksum(stored_candidate, "candidate_checksum")
        if stored_candidate != request.candidate:
            raise ValueError("simulation package archive does not contain the exact queued candidate")
        stored_manifest = CandidateManifest.model_validate_json(manifest_path.read_bytes())
        if stored_manifest != request.candidate.candidate_manifest:
            raise ValueError("simulation package archive candidate manifest differs from its candidate")
        if sha256_file(candidate_usd_path) != request.candidate.entrypoint_usd.artifact_checksum:
            raise ValueError("packaged USD entrypoint bytes differ from the candidate inventory")
        environment_collision = package_root / "environment_collision.usda"
        if (
            environment_collision.is_symlink()
            or not environment_collision.is_file()
            or sha256_file(environment_collision)
            not in {reference.artifact_checksum for reference in request.candidate.colliders}
        ):
            raise ValueError("packaged environment collider bytes differ from the candidate inventory")

        expected_layers: set[str] = set()
        for reference in request.candidate.assets:
            if reference.artifact_type == "OpenUSDLayer":
                marker = "/hybrid/"
                if marker not in reference.artifact_uri:
                    raise ValueError("candidate OpenUSD layer has no package-relative artifact URI")
                relative = PurePosixPath(reference.artifact_uri.split(marker, maxsplit=1)[1])
                if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                    raise ValueError("candidate OpenUSD layer URI is not package-relative")
                layer_path = package_root.joinpath(*relative.parts)
                if (
                    layer_path.is_symlink()
                    or not layer_path.is_file()
                    or sha256_file(layer_path) != reference.artifact_checksum
                ):
                    raise ValueError("packaged OpenUSD layer bytes differ from the candidate inventory")
                expected_layers.add(relative.as_posix())

        for dependency in package_root.rglob("*"):
            if not dependency.is_file():
                continue
            relative = dependency.relative_to(package_root).as_posix()
            if dependency.suffix.lower() in {".usd", ".usda", ".usdc"} and relative not in {
                "scene.usda",
                "environment_collision.usda",
                *expected_layers,
            }:
                raise ValueError("simulation package contains an unbound USD dependency")
            if relative.startswith("assets/") and sha256_file(dependency) not in {
                reference.artifact_checksum for reference in request.candidate.assets
            }:
                raise ValueError("packaged external USD asset bytes are absent from the candidate inventory")
        return candidate_usd_path

    @staticmethod
    def _child_payload(
        request: IsaacValidationRequest,
        resolver: ArtifactResolver,
        candidate_usd_path: Path,
    ) -> dict[str, object]:
        run, candidate, config, profile = request.run, request.candidate, request.config, request.profile
        return {
            "schema_version": "1.0",
            "run_id": run.run_id,
            "candidate_checksum": candidate.candidate_checksum,
            "config_checksum": config.config_checksum,
            "profile_checksum": profile.profile_checksum,
            "runtime_identity": profile.runtime_identity,
            "candidate_usd_path": str(candidate_usd_path.resolve()),
            "robot_asset_path": str(resolver.require(profile.robot_asset_ref)),
            "required_check_ids": config.required_check_ids,
            "warning_check_ids": config.warning_check_ids,
            "path_pairs": [item.model_dump(mode="json") for item in config.path_pairs],
            "robot_footprint_m": list(profile.robot_footprint_m),
            "spawn_position_xyz_m": list(profile.spawn_position_xyz_m),
            "spawn_orientation_xyzw": list(profile.spawn_orientation_xyzw),
            "units": profile.units,
            "up_axis": profile.up_axis,
            "physics_timestep_seconds": profile.physics_timestep_seconds,
            "collision_tolerance_m": profile.collision_tolerance_m,
            "penetration_limit_m": profile.penetration_limit_m,
        }

    @staticmethod
    def _verify_observations(request: IsaacValidationRequest, result: IsaacExecutionObservations) -> None:
        run, candidate, config, profile = request.run, request.candidate, request.config, request.profile
        if (
            result.run_id != run.run_id
            or result.candidate_checksum != candidate.candidate_checksum
            or result.config_checksum != config.config_checksum
            or result.profile_checksum != profile.profile_checksum
            or result.runtime_identity != profile.runtime_identity
            or result.runtime_versions.get("isaac_sim") != profile.runtime_identity
        ):
            raise IsaacValidationProcessError("ISAAC_RESULT_IDENTITY_MISMATCH", "Isaac result is not bound to this run")
        expected_checks = set(config.required_check_ids) | set(config.warning_check_ids)
        expected_pairs = {pair.pair_id for pair in config.path_pairs}
        if {item.check_id for item in result.checks} != expected_checks:
            raise IsaacValidationProcessError(
                "ISAAC_RESULT_CHECK_SET_MISMATCH", "Isaac result check IDs differ from policy"
            )
        if {item.pair_id for item in result.path_results} != expected_pairs:
            raise IsaacValidationProcessError(
                "ISAAC_RESULT_PATH_SET_MISMATCH", "Isaac result path IDs differ from policy"
            )
