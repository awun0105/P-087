"""COLMAP CLI process boundary: capability, timeout, exit code và log evidence."""

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId, StageStatus
from src.models.contracts.retryability import classify_retryability
from src.services.reconstruction.adapters.log_excerpt import redacted_excerpt
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig


class ColmapRuntimeSettings(BaseSettings):
    """Composition root inject executable/container launcher; không lưu path vào artifact."""

    command: tuple[str, ...] = ("colmap",)
    runtime_identity: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, default=1800, allow_inf_nan=False)
    model_config = SettingsConfigDict(env_prefix="REC03_COLMAP_", extra="forbid")


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
                result = subprocess.run(
                    [*self.settings.command, *arguments],
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=self.settings.timeout_seconds,
                )
            except subprocess.TimeoutExpired as error:
                log.write("\nCOLMAP_TIMEOUT\n")
                new_log = _log_since(log_path, log_offset)
                excerpt = redacted_excerpt(new_log, workspace)
                raise ColmapError(
                    "COLMAP_TIMEOUT",
                    "COLMAP exceeded configured timeout",
                    details={"log_excerpt": excerpt},
                ) from error
            except OSError as error:
                log.write("\nCOLMAP_UNAVAILABLE\n")
                raise ColmapError("COLMAP_UNAVAILABLE", "Cannot start configured COLMAP runtime") from error
            log.write(json.dumps({"returncode": result.returncode, "elapsed_seconds": time.monotonic() - start}) + "\n")
        if result.returncode:
            new_log = _log_since(log_path, log_offset)
            excerpt = redacted_excerpt(new_log, workspace)
            if result.returncode in {-9, 137} or "std::bad_alloc" in new_log:
                raise ColmapError(
                    "COLMAP_OUT_OF_MEMORY",
                    "COLMAP ran out of memory (OOM)",
                    details={"log_excerpt": excerpt},
                )
            raise ColmapError(
                "COLMAP_PROCESS_FAILED",
                f"COLMAP {arguments[0]} failed (exit {result.returncode})",
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
    mapper = ["mapper", "--database_path", "database.db", "--image_path", "images", "--output_path", "sparse"]
    mapper += ["--Mapper.num_threads", str(config.num_threads), "--Mapper.random_seed", str(config.random_seed)]
    return [_extraction_command(config, feature), _matching_command(config, match), mapper]


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


def _matching_command(config: ColmapConfig, match: str) -> list[str]:
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
        str(config.sequential_overlap),
        "--SequentialMatching.loop_detection",
        str(int(config.matching_mode == "sequential_vocab_tree")),
    ]
    if config.matching_mode == "sequential_vocab_tree":
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
