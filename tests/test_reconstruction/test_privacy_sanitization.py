"""AUD-18: hình học vùng che và hợp đồng SanitizationManifest. Không cần torch hay EgoBlur."""

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.sanitization import SanitizationManifest
from src.services.reconstruction.adapters.sanitization_regions import (
    expand_box,
    fill_regions,
    iou,
    propagate_regions,
)
from src.services.reconstruction.rgb.preflight.sanitization import DEFAULT_CONFIG, manifest_from_runner_result

SOURCE = "sha256:" + "1" * 64
A, B, C = ("sha256:" + digit * 64 for digit in "abc")
DETECTOR = {
    "name": "egoblur-gen2",
    "package_version": "2.0.1",
    "torch_version": "2.7.1+cu126",
    "torchvision_version": "0.22.1+cu126",
    "face_weights_checksum": A,
    "plate_weights_checksum": B,
}


def _face(box: list[float], score: float | None = 0.9, origin: str = "detected") -> dict:
    return {"kind": "face", "box": box, "score": score, "origin": origin}


def _frame(name: str, regions: list[dict] | None = None, sanitized: str = A) -> dict:
    return {
        "frame_name": name,
        "width": 100,
        "height": 80,
        "source_checksum": A,
        "sanitized_checksum": sanitized,
        "regions": regions or [],
    }


def _result(frames: list[dict], failures: list[str] | None = None) -> dict:
    failures = failures or []
    return {
        "detector": DETECTOR,
        "config": DEFAULT_CONFIG,
        "requested_frame_count": len(frames) + len(failures),
        "frames": frames,
        "failures": failures,
    }


def test_iou_and_expand_box_clamp_to_the_image() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (10, 10, 20, 20)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    assert expand_box((40, 30, 60, 50), 100, 80, 1.0) == (40, 30, 61, 51)
    assert expand_box((40, 30, 60, 50), 100, 80, 2.0) == (30, 20, 71, 61)
    assert expand_box((0, 0, 20, 20), 100, 80, 2.0) == (0, 0, 31, 31)
    assert expand_box((90, 70, 100, 80), 100, 80, 3.0) == (80, 60, 100, 80)
    with pytest.raises(ValueError, match="positive"):
        expand_box((0, 0, 1, 1), 10, 10, 0)


def test_propagation_fills_neighbours_the_detector_missed() -> None:
    detected = [[], [], [_face([10, 10, 30, 30])], [], [], []]
    planned = propagate_regions(detected, radius=2, growth=0.15)

    assert [len(frame) for frame in planned] == [1, 1, 1, 1, 1, 0]
    assert planned[2][0]["origin"] == "detected"
    assert {planned[i][0]["origin"] for i in (0, 1, 3, 4)} == {"propagated"}
    assert planned[1][0]["extra_scale"] == pytest.approx(1.15)
    assert planned[0][0]["extra_scale"] == pytest.approx(1.30)
    assert planned[1][0]["score"] is None
    assert detected[1] == [], "đầu vào không bị sửa"


def test_propagation_skips_frames_that_already_cover_the_same_object() -> None:
    plate = {"kind": "license_plate", "box": [10, 10, 30, 30], "score": 0.8, "origin": "detected"}
    detected = [[_face([10, 10, 30, 30])], [_face([12, 11, 32, 31]), plate], []]
    planned = propagate_regions(detected, radius=1, growth=0.1)

    # Hai mặt chồng nhau ở frame 0 và 1 không sinh vùng lan sang nhau; biển số (khác loại) thì có.
    assert [region["origin"] for region in planned[0]] == ["detected", "propagated"]
    assert planned[0][1]["kind"] == "license_plate"
    assert [region["origin"] for region in planned[1]] == ["detected", "detected"]
    assert sorted(region["kind"] for region in planned[2]) == ["face", "license_plate"]
    with pytest.raises(ValueError, match="negative"):
        propagate_regions(detected, radius=-1, growth=0.1)


def test_fill_overwrites_exactly_the_applied_boxes() -> None:
    image = np.full((80, 100, 3), 200, dtype=np.uint8)
    regions = [_face([40, 30, 60, 50]), {**_face([0, 0, 10, 10], None, "propagated"), "extra_scale": 2.0}]

    covered = fill_regions(image, regions, scale=1.0, color=[0, 0, 0])

    assert regions[0]["applied_box"] == [40, 30, 61, 51]
    assert regions[1]["applied_box"] == [0, 0, 16, 16]
    assert covered == 21 * 21 + 16 * 16
    assert not image[30:51, 40:61].any() and not image[0:16, 0:16].any()
    assert int((image == 0).all(axis=2).sum()) == covered
    assert (image[60:, 70:] == 200).all()


def test_manifest_binds_frames_detector_and_config() -> None:
    region = {**_face([40, 30, 60, 50]), "applied_box": [38, 28, 63, 53]}
    manifest = manifest_from_runner_result(_result([_frame("000001.png"), _frame("000002.png", [region], B)]), SOURCE)

    assert manifest.complete and manifest.requested_frame_count == 2
    verify_content_checksum(manifest, "manifest_checksum")
    changed = manifest_from_runner_result(_result([_frame("000001.png"), _frame("000002.png", [region], C)]), SOURCE)
    assert changed.sanitized_inventory_checksum != manifest.sanitized_inventory_checksum
    assert changed.manifest_checksum != manifest.manifest_checksum
    other_weights = _result([_frame("000001.png")])
    other_weights["detector"] = {**DETECTOR, "face_weights_checksum": C}
    assert (
        manifest_from_runner_result(other_weights, SOURCE).manifest_checksum
        != manifest_from_runner_result(_result([_frame("000001.png")]), SOURCE).manifest_checksum
    )


def test_failed_frames_make_the_manifest_incomplete_and_are_never_counted_as_covered() -> None:
    manifest = manifest_from_runner_result(_result([_frame("000001.png")], ["000002.png"]), SOURCE)
    assert not manifest.complete and manifest.failures == ["000002.png"]

    missing = _result([_frame("000001.png")])
    missing["requested_frame_count"] = 2
    with pytest.raises(ValidationError, match="processed or listed as a failure"):
        manifest_from_runner_result(missing, SOURCE)
    with pytest.raises(ValidationError, match="more than once"):
        manifest_from_runner_result(_result([_frame("000001.png")], ["000001.png"]), SOURCE)


def test_manifest_rejects_bytes_that_contradict_the_recorded_regions() -> None:
    region = {**_face([40, 30, 60, 50]), "applied_box": [38, 28, 63, 53]}
    with pytest.raises(ValidationError, match="cannot keep its source bytes"):
        manifest_from_runner_result(_result([_frame("000001.png", [region], A)]), SOURCE)
    with pytest.raises(ValidationError, match="byte-identical copy"):
        manifest_from_runner_result(_result([_frame("000001.png", [], B)]), SOURCE)
    with pytest.raises(ValidationError, match="exceeds the frame"):
        outside = {**_face([90, 70, 99, 79]), "applied_box": [90, 70, 120, 80]}
        manifest_from_runner_result(_result([_frame("000001.png", [outside], B)]), SOURCE)
    with pytest.raises(ValidationError, match="detector score"):
        unscored = {**_face([1, 1, 5, 5], None), "applied_box": [1, 1, 6, 6]}
        manifest_from_runner_result(_result([_frame("000001.png", [unscored], B)]), SOURCE)


def test_manifest_inventory_is_recomputed_not_trusted() -> None:
    manifest = manifest_from_runner_result(_result([_frame("000001.png")]), SOURCE)
    tampered = manifest.model_dump()
    tampered["frames"][0]["frame_name"] = "000009.png"
    with pytest.raises(ValidationError, match="sanitized_inventory_checksum"):
        SanitizationManifest.model_validate(tampered)
