"""Duyệt và phát hành (PRODUCT-10/11) trên đúng gói mô phỏng của revision SceneIR hiện tại.

Trạng thái không lưu riêng mà **suy ra từ artifact bất biến** gắn với candidate checksum:

- gói mô phỏng của revision hiện tại (SIM-05)            → `CANDIDATE_READY`
- `ValidationReport` của đúng candidate (SIM-06/07)       → `READY_FOR_REVIEW` (PASS) / `DRAFT` (FAIL/ERROR)
- `ApprovalRecord` (một quyết định cho mỗi candidate)     → `APPROVED` / `REJECTED`
- `ReleaseManifest` niêm phong                            → `RELEASED`

Sửa scene tạo revision mới, revision mới chưa có gói nên mọi report/quyết định cũ tự hết hiệu lực
(Contract §9). Quyết định chỉ do Reviewer đã xác thực; không nhận reviewer_id từ payload.
Phát hành tự chạy ngay sau khi duyệt, không có thêm cổng người (STUDIO_UX_SPEC.md F8); lỗi niêm phong giữ
`APPROVED` và cho thử lại. Không build lại USD: bản phát hành dùng lại đúng byte của gói đã kiểm.
"""

import hashlib
import io
import logging
import zipfile
import zlib
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.release import (
    ApprovalDecision,
    ApprovalRecord,
    ArtifactInventoryItem,
    ReleaseApproval,
    ReleaseManifest,
    ReleaseRunType,
    SceneRevisionRecord,
    SceneRevisionStatus,
)
from src.models.contracts.validation import ValidationReport
from src.services.orchestration.artifacts import ArtifactAlreadyExistsError
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.release_seals import (
    ReleaseSealError,
    ReleaseSealIntent,
    ReleaseSealRepository,
    ReleaseSealStatus,
)
from src.services.orchestration.review.simulation_package import SimulationPackage, current_package
from src.services.orchestration.review.validation_gate import evaluate_validation_eligibility

SCHEMA_VERSION = "1.0"
ZERO = "sha256:" + "0" * 64
_RELEASE_RETRY_MESSAGE = "Bản phát hành chưa hoàn tất hoặc chưa vượt qua kiểm tra toàn vẹn; Reviewer có thể thử lại."
logger = logging.getLogger(__name__)


class ReviewError(ValueError):
    """Thao tác không hợp lệ với trạng thái hiện tại (API trả 409/422 theo `conflict`)."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


class ReviewState(BaseModel):
    """Trạng thái duyệt của revision SceneIR hiện tại, kèm các artifact làm căn cứ."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    record: SceneRevisionRecord
    package: SimulationPackage | None = None
    validation: ValidationReport | None = None
    #: Chỉ True khi run worker, runtime manifest và report đã được xác minh cùng selection.
    isaac_runtime_proof: bool | None = None
    warning_ids: list[str] = []
    approval: ApprovalRecord | None = None
    #: Tên hiển thị của `approval.reviewer_id`, API điền lúc trả về (contract ApprovalRecord chỉ lưu id).
    reviewer_name: str | None = None
    release: ReleaseManifest | None = None
    release_archive: ProductArtifactRef | None = None
    #: Thông báo an toàn khi seal còn dở hoặc artifact release không vượt qua kiểm tra toàn vẹn.
    release_seal_error: str | None = None
    #: Lý do chưa duyệt được (hiện nguyên văn trên UI).
    blockers: list[str] = []


def _hex(checksum: str) -> str:
    return checksum.removeprefix("sha256:")


def validation_uri(job_id: str, candidate_checksum: str) -> str:
    return f"artifact://jobs/{job_id}/validation/{_hex(candidate_checksum)}/validation_report.json"


def approval_uri(job_id: str, candidate_checksum: str) -> str:
    return f"artifact://jobs/{job_id}/review/{_hex(candidate_checksum)}/approval_record.json"


def release_uri(job_id: str, candidate_checksum: str) -> str:
    return f"artifact://jobs/{job_id}/release/{_hex(candidate_checksum)}/release_manifest.json"


def _ref(job_id: str, uri: str, artifact_type: str, stage: StageId, payload: bytes) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version=SCHEMA_VERSION,
        artifact_uri=uri,
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=job_id,
    )


def _read(registry: ProjectRegistry, uri: str) -> bytes | None:
    path = registry.runtime_resolver.locate(uri)
    return path.read_bytes() if path is not None else None


def _publish_once(registry: ProjectRegistry, reference: ProductArtifactRef, payload: bytes) -> None:
    """Artifact quyết định/phát hành chỉ ghi một lần; lần hai là xung đột (409), không ghi đè."""
    try:
        registry.scene.store.publish(reference, payload)
    except ArtifactAlreadyExistsError as error:
        raise ReviewError("Đã có quyết định/bản phát hành cho gói này", conflict=True) from error


def review_state(registry: ProjectRegistry, job_id: str) -> ReviewState:
    """Suy trạng thái từ artifact của revision hiện tại."""
    scene = registry.scene.current(job_id).scene
    package = current_package(registry, job_id)
    record = SceneRevisionRecord(
        schema_version=SCHEMA_VERSION,
        scene_id=scene.scene_id,
        scene_revision=scene.scene_revision,
        scene_ir_checksum=scene.scene_ir_checksum,
        status=SceneRevisionStatus.DRAFT,
    )
    if package is None or package.candidate is None:
        return ReviewState(
            job_id=job_id,
            record=record,
            blockers=["Chưa có gói mô phỏng cho revision này — bấm Tạo gói mô phỏng"],
        )
    candidate = package.candidate.candidate_checksum
    record = record.model_copy(update={"status": SceneRevisionStatus.CANDIDATE_READY, "candidate_checksum": candidate})
    state = ReviewState(job_id=job_id, record=record, package=package)

    # Legacy report chỉ giữ để xem lại. Nó không cấp eligibility kể cả khi checksum hợp lệ
    # hoặc environment_versions khai một phiên bản Isaac có vẻ thật.
    raw = _read(registry, validation_uri(job_id, candidate))
    if raw is not None:
        try:
            legacy = ValidationReport.model_validate_json(raw)
            verify_content_checksum(legacy, "report_checksum")
            if legacy.candidate_checksum == candidate:
                state.validation = legacy
                state.record = state.record.model_copy(update={"validation_report_checksum": legacy.report_checksum})
                state.isaac_runtime_proof = False
        except (ValueError, OSError):
            state.blockers = ["Legacy validation report không hợp lệ; không được dùng làm bằng chứng"]
            return state

    eligibility = evaluate_validation_eligibility(
        registry,
        job_id,
        scene,
        package.candidate,
        package_scene_revision=package.scene_revision,
        package_scene_ir_checksum=package.scene_ir_checksum,
    )
    if not eligibility.eligible:
        if eligibility.report is not None or state.validation is not None:
            state.isaac_runtime_proof = False
        state.blockers = eligibility.blockers or ["Validation chưa đạt policy hiện tại"]
        return state
    report = eligibility.report
    assert report is not None
    state.validation = report
    state.isaac_runtime_proof = True
    state.warning_ids = eligibility.warning_ids
    state.record = state.record.model_copy(
        update={"validation_report_checksum": report.report_checksum, "status": SceneRevisionStatus.READY_FOR_REVIEW}
    )
    raw = _read(registry, approval_uri(job_id, candidate))
    if raw is None:
        return state
    try:
        approval = ApprovalRecord.model_validate_json(raw)
        verify_content_checksum(approval, "record_checksum")
    except (ValueError, OSError):
        state.blockers = ["Approval record không hợp lệ"]
        return state
    if approval.candidate_checksum != candidate or approval.validation_report_checksum != report.report_checksum:
        state.blockers = ["Approval record không khớp candidate/report validation hiện tại"]
        return state
    if approval.decision == ApprovalDecision.APPROVE and approval.accepted_warning_ids != sorted(state.warning_ids):
        state.blockers = ["Approval record không chấp nhận đúng từng validation warning hiện tại"]
        return state
    state.approval = approval
    decided = (
        SceneRevisionStatus.APPROVED if approval.decision == ApprovalDecision.APPROVE else SceneRevisionStatus.REJECTED
    )
    state.record = state.record.model_copy(
        update={"status": decided, "approval_record_checksum": approval.record_checksum}
    )
    repository = ReleaseSealRepository(registry.persistence.database) if registry.persistence else None
    intent: ReleaseSealIntent | None = None
    has_failure = False
    if repository is not None:
        try:
            intent = repository.get(job_id, candidate, report.report_checksum, approval.record_checksum)
            has_failure = repository.has_failure(job_id, candidate, report.report_checksum, approval.record_checksum)
        except (ReleaseSealError, OSError, ValueError):
            state.release_seal_error = _RELEASE_RETRY_MESSAGE
            return state

    uri = release_uri(job_id, candidate)
    raw = _read(registry, uri)
    archive_uri = f"artifact://jobs/{job_id}/release/{_hex(candidate)}/release.zip"
    archive_path = registry.runtime_resolver.locate(archive_uri)
    if raw is None:
        if has_failure or intent is not None or archive_path is not None:
            state.release_seal_error = _RELEASE_RETRY_MESSAGE
        return state

    try:
        release = ReleaseManifest.model_validate_json(raw)
        verify_content_checksum(release, "release_manifest_checksum")
        _verify_release_manifest_identity(release, registry, state, package, report, approval)
        if intent is not None:
            if intent.status != ReleaseSealStatus.SEALED or intent.manifest_payload.encode("utf-8") != raw:
                state.release_seal_error = _RELEASE_RETRY_MESSAGE
                return state
        if archive_path is None:
            state.release_seal_error = _RELEASE_RETRY_MESSAGE
            return state
        archive_bytes = archive_path.read_bytes()
        archive_ref = _ref(job_id, archive_uri, "ReleaseArchive", StageId.RELEASE, archive_bytes)
        if intent is not None and intent.archive_ref != archive_ref:
            state.release_seal_error = _RELEASE_RETRY_MESSAGE
            return state
        package_zip = registry.runtime_resolver.require(package.package_ref).read_bytes()
        _verify_release_archive(package_zip, archive_bytes, raw, report, approval)
    except (ArtifactStoreError, OSError, ValueError, zipfile.BadZipFile):
        state.release_seal_error = _RELEASE_RETRY_MESSAGE
        return state

    state.release = release
    state.release_archive = archive_ref
    state.record = state.record.model_copy(update={"status": SceneRevisionStatus.RELEASED})
    return state


def _release_inventory(package: SimulationPackage) -> list[ArtifactInventoryItem]:
    candidate = package.candidate
    if candidate is None or package.package_ref is None:
        raise ValueError("Simulation package has no sealed candidate artifacts")
    refs = [candidate.entrypoint_usd, *candidate.assets, *candidate.geometry, *candidate.colliders, package.package_ref]
    return [
        ArtifactInventoryItem(
            artifact_type=ref.artifact_type,
            artifact_uri=ref.artifact_uri,
            artifact_checksum=ref.artifact_checksum,
            data_class=ref.data_class,
        )
        for ref in refs
    ]


def _verify_release_manifest_identity(
    manifest: ReleaseManifest,
    registry: ProjectRegistry,
    state: ReviewState,
    package: SimulationPackage,
    report: ValidationReport,
    approval: ApprovalRecord,
) -> None:
    """Bind every manifest identity field to the current immutable package and decisions."""
    candidate = package.candidate
    if candidate is None:
        raise ValueError("Release candidate is missing")
    job = registry.get_job(state.job_id)
    expected_approval = ReleaseApproval(
        reviewer_id=approval.reviewer_id,
        approved_at=approval.decided_at,
        accepted_warning_ids=approval.accepted_warning_ids,
        record_checksum=approval.record_checksum,
    )
    if (
        manifest.run_type != ReleaseRunType.ORDINARY
        or manifest.project_id != job.project_id
        or manifest.scene_version != state.record.scene_revision
        or manifest.input_manifest_checksum != job.input_manifest_checksum
        or manifest.job_manifest_checksum != job.job_manifest_checksum
        or manifest.candidate_checksum != candidate.candidate_checksum
        or manifest.preflight_report_checksum != package.preflight.report_checksum
        or manifest.validation_report_checksum != report.report_checksum
        or manifest.processing_config_checksum != job.config_checksum
        or manifest.software_versions != {"validator": report.validator_version, **report.environment_versions}
        or manifest.artifact_inventory != _release_inventory(package)
        or manifest.approval_record != expected_approval
    ):
        raise ValueError("Release manifest does not match current sealed inputs")


def _zip_members(payload: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("ZIP contains duplicate member names")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError("ZIP CRC verification failed")
            return {info.filename: archive.read(info.filename) for info in infos}
    except (OSError, RuntimeError, KeyError, zipfile.BadZipFile, zlib.error) as error:
        raise ValueError("ZIP payload failed integrity checks") from error


def _verify_release_archive(
    package_zip: bytes,
    archive_bytes: bytes,
    manifest_bytes: bytes,
    report: ValidationReport,
    approval: ApprovalRecord,
) -> None:
    """Check exact package closure and the three approval-bound records inside the ZIP."""
    package_members = _zip_members(package_zip)
    archive_members = _zip_members(archive_bytes)
    extra_names = {"release_manifest.json", "validation_report.json", "approval_record.json"}
    if extra_names.intersection(package_members):
        raise ValueError("Simulation package collides with release record names")
    if set(archive_members) != set(package_members).union(extra_names):
        raise ValueError("Release archive contains missing or unexpected members")
    if any(archive_members[name] != data for name, data in package_members.items()):
        raise ValueError("Release archive changed simulation package bytes")
    if archive_members["release_manifest.json"] != manifest_bytes:
        raise ValueError("Release manifest bytes differ from archive")
    embedded_report = ValidationReport.model_validate_json(archive_members["validation_report.json"])
    verify_content_checksum(embedded_report, "report_checksum")
    if embedded_report != report:
        raise ValueError("Release archive validation report differs from approval evidence")
    embedded_approval = ApprovalRecord.model_validate_json(archive_members["approval_record.json"])
    verify_content_checksum(embedded_approval, "record_checksum")
    if embedded_approval != approval:
        raise ValueError("Release archive approval differs from decision record")


def record_validation_report(registry: ProjectRegistry, job_id: str, report: ValidationReport) -> ProductArtifactRef:
    """Nhận ValidationReport từ simulation worker (SIM-09); chỉ cho đúng candidate hiện tại."""
    verify_content_checksum(report, "report_checksum")
    package = current_package(registry, job_id)
    if package is None or package.candidate is None:
        raise ReviewError("Revision hiện tại chưa có gói mô phỏng", conflict=True)
    if report.candidate_checksum != package.candidate.candidate_checksum:
        raise ReviewError("Báo cáo validation thuộc gói khác (scene đã đổi?)", conflict=True)
    payload = report.model_dump_json(indent=2).encode()
    uri = validation_uri(job_id, report.candidate_checksum)
    reference = _ref(job_id, uri, "ValidationReport", StageId.ISAAC_VALIDATE, payload)
    _publish_once(registry, reference, payload)
    return reference


def _require_current(state: ReviewState, candidate_checksum: str, validation_report_checksum: str) -> None:
    """Quyết định phải gắn đúng gói + báo cáo đang hiện; lệch là màn hình cũ (409)."""
    if state.record.candidate_checksum != candidate_checksum:
        raise ReviewError("Gói đang xem không còn là gói hiện tại — tải lại trang", conflict=True)
    if state.record.validation_report_checksum != validation_report_checksum:
        raise ReviewError("Báo cáo validation đã đổi — tải lại trang", conflict=True)


def decide(
    registry: ProjectRegistry,
    job_id: str,
    reviewer_id: str,
    decision: ApprovalDecision,
    candidate_checksum: str,
    validation_report_checksum: str,
    accepted_warning_ids: list[str],
    reason: str | None,
) -> ReviewState:
    """Ghi quyết định của Reviewer; duyệt thì niêm phong phát hành ngay."""
    state = review_state(registry, job_id)
    if state.record.status != SceneRevisionStatus.READY_FOR_REVIEW:
        raise ReviewError(f"Revision đang ở {state.record.status.value}, không chờ duyệt", conflict=True)
    _require_current(state, candidate_checksum, validation_report_checksum)
    if decision == ApprovalDecision.REJECT and not (reason or "").strip():
        raise ReviewError("Từ chối cần lý do cụ thể")
    accepted = sorted(set(accepted_warning_ids))
    if decision == ApprovalDecision.APPROVE and accepted != sorted(state.warning_ids):
        raise ReviewError("Cần xem và chấp nhận từng cảnh báo trước khi duyệt: " + ", ".join(state.warning_ids))
    draft = ApprovalRecord(
        schema_version=SCHEMA_VERSION,
        candidate_checksum=candidate_checksum,
        validation_report_checksum=validation_report_checksum,
        reviewer_id=reviewer_id,
        decision=decision,
        reason=(reason or "").strip() or None,
        decided_at=datetime.now(UTC),
        accepted_warning_ids=accepted if decision == ApprovalDecision.APPROVE else [],
        record_checksum=ZERO,
    )
    approval = draft.model_copy(update={"record_checksum": canonical_content_checksum(draft, "record_checksum")})
    payload = approval.model_dump_json(indent=2).encode()
    uri = approval_uri(job_id, candidate_checksum)
    _publish_once(registry, _ref(job_id, uri, "ApprovalRecord", StageId.REVIEW, payload), payload)
    if decision == ApprovalDecision.APPROVE:
        try:
            seal_release(registry, job_id)
        except ReviewError:
            # Approval đã bền vững; seal_release lưu chẩn đoán an toàn để UI cho Reviewer retry.
            logger.info("Reviewer approval recorded; release sealing remains retryable", extra={"job_id": job_id})
    return review_state(registry, job_id)


def seal_release(registry: ProjectRegistry, job_id: str) -> ReviewState:
    """Niêm phong ReleaseManifest cho gói đã duyệt (gọi lại được khi lần trước lỗi)."""
    state = review_state(registry, job_id)
    if state.record.status == SceneRevisionStatus.RELEASED:
        if registry.persistence and state.approval and state.validation:
            ReleaseSealRepository(registry.persistence.database).clear_failure(
                job_id,
                state.record.candidate_checksum or "",
                state.validation.report_checksum,
                state.approval.record_checksum,
            )
        return state
    if state.record.status != SceneRevisionStatus.APPROVED or not (
        state.package and state.approval and state.validation
    ):
        raise ReviewError("Chỉ phát hành gói đã được duyệt", conflict=True)
    if registry.persistence is None:
        raise ReviewError("Niêm phong release cần runtime database bền vững")
    repository = ReleaseSealRepository(registry.persistence.database)
    package, approval, report = state.package, state.approval, state.validation
    candidate = package.candidate
    assert candidate is not None and package.package_ref is not None
    identity = (job_id, candidate.candidate_checksum, report.report_checksum, approval.record_checksum)
    try:
        result = _seal_release(registry, state, repository)
    except Exception as error:
        try:
            repository.record_failure(*identity)
        except Exception:
            logger.warning(
                "Release sealing failed and its retry diagnostic could not be persisted", extra={"job_id": job_id}
            )
        logger.warning("Release sealing failed; a safe retry diagnostic was recorded", extra={"job_id": job_id})
        if isinstance(error, ReviewError):
            raise
        raise ReviewError("Niêm phong release chưa hoàn tất; Reviewer có thể thử lại") from error
    if result.record.status != SceneRevisionStatus.RELEASED:
        repository.record_failure(*identity)
        raise ReviewError("Release chưa vượt qua kiểm tra toàn vẹn; Reviewer có thể thử lại")
    repository.clear_failure(*identity)
    return result


def _seal_release(registry: ProjectRegistry, state: ReviewState, repository: ReleaseSealRepository) -> ReviewState:
    package, approval, report = state.package, state.approval, state.validation
    assert package is not None and approval is not None and report is not None
    candidate = package.candidate
    assert candidate is not None and package.package_ref is not None
    job_id = state.job_id
    job = registry.get_job(job_id)
    candidate_checksum = candidate.candidate_checksum
    report_checksum = report.report_checksum
    approval_checksum = approval.record_checksum
    artifact_uri = release_uri(job_id, candidate_checksum)
    archive_uri = f"artifact://jobs/{job_id}/release/{_hex(candidate_checksum)}/release.zip"
    package_zip = registry.runtime_resolver.require(package.package_ref).read_bytes()
    report_bytes = report.model_dump_json(indent=2).encode("utf-8")
    approval_bytes = approval.model_dump_json(indent=2).encode("utf-8")
    inventory = _release_inventory(package)

    existing_intent = repository.get(job_id, candidate_checksum, report_checksum, approval_checksum)
    recovered_manifest_bytes: bytes | None = None
    if existing_intent is None:
        recovered_manifest_bytes = _recover_existing_manifest(
            registry,
            state,
            package,
            package_zip,
            report,
            approval,
            artifact_uri,
            archive_uri,
        )

    def create_intent() -> ReleaseSealIntent:
        if recovered_manifest_bytes is None:
            draft = ReleaseManifest(
                schema_version=SCHEMA_VERSION,
                run_type=ReleaseRunType.ORDINARY,
                project_id=job.project_id,
                scene_version=state.record.scene_revision,
                input_manifest_checksum=job.input_manifest_checksum,
                job_manifest_checksum=job.job_manifest_checksum,
                candidate_checksum=candidate_checksum,
                preflight_report_checksum=package.preflight.report_checksum,
                validation_report_checksum=report_checksum,
                processing_config_checksum=job.config_checksum,
                software_versions={"validator": report.validator_version, **report.environment_versions},
                artifact_inventory=inventory,
                review_state="APPROVED",
                approval_record=ReleaseApproval(
                    reviewer_id=approval.reviewer_id,
                    approved_at=approval.decided_at,
                    accepted_warning_ids=approval.accepted_warning_ids,
                    record_checksum=approval_checksum,
                ),
                release_timestamp=datetime.now(UTC),
                release_manifest_checksum=ZERO,
            )
            manifest = draft.model_copy(
                update={"release_manifest_checksum": canonical_content_checksum(draft, "release_manifest_checksum")}
            )
            payload_bytes = manifest.model_dump_json(indent=2).encode("utf-8")
        else:
            payload_bytes = recovered_manifest_bytes
            manifest = ReleaseManifest.model_validate_json(payload_bytes)
        verify_content_checksum(manifest, "release_manifest_checksum")
        _verify_release_manifest_identity(manifest, registry, state, package, report, approval)
        return ReleaseSealIntent.freeze(
            job_id=job_id,
            candidate_checksum=candidate_checksum,
            validation_report_checksum=report_checksum,
            approval_record_checksum=approval_checksum,
            manifest=manifest,
            manifest_payload_bytes=payload_bytes,
        )

    intent = repository.get_or_create(job_id, candidate_checksum, report_checksum, approval_checksum, create_intent)
    manifest_bytes = intent.manifest_payload.encode("utf-8")
    manifest = ReleaseManifest.model_validate_json(manifest_bytes)
    verify_content_checksum(manifest, "release_manifest_checksum")
    _verify_release_manifest_identity(manifest, registry, state, package, report, approval)

    def build_archive() -> bytes:
        return _release_archive(
            package_zip,
            {
                "release_manifest.json": manifest_bytes,
                "validation_report.json": report_bytes,
                "approval_record.json": approval_bytes,
            },
        )

    archive_path = registry.runtime_resolver.locate(archive_uri)
    if archive_path is None:
        archive = build_archive()
        computed_ref = _ref(job_id, archive_uri, "ReleaseArchive", StageId.RELEASE, archive)
        if intent.archive_ref is None:
            intent = repository.record_archive(intent, computed_ref)
        elif intent.archive_ref != computed_ref:
            raise ReviewError("Rebuilt release archive differs from the persisted seal intent", conflict=True)
        assert intent.archive_ref is not None
        _publish_release_once(registry, intent.archive_ref, archive)
    else:
        archive = archive_path.read_bytes()
        archive_ref = _ref(job_id, archive_uri, "ReleaseArchive", StageId.RELEASE, archive)
        if intent.archive_ref is None:
            intent = repository.record_archive(intent, archive_ref)
        elif intent.archive_ref != archive_ref:
            raise ReviewError("Release archive differs from the persisted seal intent", conflict=True)

    _verify_release_archive(package_zip, archive, manifest_bytes, report, approval)
    _publish_release_once(
        registry,
        _ref(job_id, artifact_uri, "ReleaseManifest", StageId.RELEASE, manifest_bytes),
        manifest_bytes,
    )
    repository.mark_sealed(intent)
    return review_state(registry, job_id)


def _recover_existing_manifest(
    registry: ProjectRegistry,
    state: ReviewState,
    package: SimulationPackage,
    package_zip: bytes,
    report: ValidationReport,
    approval: ApprovalRecord,
    manifest_uri: str,
    archive_uri: str,
) -> bytes | None:
    """Adopt an exact manifest from a pre-intent partial publish without rewriting it."""
    manifest_bytes = _read(registry, manifest_uri)
    archive_path = registry.runtime_resolver.locate(archive_uri)
    archive_bytes = archive_path.read_bytes() if archive_path is not None else None
    embedded_manifest = None
    if archive_bytes is not None:
        members = _zip_members(archive_bytes)
        embedded_manifest = members.get("release_manifest.json")
        if embedded_manifest is None:
            raise ReviewError("Existing release archive has no release manifest", conflict=True)
    if manifest_bytes is not None and embedded_manifest is not None and manifest_bytes != embedded_manifest:
        raise ReviewError("Published manifest differs from the existing release archive", conflict=True)
    payload = manifest_bytes or embedded_manifest
    if payload is None:
        return None
    manifest = ReleaseManifest.model_validate_json(payload)
    verify_content_checksum(manifest, "release_manifest_checksum")
    _verify_release_manifest_identity(manifest, registry, state, package, report, approval)
    if archive_bytes is not None:
        _verify_release_archive(package_zip, archive_bytes, payload, report, approval)
    return payload


def _publish_release_once(registry: ProjectRegistry, reference: ProductArtifactRef, payload: bytes) -> None:
    """Reuse identical immutable bytes after a crash; reject mismatches and never overwrite."""
    existing = _read(registry, reference.artifact_uri)
    if existing is not None:
        if existing != payload:
            raise ReviewError("Existing release artifact differs from the frozen seal intent", conflict=True)
        return
    try:
        registry.scene.store.publish(reference, payload)
    except ArtifactAlreadyExistsError as error:
        existing = _read(registry, reference.artifact_uri)
        if existing == payload:
            return
        raise ReviewError("Existing release artifact differs from the frozen seal intent", conflict=True) from error


def _release_archive(package_zip: bytes, extra: dict[str, bytes]) -> bytes:
    """Chép nguyên các entry của gói (không giải nén/sửa nội dung) rồi thêm bản ghi phát hành."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package_zip)) as source, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for info in source.infolist():
            out.writestr(info, source.read(info.filename))
        for name in sorted(extra):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(entry, extra[name])
    return buffer.getvalue()
