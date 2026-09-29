"""REC-09: fit đồng dạng Umeyama khôi phục đúng phép biến đổi đã biết."""

import math

import numpy as np
import pytest

from src.services.reconstruction.alignment.similarity import fit_similarity
from src.services.reconstruction.rgb.canonical.metric_math import rotate

ROTATION = (0.2, -0.4, 0.3, math.sqrt(1 - 0.04 - 0.16 - 0.09))
SCALE, OFFSET = 2.7, (4.0, -1.5, 0.25)


def _transform(point: tuple[float, float, float]) -> tuple[float, float, float]:
    rotated = rotate(point, ROTATION)
    return tuple(SCALE * value + offset for value, offset in zip(rotated, OFFSET, strict=True))  # type: ignore[return-value]


def _trajectory(count: int = 40) -> list[tuple[float, float, float]]:
    return [(0.3 * i, math.sin(i / 5), 0.1 * math.cos(i / 3)) for i in range(count)]


def test_recovers_known_similarity_exactly() -> None:
    source = _trajectory()
    fit = fit_similarity(source, [_transform(point) for point in source])
    assert fit.scale == pytest.approx(SCALE)
    assert fit.rms_residual == pytest.approx(0.0, abs=1e-9)
    probe = (1.0, -2.0, 0.5)
    assert fit.apply(probe) == pytest.approx(_transform(probe))


def test_reports_noise_as_residual() -> None:
    source = _trajectory(200)
    noise = np.random.default_rng(7).normal(0, 0.01, (len(source), 3))
    target = [tuple(np.asarray(_transform(p)) + n) for p, n in zip(source, noise, strict=True)]
    fit = fit_similarity(source, target)  # type: ignore[arg-type]
    assert fit.scale == pytest.approx(SCALE, rel=1e-2)
    assert 0.01 < fit.rms_residual < 0.03 and fit.max_residual >= fit.rms_residual


def test_rejects_degenerate_input() -> None:
    line = [(float(i), 0.0, 0.0) for i in range(5)]
    with pytest.raises(ValueError, match="thẳng hàng"):
        fit_similarity(line, [_transform(point) for point in line])
    with pytest.raises(ValueError, match="ít nhất"):
        fit_similarity(line[:2], line[:2])
    with pytest.raises(ValueError, match="bằng nhau"):
        fit_similarity(line, line[:4])
