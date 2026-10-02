"""REC-04 orchestration: Brush trainer và splat-transform nguyên engine qua adapters."""

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageArtifact, StageId, StageStatus
from src.services.reconstruction.adapters.brush_input import BrushInput, BrushInputAdapter
from src.services.reconstruction.adapters.brush_runtime import (
    Checkpointing,
    Invocation,
    VisualError,
    VisualProcess,
    brush_command,
)
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor
from src.services.reconstruction.resume import ResumeCache, checkpoint_interval, content_key
from src.services.reconstruction.rgb.splat.visual import (
    BrushConfig,
    BrushVisualArtifact,
    HoldoutQuality,
    SplatInspection,
)
from src.services.reconstruction.rgb.splat.visual_publication import VisualPublisher, VisualResolver

#: Dòng Brush in sau mỗi lần chấm ảnh giữ lại.
EVAL_LINE = re.compile(r"Eval iter (\d+): PSNR ([0-9.]+), ssim ([0-9.]+)")
LPIPS_RUNNER = Path(__file__).with_name("lpips_runner.py")
LPIPS_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class BrushDependencies:
    """Typed injection của input, runtime, publication và consumer verification."""

    inputs: BrushInputAdapter
    process: VisualProcess
    processor: SplatArtifactProcessor
    publisher: VisualPublisher
    resolver: VisualResolver
    #: Kho checkpoint cục bộ (None = không checkpoint, hành vi cũ).
    resume: ResumeCache | None = None


@dataclass(frozen=True)
class BrushRequest:
    """Một immutable attempt, workspace mới; chỉ dùng lại checkpoint cùng sparse model qua `resume_key`."""

    camera_poses: ProductArtifactRef
    config: BrushConfig
    workspace: Path
    #: Khoá sparse model do REC-03 trả; None = không checkpoint/không train tiếp.
    resume_key: str | None = None


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
        split = request.config.eval_split_every
        if split is not None and not self.deps.process.supports_eval_split:
            raise VisualError("BRUSH_CLI_UNSUPPORTED", "Brush runtime cannot hold out evaluation images")
        (request.workspace / "output").mkdir()
        log = self._train(request)
        holdout = None if split is None else self._holdout(request, split, log)
        inspection = self.deps.processor.process_artifact(request.workspace, request.config.sog_iterations)
        payload = self._payload(request, (inputs, inspection, version))
        if holdout is not None:
            held_out, quality = holdout
            payload["training_frame_ids"] = [i for i in payload["training_frame_ids"] if i not in set(held_out)]
            payload["held_out_frame_ids"] = held_out
            if quality is not None:
                payload["holdout_quality"] = quality.model_dump(mode="json")
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

    def _train(self, request: BrushRequest) -> str:
        """Train ra `output/visual.ply`; có kho resume thì checkpoint định kỳ và train tiếp từ bản mới nhất.

        Trả log của Brush. Ảnh render của lần chấm cuối (nếu có) luôn nằm ở `output/eval_<bước>/`.
        """
        process, resume = self.deps.process, self.deps.resume
        total = request.config.total_train_iters
        checkpointing, key = None, None
        if resume is not None and request.resume_key is not None and process.settings.checkpoint_every > 0:
            key = content_key(request.resume_key, request.config.checksum(), process.settings.runtime_identity)
            latest = resume.latest_checkpoint(key, total)
            if latest is not None:
                # Brush lấy `init.ply` trong dataset làm điểm bắt đầu. Trạng thái optimizer không được lưu
                # nên train tiếp không trùng từng bit với train liền mạch.
                shutil.copyfile(latest[1], request.workspace / "training" / "init.ply")
            checkpointing = Checkpointing(
                resume.checkpoint_dir(key),
                checkpoint_interval(total, process.settings.checkpoint_every),
                latest[0] if latest is not None else 0,
            )
        arguments = brush_command(request.config, request.workspace, process.iteration_flag, checkpointing)
        log = process.run(Invocation("brush-train", process.settings.command, arguments), request.workspace)
        if checkpointing is None or resume is None or key is None:
            return log
        final = resume.checkpoints(key).get(total)
        if final is None:
            raise VisualError("VISUAL_ARTIFACT_INVALID", "Brush did not export the final step")
        output = request.workspace / "output"
        shutil.move(final, output / "visual.ply")
        # Brush lưu ảnh chấm cạnh file xuất, tức trong kho checkpoint sắp bị xoá.
        for renders in checkpointing.directory.glob("eval_*"):
            shutil.move(renders, output / renders.name)
        resume.clear_checkpoints(key)
        return log

    def _holdout(self, request: BrushRequest, split: int, log: str) -> tuple[list[int], HoldoutQuality | None]:
        """Ảnh Brush đã giữ lại và điểm chấm ở bước cuối.

        Brush giữ lại ảnh có chỉ số chia hết cho `split` theo thứ tự tên. Khi Brush có lưu ảnh render của lần chấm,
        danh sách đó phải trùng với quy tắc này — lệch thì dừng, vì không còn biết chắc ảnh nào đã được train.
        """
        images = request.workspace / "training" / "images"
        names = sorted(path.stem for path in images.iterdir())
        held_out = [int(name) for index, name in enumerate(names) if index % split == 0]
        total = request.config.total_train_iters
        renders = request.workspace / "output" / f"eval_{total}"
        if renders.is_dir():
            rendered = sorted(int(path.stem) for path in renders.glob("*.png"))
            if rendered != held_out:
                raise VisualError("VISUAL_ARTIFACT_INVALID", "Brush held out different images than recorded")
        final = [match for match in EVAL_LINE.finditer(log) if int(match[1]) == total]
        if not final:
            return held_out, None
        lpips = self._lpips(renders, images, request.workspace) if renders.is_dir() else None
        quality = HoldoutQuality(
            eval_split_every=split,
            iteration=total,
            views=len(held_out),
            psnr=float(final[-1][2]),
            ssim=float(final[-1][3]),
            lpips=lpips,
            lpips_net=None if lpips is None else "vgg",
        )
        return held_out, quality

    def _lpips(self, renders: Path, images: Path, workspace: Path) -> float | None:
        """LPIPS-VGG trong runtime có torch (`REC04_BRUSH_LPIPS_PYTHON`). Không cấu hình hoặc lỗi → None.

        LPIPS là số đo phụ: thiếu runtime, thiếu trọng số mạng hay hết giờ không được làm hỏng bước dựng hình.
        """
        python = self.deps.process.settings.lpips_python
        if python is None:
            return None
        command = [str(python), str(LPIPS_RUNNER), "--renders", str(renders), "--gt", str(images), "--net", "vgg"]
        try:
            completed = subprocess.run(  # noqa: S603 - argv cố định, không qua shell
                command, capture_output=True, text=True, check=False, timeout=LPIPS_TIMEOUT_SECONDS
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            logging.getLogger(__name__).warning("LPIPS không chạy được: %s", type(error).__name__)
            return None
        (workspace / "lpips.log").write_text(completed.stdout[-4000:] + completed.stderr[-4000:])
        if completed.returncode != 0:
            logging.getLogger(__name__).warning("LPIPS thoát với mã %d; xem lpips.log", completed.returncode)
            return None
        try:
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            if int(result["count"]) != len(list(renders.glob("*.png"))):
                return None
            return float(result["lpips"])
        except (IndexError, KeyError, TypeError, ValueError):
            return None

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
