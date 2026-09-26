"""Handoff REC-03 → Brush; reuse COLMAP undistorter, không tự sửa intrinsics."""

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.adapters.colmap_model import read_sparse_model
from src.services.reconstruction.adapters.colmap_runtime import ColmapProcess
from src.services.reconstruction.rgb.camera_pose import CameraPoseArtifact
from src.services.reconstruction.rgb.ffmpeg_probe import FFmpegRGBProbe
from src.services.reconstruction.rgb.frame_set import _sha256
from src.services.reconstruction.rgb.pose_publication import CameraPoseResolver


@dataclass(frozen=True)
class BrushInput:
    """Source manifest cùng provenance bridge; input images chỉ là train set."""

    poses: CameraPoseArtifact
    provenance: dict


class BrushInputAdapter:
    """Workspace riêng; chỉ copy selected model và registered frames đã checksum."""

    def __init__(self, poses: CameraPoseResolver, colmap: ColmapProcess | None = None) -> None:
        self.poses = poses
        self.colmap = colmap

    def prepare(self, reference: ProductArtifactRef, workspace: Path) -> BrushInput:
        """Camera distortion được xử lý bởi COLMAP, không gắn nhãn PINHOLE giả."""
        artifact = self.poses.load(reference)
        frame_set = self.poses.frames.load(artifact.source_frame_set)
        rows = self.poses.frames.materialize(frame_set)
        source = workspace / "source"
        self.poses.materialize_sparse(artifact, source / "sparse" / "0")
        parsed = read_sparse_model(source / "sparse" / "0", tuple(artifact.input_frame_ids))
        if parsed.poses != artifact.poses or parsed.cameras != artifact.cameras:
            raise ValueError("COLMAP payload differs from camera pose manifest")
        image_dir = source / "images"
        image_dir.mkdir()
        registered = {pose.frame_id for pose in artifact.poses}
        for frame_id, path, _ in rows:
            if frame_id in registered:
                shutil.copyfile(path, image_dir / f"{frame_id:06d}.png")
        distorted = any(c.model not in {"PINHOLE", "SIMPLE_PINHOLE"} for c in artifact.cameras)
        version = self._undistort(workspace) if distorted else "not_required"
        if not distorted:
            shutil.copytree(source, workspace / "training")
        checksums = self._verify_training(workspace, artifact)
        provenance = {"undistorted": distorted, "colmap_version": version, "training_files": checksums}
        if distorted and self.colmap:
            provenance["colmap_runtime_identity"] = self.colmap.settings.runtime_identity
        return BrushInput(artifact, provenance)

    def _undistort(self, workspace: Path) -> str:
        if self.colmap is None:
            raise ValueError("distorted cameras require a configured COLMAP undistorter")
        help_text = self.colmap.run(["-h"], workspace)
        version = next((line.strip() for line in help_text.splitlines() if line.startswith("COLMAP ")), "")
        if not version:
            raise ValueError("undistorter version could not be verified")
        self.colmap.run(
            [
                "image_undistorter",
                "--image_path",
                "source/images",
                "--input_path",
                "source/sparse/0",
                "--output_path",
                "training",
                "--output_type",
                "COLMAP",
            ],
            workspace,
        )
        self._export_text(workspace)
        return version

    def _export_text(self, workspace: Path) -> None:
        """Brush chỉ thấy một model, tránh tự chọn BIN/TXT khác nhau."""
        assert self.colmap is not None
        model = workspace / "training" / "sparse"
        output = model / "0"
        output.mkdir()
        self.colmap.run(
            [
                "model_converter",
                "--input_path",
                "training/sparse",
                "--output_path",
                "training/sparse/0",
                "--output_type",
                "TXT",
            ],
            workspace,
        )
        # Chỉ một model TXT trong Brush dataset; không cho VFS tự chọn bản BIN khác.
        for item in model.iterdir():
            if item.is_file():
                item.unlink()

    @staticmethod
    def _verify_training(workspace: Path, artifact: CameraPoseArtifact) -> dict[str, str]:
        root = workspace / "training"
        model = read_sparse_model(root / "sparse" / "0", tuple(artifact.input_frame_ids))
        if [p.frame_id for p in model.poses] != [p.frame_id for p in artifact.poses]:
            raise ValueError("Brush bridge changed registered frame inventory")
        for actual, expected in zip(model.poses, artifact.poses, strict=True):
            values = zip(actual.translation + actual.rotation_xyzw, expected.translation + expected.rotation_xyzw)
            if any(not math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6) for a, b in values):
                raise ValueError("undistortion changed camera world poses")
        cameras = {c.camera_id: c for c in model.cameras}
        names = {p.image_name for p in model.poses}
        if {p.name for p in (root / "images").iterdir()} != names:
            raise ValueError("unexpected or missing training image")
        for pose in model.poses:
            camera = cameras[pose.camera_id]
            count, width, height = FFmpegRGBProbe().video_info(root / "images" / pose.image_name)
            if camera.model not in {"PINHOLE", "SIMPLE_PINHOLE"} or (count, width, height) != (
                1,
                camera.width,
                camera.height,
            ):
                raise ValueError("training image/intrinsics mismatch")
        if list(root.rglob("args.txt")):
            raise ValueError("implicit Brush dataset config is not allowed")
        return {str(path.relative_to(root)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file()}
