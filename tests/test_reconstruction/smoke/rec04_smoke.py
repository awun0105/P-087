"""Manual real-tool smoke: python -m tests.test_reconstruction.smoke.rec04_smoke.

REC04_SMOKE_* chọn published inputs; REC04_BRUSH_*, REC04_SPLAT_* và
REC03_COLMAP_* inject pinned runtimes. Không dùng test/evaluation-only frames.
"""

import json
import time
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import InputManifest
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.brush import BrushAdapter, BrushDependencies, BrushRequest
from src.services.reconstruction.adapters.brush_input import BrushInputAdapter
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings, VisualProcess
from src.services.reconstruction.adapters.colmap_runtime import ColmapProcess, ColmapRuntimeSettings
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor, SplatRuntimeSettings
from src.services.reconstruction.adapters.torwic_frame_source import TorwicFrameSource, TorwicFrameSourceConfig
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.splat.visual import BrushConfig
from src.services.reconstruction.rgb.splat.visual_publication import VisualPublisher, VisualResolver


class SmokeSettings(BaseSettings):
    """Composition root riêng, không publish filesystem paths."""

    dataset_root: Path
    review_dir: Path
    frame_artifact_root: Path
    pose_artifact_root: Path
    pose_receipt: Path
    output_root: Path
    workspace: Path
    config_path: Path
    job_id: str
    traversal_id: str = "Aisle_CW"
    model_config = SettingsConfigDict(env_prefix="REC04_SMOKE_", extra="forbid")


def dependencies(settings: SmokeSettings) -> BrushDependencies:
    """Reuse các published producer/resolver; không đọc workspace REC-03."""
    manifest = InputManifest.model_validate_json((settings.review_dir / "input_manifest.json").read_text())
    source = TorwicFrameSource(
        TorwicFrameSourceConfig(
            settings.dataset_root, settings.traversal_id, settings.review_dir / "frame_inventory.json"
        ),
        manifest,
    )
    frames = FrameSetResolver(source.resolve, ArtifactResolver(settings.frame_artifact_root).require)
    poses = CameraPoseResolver(ArtifactResolver(settings.pose_artifact_root).require, frames)
    output = ArtifactResolver(settings.output_root)
    process = VisualProcess(BrushRuntimeSettings())
    return BrushDependencies(
        BrushInputAdapter(poses, ColmapProcess(ColmapRuntimeSettings())),
        process,
        SplatArtifactProcessor(SplatRuntimeSettings(), process),
        VisualPublisher(FilesystemArtifactStore(output), settings.job_id),
        VisualResolver(output.require, poses),
    )


def main() -> None:
    """Receipt chỉ xuất hiện sau consumer verification thành công."""
    settings = SmokeSettings()
    ref = ProductArtifactRef.model_validate(json.loads(settings.pose_receipt.read_text())["reference"])
    config = BrushConfig.model_validate_json(settings.config_path.read_text())
    start = time.monotonic()
    result = BrushAdapter(dependencies(settings)).execute(BrushRequest(ref, config, settings.workspace))
    receipt = dict(
        reference=result.reference.model_dump(mode="json"),
        stage=result.stage.model_dump(mode="json"),
        config=config.model_dump(),
        config_checksum=config.checksum(),
        num_gaussians=result.artifact.inspection.num_gaussians,
        brush_version=result.artifact.brush_version,
        runtime_identity=result.artifact.runtime_identity,
        splat_version=result.artifact.inspection.version,
        splat_revision=result.artifact.inspection.revision,
        elapsed_seconds=time.monotonic() - start,
        consumer_verified=True,
        qualification="real Brush technical smoke; not Primary Demo or metric geometry acceptance",
    )
    (settings.output_root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
