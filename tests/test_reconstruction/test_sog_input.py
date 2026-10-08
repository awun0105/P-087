"""SOG upload classification is content-based, bounded and version-gated."""

import io
import zipfile

import pytest

from src.services.reconstruction.inputs.detect import InputRejectedError, detect_stream, validate_sog_bundle
from tests.test_reconstruction.support.sog_fixtures import sog_archive


def _detect(payload: bytes):
    return detect_stream(io.BytesIO(payload), len(payload), 16 * 1024 * 1024)


def _webp(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    data = b"\x2f" + bits.to_bytes(4, "little")
    return b"RIFF\x12\x00\x00\x00WEBPVP8L\x05\x00\x00\x00" + data + b"\x00"


def _replace_texture(payload: bytes, name: str, texture: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as original, zipfile.ZipFile(output, "w") as archive:
        for info in original.infolist():
            archive.writestr(info.filename, texture if info.filename == name else original.read(info.filename))
    return output.getvalue()


def test_sog_v2_reports_source_model_count_and_sh_degree() -> None:
    detection = _detect(sog_archive(model="antialiased", sh_bands=3, count=17))

    assert detection.kind == "gaussian_sog"
    assert detection.sog is not None
    assert detection.sog.format_version == 2
    assert detection.sog.model == "antialiased"
    assert detection.sog.gaussian_count == 17
    assert detection.sog.sh_degree == 3


def test_sog_worker_validation_checks_every_webp_header_and_pixel_budget(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "scene.sog"
    path.write_bytes(sog_archive(count=4))
    valid = validate_sog_bundle(path, 16 * 1024 * 1024)
    assert valid.sog is not None and valid.sog.gaussian_count == 4

    path.write_bytes(_replace_texture(sog_archive(count=4), "means_l.webp", _webp(2000, 2000)))
    with pytest.raises(InputRejectedError, match="Kích thước hoặc số kênh"):
        validate_sog_bundle(path, 16 * 1024 * 1024)


def test_sog_worker_validation_rejects_truncated_webp_container(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "scene.sog"
    path.write_bytes(_replace_texture(sog_archive(), "means_l.webp", b"RIFF\x04\x00\x00\x00WEBPX"))
    with pytest.raises(InputRejectedError, match="không phải WebP hoàn chỉnh"):
        validate_sog_bundle(path, 16 * 1024 * 1024)


def test_sog_rejects_hidden_extra_archive_members() -> None:
    source = sog_archive()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(output, "w") as archive:
        for info in original.infolist():
            archive.writestr(info.filename, original.read(info.filename))
        archive.writestr(".DS_Store", b"unreferenced metadata")

    with pytest.raises(InputRejectedError, match="file ngoài gói"):
        _detect(output.getvalue())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (sog_archive(version=1), "version 2"),
        (sog_archive(version=3), "version 2"),
        (sog_archive(model="dynamic"), "Model SOG không được hỗ trợ"),
        (sog_archive(count=25_000_001), "Số Gaussian"),
        (sog_archive(means_mins=(2.0, -1.0, -1.0)), "mins không được vượt"),
    ],
)
def test_sog_unsupported_version_model_and_count_fail_closed(payload: bytes, message: str) -> None:
    with pytest.raises(InputRejectedError, match=message):
        _detect(payload)
