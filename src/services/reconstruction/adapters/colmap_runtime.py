"""COLMAP CLI process boundary: capability, timeout, exit code và log evidence."""

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId, StageStatus
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig


class ColmapRuntimeSettings(BaseSettings):
    """Composition root inject executable/container launcher; không lưu path vào artifact."""

    command: tuple[str, ...] = ("colmap",)
    runtime_identity: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, default=1800, allow_inf_nan=False)
    model_config = SettingsConfigDict(env_prefix="REC03_COLMAP_", extra="forbid")


class ColmapError(ValueError):
    """Lỗi có remediation, không serialize private process path/stderr ra UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_failed_stage(self) -> StageArtifact:
        """Worker ghi failed stage với log riêng của attempt để điều tra."""
        error = ExecutionError(
            error_code=self.code,
            stage_id=StageId.CAMERA_POSE,
            human_message=str(self),
            retryable=True,
            details={"action": "Inspect attempt logs, input overlap and COLMAP runtime; retry with a new attempt"},
        )
        return StageArtifact(
            stage_id=StageId.CAMERA_POSE, status=StageStatus.FAILED, completed_at=datetime.now(UTC), error=error
        )


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
                raise ColmapError("COLMAP_TIMEOUT", "COLMAP exceeded configured timeout") from error
            except OSError as error:
                log.write("\nCOLMAP_UNAVAILABLE\n")
                raise ColmapError("COLMAP_UNAVAILABLE", "Cannot start configured COLMAP runtime") from error
            log.write(json.dumps({"returncode": result.returncode, "elapsed_seconds": time.monotonic() - start}) + "\n")
        if result.returncode:
            raise ColmapError("COLMAP_PROCESS_FAILED", f"COLMAP {arguments[0]} failed (exit {result.returncode})")
        return log_path.read_text()

    def capabilities(self, workspace: Path) -> tuple[str, str, str]:
        """Probe actual CLI flags để không áp flag của checkout lên binary version khác."""
        output = self.run(["-h"], workspace)
        version = next((line.strip() for line in output.splitlines() if line.startswith("COLMAP ")), "")
        if not version:
            raise ColmapError("COLMAP_VERSION_UNKNOWN", "COLMAP help did not report a version")
        extraction = self.run(["feature_extractor", "-h"], workspace)
        matching = self.run(["sequential_matcher", "-h"], workspace)
        feature = "FeatureExtraction" if "--FeatureExtraction.use_gpu" in extraction else "SiftExtraction"
        match = "FeatureMatching" if "--FeatureMatching.use_gpu" in matching else "SiftMatching"
        if f"--{feature}.use_gpu" not in extraction or f"--{match}.use_gpu" not in matching:
            raise ColmapError("COLMAP_CLI_UNSUPPORTED", "COLMAP runtime lacks supported CPU/GPU controls")
        return version, feature, match


def reconstruction_commands(config: ColmapConfig, flags: tuple[str, str]) -> list[list[str]]:
    """Chuỗi Re3Sim/Nannigalaxy qua CLI; vocabulary tùy chọn đã verify trước."""
    feature, match = flags
    mapper = ["mapper", "--database_path", "database.db", "--image_path", "images", "--output_path", "sparse"]
    mapper += ["--Mapper.num_threads", str(config.num_threads), "--random_seed", str(config.random_seed)]
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
        "sequential_matcher",
        "--database_path",
        "database.db",
        f"--{match}.use_gpu",
        str(int(config.use_gpu)),
        f"--{match}.num_threads",
        str(config.num_threads),
        "--SequentialMatching.overlap",
        str(config.sequential_overlap),
        "--SequentialMatching.loop_detection",
        str(int(config.vocab_tree is not None)),
    ]
    if config.vocab_tree is not None:
        matching += ["--SequentialMatching.vocab_tree_path", "vocab_tree.bin"]
    return matching
