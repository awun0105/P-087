"""COLMAP CLI process boundary: capability, timeout, exit code và log evidence."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId, StageStatus
from src.models.contracts.retryability import classify_retryability
from src.runtime_env import RuntimeSettings
from src.services.process_control import (
    ProcessStalledError,
    ProcessTimeoutError,
    file_size_marker,
    run_cancellable_process,
    tree_marker,
)
from src.services.reconstruction.adapters.log_excerpt import redacted_excerpt
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig


class ColmapRuntimeSettings(RuntimeSettings):
    """Composition root inject executable/container launcher; không lưu path vào artifact."""

    command: tuple[str, ...] = ("colmap",)
    runtime_identity: str = Field(min_length=1)
    #: Giới hạn cứng mỗi lệnh COLMAP (lưới cuối, T-043 bước 6). Canh treo và hạn tự tính chạy trước nó.
    timeout_seconds: float = Field(gt=0, default=14400, allow_inf_nan=False)
    #: Không dấu hiệu tiến triển (log, database, sparse/) trong khoảng này thì coi như treo. Đo từ log COLMAP thật:
    #: khoảng im lặng lớn nhất là 16,5 s (bundle adjustment toàn cục), nên 600 s cách xa nhiều lần. Xem report T-043.
    stall_seconds: float = Field(gt=0, default=600, allow_inf_nan=False)
    model_config = SettingsConfigDict(env_prefix="R2S_COLMAP_", extra="forbid")


#: Thư mục sparse của các bậc thử lại; bậc thành công được đổi tên thành `sparse/` trước khi lưu.
RETRY_SPARSE_DIRS: tuple[str, ...] = ("sparse_r1", "sparse_r2")


class ColmapError(ValueError):
    """Lỗi có remediation, không serialize private process path/stderr ra UI."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_failed_stage(self) -> StageArtifact:
        """Worker ghi failed stage với log riêng của attempt để điều tra."""
        details: dict[str, Any] = {"action": "Inspect attempt logs, input overlap and the configured COLMAP runtime"}
        if self.__cause__ is not None:
            details["exception_type"] = type(self.__cause__).__name__
        if self.details:
            details.update(self.details)
        error = ExecutionError(
            error_code=self.code,
            stage_id=StageId.CAMERA_POSE,
            human_message=str(self),
            retryable=classify_retryability(
                self.code,
                details,
            ),
            details=details,
        )
        return StageArtifact(
            stage_id=StageId.CAMERA_POSE, status=StageStatus.FAILED, completed_at=datetime.now(UTC), error=error
        )


def _run_watched(
    command: list[str], *, workspace: Path, log: TextIO, settings: ColmapRuntimeSettings, label: str
) -> int:
    """Chạy COLMAP trong nhóm tiến trình riêng, canh tiến độ bằng log, database.db và thư mục kết quả."""
    return run_cancellable_process(
        command,
        cwd=workspace,
        timeout_seconds=settings.timeout_seconds,
        output=log,
        stall_seconds=settings.stall_seconds,
        progress=[
            file_size_marker(workspace / "process.log"),
            file_size_marker(workspace / "database.db"),
            tree_marker(workspace / "sparse", depth=2),
            # Thang thử lại ghi mô hình của từng bậc vào thư mục riêng (T-071 C1).
            *(tree_marker(workspace / name, depth=2) for name in RETRY_SPARSE_DIRS),
            tree_marker(workspace / "training", depth=2),
        ],
        stall_code="PROCESS_STALLED",
        label=label,
    )


def _log_since(log_path: Path, offset: int) -> str:
    """Phần log ghi sau `offset` (tính theo byte, như `st_size`); file không đọc được thì rỗng."""
    try:
        return log_path.read_bytes()[offset:].decode("utf-8", errors="replace")
    except OSError:
        return ""


class ColmapProcess:
    """Mỗi invocation có output/exit record; không coi exit 0 là artifact success."""

    def __init__(self, settings: ColmapRuntimeSettings) -> None:
        if not settings.command or any(not item for item in settings.command):
            raise ValueError("COLMAP command must not be empty")
        self.settings = settings

    def run(self, arguments: list[str], workspace: Path) -> str:
        """Dùng argv và cwd, không shell interpolation; giữ failure evidence tại workspace."""
        start = time.monotonic()
        log_path = workspace / "process.log"
        log_offset = log_path.stat().st_size if log_path.exists() else 0
        with log_path.open("a") as log:
            log.write(json.dumps({"command": ["colmap", *arguments]}) + "\n")
            log.flush()
            try:
                returncode = _run_watched(
                    [*self.settings.command, *arguments],
                    workspace=workspace,
                    log=log,
                    settings=self.settings,
                    label=f"COLMAP {arguments[0]}",
                )
            except ProcessTimeoutError as error:
                log.write("\nCOLMAP_TIMEOUT\n")
                new_log = _log_since(log_path, log_offset)
                excerpt = redacted_excerpt(new_log, workspace)
                raise ColmapError(
                    "COLMAP_TIMEOUT",
                    "COLMAP exceeded configured timeout",
                    details={"log_excerpt": excerpt},
                ) from error
            except ProcessStalledError as error:
                log.write("\nPROCESS_STALLED\n")
                new_log = _log_since(log_path, log_offset)
                excerpt = redacted_excerpt(new_log, workspace)
                raise ColmapError(
                    "PROCESS_STALLED",
                    f"{error} Tiến trình đã được dừng; thử lại thường chạy được. Nếu scene rất lớn, tăng R2S_COLMAP_STALL_SECONDS.",
                    details={"log_excerpt": excerpt, "stall_seconds": self.settings.stall_seconds},
                ) from error
            except OSError as error:
                log.write("\nCOLMAP_UNAVAILABLE\n")
                raise ColmapError("COLMAP_UNAVAILABLE", "Cannot start configured COLMAP runtime") from error
            log.write(json.dumps({"returncode": returncode, "elapsed_seconds": time.monotonic() - start}) + "\n")
        if returncode:
            new_log = _log_since(log_path, log_offset)
            excerpt = redacted_excerpt(new_log, workspace)
            if returncode in {-9, 137} or "std::bad_alloc" in new_log:
                raise ColmapError(
                    "COLMAP_OUT_OF_MEMORY",
                    "COLMAP ran out of memory (OOM)",
                    details={"log_excerpt": excerpt},
                )
            raise ColmapError(
                "COLMAP_PROCESS_FAILED",
                f"COLMAP {arguments[0]} failed (exit {returncode})",
                details={"log_excerpt": excerpt},
            )
        return log_path.read_text()

    def capabilities(self, workspace: Path, matching_mode: str = "sequential") -> tuple[str, str, str]:
        """Probe actual CLI flags để không áp flag của checkout lên binary version khác."""
        output = self.run(["-h"], workspace)
        version = next((line.strip() for line in output.splitlines() if line.startswith("COLMAP ")), "")
        if not version:
            raise ColmapError("COLMAP_VERSION_UNKNOWN", "COLMAP help did not report a version")
        extraction = self.run(["feature_extractor", "-h"], workspace)
        matcher = "exhaustive_matcher" if matching_mode == "exhaustive" else "sequential_matcher"
        matching = self.run([matcher, "-h"], workspace)
        feature = "FeatureExtraction" if "--FeatureExtraction.use_gpu" in extraction else "SiftExtraction"
        match = "FeatureMatching" if "--FeatureMatching.use_gpu" in matching else "SiftMatching"
        if f"--{feature}.use_gpu" not in extraction or f"--{match}.use_gpu" not in matching:
            raise ColmapError("COLMAP_CLI_UNSUPPORTED", "COLMAP runtime lacks supported CPU/GPU controls")
        if matching_mode == "sequential_vocab_tree":
            required = (
                "loop_detection",
                "vocab_tree_path",
                "loop_detection_period",
                "loop_detection_num_images",
                "loop_detection_min_index_distance",
            )
            if any(f"--SequentialMatching.{flag}" not in matching for flag in required):
                raise ColmapError("COLMAP_CLI_UNSUPPORTED", "COLMAP runtime lacks vocabulary loop controls")
        return version, feature, match


def reconstruction_commands(config: ColmapConfig, flags: tuple[str, str]) -> list[list[str]]:
    """Chuỗi Re3Sim/Nannigalaxy qua CLI; vocabulary tùy chọn đã verify trước."""
    feature, match = flags
    return [_extraction_command(config, feature), _matching_command(config, match), mapper_command(config)]


def mapper_command(config: ColmapConfig, output: str = "sparse") -> list[str]:
    """`mapper` trên database.db hiện có; thang thử lại ghi mỗi bậc vào thư mục riêng."""
    mapper = ["mapper", "--database_path", "database.db", "--image_path", "images", "--output_path", output]
    return mapper + ["--Mapper.num_threads", str(config.num_threads), "--Mapper.random_seed", str(config.random_seed)]


def retry_matching_command(config: ColmapConfig, match: str, *, overlap: int | None, loop_detection: bool) -> list[str]:
    """Lệnh ghép ảnh của một bậc thử lại; `overlap=None` là ghép mọi cặp.

    Chạy trên cùng database.db: cặp đã ghép được bỏ qua, chỉ cặp mới được thêm vào.
    """
    if overlap is None:
        return _matching_command(config.model_copy(update={"matching_mode": "exhaustive"}), match)
    return _matching_command(config, match, overlap=overlap, loop_detection=loop_detection)


def _extraction_command(config: ColmapConfig, feature: str) -> list[str]:
    extraction = [
        "feature_extractor",
        "--database_path",
        "database.db",
        "--image_path",
        "images",
        "--ImageReader.camera_model",
        config.camera_model,
        "--ImageReader.single_camera",
        str(int(config.single_camera)),
        f"--{feature}.use_gpu",
        str(int(config.use_gpu)),
        f"--{feature}.num_threads",
        str(config.num_threads),
        "--SiftExtraction.max_num_features",
        str(config.max_num_features),
    ]
    size_flag = "FeatureExtraction" if feature == "FeatureExtraction" else "SiftExtraction"
    extraction += [f"--{size_flag}.max_image_size", str(config.max_image_size)]
    return extraction


def _matching_command(
    config: ColmapConfig, match: str, *, overlap: int | None = None, loop_detection: bool | None = None
) -> list[str]:
    """Lệnh ghép theo config; bậc thử lại truyền `overlap` và `loop_detection` tường minh."""
    loop = config.matching_mode == "sequential_vocab_tree" if loop_detection is None else loop_detection
    matching = [
        "exhaustive_matcher" if config.matching_mode == "exhaustive" else "sequential_matcher",
        "--database_path",
        "database.db",
        f"--{match}.use_gpu",
        str(int(config.use_gpu)),
        f"--{match}.num_threads",
        str(config.num_threads),
    ]
    if config.matching_mode == "exhaustive":
        return matching
    matching += [
        "--SequentialMatching.overlap",
        str(config.sequential_overlap if overlap is None else overlap),
        "--SequentialMatching.loop_detection",
        str(int(loop)),
    ]
    if loop:
        matching += [
            "--SequentialMatching.vocab_tree_path",
            "vocab_tree.bin",
            "--SequentialMatching.loop_detection_period",
            str(config.loop_detection_period),
            "--SequentialMatching.loop_detection_num_images",
            str(config.loop_detection_num_images),
            "--SequentialMatching.loop_detection_min_index_distance",
            str(config.loop_detection_min_index_distance),
        ]
    return matching
