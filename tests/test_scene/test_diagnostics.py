"""Evidence limits and exact source identity do not participate in inference."""

import hashlib
import json
import zlib

from src.services.scene.diagnostics import EvidenceRecorder


def test_bounded_events_leave_explicit_coverage_and_complete_json_lines(tmp_path):
    trace = EvidenceRecorder(tmp_path, "sam", event_budget=150)
    for i in range(20):
        trace.emit("mask", record=i, reason="low_score")
    lines = (tmp_path / "sam.jsonl").read_text().splitlines()
    assert all(json.loads(line)["kind"] == "mask" for line in lines)
    coverage = json.loads((tmp_path / "sam.coverage.json").read_text())
    assert coverage["events_dropped"] == 20 - len(lines) > 0
    assert coverage["event_bytes"] <= 150
    assert coverage["event_counts"] == {"mask": 20}
    assert coverage["reason_counts"] == {"low_score": 20}


def test_lossless_masks_are_content_addressed_and_budget_is_reported(tmp_path):
    trace = EvidenceRecorder(tmp_path, "sam", mask_budget=20)
    payload = b"\x8f" * 100
    trace.mask("view:0/prompt:9", payload, (10, 80))
    sample = json.loads((tmp_path / "sam.jsonl").read_text())
    assert zlib.decompress((tmp_path / sample["file"]).read_bytes()) == payload
    assert sample["packed_checksum"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    trace.mask("view:1/prompt:9", bytes(range(100)), (10, 80))
    missing = json.loads((tmp_path / "sam.jsonl").read_text().splitlines()[-1])
    assert missing["file"] is None and missing["omitted_reason"] == "mask_budget"
    assert json.loads((tmp_path / "sam.coverage.json").read_text())["masks_dropped"] == 1


def test_disabled_recorder_creates_no_files(tmp_path):
    trace = EvidenceRecorder(None, "sam")
    trace.emit("ignored", count=9)
    trace.mask("ignored", b"bits", (2, 2))
    assert not list(tmp_path.iterdir())


def test_nonfinite_observation_does_not_interrupt_the_algorithm(tmp_path):
    trace = EvidenceRecorder(tmp_path, "sam")
    trace.emit("mask", score=float("nan"))
    assert json.loads((tmp_path / "sam.jsonl").read_text())["score"] == "nonfinite"


def test_mask_sample_count_has_a_hard_limit(tmp_path):
    trace = EvidenceRecorder(tmp_path, "sam")
    for index in range(40):
        trace.mask(str(index), bytes([index]), (1, 8))
    assert len(list(tmp_path.glob("*.bits.zlib"))) == 32
    assert json.loads((tmp_path / "sam.coverage.json").read_text())["masks_dropped"] == 8


def test_write_failure_does_not_replace_pipeline_result(tmp_path, monkeypatch):
    trace = EvidenceRecorder(tmp_path, "sam")

    def unavailable(*args, **kwargs):
        raise OSError("full disk")

    monkeypatch.setattr(type(tmp_path), "open", unavailable)
    trace.emit("mask", reason="low_score")
    assert trace.directory is None
