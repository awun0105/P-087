"""Reuse splat-transform 3.6.6 public API qua Node process, không vendor parser/codec."""

from pathlib import Path
from typing import Literal

from pydantic_settings import SettingsConfigDict

from src.runtime_env import RuntimeSettings
from src.services.reconstruction.adapters.brush_runtime import Invocation, VisualProcess
from src.services.reconstruction.rgb.frames.frame_set import _sha256
from src.services.reconstruction.rgb.splat.visual import SplatInspection


class SplatRuntimeSettings(RuntimeSettings):
    """Path module deployment-supplied; npm dependency ở runtime riêng."""

    module_path: Path
    node_command: tuple[str, ...] = ("node",)
    #: Nén SOG bằng WebGPU (Dawn) nhanh hơn CPU 5–10× theo README upstream; không tạo
    #: được GPU device thì bridge tự lùi về CPU và ghi lại thiết bị thực tế.
    device: Literal["gpu", "cpu"] = "gpu"
    model_config = SettingsConfigDict(env_prefix="R2S_SPLAT_", extra="forbid")


class SplatArtifactProcessor:
    """Master bất biến; fail closed khi reader/stats/roundtrip không hợp lệ."""

    def __init__(self, settings: SplatRuntimeSettings, process: VisualProcess) -> None:
        self.settings = settings
        self.process = process

    def process_artifact(self, workspace: Path, iterations: int) -> SplatInspection:
        """Header inspection + streaming stats + SOG encode/decode dùng upstream."""
        master = workspace / "output" / "visual.ply"
        before = _sha256(master)
        bridge = Path(__file__).with_name("splat_bridge.mjs").resolve()
        arguments = (str(bridge), str(self.settings.module_path.resolve()), str(iterations), self.settings.device)
        self.process.run(Invocation("splat-process", self.settings.node_command, arguments), workspace)
        if before != _sha256(master):
            raise ValueError("splat processor mutated immutable Brush master")
        return SplatInspection.model_validate_json((workspace / "output" / "inspection.json").read_text())
