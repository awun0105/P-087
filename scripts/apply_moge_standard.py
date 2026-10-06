"""Áp dụng bản MoGe (3DGS đã xoay đúng sàn và trục Z-up) cho job theo quy trình chuẩn của hệ thống.

Bao gồm:
1. Tạo ReconstructionBundle (REC-10) trỏ tới visual SOG và camera poses của MoGe.
2. Tạo SceneIR rev-002 với environment.visual_ref trỏ tới MoGe SOG và kiểm tra canonical checksum.
3. Tạo JobManifest mới cập nhật các stage artifacts và scene_revision: "rev-002".
4. Lưu qua ProjectRegistry.persistence.save_job vào runtime.db và r2s_job_events.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import MetricScale, MetricScaleStatus
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.manifests import JobStatus, StageId
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts import with_canonical_checksum
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.registry import get_project_registry
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService


def apply_moge_canonical(job_id: str = "job-ed9cf7739a70") -> None:
    registry = get_project_registry()
    current_job = registry.get_job(job_id)

    rec_dir = Path(
        "data/studio_local/artifacts/jobs",
        job_id,
        "rec06/1f83ecf6365cd096240adeb0938b0a5dd14fdf5fe86fdcca11393470081b7952",
    )
    visual_json_path = rec_dir / "97b57e013ecf1ec079e40062928e67633963b688f49d8e7cc0216b86abd5d956/visual.json"
    with open(visual_json_path, encoding="utf-8") as f:
        v = json.load(f)

    # 1. ProductArtifactRefs for MoGe
    moge_sog_uri = f"artifact://jobs/{job_id}/rec06/1f83ecf6365cd096240adeb0938b0a5dd14fdf5fe86fdcca11393470081b7952/a9800ac899ced801f9fde78e36ff4d72245381e059d55a20e97267d1bf68486e/scene.sog"
    moge_sog_file = Path(
        "data/studio_local/artifacts/jobs",
        job_id,
        "rec06/1f83ecf6365cd096240adeb0938b0a5dd14fdf5fe86fdcca11393470081b7952/a9800ac899ced801f9fde78e36ff4d72245381e059d55a20e97267d1bf68486e/scene.sog",
    )
    moge_sog_sha = hashlib.sha256(moge_sog_file.read_bytes()).hexdigest()

    new_visual_ref = ProductArtifactRef(
        artifact_type="VisualArtifact",
        schema_version="1.0",
        artifact_uri=moge_sog_uri,
        artifact_checksum=f"sha256:{moge_sog_sha}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.VISUAL_RECON,
        job_id=job_id,
        source_provenance=v["visual"].get("provenance"),
    )

    moge_poses_uri = f"artifact://jobs/{job_id}/rec06/9e8027eb290690a26d655151a152bf31f837553c4080bd34a9daf0b28820fc69/camera_poses.json"
    moge_poses_file = Path(
        "data/studio_local/artifacts/jobs",
        job_id,
        "rec06/9e8027eb290690a26d655151a152bf31f837553c4080bd34a9daf0b28820fc69/camera_poses.json",
    )
    moge_poses_sha = hashlib.sha256(moge_poses_file.read_bytes()).hexdigest()

    new_pose_ref = ProductArtifactRef(
        artifact_type="CameraPoseArtifact",
        schema_version="1.0",
        artifact_uri=moge_poses_uri,
        artifact_checksum=f"sha256:{moge_poses_sha}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
        source_provenance=v["request"]["canonical_pose_ref"].get("source_provenance"),
    )

    # 2. Build ReconstructionBundle
    orig_bundle_path = Path(
        "data/studio_local/artifacts/jobs",
        job_id,
        "reconstruction/602003dd7f8af5814e8333ffd2ea82e7e651f8fb11753813c1af3f7ed2155bd7/bundle.json",
    )
    orig_bundle = ReconstructionBundle.model_validate_json(orig_bundle_path.read_text(encoding="utf-8"))

    bundle_req = BundleBuildRequest(
        job_id=job_id,
        source_input_checksum=orig_bundle.source_input_checksum,
        input_configuration=orig_bundle.input_configuration,
        metric_scale=MetricScale(status=MetricScaleStatus.CONFIRMED, meters_per_unit=1.0),
        coordinate_system=orig_bundle.coordinate_system,
        rgb_frame_refs=orig_bundle.rgb_frame_refs,
        camera_pose_refs=[new_pose_ref],
        visual_artifact_ref=new_visual_ref,
        rgb_geometry_ref=orig_bundle.rgb_geometry_ref,
        canonical_geometry_ref=orig_bundle.canonical_geometry_ref,
        provenance=orig_bundle.provenance,
    )

    bundle_service = ReconstructionBundleService(writer=None)  # type: ignore
    new_bundle = bundle_service._construct_bundle(bundle_req)
    verify_content_checksum(new_bundle, "artifact_checksum")

    bundle_payload = new_bundle.model_dump_json(indent=2).encode("utf-8") + b"\n"
    bundle_file_checksum = f"sha256:{hashlib.sha256(bundle_payload).hexdigest()}"

    bundle_disk_path = Path(
        "data/studio_local/artifacts/jobs",
        job_id,
        "reconstruction",
        Path(new_bundle.artifact_uri).parent.name,
        "bundle.json",
    )
    bundle_disk_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_disk_path.write_bytes(bundle_payload)
    print(f"1. Saved ReconstructionBundle to {bundle_disk_path}")
    print(f"   Bundle URI: {new_bundle.artifact_uri}")
    print(f"   Bundle File Checksum: {bundle_file_checksum}")

    # 3. Build SceneIR rev-002
    scene_v1_path = Path("data/studio_local/artifacts/jobs", job_id, "scene/scene_ir.rev-001.json")
    scene_v1 = SceneIR.model_validate_json(scene_v1_path.read_text(encoding="utf-8"))

    env_v2 = scene_v1.environment.model_copy(update={"visual_ref": new_visual_ref})
    scene_draft = scene_v1.model_copy(
        update={
            "scene_revision": "rev-002",
            "environment": env_v2,
            "provenance": {
                **scene_v1.provenance,
                "edited_from": "rev-001",
                "bundle_checksum": new_bundle.artifact_checksum,
            },
        }
    )
    scene_v2 = with_canonical_checksum(scene_draft, "scene_ir_checksum")
    verify_content_checksum(scene_v2, "scene_ir_checksum")

    scene_payload = scene_v2.model_dump_json(indent=2).encode("utf-8") + b"\n"
    scene_file_checksum = f"sha256:{hashlib.sha256(scene_payload).hexdigest()}"

    scene_v2_path = Path("data/studio_local/artifacts/jobs", job_id, "scene/scene_ir.rev-002.json")
    scene_v2_path.write_bytes(scene_payload)
    print(f"2. Saved SceneIR rev-002 to {scene_v2_path}")
    print(f"   SceneIR Checksum: {scene_v2.scene_ir_checksum}")
    print(f"   SceneIR File Checksum: {scene_file_checksum}")

    # 4. Build JobManifest
    new_stage_artifacts = []
    for sa in current_job.stage_artifacts:
        if sa.artifact_type == "ReconstructionBundle":
            new_stage_artifacts.append(
                sa.model_copy(
                    update={
                        "artifact_uri": new_bundle.artifact_uri,
                        "artifact_checksum": bundle_file_checksum,
                        "completed_at": datetime.now(UTC),
                    }
                )
            )
        elif sa.artifact_type == "SceneIR":
            new_stage_artifacts.append(
                sa.model_copy(
                    update={
                        "artifact_uri": f"artifact://jobs/{job_id}/scene/scene_ir.rev-002.json",
                        "artifact_checksum": scene_file_checksum,
                        "completed_at": datetime.now(UTC),
                    }
                )
            )
        else:
            new_stage_artifacts.append(sa)

    manifest_draft = current_job.model_copy(
        update={
            "scene_revision": "rev-002",
            "stage_artifacts": new_stage_artifacts,
        }
    )
    new_manifest = with_canonical_checksum(manifest_draft, "job_manifest_checksum")
    verify_content_checksum(new_manifest, "job_manifest_checksum")

    manifest_payload = new_manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
    manifest_file_checksum = f"sha256:{hashlib.sha256(manifest_payload).hexdigest()}"

    manifest_id = uuid4().hex
    manifest_disk_path = Path("data/studio_local/artifacts/jobs", job_id, "manifests", f"{manifest_id}.json")
    manifest_disk_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_disk_path.write_bytes(manifest_payload)
    print(f"3. Saved JobManifest to {manifest_disk_path}")
    print(f"   Manifest Checksum: {new_manifest.job_manifest_checksum}")
    print(f"   Manifest File Checksum: {manifest_file_checksum}")

    manifest_ref = ProductArtifactRef(
        artifact_type="JobManifest",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/manifests/{manifest_id}.json",
        artifact_checksum=manifest_file_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=job_id,
        source_provenance=None,
    )

    # 5. Persist to database through standard ProjectRegistry persistence
    with registry.persistence.database.transaction() as tx:
        event_row = tx.execute(
            "SELECT payload FROM r2s_job_events WHERE job_id = ? ORDER BY version DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    prev_event = JobAttemptRecord.model_validate_json(event_row[0])

    event = JobAttemptRecord(
        attempt=prev_event.attempt,
        status=JobStatus.SUCCEEDED,
        current_stage=StageId.OBJECT_EXTRACT,
        recorded_at=datetime.now(UTC),
        job_manifest_uri=manifest_ref.artifact_uri,
        job_manifest_checksum=manifest_file_checksum,
        error=None,
    )

    registry.persistence.save_job(new_manifest, manifest_ref, event, expected=current_job)
    print("4. Persisted new JobManifest via registry.persistence.save_job!")

    # Verify retrieval
    loaded = registry.get_job(job_id)
    print(f"5. Verification: Registry loaded job successfully with revision={loaded.scene_revision}!")


if __name__ == "__main__":
    apply_moge_canonical()
