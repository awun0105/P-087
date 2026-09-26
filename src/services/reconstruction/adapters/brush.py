"""REC-04 orchestration: Brush trainer và splat-transform nguyên engine qua adapters."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageArtifact, StageId, StageStatus
from src.services.reconstruction.adapters.brush_input import BrushInput, BrushInputAdapter
from src.services.reconstruction.adapters.brush_runtime import Invocation, VisualError, VisualProcess, brush_command
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor
from src.services.reconstruction.rgb.visual import BrushConfig, BrushVisualArtifact, SplatInspection
from src.services.reconstruction.rgb.visual_publication import VisualPublisher, VisualResolver


@dataclass(frozen=True)
class BrushDependencies:
    """Typed injection của input, runtime, publication và consumer verification."""

    inputs: BrushInputAdapter
    process: VisualProcess
    processor: SplatArtifactProcessor
    publisher: VisualPublisher
    resolver: VisualResolver


@dataclass(frozen=True)
class BrushRequest:
    """Một immutable attempt, không resume workspace cũ."""

    camera_poses: ProductArtifactRef
    config: BrushConfig
    workspace: Path


@dataclass(frozen=True)
class BrushResult:
    """Raw visual chưa metric-ready; REC-06 sở hữu canonicalization."""

    artifact: BrushVisualArtifact
    reference: ProductArtifactRef
    stage: StageArtifact


class BrushAdapter:
    """Chỉ thành công sau train, semantic inspection, SOG roundtrip và consumer read."""

    def __init__(self, dependencies: BrushDependencies) -> None:
        self.deps = dependencies

    def execute(self, request: BrushRequest) -> BrushResult:
        """Service boundary giữ cause; không lộ private path/driver stderr ra UI."""
        try:
            request.workspace.mkdir(parents=True, exist_ok=False)
            return self._execute(request)
        except VisualError:
            raise
        except (OSError, ValueError) as error:
            raise VisualError("VISUAL_ARTIFACT_INVALID", "Visual input/output invalid; inspect attempt logs") from error
        except Exception as error:
            # Injected storage có exception types thuộc owner khác; preserve cause.
            logging.getLogger(__name__).error("REC-04 dependency failed: %s", type(error).__name__)
            raise VisualError("VISUAL_DEPENDENCY_FAILED", "Visual runtime/storage dependency failed") from error

    def _execute(self, request: BrushRequest) -> BrushResult:
        inputs = self.deps.inputs.prepare(request.camera_poses, request.workspace)
        version = self.deps.process.qualify(request.workspace)
        (request.workspace / "output").mkdir()
        arguments = brush_command(request.config, request.workspace, self.deps.process.iteration_flag)
        self.deps.process.run(
            Invocation("brush-train", self.deps.process.settings.command, arguments), request.workspace
        )
        inspection = self.deps.processor.process_artifact(request.workspace, request.config.sog_iterations)
        payload = self._payload(request, (inputs, inspection, version))
        self._verify_payload(payload)
        artifact, ref = self.deps.publisher.manifest(payload)
        self.deps.resolver.load(ref)
        stage = StageArtifact(
            stage_id=StageId.VISUAL_RECON,
            status=StageStatus.SUCCEEDED,
            completed_at=datetime.now(UTC),
            artifact_type=ref.artifact_type,
            artifact_uri=ref.artifact_uri,
            artifact_checksum=ref.artifact_checksum,
            data_class=ref.data_class,
        )
        return BrushResult(artifact, ref, stage)

    def _verify_payload(self, payload: dict) -> None:
        """Không công bố manifest thành công nếu injected store làm hỏng payload."""
        self.deps.resolver.poses.load(ProductArtifactRef.model_validate(payload["source_camera_poses"]))
        for ref in (payload["master"], payload["delivery"], *payload["logs"].values()):
            self.deps.resolver.require(ProductArtifactRef.model_validate(ref))

    def _payload(self, request: BrushRequest, result: tuple[BrushInput, SplatInspection, str]) -> dict:
        inputs, inspection, version = result
        publisher = self.deps.publisher
        output = request.workspace / "output"
        master = publisher.publish("visual.ply", (output / "visual.ply").read_bytes(), "GaussianPLY")
        delivery = publisher.publish("scene.sog", (output / "scene.sog").read_bytes(), "GaussianSOG")
        logs = self._publish_logs(request.workspace)
        return dict(
            source_camera_poses=request.camera_poses.model_dump(mode="json"),
            source_frame_set=inputs.poses.source_frame_set.model_dump(mode="json"),
            config=request.config.model_dump(mode="json"),
            config_checksum=request.config.checksum(),
            brush_version=version,
            runtime_identity=self.deps.process.settings.runtime_identity,
            training_frame_ids=[p.frame_id for p in inputs.poses.poses],
            master=master.model_dump(mode="json"),
            delivery=delivery.model_dump(mode="json"),
            inspection=inspection.model_dump(mode="json"),
            bridge=inputs.provenance,
            logs={name: ref.model_dump(mode="json") for name, ref in logs.items()},
        )

    def _publish_logs(self, workspace: Path) -> dict[str, ProductArtifactRef]:
        result = {}
        replacements = [
            str(workspace.resolve()),
            str(self.deps.processor.settings.module_path.resolve()),
            str(Path(__file__).parent.resolve()),
        ]
        for path in sorted(workspace.glob("*.log")):
            text = path.read_text()
            for private_path in replacements:
                text = text.replace(private_path, "<runtime>")
            result[path.name] = self.deps.publisher.publish(f"logs/{path.name}", text.encode())
        return result
