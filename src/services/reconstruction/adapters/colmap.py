"""REC-03 orchestration, tái sử dụng COLMAP SfM qua process boundary."""

import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageArtifact, StageId, StageStatus
from src.services.reconstruction.adapters.colmap_input import ColmapImageInput, ColmapInputAdapter
from src.services.reconstruction.adapters.colmap_model import ParsedSparseModel, read_sparse_model, select_sparse_model
from src.services.reconstruction.adapters.colmap_priors import (
    PoseGuidance,
    PosePriorError,
    guided_commands,
    prepare_guidance,
)
from src.services.reconstruction.adapters.colmap_runtime import (
    ColmapError,
    ColmapProcess,
    mapper_command,
    reconstruction_commands,
    retry_matching_command,
)
from src.services.reconstruction.adapters.log_excerpt import redacted_excerpt
from src.services.reconstruction.adapters.vocab_tree import file_format, get_vocab_tree_path, vocabulary_format
from src.services.reconstruction.resume import ResumeCache, content_key
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver, _sha256
from src.services.reconstruction.rgb.pose.camera_pose import CameraPoseArtifact, ColmapConfig
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver, PosePublisher
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter


@dataclass(frozen=True)
class ColmapDependencies:
    """Storage/runtime qua injection, không coupling với orchestrator implementation."""

    frames: FrameSetResolver
    process: ColmapProcess
    writer: ArtifactWriter
    resolve: Callable[[ProductArtifactRef], Path]
    #: Kho dùng lại sparse model đã hoàn tất của attempt trước (None = luôn chạy COLMAP).
    resume: ResumeCache | None = None


@dataclass(frozen=True)
class ColmapRequest:
    """Workspace riêng; retry giữ job nhưng dùng attempt namespace mới."""

    frame_set: ProductArtifactRef
    config: ColmapConfig
    workspace: Path
    job_id: str
    attempt_id: str | None = None
    #: Pose từ quỹ đạo của gói LiDAR (ADR 0009). Có thì dựng bám quỹ đạo thay cho `mapper`; tên ảnh là `<frame_id>.png`.
    guidance: PoseGuidance | None = None


@dataclass(frozen=True)
class ColmapResult:
    """Chỉ có success khi manifest và dependencies đã resolve/verify."""

    artifact: CameraPoseArtifact
    reference: ProductArtifactRef
    stage: StageArtifact
    #: Khoá kho resume của sparse model này; REC-04 dùng để tìm checkpoint cùng hệ toạ độ.
    resume_key: str | None = None
    #: Bản ghi độ lệch giữa pose cuối và quỹ đạo khi dựng bám quỹ đạo (bằng chứng cho bước xác nhận tỉ lệ).
    guidance_ref: ProductArtifactRef | None = None


#: Bậc ghép mọi cặp chỉ chạy khi số ảnh không quá mức này (số cặp tăng theo bình phương số ảnh).
EXHAUSTIVE_RETRY_MAX_IMAGES = 400
RETRY_MAX_OVERLAP = 30
LOOP_FLAGS = (
    "loop_detection",
    "vocab_tree_path",
    "loop_detection_period",
    "loop_detection_num_images",
    "loop_detection_min_index_distance",
)


def _passes(config: ColmapConfig, models: list[ParsedSparseModel], frame_count: int) -> bool:
    """Mô hình tốt nhất đạt cả hai ngưỡng đăng ký ảnh của config."""
    best = max((len(model.poses) for model in models), default=0)
    return best >= config.min_registered_frames and best / frame_count >= config.min_registered_ratio


class ColmapAdapter:
    """REUSE core SfM; team chỉ sở hữu validation/orchestration/publication."""

    def __init__(self, dependencies: ColmapDependencies) -> None:
        self.deps = dependencies

    def execute(self, request: ColmapRequest) -> ColmapResult:
        """Không resume database cũ hoặc biến partial sparse output thành success.

        Sparse model **đã hoàn tất** của lần chạy trước (cùng frame set, cấu hình, runtime) thì được dùng lại
        qua `ResumeCache`: mọi bước kiểm và publish vẫn chạy đủ trong namespace của attempt này.
        """
        try:
            request.workspace.mkdir(parents=True, exist_ok=False)
            return self._execute(request)
        except ColmapError:
            raise
        except PosePriorError as error:
            raise ColmapError("COLMAP_GUIDANCE_INVALID", str(error)) from error
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
        if request.config.matching_mode == "sequential":
            version, feature, match = self.deps.process.capabilities(request.workspace)
        else:
            version, feature, match = self.deps.process.capabilities(request.workspace, request.config.matching_mode)
        vocabulary_checksum = self._vocabulary(request, version)
        resume = self.deps.resume
        key = content_key(
            request.frame_set.artifact_checksum,
            request.config.checksum(),
            self.deps.process.settings.runtime_identity,
            version,
            *([request.config.matching_mode, vocabulary_checksum] if vocabulary_checksum is not None else []),
            *([request.guidance.checksum()] if request.guidance is not None else []),
        )
        reused = False
        if resume is not None:
            try:
                reused = resume.restore_colmap(key, request.workspace)
            except (OSError, shutil.Error) as error:
                # A failed cache read/restore is a miss; COLMAP still takes the ordinary cold path.
                logging.getLogger(__name__).warning("REC-03 không phục hồi resume cache cause=%s", type(error).__name__)
        if not reused:
            (request.workspace / "sparse").mkdir()
            commands = reconstruction_commands(request.config, (feature, match))
            if request.guidance is not None:
                # Trích + ghép đặc trưng như thường lệ, rồi dựng bám quỹ đạo thay cho `mapper`.
                for command in commands[:2]:
                    self.deps.process.run(command, request.workspace)
                prepare_guidance(request.workspace, request.guidance)
                (request.workspace / "sparse" / "0").mkdir()
                commands = guided_commands(request.config, request.guidance)
            for command in commands:
                self.deps.process.run(command, request.workspace)
        frame_count = len(images.frame_ids)
        models = self._models(request.workspace, images.frame_ids)
        ladder: list[dict] = []
        if not reused and request.guidance is None and not _passes(request.config, models, frame_count):
            models, ladder = self._retry_ladder(request, version, match, images.frame_ids, models)
        if not models:
            log_path = request.workspace / "process.log"
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            no_initial_pair = log_text.count("Discarding reconstruction due to no initial pair")
            insufficient_size = log_text.count("Discarding reconstruction due to insufficient size")
            excerpt = redacted_excerpt(log_text, request.workspace)
            raise ColmapError(
                "COLMAP_NO_MODEL",
                "COLMAP produced no sparse model",
                details={
                    "diagnostics": {
                        "no_initial_pair": no_initial_pair,
                        "insufficient_size": insufficient_size,
                    },
                    "log_excerpt": excerpt,
                    **({"retry_ladder": ladder} if ladder else {}),
                },
            )
        best = select_sparse_model(models)
        ratio = len(best.poses) / frame_count
        warning = False
        if not _passes(request.config, [best], frame_count):
            accept = request.config.accept_registered_ratio_after_retry
            # Chỉ nhận mô hình thiếu ảnh sau khi thang đã chạy (hoặc mô hình đã được nhận như vậy và lưu cache).
            if (
                accept is not None
                and (ladder or reused)
                and len(best.poses) >= request.config.min_registered_frames
                and ratio >= accept
            ):
                warning = True
            else:
                raise ColmapError(
                    "COLMAP_REGISTRATION_LOW",
                    "Best COLMAP model is below configured registration threshold",
                    details={
                        "registered_frames": len(best.poses),
                        "input_frames": frame_count,
                        "min_registered_ratio": request.config.min_registered_ratio,
                        **({"retry_ladder": ladder} if ladder else {}),
                    },
                )
        payload = self._payload(request, images, best)
        payload.update(colmap_version=version, models=[model.stats.model_dump() for model in models])
        if ladder:
            payload["retry_ladder"] = ladder
        if warning:
            payload["registration_warning"] = True
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
        if resume is not None and not reused:
            # Chỉ giữ sau khi artifact đã publish và consumer đọc lại được: kho không chứa kết quả hỏng.
            try:
                resume.store_colmap(key, request.workspace)
            except (OSError, ValueError) as error:
                # Cache chỉ tăng tốc retry; cache I/O lỗi không được biến pose đã verify thành job failure.
                logging.getLogger(__name__).warning("REC-03 không lưu resume cache cause=%s", type(error).__name__)
        guidance_ref = self._guidance_record(request, artifact, reference) if request.guidance is not None else None
        return ColmapResult(artifact, reference, stage, key if resume is not None else None, guidance_ref)

    def _guidance_record(
        self, request: ColmapRequest, artifact: CameraPoseArtifact, poses_ref: ProductArtifactRef
    ) -> ProductArtifactRef:
        """Độ lệch giữa tâm camera cuối cùng và quỹ đạo: bằng chứng căn chỉnh hiện cho người dùng xác nhận."""
        assert request.guidance is not None
        priors = {prior.image_name: prior.translation for prior in request.guidance.priors}
        offsets = sorted(
            sum((a - b) ** 2 for a, b in zip(pose.translation, priors[pose.image_name], strict=True)) ** 0.5
            for pose in artifact.poses
        )
        record = {
            "schema_version": "1.0",
            "artifact_type": "PoseGuidanceRecord",
            "method": "trajectory_guided_colmap",
            "camera_poses_checksum": poses_ref.artifact_checksum,
            "guidance_checksum": request.guidance.checksum(),
            "position_std_m": request.guidance.position_std_m,
            "calibrated_intrinsics": request.guidance.calibration is not None,
            "input_frames": len(request.guidance.priors),
            "registered_frames": len(offsets),
            "offset_median_m": offsets[len(offsets) // 2],
            "offset_p90_m": offsets[min(len(offsets) - 1, int(len(offsets) * 0.9))],
            "offset_max_m": offsets[-1],
        }
        publisher = PosePublisher(self.deps.writer, request.job_id, request.attempt_id)
        return publisher.publish("pose_guidance.json", json.dumps(record, indent=2).encode() + b"\n")

    def _vocabulary(self, request: ColmapRequest, version: str) -> str | None:
        reference = request.config.vocab_tree
        if reference is None and request.config.matching_mode != "sequential_vocab_tree":
            return None
        runtime_format = vocabulary_format(version)
        if request.config.matching_mode == "sequential_vocab_tree" and runtime_format is None:
            raise ColmapError("COLMAP_VERSION_UNKNOWN", "Cannot select vocabulary format without a COLMAP version")
        faiss = runtime_format == "faiss"
        if reference is not None:
            path = self.deps.resolve(reference)
            if not path.is_file() or _sha256(path) != reference.artifact_checksum:
                raise ValueError("COLMAP vocabulary missing or checksum mismatch")
            checksum = reference.artifact_checksum
        else:
            path = get_vocab_tree_path(format="faiss" if faiss else "flann")
            if path is None:
                raise ColmapError(
                    "VOCAB_TREE_MISSING",
                    "Loop matching requires a verified COLMAP vocabulary",
                    details={
                        "action": f"Run scripts/assets/download_vocab_tree.py --format {'faiss' if faiss else 'flann'} on the worker, or configure PRODUCT_COLMAP_VOCAB_TREE"
                    },
                )
            checksum = _sha256(path)
        if request.config.matching_mode == "sequential_vocab_tree":
            if (file_format(path) == "faiss") != faiss:
                raise ColmapError(
                    "VOCAB_TREE_INCOMPATIBLE",
                    "Vocabulary format does not match the COLMAP runtime",
                    details={"action": f"Use a {'FAISS' if faiss else 'FLANN'} vocabulary for this worker"},
                )
        target = request.workspace / "vocab_tree.bin"
        shutil.copyfile(path, target)
        if _sha256(target) != checksum:
            raise ValueError("COLMAP vocabulary changed during staging")
        return checksum

    def _retry_ladder(
        self,
        request: ColmapRequest,
        version: str,
        match: str,
        frame_ids: tuple[int, ...],
        initial: list[ParsedSparseModel],
    ) -> tuple[list[ParsedSparseModel], list[dict]]:
        """Thang thử lại trên cùng database.db khi lần ghép đầu không ra mô hình đạt ngưỡng (T-071 C1).

        Bậc 1: ghép liên tiếp với gấp đôi số ảnh lân cận (tối đa 30), bật khép vòng nếu worker có từ điển. Bậc 2 (chỉ
        khi ≤ 400 ảnh): ghép mọi cặp. Dừng ở bậc đầu tiên đạt ngưỡng; không bậc nào đạt thì giữ bậc có nhiều ảnh nhất
        (bậc sớm hơn khi bằng nhau). Thang là hàm tất định của config + frame set nên khoá resume cache không đổi.
        """
        config = request.config
        if config.matching_mode == "exhaustive":
            return initial, []  # Ghép mọi cặp đã là bậc cuối của thang: chạy lại không thêm cặp nào.
        frame_count = len(frame_ids)
        loop = config.matching_mode == "sequential_vocab_tree" or self._loop_vocabulary(request, version)
        overlap = max(config.sequential_overlap, min(RETRY_MAX_OVERLAP, config.sequential_overlap * 2))
        plan: list[tuple[int, int | None, bool]] = [(1, overlap, loop)]
        if frame_count <= EXHAUSTIVE_RETRY_MAX_IMAGES:
            plan.append((2, None, False))
        attempts: list[tuple[int, str, str, list[ParsedSparseModel]]] = [(0, "sparse", "text", initial)]
        ladder: list[dict] = []
        for step, step_overlap, step_loop in plan:
            sparse, text = f"sparse_r{step}", f"text_r{step}"
            (request.workspace / sparse).mkdir()
            command = retry_matching_command(config, match, overlap=step_overlap, loop_detection=step_loop)
            self.deps.process.run(command, request.workspace)
            self.deps.process.run(mapper_command(config, sparse), request.workspace)
            models = self._models(request.workspace, frame_ids, sparse=sparse, text=text)
            mode = "exhaustive" if step_overlap is None else "sequential_vocab_tree" if step_loop else "sequential"
            ladder.append(
                dict(
                    step=step,
                    matching_mode=mode,
                    overlap=step_overlap,
                    registered_frames=max((len(model.poses) for model in models), default=0),
                    input_frames=frame_count,
                )
            )
            attempts.append((step, sparse, text, models))
            if _passes(config, models, frame_count):
                break
        logging.getLogger(__name__).info("REC-03 thang thử lại COLMAP: %s", ladder)
        chosen = next((item for item in attempts if _passes(config, item[3], frame_count)), None) or max(
            attempts, key=lambda item: (max((len(model.poses) for model in item[3]), default=0), -item[0])
        )
        step, sparse, text, models = chosen
        if step == 0:
            return models, ladder
        # Bậc thành công thành `sparse/` (và `text/`): resume cache và artifact chỉ thấy đúng một mô hình.
        workspace = request.workspace
        (workspace / "sparse").rename(workspace / "sparse_r0")
        if (workspace / "text").exists():
            (workspace / "text").rename(workspace / "text_r0")
        (workspace / sparse).rename(workspace / "sparse")
        if (workspace / text).exists():
            (workspace / text).rename(workspace / "text")
        return [replace(model, directory=workspace / "text" / model.directory.name) for model in models], ladder

    def _loop_vocabulary(self, request: ColmapRequest, version: str) -> bool:
        """Bậc 1 của config ghép liên tiếp bật khép vòng chỉ khi binary hỗ trợ và worker có từ điển đúng định dạng.

        Thiếu từ điển hoặc binary không có cờ khép vòng → chạy không khép vòng (không ném `VOCAB_TREE_MISSING`);
        từ điển sai định dạng vẫn là lỗi cứng của deploy (`VOCAB_TREE_INCOMPATIBLE`).
        """
        if vocabulary_format(version) is None:
            return False
        options = self.deps.process.run(["sequential_matcher", "-h"], request.workspace)
        if any(f"--SequentialMatching.{flag}" not in options for flag in LOOP_FLAGS):
            return False
        loop_config = request.config.model_copy(update={"matching_mode": "sequential_vocab_tree"})
        try:
            self._vocabulary(replace(request, config=loop_config), version)
        except ColmapError as error:
            if error.code in {"VOCAB_TREE_MISSING", "COLMAP_VERSION_UNKNOWN"}:
                return False
            raise
        return True

    def _models(
        self, workspace: Path, frame_ids: tuple[int, ...], *, sparse: str = "sparse", text: str = "text"
    ) -> list[ParsedSparseModel]:
        models = []
        candidates = sorted((workspace / sparse).iterdir(), key=lambda path: path.name)
        for source in candidates:
            if not source.is_dir() or not source.name.isdigit():
                continue
            output = workspace / text / source.name
            output.mkdir(parents=True)
            self.deps.process.run(
                [
                    "model_converter",
                    "--input_path",
                    f"{sparse}/{source.name}",
                    "--output_path",
                    f"{text}/{source.name}",
                    "--output_type",
                    "TXT",
                ],
                workspace,
            )
            model = read_sparse_model(output, frame_ids)
            if any(not (workspace / "images" / pose.image_name).is_file() for pose in model.poses):
                raise ValueError("COLMAP model image name differs from staged source format")
            models.append(model)
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
