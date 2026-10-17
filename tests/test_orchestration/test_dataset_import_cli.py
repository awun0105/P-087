from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.datasets import import_image_scene
from scripts.datasets.import_image_scene import ordered_images, preset_for_scene


def test_ordered_images_accepts_jpeg_png_and_ignores_case(tmp_path: Path) -> None:
    for name in ("b.JPG", "a.png", "c.jpeg"):
        (tmp_path / name).write_bytes(name.encode())
    assert [path.name for path in ordered_images(tmp_path)] == ["a.png", "b.JPG", "c.jpeg"]


@pytest.mark.parametrize("sidecar", ("sparse", "poses_bounds.npy"))
def test_ordered_images_rejects_dataset_sidecars_in_input_directory(tmp_path: Path, sidecar: str) -> None:
    (tmp_path / "000.jpg").write_bytes(b"first")
    (tmp_path / "001.jpg").write_bytes(b"second")
    (tmp_path / sidecar).mkdir() if sidecar == "sparse" else (tmp_path / sidecar).write_bytes(b"forbidden")
    with pytest.raises(ValueError, match="sidecars are forbidden"):
        ordered_images(tmp_path)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("drjohnson", "photo_collection_indoor"),
        ("bonsai", "photo_collection_indoor"),
        ("bicycle", "photo_collection_outdoor"),
        ("garden", "photo_collection_outdoor"),
        ("stump", "photo_collection_outdoor"),
    ],
)
def test_scene_uses_planned_processing_preset(name: str, expected: str) -> None:
    assert preset_for_scene(name) == expected


def test_import_cli_uses_actor_factory_from_auth_models(tmp_path: Path, monkeypatch, capsys) -> None:
    from src.api import auth
    from src.services.orchestration import processing
    from src.services.orchestration.projects import dataset_video, registry

    images = tmp_path / "images"
    images.mkdir()
    (images / "one.jpg").write_bytes(b"one")
    (images / "two.png").write_bytes(b"two")
    video = tmp_path / "scene.mp4"
    user = SimpleNamespace(role="reviewer", user_id="reviewer-id", display_name="Reviewer")
    monkeypatch.setenv("R2S_REVIEWER_EMAIL", "reviewer@example.test")
    monkeypatch.setenv("R2S_REVIEWER_PASSWORD", "test-only-password")
    monkeypatch.setattr(auth, "auth_service", lambda: SimpleNamespace(login=lambda *_: (None, user)))
    monkeypatch.setattr(
        dataset_video,
        "compose_display_video",
        lambda ordered, output: (output.write_bytes(b"video"), len(ordered))[1],
    )
    monkeypatch.setattr(processing, "load_presets", lambda *_: ({}, "checksum"))
    monkeypatch.setattr(processing, "preset_values", lambda *_: {})
    monkeypatch.setattr(processing, "build_job_config", lambda *_: object())
    monkeypatch.setattr(
        registry,
        "get_project_registry",
        lambda: SimpleNamespace(
            create_project_from_dataset_images=lambda **_: SimpleNamespace(project_id="project-test"),
            create_job=lambda *_args, **_kwargs: SimpleNamespace(job_id="job-test"),
        ),
    )

    result = import_image_scene.main(
        ["--images", str(images), "--name", "drjohnson", "--dataset-owner", "Deep Blending", "--video", str(video)]
    )

    assert result == 0
    assert "job_id=job-test image_count=2 video_frames=2" in capsys.readouterr().out
