#!/usr/bin/env python3
"""Create one DATASET project/job from a composed MP4 and its original pre-extracted images."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ordered_images(directory: Path) -> tuple[Path, ...]:
    """Read only direct JPG/JPEG/PNG children; reject COLMAP/NeRF sidecars in the input folder."""
    if not directory.is_dir():
        raise ValueError(f"image directory does not exist: {directory}")
    names = {item.name.lower() for item in directory.iterdir()}
    if "sparse" in names or "poses_bounds.npy" in names:
        raise ValueError("pass the dataset images directory only; COLMAP/NeRF sidecars are forbidden")
    entries = tuple(directory.iterdir())
    if any(item.is_dir() for item in entries):
        raise ValueError("image input must be a flat directory of JPG/JPEG/PNG files")
    images = tuple(
        sorted(
            (item for item in entries if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png"}),
            key=lambda item: item.name.casefold(),
        )
    )
    if len(images) < 2 or len(images) != len(entries):
        raise ValueError("image directory must contain only at least two JPG/JPEG/PNG files")
    return images


def preset_for_scene(name: str) -> str:
    """Select the task's indoor, single-object, or outdoor capture preset."""
    key = name.strip().lower()
    if key in {"drjohnson", "playroom", "bonsai", "counter", "kitchen", "room"}:
        return "video_indoor_walkthrough"
    if key == "bicycle":
        return "video_single_object"
    if key in {"garden", "stump"}:
        return "video_outdoor_forward"
    raise ValueError(f"no T-045 capture preset is defined for scene: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--dataset-owner", required=True)
    parser.add_argument(
        "--video", required=True, type=Path, help="output MP4 path submitted with the pre-extracted images"
    )
    args = parser.parse_args(argv)
    try:
        from src.api.auth import auth_service
        from src.services.orchestration.auth.models import actor_of
        from src.services.orchestration.processing import build_job_config, load_presets, preset_values
        from src.services.orchestration.projects.dataset_video import compose_display_video
        from src.services.orchestration.projects.models import JobCreateInput
        from src.services.orchestration.projects.registry import get_project_registry

        images = ordered_images(args.images)
        frames = compose_display_video(images, args.video)
        email = os.environ["R2S_REVIEWER_EMAIL"]
        password = os.environ["R2S_REVIEWER_PASSWORD"]
        _, user = auth_service().login(email, password)
        if user.role != "reviewer":
            raise PermissionError("configured local account is not a Reviewer")
        registry = get_project_registry()
        project = registry.create_project_from_dataset_images(
            name=args.name,
            dataset_owner=args.dataset_owner,
            images=images,
            display_video=args.video,
            created_by=actor_of(user),
        )
        presets, checksum = load_presets(ROOT / "configs/product/processing_presets_v1.json")
        config = build_job_config(presets, checksum, preset_values(presets, preset_for_scene(args.name)), None)
        job = registry.create_job(
            JobCreateInput(project_id=project.project_id),
            config,
            requested_by=actor_of(user),
            owner_user_id=user.user_id,
        )
        print(f"project_id={project.project_id} job_id={job.job_id} image_count={len(images)} video_frames={frames}")
        return 0
    except (KeyError, OSError, ValueError, RuntimeError, PermissionError) as error:
        print(f"dataset import failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
