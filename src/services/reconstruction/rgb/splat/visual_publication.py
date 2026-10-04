"""Publish raw visual manifest cuối cùng; consumer xác minh bytes và lineage."""

import hashlib
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.services.reconstruction.attempt import PublicationNamespace
from src.services.reconstruction.rgb.frames.frame_set import _sha256
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual import BrushVisualArtifact


class VisualPublisher:
    """Không import storage implementation của EX-PRODUCT."""

    def __init__(self, writer: ArtifactWriter, job_id: str, attempt_id: str | None = None) -> None:
        self.writer = writer
        self.job_id = job_id
        self.namespace = PublicationNamespace(job_id=job_id, attempt_id=attempt_id)

    def publish(self, name: str, payload: bytes, kind: str = "VisualPayload") -> ProductArtifactRef:
        """Exact byte identity và immutable namespace của attempt."""
        ref = ProductArtifactRef(
            artifact_type=kind,
            schema_version="1.0",
            artifact_uri=self.namespace.uri("rec04", name),
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class="derived",
            producer_stage=StageId.VISUAL_RECON,
            job_id=self.job_id,
            source_provenance={"producer_version": "rec04-v1", "scale_status": "arbitrary_sfm"}
            | self.namespace.provenance(),
        )
        if self.writer.publish(ref, payload) != ref:
            raise ValueError("artifact store changed visual publication identity")
        return ref

    def manifest(self, payload: dict) -> tuple[BrushVisualArtifact, ProductArtifactRef]:
        """Validate typed inventory trước publication marker cuối cùng."""
        payload["artifact_checksum"] = "sha256:" + "0" * 64
        # Defaults phải tham gia checksum giống consumer serialization.
        defaults = {
            "schema_version": "1.0",
            "artifact_type": "BrushVisualArtifact",
            "parent_frame": "sfm_world",
            "scale_status": "arbitrary_sfm",
            "world_alignment_status": "unconfirmed",
            "format": "gaussian_ply",
        }
        payload = defaults | payload
        payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
        artifact = BrushVisualArtifact.model_validate(payload)
        ref = self.publish("visual.json", artifact.model_dump_json(indent=2).encode() + b"\n", "BrushVisualArtifact")
        return artifact, ref


class VisualResolver:
    """REC-05/06 nhận logical refs, không đọc training workspace."""

    def __init__(self, resolve: Callable[[ProductArtifactRef], Path], poses: CameraPoseResolver) -> None:
        self.resolve = resolve
        self.poses = poses

    def require(self, reference: ProductArtifactRef) -> Path:
        """Verify exact bytes ngay cả khi injected resolver chỉ trả path."""
        path = self.resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("visual artifact missing or checksum mismatch")
        return path

    def load(self, reference: ProductArtifactRef) -> BrushVisualArtifact:
        """Bind training IDs với model đã chọn, không với toàn frame inventory."""
        if reference.artifact_type != "BrushVisualArtifact" or reference.producer_stage != StageId.VISUAL_RECON:
            raise ValueError("not a REC-04 raw visual manifest")
        artifact = BrushVisualArtifact.model_validate_json(self.require(reference).read_text())
        poses = self.poses.load(artifact.source_camera_poses)
        if artifact.source_frame_set != poses.source_frame_set:
            raise ValueError("visual frame-set lineage mismatch")
        # Ảnh train + ảnh giữ lại phải đúng bằng các ảnh COLMAP đã đăng ký: không ảnh nào bị bỏ lặng lẽ.
        if sorted(artifact.training_frame_ids + (artifact.held_out_frame_ids or [])) != [
            pose.frame_id for pose in poses.poses
        ]:
            raise ValueError("visual training inventory differs from selected COLMAP model")
        for ref in (artifact.master, artifact.delivery, *artifact.logs.values()):
            self.require(ref)
        return artifact
