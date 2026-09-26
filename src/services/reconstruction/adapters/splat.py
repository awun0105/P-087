"""Reuse splat-transform 3.6.6 public API qua Node process, không vendor parser/codec."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.services.reconstruction.adapters.brush_runtime import Invocation, VisualProcess
from src.services.reconstruction.rgb.frame_set import _sha256
from src.services.reconstruction.rgb.visual import SplatInspection


class SplatRuntimeSettings(BaseSettings):
    """Path module deployment-supplied; npm dependency ở runtime riêng."""

    module_path: Path
    node_command: tuple[str, ...] = ("node",)
    model_config = SettingsConfigDict(env_prefix="REC04_SPLAT_", extra="forbid")


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
        arguments = (str(bridge), str(self.settings.module_path.resolve()), str(iterations))
        self.process.run(Invocation("splat-process", self.settings.node_command, arguments), workspace)
        if before != _sha256(master):
            raise ValueError("splat processor mutated immutable Brush master")
        return SplatInspection.model_validate_json((workspace / "output" / "inspection.json").read_text())
