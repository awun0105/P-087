"""ObjectGS build: observations are immutable, masks follow current labels, and failures never fall back silently."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import numpy as np
import pytest

from src.services.orchestration.scene.objectgs_observations import package_observations, unpack_observations


def view(root: Path, index: int, width: int = 16, height: int = 12) -> dict:
    image = root / f"frame-{index}.png"
    mask = root / f"mask-{index}.npy"
    image.write_bytes(b"png-%d" % index)
    np.save(mask, np.full((height, width), index, dtype=np.int32), allow_pickle=False)
    return {
        "image_path": str(image),
        "mask_path": str(mask),
        "width": width,
        "height": height,
        "center": [0.0, 0.0, 1.0],
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "parameters": [10.0, 10.0, 8.0, 6.0],
        "camera_model": "PINHOLE",
        "coordinate_frame": "world",
        "distance_unit": "m",
    }


def test_package_is_byte_stable_and_round_trips_views_in_order(tmp_path: Path) -> None:
    views = [view(tmp_path, 0), view(tmp_path, 1)]
    payload = package_observations(views)
    assert package_observations(views) == payload
    restored = unpack_observations(payload, tmp_path / "restored")
    assert [Path(item["image_path"]).read_bytes() for item in restored] == [b"png-0", b"png-1"]
    assert int(np.load(restored[1]["mask_path"], allow_pickle=False).max()) == 1
    assert restored[0]["model"] == "PINHOLE"
    assert restored[0]["parameters"] == [10.0, 10.0, 8.0, 6.0]


def test_empty_observation_list_is_a_valid_package(tmp_path: Path) -> None:
    assert unpack_observations(package_observations([]), tmp_path / "empty") == []


def test_undeclared_or_escaping_members_are_rejected(tmp_path: Path) -> None:
    payload = package_observations([view(tmp_path, 0)])
    tampered = io.BytesIO()
    with tarfile.open(fileobj=tampered, mode="w") as archive:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as source:
            for member in source.getmembers():
                archive.addfile(member, source.extractfile(member))
        extra = tarfile.TarInfo("../escape.txt")
        extra.size = 1
        archive.addfile(extra, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        unpack_observations(tampered.getvalue(), tmp_path / "restored")
