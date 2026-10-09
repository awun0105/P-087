"""Durable input assembly snapshots and deterministic resolution reports."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.input_assembly import (
    InputAssemblyDeclarations,
    InputAssemblySnapshot,
    InputBinding,
    InputResolutionReport,
    InputWorkflowIntent,
    RuntimeCapabilityKey,
    RuntimeQualificationRegistry,
    RuntimeQualificationStatus,
    StagedInputFile,
    seal_input_assembly,
    seal_runtime_registry,
    verify_input_assembly_checksum,
    verify_input_resolution_checksum,
    verify_runtime_registry_checksum,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.assembly_models import StagedInputUploadRecord
from src.services.reconstruction.inputs.input_probe import InputProbe
from src.services.reconstruction.inputs.input_resolver import resolve_input_assembly


class InputAssemblyNotFoundError(LookupError):
    """Requested input assembly, revision, upload, or resolution does not exist."""


class InputAssemblyConflictError(RuntimeError):
    """The assembly head or immutable resolution changed during a command."""


class InputAssemblyRuntimeConfigError(ValueError):
    """The deployment's optional input runtime qualification registry is invalid."""


class StoredInputAssembly(BaseModel):
    """Immutable assembly snapshot with the byte-bound probes used by its resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: InputAssemblySnapshot
    probes: tuple[InputProbe, ...] = Field(min_length=1)


class InputResolutionRecord(BaseModel):
    """Immutable resolver result and the exact runtime registry used to create it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report: InputResolutionReport
    runtime_registry: RuntimeQualificationRegistry


class InputAssemblyService:
    """Database-backed assembly/revision store shared by Studio API processes."""

    _IMPLEMENTED_ADAPTERS = frozenset(
        {
            RuntimeCapabilityKey.R1,
            RuntimeCapabilityKey.R2,
            RuntimeCapabilityKey.R3,
            RuntimeCapabilityKey.R4,
            RuntimeCapabilityKey.R5,
            RuntimeCapabilityKey.R6,
            RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW,
            RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW,
        }
    )

    def __init__(
        self,
        database: RuntimeDatabase,
        runtime_registry_path: str | None = None,
        resolver: ArtifactResolver | None = None,
    ) -> None:
        self.database = database
        self.runtime_registry_path = runtime_registry_path
        self.resolver = resolver

    def save_upload(self, record: StagedInputUploadRecord) -> None:
        """Persist a finished, checksummed assembly upload after server-side probing."""
        with self.database.transaction(write=True) as tx:
            existing = tx.execute(
                "SELECT payload FROM r2s_input_uploads WHERE upload_id=?", (record.upload_id,)
            ).fetchone()
            if existing is not None:
                if StagedInputUploadRecord.model_validate_json(existing[0]) != record:
                    raise RuntimeStateConflictError("Upload ID đã được dùng cho nội dung assembly khác")
                return
            tx.execute(
                "INSERT INTO r2s_input_uploads(upload_id,payload) VALUES (?,?)",
                (record.upload_id, record.model_dump_json()),
            )

    def get_upload(self, upload_id: str) -> StagedInputUploadRecord:
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_input_uploads WHERE upload_id=?", (upload_id,)).fetchone()
        if row is None:
            raise InputAssemblyNotFoundError(f"input upload not found: {upload_id}")
        return StagedInputUploadRecord.model_validate_json(row[0])

    def get_uploads(self, upload_ids: list[str] | tuple[str, ...]) -> list[StagedInputUploadRecord]:
        if not upload_ids or len(upload_ids) != len(set(upload_ids)):
            raise ValueError("assembly upload IDs must be non-empty and unique")
        records = [self.get_upload(upload_id) for upload_id in upload_ids]
        return records

    def verify_upload_sources(
        self,
        stored: StoredInputAssembly,
        *,
        upload_ids: set[str] | None = None,
    ) -> None:
        """Re-read staged records and verify the immutable source bytes before a consumer accepts them."""
        if self.resolver is None:
            raise InputAssemblyRuntimeConfigError("Artifact resolver is required to verify staged input bytes")
        selected_ids = upload_ids if upload_ids is not None else {item.upload_id for item in stored.snapshot.files}
        expected_files: dict[str, list[StagedInputFile]] = {}
        for item in stored.snapshot.files:
            if item.upload_id in selected_ids:
                expected_files.setdefault(item.upload_id, []).append(item)
        expected_probes: dict[str, list[InputProbe]] = {}
        for probe in stored.probes:
            staged = next(item for item in stored.snapshot.files if item.file_id == probe.file_id)
            if staged.upload_id in selected_ids:
                expected_probes.setdefault(staged.upload_id, []).append(probe)
        for upload_id in sorted(selected_ids):
            record = self.get_upload(upload_id)
            files = sorted(expected_files.get(upload_id, []), key=lambda item: item.file_id)
            probes = sorted(expected_probes.get(upload_id, []), key=lambda item: item.file_id)
            if (
                not files
                or record.source_file != files[0].source_file
                or sorted(record.staged_files, key=lambda item: item.file_id) != files
                or sorted(record.probes, key=lambda item: item.file_id) != probes
            ):
                raise InputAssemblyConflictError("staged upload record differs from the immutable assembly revision")
            self.resolver.require_uri(record.source_file.artifact_uri, record.source_file.checksum)

    def create(
        self,
        owner_id: str,
        upload_ids: list[str],
        declarations: InputAssemblyDeclarations,
        bindings: list[InputBinding],
        requested_intent: InputWorkflowIntent | None,
    ) -> StoredInputAssembly:
        """Create revision one from ready upload records; caller must authorize every ref."""
        return self._write_snapshot(
            assembly_id=f"assembly-{uuid4().hex[:16]}",
            expected_revision=None,
            next_revision=1,
            owner_id=owner_id,
            upload_ids=upload_ids,
            declarations=declarations,
            bindings=bindings,
            requested_intent=requested_intent,
        )

    def revise(
        self,
        assembly_id: str,
        owner_id: str,
        expected_revision: int,
        upload_ids: list[str],
        declarations: InputAssemblyDeclarations,
        bindings: list[InputBinding],
        requested_intent: InputWorkflowIntent | None,
    ) -> StoredInputAssembly:
        """Create a new immutable revision only when the expected head still matches."""
        if expected_revision < 1:
            raise ValueError("expected revision must be positive")
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT owner_id,revision FROM r2s_input_assembly_heads WHERE assembly_id=?",
                (assembly_id,),
            ).fetchone()
        if row is None or row[0] != owner_id:
            raise InputAssemblyNotFoundError(f"input assembly not found: {assembly_id}")
        if int(row[1]) != expected_revision:
            raise InputAssemblyConflictError("assembly revision changed; read the current head before editing")
        return self._write_snapshot(
            assembly_id=assembly_id,
            expected_revision=expected_revision,
            next_revision=expected_revision + 1,
            owner_id=owner_id,
            upload_ids=upload_ids,
            declarations=declarations,
            bindings=bindings,
            requested_intent=requested_intent,
        )

    def _write_snapshot(
        self,
        *,
        assembly_id: str,
        expected_revision: int | None,
        next_revision: int,
        owner_id: str,
        upload_ids: list[str],
        declarations: InputAssemblyDeclarations,
        bindings: list[InputBinding],
        requested_intent: InputWorkflowIntent | None,
    ) -> StoredInputAssembly:
        uploads = self.get_uploads(upload_ids)
        staged_files = sorted(
            (item for upload in uploads for item in upload.staged_files), key=lambda item: item.file_id
        )
        probes = tuple(sorted((item for upload in uploads for item in upload.probes), key=lambda item: item.file_id))
        video_preparation = self._video_preparation_for(uploads)
        now = datetime.now(UTC)
        snapshot = seal_input_assembly(
            {
                "schema_version": "1.0",
                "assembly_id": assembly_id,
                "revision": next_revision,
                "owner_id": owner_id,
                "created_at": now,
                "requested_intent": requested_intent,
                "files": staged_files,
                "bindings": bindings,
                "declarations": declarations,
                "video_preparation_verification": video_preparation,
                "assembly_checksum": "sha256:" + "0" * 64,
            }
        )
        stored = StoredInputAssembly(snapshot=snapshot, probes=probes)
        self._validate_probes(stored)
        self._persist_snapshot(stored, expected_revision)
        return stored

    def _video_preparation_for(self, uploads: list[StagedInputUploadRecord]) -> object | None:
        """Carry a verified RGB frame map only when its legacy upload record still matches."""
        video_uploads = {
            item.upload_id
            for upload in uploads
            for item in upload.staged_files
            if item.observed_format.value in {"video_mp4", "video_mov"}
        }
        if len(video_uploads) != 1:
            return None
        upload_id = next(iter(video_uploads))
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_uploads WHERE upload_id=?", (upload_id,)).fetchone()
        if row is None:
            return None
        from src.services.orchestration.uploads.models import UploadRecord

        legacy = UploadRecord.model_validate_json(row[0])
        staged = next(item for item in uploads if item.upload_id == upload_id)
        if legacy.checksum != staged.source_file.checksum or legacy.size_bytes != staged.source_file.size_bytes:
            raise InputAssemblyConflictError("video upload differs from its staged input bytes")
        return legacy.video_preparation

    @staticmethod
    def _validate_probes(stored: StoredInputAssembly) -> None:
        verify_input_assembly_checksum(stored.snapshot)
        by_id = {item.file_id: item for item in stored.probes}
        if len(by_id) != len(stored.probes):
            raise ValueError("assembly probes must have unique file IDs")
        if set(by_id) != {item.file_id for item in stored.snapshot.files}:
            raise ValueError("assembly probes must cover every staged file exactly once")
        for staged in stored.snapshot.files:
            probe = by_id[staged.file_id]
            if probe.source_checksum != staged.source_file.checksum:
                raise ValueError("assembly probe checksum differs from the staged source")
            if probe.observed_format != staged.observed_format:
                raise ValueError("assembly probe format differs from its staged file")

    def _persist_snapshot(self, stored: StoredInputAssembly, expected_revision: int | None) -> None:
        snapshot = stored.snapshot
        payload = stored.model_dump_json()
        with self.database.transaction(write=True) as tx:
            head = tx.execute(
                "SELECT owner_id,revision FROM r2s_input_assembly_heads WHERE assembly_id=?" + tx.lock_suffix(),
                (snapshot.assembly_id,),
            ).fetchone()
            if expected_revision is None:
                if head is not None:
                    raise InputAssemblyConflictError("assembly ID already exists")
                tx.execute(
                    "INSERT INTO r2s_input_assemblies(assembly_id,revision,owner_id,payload) VALUES (?,?,?,?)",
                    (snapshot.assembly_id, snapshot.revision, snapshot.owner_id, payload),
                )
                tx.execute(
                    "INSERT INTO r2s_input_assembly_heads(assembly_id,owner_id,revision) VALUES (?,?,?)",
                    (snapshot.assembly_id, snapshot.owner_id, snapshot.revision),
                )
            else:
                if head is None or head[0] != snapshot.owner_id or int(head[1]) != expected_revision:
                    raise InputAssemblyConflictError("assembly revision changed before commit")
                tx.execute(
                    "INSERT INTO r2s_input_assemblies(assembly_id,revision,owner_id,payload) VALUES (?,?,?,?)",
                    (snapshot.assembly_id, snapshot.revision, snapshot.owner_id, payload),
                )
                changed = tx.execute(
                    "UPDATE r2s_input_assembly_heads SET revision=? WHERE assembly_id=? AND owner_id=? AND revision=?",
                    (snapshot.revision, snapshot.assembly_id, snapshot.owner_id, expected_revision),
                ).rowcount
                if changed != 1:
                    raise InputAssemblyConflictError("assembly revision changed before commit")

    def get_assembly(self, assembly_id: str, revision: int | None = None) -> StoredInputAssembly:
        with self.database.transaction() as tx:
            if revision is None:
                head = tx.execute(
                    "SELECT revision FROM r2s_input_assembly_heads WHERE assembly_id=?", (assembly_id,)
                ).fetchone()
                if head is None:
                    raise InputAssemblyNotFoundError(f"input assembly not found: {assembly_id}")
                revision = int(head[0])
            row = tx.execute(
                "SELECT payload FROM r2s_input_assemblies WHERE assembly_id=? AND revision=?",
                (assembly_id, revision),
            ).fetchone()
        if row is None:
            raise InputAssemblyNotFoundError(f"input assembly revision not found: {assembly_id}@{revision}")
        stored = StoredInputAssembly.model_validate_json(row[0])
        self._validate_probes(stored)
        return stored

    def get_assembly_owner(self, assembly_id: str) -> str:
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT owner_id FROM r2s_input_assembly_heads WHERE assembly_id=?", (assembly_id,)
            ).fetchone()
        if row is None:
            raise InputAssemblyNotFoundError(f"input assembly not found: {assembly_id}")
        return str(row[0])

    def runtime_registry(self) -> RuntimeQualificationRegistry:
        """Load only an explicit, checksummed deployment registry; absent config stays unavailable."""
        if self.runtime_registry_path is None:
            return seal_runtime_registry(
                {
                    "schema_version": "1.0",
                    "registry_version": "unconfigured",
                    "capabilities": [],
                    "registry_checksum": "sha256:" + "0" * 64,
                }
            )
        from pathlib import Path

        try:
            registry = RuntimeQualificationRegistry.model_validate_json(
                Path(self.runtime_registry_path).read_text(encoding="utf-8")
            )
            verify_runtime_registry_checksum(registry)
        except (OSError, ValueError) as error:
            raise InputAssemblyRuntimeConfigError(
                "PRODUCT_INPUT_RUNTIME_REGISTRY is unreadable or has an invalid checksum"
            ) from error
        capabilities = [
            item
            if item.status != RuntimeQualificationStatus.QUALIFIED or item.capability_key in self._IMPLEMENTED_ADAPTERS
            else item.model_copy(
                update={
                    "status": RuntimeQualificationStatus.INCOMPATIBLE,
                    "reason_codes": sorted(set([*item.reason_codes, "consumer_adapter_unavailable"])),
                }
            )
            for item in registry.capabilities
        ]
        return seal_runtime_registry(
            {
                **registry.model_dump(mode="json"),
                "capabilities": capabilities,
                "registry_checksum": "sha256:" + "0" * 64,
            }
        )

    def resolve(self, assembly_id: str, revision: int | None = None) -> InputResolutionRecord:
        stored = self.get_assembly(assembly_id, revision)
        registry = self.runtime_registry()
        report = resolve_input_assembly(stored.snapshot, registry, stored.probes)
        verify_input_resolution_checksum(report)
        record = InputResolutionRecord(report=report, runtime_registry=registry)
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_input_resolutions(report_checksum,assembly_id,revision,owner_id,payload) "
                "VALUES (?,?,?,?,?) ON CONFLICT(report_checksum) DO NOTHING",
                (
                    report.report_checksum,
                    report.assembly_id,
                    report.assembly_revision,
                    stored.snapshot.owner_id,
                    record.model_dump_json(),
                ),
            )
            row = tx.execute(
                "SELECT payload FROM r2s_input_resolutions WHERE report_checksum=?", (report.report_checksum,)
            ).fetchone()
        if row is None:
            raise InputAssemblyConflictError("resolution was not persisted")
        saved = InputResolutionRecord.model_validate_json(row[0])
        if saved != record:
            raise InputAssemblyConflictError("report checksum already points to different resolution evidence")
        return saved

    def get_resolution(self, report_checksum: str) -> InputResolutionRecord:
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_input_resolutions WHERE report_checksum=?", (report_checksum,)
            ).fetchone()
        if row is None:
            raise InputAssemblyNotFoundError(f"input resolution not found: {report_checksum}")
        record = InputResolutionRecord.model_validate_json(row[0])
        verify_input_resolution_checksum(record.report)
        verify_runtime_registry_checksum(record.runtime_registry)
        return record
