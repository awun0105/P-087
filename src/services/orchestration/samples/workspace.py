"""Freeze a completed job alongside a published demo, independently of its live source."""

import json
import shutil
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.manifests import JobManifest, JobStatus
from src.models.contracts.validation_run import ValidationRunRecord, ValidationRunSelection, ValidationRunStatus
from src.services.orchestration.artifacts import ArtifactResolver, sha256_file
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.progress import sanitized_frame_stage
from src.services.orchestration.processing.config import job_config_reference
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.privacy import require_project_dispatch
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.simulation_package import record_uri
from src.services.orchestration.review.workflow import approval_uri, release_uri, validation_uri
from src.services.orchestration.samples.bundle import DemoBundle, DemoUnavailableError
from src.services.orchestration.samples.snapshot import copy_artifact_graph
from src.services.orchestration.scene.heads import SceneHeadRecord, verify_scene_head


class DemoWorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    sample_manifest_checksum: str
    job: JobManifest
    project: ProjectRecord
    head: SceneHeadRecord
    attempts: list[JobAttemptRecord]
    files: list[dict[str, str | bool]]
    protected_uris: list[str]
    validation_runs: list[ValidationRunRecord] = []
    validation_selections: list[ValidationRunSelection] = []


def load_workspace(bundle: DemoBundle) -> DemoWorkspaceSnapshot:
    manifest = bundle.manifest()
    try:
        snapshot = DemoWorkspaceSnapshot.model_validate_json((bundle.root / "workspace/snapshot.json").read_bytes())
        verify_scene_head(snapshot.head)
        if (
            snapshot.sample_manifest_checksum != sha256_file(bundle.root / "manifest.json")
            or snapshot.job.job_id != manifest.provenance.get("job_id")
            or snapshot.head.job_id != snapshot.job.job_id
            or snapshot.project.project_id != snapshot.job.project_id
        ):
            raise ValueError("workspace does not match published demo")
        return snapshot
    except (OSError, ValueError) as error:
        raise DemoUnavailableError("Mẫu chưa có bản chụp workspace hợp lệ; cần xuất lại từ job") from error


def freeze_workspace(registry: ProjectRegistry, bundle: DemoBundle, *, recording_dir: Path | None = None) -> None:
    """Add one immutable baseline; never replace an existing one or modify the source job."""
    manifest = bundle.manifest()
    job_id = manifest.provenance.get("job_id")
    if not job_id or manifest.origin != "pipeline_job" or registry.persistence is None:
        raise DemoUnavailableError("Cần job thật có DB để xuất workspace tương tác")
    job = registry.get_job(job_id)
    if job.status != JobStatus.SUCCEEDED:
        raise DemoUnavailableError("Job chưa hoàn tất để xuất workspace tương tác")
    project = registry.get_project(job.project_id)
    if any(
        project.source_rights_attestation.get(key) is not True
        for key in ("rights_to_use_confirmed", "anonymization_confirmed")
    ):
        raise DemoUnavailableError("Job chưa xác nhận quyền công khai và ẩn danh")
    require_project_dispatch(project)
    current = registry.scene.current(job_id)
    with registry.persistence.database.transaction() as tx:
        row = tx.execute("SELECT payload FROM r2s_scene_heads WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise DemoUnavailableError("Scene nguồn chưa có head trong DB")
    head = SceneHeadRecord.model_validate_json(row[0])
    verify_scene_head(head)
    if head.scene_revision != current.scene.scene_revision:
        raise DemoUnavailableError("Scene vừa thay đổi khi xuất mẫu; thử lại")
    destination = bundle.root / "workspace"
    if destination.exists():
        raise DemoUnavailableError("Mẫu đã có workspace; không ghi đè bản đã công khai")
    temporary = bundle.root / f".workspace-{uuid4().hex}"
    temporary.mkdir()
    try:
        resolver = registry.runtime_resolver
        target = ArtifactResolver(temporary / "artifacts")
        roots: list[object] = [
            job.model_dump(mode="json"),
            project.model_dump(mode="json"),
            current.scene.model_dump(mode="json"),
        ]
        revision = current
        while True:
            roots.append({**revision.scene_reference.model_dump(mode="json"), "_demo_shallow": True})
            if revision.supersedes_revision is None:
                break
            previous = registry.scene.revision(job_id, revision.supersedes_revision)
            if previous is None:
                raise DemoUnavailableError("Lịch sử scene thiếu revision; chưa xuất được workspace")
            revision = previous
        config = job_config_reference(job_id, job.config_checksum)
        if resolver.locate(config.artifact_uri) is not None:
            roots.append(config.model_dump(mode="json"))
        attempts = registry.list_job_attempts(job_id)
        for attempt in attempts:
            if attempt.job_manifest_uri and attempt.job_manifest_checksum:
                roots.append(
                    {
                        "artifact_uri": attempt.job_manifest_uri,
                        "artifact_checksum": attempt.job_manifest_checksum,
                        "_demo_shallow": True,
                    }
                )
        # These product records are addressed by native URI helpers, rather than SceneIR refs.
        package_path = resolver.locate(record_uri(job_id, head.scene_revision))
        optional = [record_uri(job_id, head.scene_revision)]
        if package_path is not None:
            candidate = json.loads(package_path.read_bytes()).get("candidate")
            if candidate:
                checksum = candidate["candidate_checksum"]
                optional.extend(helper(job_id, checksum) for helper in (validation_uri, approval_uri, release_uri))
                optional.append(release_uri(job_id, checksum).rsplit("/", 1)[0] + "/release.zip")
        runs: list[ValidationRunRecord] = []
        selections: list[ValidationRunSelection] = []
        with registry.persistence.database.transaction() as tx:
            for row in tx.execute(
                "SELECT payload FROM r2s_validation_runs WHERE job_id=? AND status IN ('COMPLETED','FAILED','CANCELLED')",
                (job_id,),
            ).fetchall():
                run = ValidationRunRecord.model_validate_json(row[0])
                verify_content_checksum(run, "run_checksum")
                runs.append(run)
            for row in tx.execute("SELECT payload FROM r2s_validation_selections WHERE job_id=?", (job_id,)).fetchall():
                selection = ValidationRunSelection.model_validate_json(row[0])
                verify_content_checksum(selection, "selection_checksum")
                if any(run.run_id == selection.run_id and run.status == ValidationRunStatus.COMPLETED for run in runs):
                    selections.append(selection)
        roots.extend(run.model_dump(mode="json") for run in runs)
        sanitized = sanitized_frame_stage(job)
        if sanitized is not None:
            from src.services.orchestration.jobs.anonymization_review import review

            review(registry, job_id)  # Verify the implicit sanitization manifest against the frame set.
            optional.append(sanitized.artifact_uri.rsplit("/", 1)[0] + "/manifest.json")
        for attempt in sorted({event.attempt for event in attempts}):
            for phase in ("terminal", "partial"):
                optional.append(f"artifact://jobs/{job_id}/benchmark/pipeline_runtime/attempt-{attempt}-{phase}.json")
        for uri in optional:
            path = resolver.locate(uri)
            if path is not None:
                roots.append({"artifact_uri": uri, "artifact_checksum": sha256_file(path)})
        copied = copy_artifact_graph(resolver, target, roots)
        protected: list[str] = []
        sanitized = sanitized_frame_stage(job)
        if sanitized is not None:
            raw: list[object] = [
                stage.model_dump(mode="json")
                for stage in job.stage_artifacts
                if stage.stage_id == "ST-FRAME-EXTRACT" and stage.artifact_uri != sanitized.artifact_uri
            ]
            if project.input_manifest_ref is not None:
                raw.append(project.input_manifest_ref.model_dump(mode="json"))
            protected = copy_artifact_graph(resolver, target, raw)
        files = [
            {"artifact_uri": uri, "artifact_checksum": sha256_file(target.resolve(uri)), "_demo_shallow": True}
            for uri in dict.fromkeys([*copied, *protected])
        ]
        snapshot = DemoWorkspaceSnapshot(
            sample_manifest_checksum=sha256_file(bundle.root / "manifest.json"),
            job=job,
            project=project,
            head=head,
            attempts=attempts,
            files=files,
            protected_uris=protected,
            validation_runs=runs,
            validation_selections=selections,
        )
        if recording_dir is not None and (recording_dir / f"{job_id}.rrd").is_file():
            (temporary / "recordings").mkdir()
            shutil.copyfile(recording_dir / f"{job_id}.rrd", temporary / "recordings" / f"{job_id}.rrd")
        (temporary / "snapshot.json").write_text(snapshot.model_dump_json())
        with registry.persistence.database.transaction() as tx:
            latest = tx.execute("SELECT head_checksum FROM r2s_scene_heads WHERE job_id=?", (job_id,)).fetchone()
        if latest is None or latest[0] != head.head_checksum or registry.get_job(job_id) != job:
            raise DemoUnavailableError("Job hoặc scene vừa thay đổi khi xuất mẫu; thử lại")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
