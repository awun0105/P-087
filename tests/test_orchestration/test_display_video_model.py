from pathlib import Path

from src.models.contracts.manifests import InputManifest
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.registry import ProjectRegistry


def test_dataset_project_keeps_composed_video_as_pipeline_input_and_replay_ref(tmp_path: Path) -> None:
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    images = (tmp_path / "one.jpg", tmp_path / "two.png")
    for path in images:
        path.write_bytes(path.name.encode())
    video = tmp_path / "replay.mp4"
    video.write_bytes(b"display-video")
    project = registry.create_project_from_dataset_images(
        name="scene",
        dataset_owner="dataset owner",
        images=images,
        display_video=video,
    )
    manifest = InputManifest.model_validate_json(
        registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    assert project.input_video is not None and project.display_video_ref is not None
    assert [item.media_type for item in manifest.files] == ["image/jpeg", "image/png", "video/mp4"]
    restored = ProjectRecord.model_validate_json(project.model_dump_json())
    assert restored.display_video_ref == project.display_video_ref
    assert restored.input_video == project.input_video
