"""Unit và integration tests cho REC-05 Product Voxel Pipeline."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.models.contracts.manifests import StageId
from src.services.reconstruction.adapters.voxel import ProductVoxelRequest, SplatTransformVoxelAdapter, file_checksum
from src.services.reconstruction.adapters.voxel_runtime import VoxelRuntimeSettings
from src.services.reconstruction.rgb.geometry_publication import (
    GeometryDependencies,
    GeometryExecutionRequest,
    GeometryPublisher,
    GeometryResolver,
    RgbGeometryService,
)
from tests.test_reconstruction.rec06_fixtures import acceptance_for, metric_fixture
from tests.test_reconstruction.test_rec05_adapter import FixtureProcess, config


def setup_pipeline(tmp_path: Path) -> tuple:
    """Khởi tạo môi trường test hoàn chỉnh với real artifact store và FixtureProcess."""
    canonicalizer, metric_req = metric_fixture(tmp_path)
    preview = canonicalizer.preview(metric_req)
    record = canonicalizer.confirm(preview, acceptance_for(canonicalizer, preview))
    conf_ref = canonicalizer.publish(record, "test-job-rec05")
    publisher = GeometryPublisher(canonicalizer.deps.writer, "test-job-rec05")
    adapter = SplatTransformVoxelAdapter(
        FixtureProcess(VoxelRuntimeSettings(cli=Path("unused"), module_path=Path("unused")))
    )
    service = RgbGeometryService(
        GeometryDependencies(
            canonicalizer=canonicalizer,
            visuals=canonicalizer.deps.visuals,
            adapter=adapter,
            publisher=publisher,
        )
    )
    return service, canonicalizer, conf_ref, metric_req, record


def test_product_pipeline_success(tmp_path: Path) -> None:
    """Pipeline chạy thành công, tạo RgbGeometry và VoxelMetadata với provenance chuẩn."""
    service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    proposal = canonicalizer.propose_navigation_seed(conf_ref)
    cfg = config()
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        config=cfg,
        job_id="test-job-rec05",
        seed_proposal=proposal,
    )
    workspace = tmp_path / "workspace_prod"
    result = service.execute(req, workspace)
    assert result.geometry_ref.artifact_type == "RgbGeometry"
    assert result.geometry_ref.producer_stage == StageId.RGB_GEOMETRY
    assert result.geometry_ref.source_provenance["applied_confirmation_checksum"] == record.record_checksum
    assert result.geometry_ref.source_provenance["scale_applied"] == record.preview.transform.scale_m_per_sfm_unit
    assert result.geometry_ref.source_provenance["applied_transform"] == record.preview.transform.model_dump(
        mode="json"
    )
    assert result.geometry_ref.source_provenance["evidence_kind"] == "synthetic_fixture"
    assert result.metadata_ref.artifact_type == "VoxelMetadata"
    assert result.metadata_ref.producer_stage == StageId.RGB_GEOMETRY
    resolver = GeometryResolver(canonicalizer.deps.visuals.resolve)
    assert resolver.require(result.geometry_ref).is_file()
    meta = resolver.load_metadata(result.metadata_ref)
    assert meta["version"] == "1.1"


def test_product_default_rejects_synthetic_confirmation(tmp_path: Path) -> None:
    """Không cho fixture authority đi qua product default dù typed status CONFIRMED."""
    service, _, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    request = GeometryExecutionRequest(
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        config=config(),
        job_id="test-job-rec05",
    )
    with pytest.raises(ValueError, match="synthetic confirmation"):
        service.execute(request, tmp_path / "real-attempt")
    assert not (tmp_path / "real-attempt").exists()


def test_adapter_rejects_different_confirmed_master(tmp_path: Path) -> None:
    """Dù hợp lệ theo hash riêng, input khác master của confirmation vẫn bị chặn."""
    service, _, _, _, confirmation = setup_pipeline(tmp_path)
    source = tmp_path / "other.ply"
    source.write_bytes(b"different but checksummed source")
    request = ProductVoxelRequest(
        confirmation=confirmation,
        source=source,
        source_checksum=file_checksum(source),
        config=config(),
    )
    with pytest.raises(ValueError, match="not the master"):
        service.deps.adapter.run_product(request, tmp_path / "attempt")
    assert not (tmp_path / "attempt").exists()


def test_product_pipeline_rejects_double_scaling(tmp_path: Path) -> None:
    """Chặn thực thi khi applied_record_checksum đã được áp dụng trước đó."""
    service, _, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        config=config(),
        job_id="test-job-rec05",
        applied_record_checksum=record.record_checksum,
    )
    with pytest.raises(ValueError, match="refusing double scaling"):
        service.execute(req, tmp_path / "workspace_double")


def test_product_pipeline_rejects_mismatched_visual_master(tmp_path: Path) -> None:
    """Từ chối khi visual artifact không trùng với master của distance anchor."""
    service, _, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    tampered_visual = metric_req.source_visual.model_copy(update={"artifact_checksum": "sha256:" + "0" * 64})
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=tampered_visual,
        config=config(),
        job_id="test-job-rec05",
    )
    with pytest.raises(Exception):
        service.execute(req, tmp_path / "workspace_tamper")


def test_product_pipeline_rejects_mismatched_seed_proposal(tmp_path: Path) -> None:
    """Từ chối khi seed proposal thuộc về một confirmation record khác."""
    service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    proposal = canonicalizer.propose_navigation_seed(conf_ref)
    tampered_proposal = proposal.model_copy(update={"confirmation_checksum": "sha256:" + "9" * 64})
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        config=config(),
        job_id="test-job-rec05",
        seed_proposal=tampered_proposal,
    )
    with pytest.raises(ValueError, match="seed proposal does not match"):
        service.execute(req, tmp_path / "workspace_bad_seed")


def test_product_pipeline_rejects_tampered_source(tmp_path: Path) -> None:
    """Từ chối khi nội dung file source PLY bị thay đổi sau khi ghi nhận checksum."""
    service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    visual = canonicalizer.deps.visuals.load(metric_req.source_visual)
    master_path = canonicalizer.deps.visuals.require(visual.master)
    master_path.write_bytes(b"tampered content")
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        config=config(),
        job_id="test-job-rec05",
    )
    with pytest.raises(Exception):
        service.execute(req, tmp_path / "workspace_corrupt")


def test_optional_seed_policy_cannot_override_clearance(tmp_path: Path) -> None:
    """Callback true không được bypass actual occupancy guard của adapter."""
    service, _, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    service = RgbGeometryService(replace(service.deps, verify_seed=lambda request: True))
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        job_id="test-job-rec05",
        config=config().model_copy(update={"navigation_seed_world": (100, 0, 0)}),
    )
    with pytest.raises(ValueError, match="no artifact published"):
        service.execute(req, tmp_path / "invalid-seed")
    assert not (tmp_path / "invalid-seed/collision.log").exists()


def test_product_scope_still_fails_loud_without_seed_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Product bắt buộc có seed policy gate; thiếu config không được im lặng lọt.

    Monkeypatch chỉ thay realness gate của REC-06 để tới đúng gate đang kiểm;
    geometry guard của adapter vẫn chạy nguyên vẹn.
    """
    service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    monkeypatch.setattr(canonicalizer, "require_real", lambda ref: record)
    monkeypatch.setattr(canonicalizer, "load", lambda ref: record)
    req = GeometryExecutionRequest(
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        job_id="test-job-rec05",
        config=config(),
    )
    with pytest.raises(ValueError, match="seed clearance policy is not configured"):
        service.execute(req, tmp_path / "no-policy")
    assert not (tmp_path / "no-policy").exists()


@pytest.fixture
def published_clearance(tmp_path: Path):
    """Chạy pipeline một lần rồi tái sử dụng refs để kiểm phía consumer."""
    service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=conf_ref,
        source_visual=metric_req.source_visual,
        config=config(),
        job_id="test-job-rec05",
    )
    result = service.execute(req, tmp_path / "workspace_published")
    return service, canonicalizer, result.clearance


def test_published_clearance_is_independently_reverifiable(published_clearance) -> None:
    """Consumer dựng lại kernel từ bytes publish và tự kiểm, không tin status của producer."""
    _, canonicalizer, clearance = published_clearance
    assert clearance.occupancy_metadata.artifact_type == "VoxelOccupancy"
    assert clearance.occupancy_binary.artifact_type == "VoxelOccupancy"
    assert clearance.seed_clearance.artifact_type == "SeedClearance"
    decision = GeometryResolver(canonicalizer.deps.visuals.resolve).load_seed_clearance(clearance)
    assert decision["status"] == "VALID"
    assert decision["requested_seed_world"] == list(config().navigation_seed_world)


@pytest.mark.parametrize("tamper", ["binary", "metadata", "wrong_type", "kernel_conflict"])
def test_consumer_rejects_unverifiable_clearance_evidence(published_clearance, tamper: str) -> None:
    """Publish thiếu, sai bytes, sai type hoặc kernel mâu thuẫn đều bị chặn ở consumer."""
    service, canonicalizer, clearance = published_clearance
    resolver = GeometryResolver(canonicalizer.deps.visuals.resolve)
    if tamper == "binary":
        clearance = clearance.model_copy(update={"occupancy_binary": clearance.occupancy_metadata})
        expected = "occupancy binary differs"
    elif tamper == "metadata":
        clearance = clearance.model_copy(update={"occupancy_metadata": clearance.occupancy_binary})
        expected = "occupancy metadata differs"
    elif tamper == "wrong_type":
        clearance = clearance.model_copy(update={"seed_clearance": clearance.occupancy_metadata})
        expected = "not a SeedClearance"
    else:
        decision = json.loads(resolver.require(clearance.seed_clearance).read_text())
        decision["kernel_low"] = [0, 0, 0]
        decision["kernel_high"] = [63, 63, 63]
        clearance = clearance.model_copy(
            update={
                "seed_clearance": service.deps.publisher.publish_clearance(
                    "seed-clearance-conflict.json", json.dumps(decision).encode(), {}
                )
            }
        )
        expected = "intersects published occupancy"
    with pytest.raises(ValueError, match=expected):
        resolver.load_seed_clearance(clearance)
