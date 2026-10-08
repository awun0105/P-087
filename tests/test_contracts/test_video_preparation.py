"""Versioned browser video preparation contracts and timeline provenance."""

import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.video_preparation import (
    ClientVideoPreparationManifest,
    VideoFrameBinding,
    VideoFrameMapDescriptor,
    VideoNormalizationCapability,
    VideoNormalizationProfile,
    default_video_normalization_profile,
    validate_video_frame_map_rows,
)

FIXTURE = Path(__file__).parents[2] / "fixtures/contracts/video_preparation_v1.json"


def _fixtures() -> dict[str, object]:
    """Load the shared Python/TypeScript fixture for isolated contract checks."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _resign_manifest(payload: dict[str, object]) -> dict[str, object]:
    """Recompute the logical identity after an intentional metadata change."""
    transform = payload["pixel_transform"]
    transform["matrix"] = [[float(value) for value in row] for row in transform["matrix"]]
    payload["preparation_checksum"] = "sha256:" + "0" * 64
    payload["preparation_checksum"] = canonical_content_checksum(payload, "preparation_checksum")
    return payload


def _set_source_and_output_hdr(payload: dict[str, object]) -> None:
    payload["source_video"]["color"].update(transfer="smpte2084")
    payload["prepared_video"]["color"].update(transfer="smpte2084")


def _set_explicit_omission_without_source_audio(payload: dict[str, object]) -> None:
    payload["source_video"].update(audio_track_count=0)
    payload["prepared_video"].update(audio_track_count=0)
    payload["audio_disposition"] = "omitted_with_user_consent"


def _set_partial_audio_preservation(payload: dict[str, object]) -> None:
    payload["source_video"].update(audio_track_count=2)


def _set_output_larger_than_source(payload: dict[str, object]) -> None:
    payload["source_video"].update(coded_width=640, coded_height=360, display_width=640, display_height=360)


def test_shared_profile_is_versioned_and_portrait_bounds_are_orientation_independent() -> None:
    fixture = _fixtures()
    profile = VideoNormalizationProfile.model_validate(fixture["profile"])
    verify_content_checksum(profile, "profile_checksum")
    presets = {item.preset.value: item for item in profile.presets}

    assert profile.default_preset.value == "720p"
    assert profile.max_frame_rate.numerator == 30
    assert (presets["1080p"].max_long_edge_px, presets["1080p"].max_short_edge_px) == (1920, 1080)
    assert (presets["720p"].max_long_edge_px, presets["720p"].max_short_edge_px) == (1280, 720)
    assert (presets["480p"].max_long_edge_px, presets["480p"].max_short_edge_px) == (854, 480)
    assert profile.profile_checksum == default_video_normalization_profile().profile_checksum


def test_capability_contract_reports_each_declared_blocker() -> None:
    fixture = _fixtures()
    supported = VideoNormalizationCapability.model_validate(fixture["capability_supported"])
    unsupported = VideoNormalizationCapability.model_validate(fixture["capability_unsupported"])

    assert supported.status == "supported"
    assert unsupported.status == "unsupported"
    assert unsupported.blockers == ["hdr_unsupported"]

    broken = copy.deepcopy(fixture["capability_unsupported"])
    broken["blockers"] = []
    with pytest.raises(ValidationError, match="exactly match"):
        VideoNormalizationCapability.model_validate(broken)

    extra = copy.deepcopy(fixture["capability_supported"])
    extra["blockers"] = ["hdr_unsupported"]
    extra["status"] = "unsupported"
    with pytest.raises(ValidationError, match="exactly match"):
        VideoNormalizationCapability.model_validate(extra)


def test_preparation_manifest_binds_60_to_30_source_frames_and_checksum() -> None:
    fixture = _fixtures()
    manifest = ClientVideoPreparationManifest.model_validate(fixture["preparation_manifest"])
    verify_content_checksum(manifest, "preparation_checksum")
    rows = [VideoFrameBinding.model_validate(row) for row in fixture["frame_map_rows"]]
    descriptor = VideoFrameMapDescriptor.model_validate(manifest.frame_map)

    validate_video_frame_map_rows(
        iter(rows),
        descriptor=descriptor,
        source_frame_count=manifest.source_video.frame_count,
        output_frame_count=manifest.prepared_video.frame_count,
        max_sidecar_bytes=default_video_normalization_profile().max_frame_map_bytes,
    )

    assert [row.source_frame_index for row in rows] == [0, 2, 4]
    assert [row.source_pts for row in rows] == [0, 200, 400]
    assert manifest.source_video.frame_rate.numerator == 60
    assert manifest.prepared_video.frame_rate.numerator == 30


@pytest.mark.parametrize(
    ("row_index", "change", "message"),
    [
        (1, {"output_frame_index": 2}, "output indices must be contiguous"),
        (1, {"source_frame_index": 0}, "source indices must be increasing"),
        (2, {"source_frame_index": 5}, "source indices must be increasing"),
        (1, {"source_pts": 0}, "source PTS must be strictly increasing"),
        (1, {"output_pts": 0}, "output PTS must be strictly increasing"),
    ],
)
def test_frame_map_rejects_gaps_duplicates_and_nonmonotonic_timestamps(
    row_index: int, change: dict[str, int], message: str
) -> None:
    fixture = _fixtures()
    manifest = ClientVideoPreparationManifest.model_validate(fixture["preparation_manifest"])
    rows = [VideoFrameBinding.model_validate(row) for row in fixture["frame_map_rows"]]
    rows[row_index] = rows[row_index].model_copy(update=change)

    with pytest.raises(ValueError, match=message):
        validate_video_frame_map_rows(
            rows,
            descriptor=manifest.frame_map,
            source_frame_count=manifest.source_video.frame_count,
            output_frame_count=manifest.prepared_video.frame_count,
            max_sidecar_bytes=default_video_normalization_profile().max_frame_map_bytes,
        )


def test_frame_map_rejects_descriptor_and_sidecar_size_mismatch() -> None:
    fixture = _fixtures()
    manifest = ClientVideoPreparationManifest.model_validate(fixture["preparation_manifest"])
    rows = [VideoFrameBinding.model_validate(row) for row in fixture["frame_map_rows"]]

    with pytest.raises(ValueError, match="byte limit"):
        validate_video_frame_map_rows(
            rows,
            descriptor=manifest.frame_map,
            source_frame_count=5,
            output_frame_count=3,
            max_sidecar_bytes=manifest.frame_map.size_bytes - 1,
        )
    with pytest.raises(ValueError, match="frame counts"):
        validate_video_frame_map_rows(
            rows,
            descriptor=manifest.frame_map,
            source_frame_count=6,
            output_frame_count=3,
            max_sidecar_bytes=default_video_normalization_profile().max_frame_map_bytes,
        )


def test_frame_bindings_require_integer_indices_and_pts() -> None:
    fixture = _fixtures()
    row = dict(fixture["frame_map_rows"][0])
    row["output_frame_index"] = 0.5

    with pytest.raises(ValidationError, match="output_frame_index"):
        VideoFrameBinding.model_validate(row)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["prepared_video"].update(rotation_degrees=90), "bake orientation"),
        (
            lambda value: value["prepared_video"].update(sample_aspect_ratio={"numerator": 2, "denominator": 1}),
            "square pixels",
        ),
        (lambda value: value["frame_map"].update(size_bytes=33_554_433), "byte limit"),
        (lambda value: value["prepared_video"].update(display_width=1920, coded_width=1920), "exceed the selected"),
        (_set_output_larger_than_source, "must not upscale"),
        (_set_source_and_output_hdr, "HDR source"),
        (lambda value: value["prepared_video"]["color"].update(primaries="bt2020"), "preserve the observed"),
        (_set_explicit_omission_without_source_audio, "explicit audio omission"),
        (_set_partial_audio_preservation, "every source audio track"),
    ],
)
def test_preparation_manifest_rejects_unsafe_media_claims(
    mutate: Callable[[dict[str, object]], None], message: str
) -> None:
    payload = copy.deepcopy(_fixtures()["preparation_manifest"])
    mutate(payload)

    with pytest.raises((ValidationError, ValueError), match=message):
        ClientVideoPreparationManifest.model_validate(payload)


def test_portrait_rotation_is_valid_when_geometry_is_explicit() -> None:
    payload = copy.deepcopy(_fixtures()["preparation_manifest"])
    payload["source_video"].update(display_width=1080, display_height=1920, rotation_degrees=90)
    payload["prepared_video"].update(coded_width=720, coded_height=1280, display_width=720, display_height=1280)
    payload["pixel_transform"]["matrix"] = [[0, -2 / 3, 720], [2 / 3, 0, 0], [0, 0, 1]]
    _resign_manifest(payload)

    manifest = ClientVideoPreparationManifest.model_validate(payload)

    assert manifest.source_video.rotation_degrees == 90
    assert (manifest.prepared_video.display_width, manifest.prepared_video.display_height) == (720, 1280)


def test_non_square_source_pixels_are_supported_when_the_transform_is_recorded() -> None:
    payload = copy.deepcopy(_fixtures()["preparation_manifest"])
    payload["source_video"].update(coded_width=1440, sample_aspect_ratio={"numerator": 4, "denominator": 3})
    payload["pixel_transform"]["matrix"] = [[8 / 9, 0, 0], [0, 2 / 3, 0], [0, 0, 1]]
    _resign_manifest(payload)

    manifest = ClientVideoPreparationManifest.model_validate(payload)

    assert manifest.source_video.sample_aspect_ratio.numerator == 4
    assert manifest.prepared_video.sample_aspect_ratio.numerator == 1
    assert manifest.prepared_video.sample_aspect_ratio.denominator == 1


def test_preparation_checksum_rejects_mutated_profile_identity() -> None:
    payload = copy.deepcopy(_fixtures()["preparation_manifest"])
    payload["preparation_checksum"] = "sha256:" + "f" * 64

    with pytest.raises(ValidationError, match="preparation_checksum"):
        ClientVideoPreparationManifest.model_validate(payload)
