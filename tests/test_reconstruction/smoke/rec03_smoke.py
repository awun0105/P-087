"""Manual real-tool qualification: python -m tests.test_reconstruction.smoke.rec03_smoke.

Cấu hình qua REC03_SMOKE_* và REC03_COLMAP_*; không chạy trong pytest thường.
Runner này chỉ compose real producer/consumer để lưu evidence, không là REC-11.
"""

import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import InputManifest
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.colmap_model import read_sparse_model
from src.services.reconstruction.adapters.colmap_runtime import ColmapProcess, ColmapRuntimeSettings
from src.services.reconstruction.adapters.torwic_frame_source import TorwicFrameSource, TorwicFrameSourceConfig
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver


class SmokeSettings(BaseSettings):
    """Paths ở test composition root; artifact payload giữ logical refs."""

    dataset_root: Path
    review_dir: Path
    frame_artifact_root: Path
    frame_reference: Path
    output_root: Path
    workspace: Path
    config_path: Path
    job_id: str
    traversal_id: str = "Aisle_CW"
    model_config = SettingsConfigDict(env_prefix="REC03_SMOKE_", extra="forbid")


def dependencies(settings: SmokeSettings) -> ColmapDependencies:
    """Nguồn là published REC-02A + REC-02 inventory đã xác nhận."""
    manifest = InputManifest.model_validate_json((settings.review_dir / "input_manifest.json").read_text())
    source = TorwicFrameSource(
        TorwicFrameSourceConfig(
            settings.dataset_root, settings.traversal_id, settings.review_dir / "frame_inventory.json"
        ),
        manifest,
    )
    frames = FrameSetResolver(source.resolve, ArtifactResolver(settings.frame_artifact_root).require)
    output = ArtifactResolver(settings.output_root)
    return ColmapDependencies(
        frames, ColmapProcess(ColmapRuntimeSettings()), FilesystemArtifactStore(output), output.require
    )


def main() -> None:
    """Đọc lại published model ở consumer workspace và lưu receipt checksummed refs."""
    settings = SmokeSettings()
    deps = dependencies(settings)
    reference = ProductArtifactRef.model_validate_json(settings.frame_reference.read_text())
    config = ColmapConfig.model_validate_json(settings.config_path.read_text())
    request = ColmapRequest(reference, config, settings.workspace, settings.job_id)
    result = ColmapAdapter(deps).execute(request)
    consumer = CameraPoseResolver(deps.resolve, deps.frames)
    artifact = consumer.load(result.reference)
    target = settings.output_root / "consumer" / artifact.selected_model_id
    consumer.materialize_sparse(artifact, target)
    parsed = read_sparse_model(target, tuple(artifact.input_frame_ids))
    assert parsed.poses == artifact.poses and parsed.cameras == artifact.cameras
    receipt = dict(
        reference=result.reference.model_dump(mode="json"),
        stage=result.stage.model_dump(mode="json"),
        input_frames=len(artifact.input_frame_ids),
        registered_frames=len(artifact.poses),
        registered_ratio=artifact.registered_ratio,
        models=[m.model_dump() for m in artifact.models],
        selected_model_id=artifact.selected_model_id,
        colmap_version=artifact.colmap_version,
        runtime_identity=artifact.runtime_identity,
        config=artifact.config.model_dump(mode="json"),
        config_checksum=artifact.config_checksum,
        consumer_verified=True,
        qualification="real COLMAP technical smoke; not Primary Demo acceptance",
    )
    (settings.output_root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
