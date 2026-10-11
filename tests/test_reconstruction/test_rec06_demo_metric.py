"""Ba demo routes qua actual store/preview/gates; producer/correspondence là fixture."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError, ArtifactChecksumError
from src.services.reconstruction.rgb.canonical.demo_metric import DemoMetricAdapter
from src.services.reconstruction.rgb.canonical.demo_metric_models import (
    DemoLidarMeasurement,
    DemoMetricMode,
    DemoMetricRequest,
)
from tests.test_reconstruction.support.rec06_demo_fixtures import demo_fixture, request_for
from tests.test_reconstruction.support.rec06_fixtures import acceptance_for


@pytest.fixture
def context(tmp_path: Path) -> tuple[DemoMetricAdapter, DemoLidarMeasurement]:
    return demo_fixture(tmp_path)


@pytest.mark.parametrize("mode", list(DemoMetricMode))
@pytest.mark.parametrize("assisted", [False, True])
def test_three_modes_share_measured_scale(tmp_path: Path, mode: DemoMetricMode, assisted: bool) -> None:
    """Only fusion exposes LiDAR geometry; mọi mode giữ nguồn hỗ trợ và review gate."""
    ctx = demo_fixture(tmp_path, assisted)
    adapter, measurement = ctx
    preview = adapter.preview(request_for(ctx, mode))
    assert preview.suggested_distance_m == 1
    assert preview.metric_preview.transform.scale_m_per_sfm_unit == 2
    assert preview.metric_preview.status == "UNCONFIRMED"
    assert preview.independent_rgb_only is False
    assert preview.preprocessing_provenance.ground_truth_assisted == assisted
    assert preview.lidar_geometry_for_composition == (
        measurement.source_lidar if mode == DemoMetricMode.RGB_LIDAR_FUSION else None
    )
    with pytest.raises(ValueError, match="explicit acceptance"):
        adapter.confirm(preview, None)
    record = adapter.confirm(preview, acceptance_for(adapter.deps.metric, preview.metric_preview))
    reference = adapter.deps.metric.publish(record, "rec06-demo")
    assert adapter.deps.metric.load(reference) == record
    provenance = record.preview.request.anchor.measurement_ref.source_provenance
    assert provenance["assistance"] == "lidar_assisted_demo"
    assert provenance["ground_truth_assisted"] == assisted
    with pytest.raises(ValueError, match="synthetic confirmation"):
        adapter.deps.metric.require_real(reference)


@pytest.mark.parametrize("kind", ["missing", "denied", "truthy_non_boolean"])
def test_correspondence_authority_required(context: tuple, kind: str) -> None:
    adapter, measurement = context
    verifier = None if kind == "missing" else lambda value: False if kind == "denied" else 1
    adapter = DemoMetricAdapter(replace(adapter.deps, verify_measurement=verifier))
    with pytest.raises(ValueError, match="verifier|not verified"):
        adapter.publish_measurement(measurement, "rec06-demo")


@pytest.mark.parametrize("field", ["identity", "source_visual", "selected_rgb_points"])
def test_stale_scene_or_selection_rejected(context: tuple, field: str) -> None:
    adapter, _ = context
    request = request_for(context, DemoMetricMode.RGB_TWO_POINT)
    changes = {
        "identity": request.identity.model_copy(update={"traversal_id": "another-traversal"}),
        "source_visual": request.source_visual.model_copy(update={"artifact_checksum": "sha256:" + "b" * 64}),
        "selected_rgb_points": ((0, 0, 3), (9, 0, 3)),
    }
    request = request.model_copy(update={field: changes[field]})
    with pytest.raises(ValueError, match="different scene|no verified LiDAR correspondence"):
        adapter.preview(request)


def test_reverse_selection_preserves_correspondence(context: tuple) -> None:
    adapter, measurement = context
    request = request_for(context, DemoMetricMode.RGB_TWO_POINT)
    request = request.model_copy(update={"selected_rgb_points": measurement.rgb_points[::-1]})
    preview = adapter.preview(request)
    assert preview.metric_preview.request.anchor.point_a == measurement.rgb_points[1]
    assert preview.suggested_distance_m == 1


@pytest.mark.parametrize("mode", list(DemoMetricMode))
def test_selection_is_specific_to_two_point_mode(context: tuple, mode: DemoMetricMode) -> None:
    adapter, measurement = context
    request = request_for(context, mode)
    points = None if mode == DemoMetricMode.RGB_TWO_POINT else measurement.rgb_points
    with pytest.raises(ValueError, match="required only in two-point mode"):
        adapter.preview(request.model_copy(update={"selected_rgb_points": points}))


@pytest.mark.parametrize("target", ["record", "lidar", "correspondence", "frame", "master", "visual"])
def test_tampered_source_rejected_before_confirm(context: tuple, target: str) -> None:
    adapter, measurement = context
    request = request_for(context, DemoMetricMode.RGB_AUTO_SCALE_PROXY)
    preview = adapter.preview(request)
    acceptance = acceptance_for(adapter.deps.metric, preview.metric_preview)
    refs = dict(
        record=request.measurement_ref,
        lidar=measurement.source_lidar,
        correspondence=measurement.correspondence_ref,
        frame=measurement.frame.evidence_ref,
        master=measurement.source_master,
        visual=measurement.source_visual,
    )
    adapter.deps.metric.deps.visuals.require(refs[target]).write_bytes(b"tampered")
    with pytest.raises((ValueError, ArtifactChecksumError)):
        adapter.confirm(preview, acceptance)


@pytest.mark.parametrize("failure", ["gt_flag", "provenance", "raw", "eval", "coincident", "nan", "real_label"])
def test_invalid_measurement_fails_closed(context: tuple, failure: str) -> None:
    adapter, measurement = context
    value = measurement.model_dump()
    if failure == "gt_flag":
        value["preprocessing_provenance"]["ground_truth_assisted"] = True
    elif failure == "provenance":
        value["source_lidar"]["source_provenance"] = {}
    elif failure == "raw":
        value["source_lidar"]["producer_stage"] = "DP-LIDAR-PREFUSION"
    elif failure == "eval":
        value["source_lidar"]["data_class"] = "evaluation_only"
    elif failure == "coincident":
        value["lidar_points_m"] = ((1, 1, 1), (1, 1, 1))
    elif failure == "nan":
        value["lidar_points_m"] = ((float("nan"), 1, 1), (1, 2, 3))
    else:
        value["evidence_kind"] = "real_measurement"
    with pytest.raises(ValueError):
        adapter.publish_measurement(DemoLidarMeasurement.model_validate(value), "rec06-demo")


def test_measurement_publication_is_immutable(context: tuple) -> None:
    adapter, measurement = context
    request_for(context, DemoMetricMode.RGB_LIDAR_FUSION)
    with pytest.raises(ArtifactAlreadyExistsError):
        adapter.publish_measurement(measurement, "rec06-demo")


@pytest.mark.parametrize("field", ["suggested_distance_m", "lidar_geometry_for_composition"])
def test_changed_demo_preview_rejected(context: tuple, field: str) -> None:
    adapter, measurement = context
    preview = adapter.preview(request_for(context, DemoMetricMode.RGB_AUTO_SCALE_PROXY))
    changes = dict(suggested_distance_m=42, lidar_geometry_for_composition=measurement.source_lidar)
    changed = preview.model_copy(update={field: changes[field]})
    with pytest.raises(ValueError, match="preview changed"):
        adapter.confirm(changed, acceptance_for(adapter.deps.metric, preview.metric_preview))


def test_assistance_provenance_cannot_be_stripped(context: tuple) -> None:
    adapter, _ = context
    request = request_for(context, DemoMetricMode.RGB_AUTO_SCALE_PROXY)
    ref = request.measurement_ref.model_copy(update={"source_provenance": {}})
    with pytest.raises(ValueError, match="provenance differs"):
        adapter.preview(request.model_copy(update={"measurement_ref": ref}))


@pytest.mark.parametrize("scope", [None, "normal_rgb_upload"])
def test_demo_scope_is_explicit_not_a_normal_upload_fallback(context: tuple, scope: str | None) -> None:
    request = request_for(context, DemoMetricMode.RGB_AUTO_SCALE_PROXY).model_dump()
    if scope is None:
        del request["execution_scope"]
    else:
        request["execution_scope"] = scope
    with pytest.raises(ValueError, match="execution_scope"):
        DemoMetricRequest.model_validate(request)
