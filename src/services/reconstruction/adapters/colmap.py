"""REC-03 orchestration, tái sử dụng COLMAP SfM qua process boundary."""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageArtifact, StageId, StageStatus
from src.services.reconstruction.adapters.colmap_input import ColmapImageInput, ColmapInputAdapter
from src.services.reconstruction.adapters.colmap_model import ParsedSparseModel, read_sparse_model, select_sparse_model
from src.services.reconstruction.adapters.colmap_runtime import ColmapError, ColmapProcess, reconstruction_commands
from src.services.reconstruction.rgb.camera_pose import CameraPoseArtifact, ColmapConfig
from src.services.reconstruction.rgb.frame_set import FrameSetResolver, _sha256
from src.services.reconstruction.rgb.pose_publication import CameraPoseResolver, PosePublisher
from src.services.reconstruction.rgb.publication import ArtifactWriter


@dataclass(frozen=True)
class ColmapDependencies:
    """Storage/runtime qua injection, không coupling với orchestrator implementation."""

    frames: FrameSetResolver
    process: ColmapProcess
    writer: ArtifactWriter
    resolve: Callable[[ProductArtifactRef], Path]


@dataclass(frozen=True)
class ColmapRequest:
    """Workspace riêng; retry giữ job nhưng dùng attempt namespace mới."""

    frame_set: ProductArtifactRef
    config: ColmapConfig
    workspace: Path
    job_id: str
    attempt_id: str | None = None


@dataclass(frozen=True)
class ColmapResult:
    """Chỉ có success khi manifest và dependencies đã resolve/verify."""

    artifact: CameraPoseArtifact
    reference: ProductArtifactRef
    stage: StageArtifact


class ColmapAdapter:
    """REUSE core SfM; team chỉ sở hữu validation/orchestration/publication."""

    def __init__(self, dependencies: ColmapDependencies) -> None:
        self.deps = dependencies

    def execute(self, request: ColmapRequest) -> ColmapResult:
        """Không resume database cũ hoặc biến partial sparse output thành success."""
        try:
            request.workspace.mkdir(parents=True, exist_ok=False)
            return self._execute(request)
        except ColmapError:
            raise
        except (OSError, ValueError) as error:
            raise ColmapError(
                "COLMAP_ARTIFACT_INVALID", "COLMAP input/output invalid; inspect attempt artifacts"
            ) from error
        except Exception as error:
            # Service boundary: injected store có exception type riêng của owner.
            # Giữ cause cho worker; không import EX-PRODUCT hoặc lộ private path ra UI.
            logging.getLogger(__name__).error("REC-03 dependency failed: %s", type(error).__name__)
            raise ColmapError("COLMAP_DEPENDENCY_FAILED", "COLMAP artifact dependency failed") from error

    def _execute(self, request: ColmapRequest) -> ColmapResult:
        images = ColmapInputAdapter(self.deps.frames).prepare(request.frame_set, request.workspace)
        self._vocabulary(request)
        version, feature, match = self.deps.process.capabilities(request.workspace)
        (request.workspace / "sparse").mkdir()
        for command in reconstruction_commands(request.config, (feature, match)):
            self.deps.process.run(command, request.workspace)
        models = self._models(request.workspace, images.frame_ids)
        best = select_sparse_model(models)
        ratio = len(best.poses) / len(images.frame_ids)
        if len(best.poses) < request.config.min_registered_frames or ratio < request.config.min_registered_ratio:
            raise ColmapError("COLMAP_REGISTRATION_LOW", "Best COLMAP model is below configured registration threshold")
        payload = self._payload(request, images, best)
        payload.update(colmap_version=version, models=[model.stats.model_dump() for model in models])
        artifact, reference = PosePublisher(self.deps.writer, request.job_id, request.attempt_id).manifest(payload)
        CameraPoseResolver(self.deps.resolve, self.deps.frames).load(reference)
        stage = StageArtifact(
            stage_id=StageId.CAMERA_POSE,
            status=StageStatus.SUCCEEDED,
            artifact_type=reference.artifact_type,
            artifact_uri=reference.artifact_uri,
            artifact_checksum=reference.artifact_checksum,
            data_class=reference.data_class,
            completed_at=datetime.now(UTC),
        )
        return ColmapResult(artifact, reference, stage)

    def _vocabulary(self, request: ColmapRequest) -> None:
        reference = request.config.vocab_tree
        if reference is None:
            return
        path = self.deps.resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("COLMAP vocabulary missing or checksum mismatch")
        shutil.copyfile(path, request.workspace / "vocab_tree.bin")

    def _models(self, workspace: Path, frame_ids: tuple[int, ...]) -> list[ParsedSparseModel]:
        models = []
        candidates = sorted((workspace / "sparse").iterdir(), key=lambda path: path.name)
        for source in candidates:
            if not source.is_dir() or not source.name.isdigit():
                continue
            output = workspace / "text" / source.name
            output.mkdir(parents=True)
            self.deps.process.run(
                [
                    "model_converter",
                    "--input_path",
                    f"sparse/{source.name}",
                    "--output_path",
                    f"text/{source.name}",
                    "--output_type",
                    "TXT",
                ],
                workspace,
            )
            models.append(read_sparse_model(output, frame_ids))
        return models

    def _payload(self, request: ColmapRequest, images: ColmapImageInput, best: ParsedSparseModel) -> dict:
        publisher = PosePublisher(self.deps.writer, request.job_id, request.attempt_id)
        files = self._publish_sparse(publisher, best)
        raw_log = (request.workspace / "process.log").read_text()
        safe_log = raw_log.replace(str(request.workspace.resolve()), "<workspace>")
        log_ref = publisher.publish("runtime.log", safe_log.encode())
        config = request.config.model_dump(mode="json")
        registered = {pose.frame_id for pose in best.poses}
        return dict(
            schema_version="1.0",
            source_frame_set=request.frame_set.model_dump(mode="json"),
            frame_set_checksum=images.frame_set_checksum,
            config=config,
            config_checksum=request.config.checksum(),
            runtime_identity=self.deps.process.settings.runtime_identity,
            parent_frame="sfm_world",
            camera_axes="x_right_y_down_z_forward",
            transform_semantics="parent_from_local",
            scale_status="arbitrary_sfm",
            world_alignment_status="unconfirmed",
            input_frame_ids=list(images.frame_ids),
            unregistered_frame_ids=sorted(set(images.frame_ids) - registered),
            registered_ratio=len(registered) / len(images.frame_ids),
            selected_model_id=best.stats.model_id,
            cameras=[c.model_dump(mode="json") for c in best.cameras],
            poses=[p.model_dump(mode="json") for p in best.poses],
            sparse_files={name: ref.model_dump(mode="json") for name, ref in files.items()},
            log_ref=log_ref.model_dump(mode="json"),
        )

    @staticmethod
    def _publish_sparse(publisher: PosePublisher, best: ParsedSparseModel) -> dict[str, ProductArtifactRef]:
        paths = [*best.directory.glob("*.txt")]
        native = best.directory.parent.parent / "sparse" / best.stats.model_id
        paths.extend(native.glob("*.bin"))
        return {path.name: publisher.publish(f"sparse/{path.name}", path.read_bytes()) for path in sorted(paths)}
