"""Render sample REC-04 bằng upstream GPU rasterizer, không phải browser QA.

Chạy sau rec04_smoke với cùng environment; REC04_PREVIEW_CLI trỏ pinned CLI.
Camera đầu tiên là registered training view; đây không là held-out evaluation.
"""

import hashlib
import json
import math
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.adapters.brush_runtime import Invocation
from src.services.reconstruction.rgb.camera_pose import CameraPose
from tests.test_reconstruction.smoke.rec04_smoke import SmokeSettings, dependencies


class PreviewSettings(BaseSettings):
    """Chọn GPU explicit cho rasterizer, runtime pin giống codec smoke."""

    cli: Path
    gpu: int = 0
    model_config = SettingsConfigDict(env_prefix="REC04_PREVIEW_", extra="forbid")


def view_vectors(pose: CameraPose) -> tuple[tuple[float, ...], ...]:
    """SfM camera (+Z forward, +Y down) → PlayCanvas qua Transform.PLY một lần."""
    x, y, z, w = pose.rotation_xyzw
    forward = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    up = (2 * (w * z - x * y), -(1 - 2 * (x * x + z * z)), -2 * (y * z + w * x))
    target = tuple(t + f for t, f in zip(pose.translation, forward, strict=True))
    return tuple(
        tuple(v * s for v, s in zip(vector, (-1, -1, 1), strict=True)) for vector in (pose.translation, target, up)
    )


def render(settings: SmokeSettings, preview: PreviewSettings) -> dict:
    """Consumer resolve/checksum trước render; master không bị sửa."""
    deps = dependencies(settings)
    receipt = json.loads((settings.output_root / "receipt.json").read_text())
    reference = ProductArtifactRef.model_validate(receipt["reference"])
    visual = deps.resolver.load(reference)
    poses = deps.resolver.poses.load(visual.source_camera_poses)
    pose = poses.poses[0]
    camera = next(c for c in poses.cameras if c.camera_id == pose.camera_id)
    fy = camera.parameters[1 if camera.model in {"PINHOLE", "OPENCV", "FULL_OPENCV"} else 0]
    fov = math.degrees(2 * math.atan(camera.height / (2 * fy)))
    args = [str(preview.cli.resolve()), str(deps.resolver.require(visual.delivery)), "--gpu", str(preview.gpu)]
    for flag, vector in zip(("--camera-pos", "--camera-target", "--camera-up"), view_vectors(pose), strict=True):
        args.extend([flag, ",".join(str(v) for v in vector)])
    args.extend(["--camera-fov", str(fov), "--resolution", "640x480", "output/preview.webp"])
    deps.process.run(Invocation("visual-preview", ("node",), tuple(args)), settings.workspace)
    image = (settings.workspace / "output/preview.webp").read_bytes()
    ref = deps.publisher.publish("preview.webp", image, "VisualPreview")
    return dict(
        source_visual=reference.model_dump(mode="json"),
        image=ref.model_dump(mode="json"),
        frame_id=pose.frame_id,
        camera_vectors=view_vectors(pose),
        fov_degrees=fov,
        checksum="sha256:" + hashlib.sha256(image).hexdigest(),
        qualification="training-view diagnostic; approximate undistorted FOV; not browser/held-out QA",
    )


def main() -> None:
    """Lưu receipt để sample luôn có source identity, không overwrite visual master."""
    settings = SmokeSettings()
    receipt = render(settings, PreviewSettings())
    (settings.output_root / "preview_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
