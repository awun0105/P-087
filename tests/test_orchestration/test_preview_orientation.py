"""Preview chỉ lấy hướng từ xác nhận khớp nguồn; không đổi artifact hoặc đơn vị SfM."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import StageArtifact, StageId
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.jobs import stage_views as module
from src.services.reconstruction.rgb.canonical.metric_math import rotate
from tests.test_reconstruction.support.rec06_bundle_metric_fixture import prepared


@pytest.mark.parametrize("confirmation_state", ["matching", "missing", "foreign_visual", "foreign_poses", "corrupt"])
def test_preview_orientation_uses_only_matching_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirmation_state: str
) -> None:
    _, resolver, canonicalizer, reference = prepared(tmp_path)
    path = resolver.locate("artifact://jobs/input/attempts/first/rec11/preview.json")
    assert path is not None
    preview = ReconstructionPreview.model_validate_json(path.read_bytes())
    record = canonicalizer.load(reference)
    original_visual = resolver.require(preview.delivery_ref).read_bytes()
    if confirmation_state == "foreign_visual":
        preview = preview.model_copy(
            update={
                "source_visual_ref": preview.source_visual_ref.model_copy(
                    update={"artifact_checksum": "sha256:" + "f" * 64}
                )
            }
        )
    if confirmation_state == "foreign_poses":
        # Valid readable pose artifact, but a different published reference.
        preview = preview.model_copy(
            update={
                "camera_pose_ref": preview.camera_pose_ref.model_copy(
                    update={"source_provenance": {"attempt": "other"}}
                )
            }
        )
    stage = StageArtifact(
        stage_id=StageId.METRIC_CANONICALIZE,
        status="SUCCEEDED",
        artifact_type="RGBMetricConfirmation",
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        data_class="derived",
        completed_at=datetime.now(UTC),
    )
    job = SimpleNamespace(stage_artifacts=[] if confirmation_state == "missing" else [stage])
    registry = SimpleNamespace(get_job=lambda _: job, get_preview=lambda _: preview, runtime_resolver=resolver)
    monkeypatch.setattr(module, "job_frame_images", lambda *_: [])
    monkeypatch.setattr(module, "job_bundle", lambda *_: None)
    if confirmation_state == "corrupt":
        resolver.require(reference).write_bytes(b"corrupt")
        with pytest.raises((ArtifactStoreError, ValueError)):
            module.stage_views(registry, "input")
        return
    views = module.stage_views(registry, "input").views
    gaussian = next(view for view in views if view.kind == "gaussian")
    assert gaussian.unit == "arbitrary" and gaussian.refs == [preview.delivery_ref]
    assert gaussian.cameras == next(view for view in views if view.kind == "cameras").cameras
    rotation = gaussian.display_rotation_xyzw
    if confirmation_state == "matching":
        assert rotation is not None
        # Reprojection: a point and its viewing direction undergo the same proper rotation.
        point = (1.0, 2.0, 3.0)
        world = rotate(point, record.preview.transform.rotation_xyzw)
        assert rotate(point, rotation) == pytest.approx((world[0], world[2], -world[1]))
    else:
        assert rotation is None
    assert resolver.require(preview.delivery_ref).read_bytes() == original_visual
