"""SOG upload classification is content-based, bounded and version-gated."""

import io
import zipfile

import pytest

from src.services.reconstruction.inputs.detect import InputRejectedError, detect_stream
from tests.test_reconstruction.support.sog_fixtures import sog_archive


def _detect(payload: bytes):
    return detect_stream(io.BytesIO(payload), len(payload), 16 * 1024 * 1024)


def test_sog_v2_reports_source_model_count_and_sh_degree() -> None:
    detection = _detect(sog_archive(model="antialiased", sh_bands=3, count=17))

    assert detection.kind == "gaussian_sog"
    assert detection.sog is not None
    assert detection.sog.format_version == 2
    assert detection.sog.model == "antialiased"
    assert detection.sog.gaussian_count == 17
    assert detection.sog.sh_degree == 3


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
