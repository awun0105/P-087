"""Publish/resolve REC-03 via injected storage; không import EX-PRODUCT internals."""

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.services.reconstruction.attempt import PublicationNamespace
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver, _sha256
from src.services.reconstruction.rgb.pose.camera_pose import CameraPoseArtifact
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter


class PosePublisher:
    """Manifest được publish cuối cùng; orphan blob không phải stage success."""

    def __init__(self, writer: ArtifactWriter, job_id: str, attempt_id: str | None = None) -> None:
        self.writer = writer
        self.job_id = job_id
        self.namespace = PublicationNamespace(job_id=job_id, attempt_id=attempt_id)

    def publish(self, name: str, payload: bytes) -> ProductArtifactRef:
        """Logical URI + exact byte checksum cho mỗi payload."""
        kind = "CameraPoseArtifact" if name == "camera_poses.json" else "ColmapPayload"
        reference = ProductArtifactRef(
            artifact_type=kind,
            schema_version="1.0",
            artifact_uri=self.namespace.uri("rec03", name),
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.CAMERA_POSE,
            job_id=self.job_id,
            source_provenance={"producer_version": "rec03-v1"} | self.namespace.provenance(),
        )
        published = self.writer.publish(reference, payload)
        if published != reference:
            raise ValueError("artifact writer changed REC-03 publication identity")
        return reference

    def manifest(self, payload: dict) -> tuple[CameraPoseArtifact, ProductArtifactRef]:
        """Typed/checksummed manifest là điểm commit của một successful attempt."""
        payload["artifact_checksum"] = "sha256:" + "0" * 64
        payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
        artifact = CameraPoseArtifact.model_validate(payload)
        reference = self.publish("camera_poses.json", artifact.model_dump_json(indent=2).encode() + b"\n")
        return artifact, reference


class CameraPoseResolver:
    """Downstream EX-REC nhận published refs, không đọc COLMAP private workspace."""

    def __init__(self, resolve: Callable[[ProductArtifactRef], Path], frames: FrameSetResolver) -> None:
        self.resolve = resolve
        self.frames = frames

    def require(self, reference: ProductArtifactRef) -> Path:
        """Không tin resolver chỉ trả path; verify exact bytes tại consumer boundary."""
        path = self.resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("REC-03 artifact missing or byte checksum mismatch")
        return path

    def load(self, reference: ProductArtifactRef) -> CameraPoseArtifact:
        """Check cả dependency refs và frame lineage trước handoff REC-04/05/06."""
        if reference.artifact_type != "CameraPoseArtifact" or reference.producer_stage != StageId.CAMERA_POSE:
            raise ValueError("not a REC-03 camera pose artifact")
        artifact = CameraPoseArtifact.model_validate_json(self.require(reference).read_text())
        frames = self.frames.load(artifact.source_frame_set)
        if frames.frame_set_checksum != artifact.frame_set_checksum:
            raise ValueError("pose artifact frame-set checksum mismatch")
        if [frame.frame_id for frame in frames.frames] != artifact.input_frame_ids:
            raise ValueError("pose artifact input inventory mismatch")
        for item in [*artifact.sparse_files.values(), artifact.log_ref]:
            self.require(item)
        return artifact

    def materialize_sparse(self, artifact: CameraPoseArtifact, destination: Path) -> Path:
        """Recreate selected COLMAP model only, immutable source bytes giữ nguyên."""
        allowed = {
            f"{name}.{ext}" for name in ("cameras", "images", "points3D", "rigs", "frames") for ext in ("bin", "txt")
        }
        if not set(artifact.sparse_files) <= allowed:
            raise ValueError("unexpected COLMAP sparse member")
        paths = {name: self.require(ref) for name, ref in artifact.sparse_files.items()}
        destination.mkdir(parents=True, exist_ok=False)
        try:
            for name, path in paths.items():
                shutil.copyfile(path, destination / name)
        except OSError:
            shutil.rmtree(destination)
            raise
        return destination
