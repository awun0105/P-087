"""Full Gaussian similarity: native codec proof riêng với fixture orchestration."""

import json
import math
import os
import struct
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.gaussian_scale import (
    GaussianTransformRequest,
    SplatTransformSimilarityAdapter,
)
from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, VoxelRuntimeSettings
from src.services.reconstruction.lidar.cloud_header import read_header
from src.services.reconstruction.rgb.canonical.metric_math import SimilarityTransform
from src.services.reconstruction.rgb.frames.frame_set import _sha256
from tests.test_reconstruction.test_rec04_brush import gaussian_ply
from tests.test_reconstruction.test_rec05_adapter import FixtureProcess


def _transform(scale: float = 2) -> SimilarityTransform:
    return SimilarityTransform(
        scale_m_per_sfm_unit=scale,
        rotation_xyzw=(math.sqrt(0.5), 0, 0, math.sqrt(0.5)),
        translation_m=(1, -2, 4),
    )


def _request(source: Path, scale: float = 2) -> GaussianTransformRequest:
    return GaussianTransformRequest(source=source, source_checksum=_sha256(source), transform=_transform(scale))


def _native() -> SplatTransformSimilarityAdapter:
    module = os.environ.get("REC05_TEST_SPLAT_MODULE")
    if not module:
        pytest.skip("REC05_TEST_SPLAT_MODULE chưa được cấu hình")
    settings = VoxelRuntimeSettings(cli=Path("unused"), module_path=Path(module))
    return SplatTransformSimilarityAdapter(VoxelProcess(settings))


def _rows(path: Path) -> list[dict[str, float]]:
    with path.open("rb") as stream:
        header = read_header(stream)
        assert header.encoding == "binary_little_endian"
        data = stream.read()
    layout = struct.Struct("<" + "".join(header.codes))
    return [dict(zip(header.fields, row, strict=True)) for row in layout.iter_unpack(data)]


def test_checksum_and_attempt_guards(tmp_path: Path) -> None:
    source = tmp_path / "source.ply"
    gaussian_ply(source)
    settings = VoxelRuntimeSettings(cli=Path("unused"), module_path=Path("unused"))
    adapter = SplatTransformSimilarityAdapter(FixtureProcess(settings))
    request = _request(source)
    receipt = adapter.transform(request, tmp_path / "attempt")
    assert receipt.transform == request.transform
    assert _sha256(source) == request.source_checksum
    evidence = json.loads((tmp_path / "attempt/metric-derivative.json").read_text())
    assert evidence["source_checksum"] == request.source_checksum
    with pytest.raises(FileExistsError):
        adapter.transform(request, tmp_path / "attempt")
    source.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        adapter.transform(request, tmp_path / "next")
    assert not (tmp_path / "next").exists()


@pytest.mark.parametrize("scale", [1, 2, 0.5])
def test_native_full_similarity(tmp_path: Path, scale: float) -> None:
    adapter = _native()
    source = tmp_path / "source.ply"
    gaussian_ply(source)
    request = _request(source, scale)
    receipt = adapter.transform(request, tmp_path / "metric")
    before, after = _rows(source), _rows(tmp_path / "metric/input.ply")
    assert len(before) == len(after) == receipt.num_gaussians == 256
    for original, actual in zip(before, after, strict=True):
        expected = request.transform.apply_point(tuple(original[k] for k in ("x", "y", "z")))
        assert tuple(actual[k] for k in ("x", "y", "z")) == pytest.approx(expected, abs=2e-6)
        for axis in range(3):
            assert actual[f"scale_{axis}"] == pytest.approx(original[f"scale_{axis}"] + math.log(scale), abs=2e-6)
        q = (actual["rot_1"], actual["rot_2"], actual["rot_3"], actual["rot_0"])
        dot = sum(a * b for a, b in zip(q, request.transform.rotation_xyzw, strict=True))
        assert abs(dot) == pytest.approx(1, abs=1e-6)
        assert actual["opacity"] == original["opacity"]
    assert _sha256(source) == request.source_checksum


@pytest.mark.parametrize("mode", ["plain", "nan", "quaternion", "truncated"])
def test_native_invalid_input_cannot_silently_copy(tmp_path: Path, mode: str) -> None:
    adapter = _native()
    source = tmp_path / "source.ply"
    gaussian_ply(source, mode)
    with pytest.raises(GeometryError):
        adapter.transform(_request(source), tmp_path / "metric")
    assert not (tmp_path / "metric/metric-derivative.json").exists()


def _add_sh(path: Path) -> None:
    rows = _rows(path)
    fields = [*rows[0], *(f"f_rest_{i}" for i in range(9))]
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {len(rows)}\n"
    header += "".join(f"property float {key}\n" for key in fields) + "end_header\n"
    body = b"".join(struct.pack("<23f", *row.values(), *range(1, 10)) for row in rows)
    path.write_bytes(header.encode() + body)


def test_native_sh_rotation_matches_degree_one_basis(tmp_path: Path) -> None:
    adapter = _native()
    source = tmp_path / "source.ply"
    gaussian_ply(source)
    _add_sh(source)
    receipt = adapter.transform(_request(source, 1), tmp_path / "metric")
    assert receipt.sh_bands == 1
    actual = _rows(tmp_path / "metric/input.ply")[0]
    # SH l=1 basis [-y,z,-x], active Rx(90): [a,b,c] → [b,-a,c] per RGB channel.
    assert [actual[f"f_rest_{i}"] for i in range(9)] == pytest.approx([2, -1, 3, 5, -4, 6, 8, -7, 9], abs=1e-5)
