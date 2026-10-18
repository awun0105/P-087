"""LPIPS pairs every held-out render with its unchanged source image."""

import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.services.reconstruction.adapters import lpips_runner


@pytest.fixture
def metric(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    inputs: list[Path] = []

    def tensor(path: Path, size: tuple[int, int] | None = None) -> SimpleNamespace:
        inputs.append(path)
        return SimpleNamespace(to=lambda device: path)

    model = SimpleNamespace(
        to=lambda device: SimpleNamespace(eval=lambda: lambda a, b: SimpleNamespace(item=lambda: 0.25))
    )
    monkeypatch.setitem(sys.modules, "lpips", SimpleNamespace(LPIPS=lambda **kwargs: model))
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), no_grad=nullcontext)
    )
    monkeypatch.setattr(lpips_runner, "_tensor", tensor)
    return inputs


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg", ".JPG", ".JPEG", ".PNG"])
def test_scores_all_views_without_changing_source_bytes(tmp_path: Path, metric: list[Path], suffix: str) -> None:
    renders, gt = tmp_path / "renders", tmp_path / "gt"
    renders.mkdir()
    gt.mkdir()
    for name in ["000000", "000008"]:
        Image.new("RGB", (4, 4)).save(renders / f"{name}.png")
        Image.new("RGB", (8, 8)).save(gt / f"{name}{suffix}")
    before = {p.name: p.read_bytes() for p in gt.iterdir()}
    result = lpips_runner.score(renders, gt, "vgg")
    assert result == {"net": "vgg", "count": 2, "lpips": 0.25, "per_view": {"000000": 0.25, "000008": 0.25}}
    assert metric[1::2] == [gt / f"{name}{suffix}" for name in ["000000", "000008"]]
    assert {p.name: p.read_bytes() for p in gt.iterdir()} == before


@pytest.mark.parametrize("source_names", [[], ["000000.jpg", "000000.png"]])
def test_rejects_missing_or_ambiguous_source(tmp_path: Path, metric: list[Path], source_names: list[str]) -> None:
    renders, gt = tmp_path / "renders", tmp_path / "gt"
    renders.mkdir()
    gt.mkdir()
    for name in ["000000", "000008"]:
        Image.new("RGB", (4, 4)).save(renders / f"{name}.png")
    for name in [*source_names, "000008.jpg"]:
        Image.new("RGB", (4, 4)).save(gt / name)
    with pytest.raises(ValueError, match="000000"):
        lpips_runner.score(renders, gt, "vgg")
    assert metric == []
