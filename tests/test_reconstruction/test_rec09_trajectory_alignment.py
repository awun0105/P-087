"""REC-09 chuẩn bị dataset: ghép frame job ↔ ảnh dataset phải theo dãy đều, không đoán."""

from pathlib import Path

import numpy as np
import pytest

from scripts.torwic import align_sfm_to_world as tool


def _unit(rows: np.ndarray) -> np.ndarray:
    rows = rows - rows.mean(axis=1, keepdims=True)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def _setup(tmp_path: Path, job_ids: list[int], monkeypatch: pytest.MonkeyPatch, picks: list[int]) -> tuple[Path, Path]:
    frames, dataset = tmp_path / "frames", tmp_path / "image_left"
    frames.mkdir()
    dataset.mkdir()
    for frame_id in job_ids:
        (frames / f"{frame_id:06d}.png").write_bytes(b"")
    for index in range(60):
        (dataset / f"{index:06d}.png").write_bytes(b"")
    library = _unit(np.random.default_rng(3).normal(size=(60, 50)))
    job = library[picks] + 0.01 * np.random.default_rng(4).normal(size=(len(picks), 50))

    def fake(args: list[str], count: int | None = None) -> np.ndarray:
        return _unit(job) if "glob" in args else library

    monkeypatch.setattr(tool, "_thumbnails", fake)
    return frames, dataset


def test_matches_constant_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [0, 3, 7, 12, 20]
    frames, dataset = _setup(tmp_path, ids, monkeypatch, [i + 30 for i in ids])
    assert tool.match_frames(frames, dataset) == {i: i + 30 for i in ids}


def test_rejects_out_of_sequence_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [0, 3, 7, 12, 20]
    picks = [i + 30 for i in ids]
    picks[2] = 5  # một frame ghép nhầm sang đoạn khác của traversal
    frames, dataset = _setup(tmp_path, ids, monkeypatch, picks)
    with pytest.raises(ValueError, match="dãy đều"):
        tool.match_frames(frames, dataset)
