from pathlib import Path

import pytest

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
        ("drjohnson", "video_indoor_walkthrough"),
        ("bonsai", "video_indoor_walkthrough"),
        ("bicycle", "video_single_object"),
        ("garden", "video_outdoor_forward"),
        ("stump", "video_outdoor_forward"),
    ],
)
def test_scene_uses_planned_processing_preset(name: str, expected: str) -> None:
    assert preset_for_scene(name) == expected
