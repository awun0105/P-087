"""Legacy dataset frames retain exact image bytes and strict bundle ownership."""

from pathlib import Path

import pytest

from src.services.reconstruction.rgb.frames.bundle_frames import bundle_frame_references, publish_bundle_frames
from tests.test_reconstruction.support.rec06_bundle_metric_fixture import fixture


def legacy_frames(verifier, resolver, confirmation_ref):
    sources = verifier.sources
    confirmation = sources.load(verifier.canonicalizer.load(confirmation_ref).preview.request.source_visual)
    frames = sources.poses.frames.load(confirmation.source_frame_set)
    writer = verifier.canonicalizer.deps.writer
    legacy = []
    for frame in frames.frames:
        reference = frame.image.model_copy(
            update={
                "artifact_uri": f"artifact://jobs/project-source/input/{frame.frame_id}.png",
                "data_class": "product_input",
                "producer_stage": "ST-INPUT-VALIDATE",
            }
        )
        # Revalidate enum values after model_copy.
        reference = type(reference).model_validate(reference.model_dump())
        writer.publish(reference, resolver.require(frame.image).read_bytes())
        legacy.append(frame.model_copy(update={"image": reference}))
    return frames.model_copy(update={"frames": legacy}), confirmation.source_frame_set


def setup_legacy(tmp_path):
    (verifier, acceptance), request, resolver = fixture(tmp_path)
    frames, reference = legacy_frames(verifier, resolver, request.confirmation_ref)
    return verifier, request, resolver, frames, reference


def test_legacy_frames_publish_exact_copies_and_pass_inventory(tmp_path: Path, monkeypatch):
    verifier, request, resolver, frames, source_ref = setup_legacy(tmp_path)
    original_refs = [frame.image for frame in frames.frames]
    references = publish_bundle_frames(
        frames, "input", verifier.sources.poses.frames, verifier.canonicalizer.deps.writer
    )
    for original, copied in zip(original_refs, references, strict=True):
        assert copied.artifact_uri.startswith("artifact://jobs/input/")
        assert copied.artifact_checksum == original.artifact_checksum
        assert resolver.require(copied).read_bytes() == resolver.require(original).read_bytes()
    assert [frame.image for frame in frames.frames] == original_refs
    original_load = verifier.sources.poses.frames.load
    monkeypatch.setattr(
        verifier.sources.poses.frames, "load", lambda ref: frames if ref == source_ref else original_load(ref)
    )
    changed = request.model_copy(update={"bundle": request.bundle.model_copy(update={"rgb_frame_refs": references})})
    verifier._inventory(changed)
    # Order and exact refs remain mandatory even with a valid copy of every image.
    with pytest.raises(ValueError, match="inventory"):
        verifier._inventory(
            changed.model_copy(
                update={"bundle": changed.bundle.model_copy(update={"rgb_frame_refs": references[::-1]})}
            )
        )
    resolver.require(references[0]).write_bytes(b"corrupted")
    with pytest.raises((ValueError, RuntimeError)):
        verifier._inventory(changed)


def test_source_corruption_and_foreign_job_are_rejected_before_copy(tmp_path: Path):
    verifier, _, resolver, frames, _ = setup_legacy(tmp_path)
    with pytest.raises(ValueError, match="another job"):
        bundle_frame_references(frames, "unrelated-job")
    resolver.require(frames.frames[0].image).write_bytes(b"corrupted")
    with pytest.raises((ValueError, RuntimeError)):
        publish_bundle_frames(frames, "input", verifier.sources.poses.frames, verifier.canonicalizer.deps.writer)
    refs = bundle_frame_references(frames, "input")
    assert not resolver.resolve(refs[0].artifact_uri).exists()
