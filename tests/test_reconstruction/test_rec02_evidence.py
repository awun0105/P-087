"""Contract and lineage tests for REC-02 review evidence records."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.torwic.prepare_dataset import (
    BenchmarkSplit,
    ManifestFileEntry,
    TorwicPreparationManifest,
    compute_sha256,
)
from scripts.torwic.rec02_evidence import (
    CanonicalSource,
    EvidenceConfig,
    _write_immutable,
    build_frame_inventory,
    build_input_manifest,
    build_privacy_review_packet,
)
from scripts.torwic.rec02_privacy_issue import IssuePaths, TorwicPrivacyIssuer
from src.models.contracts.artifacts import ArtifactDataClass
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import PrivacyInspectionScope, PrivacyResult
from src.services.orchestration.artifacts.store import ArtifactResolver
from src.services.reconstruction.rgb.privacy import PrivacyInspectionEvidence, PrivacyReviewRequest, RGBPrivacyGate


def _source(root: Path) -> CanonicalSource:
    """Create a small canonical source with two train frames and one held-out frame."""
    entries = []
    for frame_id in range(3):
        path = root / "normalized" / "aisle_cw" / "rgb_frames" / f"{frame_id:06d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"frame-{frame_id}".encode())
        entries.append(
            ManifestFileEntry(
                relative_path=f"normalized/aisle_cw/rgb_frames/{frame_id:06d}.png",
                artifact_checksum=compute_sha256(path),
                data_class=ArtifactDataClass.PRODUCT_INPUT,
                frame_id=frame_id,
                timestamp_sec=f"{frame_id}.0",
            )
        )
    preparation = TorwicPreparationManifest(
        traversal_id="Aisle_CW",
        selection_mode="complete",
        frame_count=3,
        source_files=entries,
        generated_files=entries,
        provenance={"train_ids": [0, 1], "held_ids": [2]},
    )
    preparation.manifest_checksum = canonical_content_checksum(preparation, "manifest_checksum")
    split = BenchmarkSplit(train_frame_ids=[0, 1], held_out_frame_ids=[2])
    split.split_checksum = canonical_content_checksum(split, "split_checksum")
    return CanonicalSource(preparation, split, "sha256:" + "d" * 64)


def _config(root: Path) -> EvidenceConfig:
    """Build explicit review metadata for the synthetic source."""
    return EvidenceConfig(
        dataset_root=root,
        traversal_id="Aisle_CW",
        job_id="rec02-test",
        received_at=datetime(2026, 9, 24, tzinfo=UTC),
    )


def _rights_record(root: Path, source: CanonicalSource, split_checksum: str | None = None) -> Path:
    record = {
        "traversal_id": "Aisle_CW",
        "usage_scope": "public_noncommercial_demo",
        "selected_frame_count": 2,
        "excluded_held_out_frame_count": 1,
        "selection_checksum": split_checksum or source.split.split_checksum,
        "attested": True,
        "reference": "user-confirmed:fixture",
        "attestation_checksum": "sha256:" + "0" * 64,
    }
    record["attestation_checksum"] = canonical_content_checksum(record, "attestation_checksum")
    path = root / "rights.json"
    path.write_text(json.dumps(record))
    return path


def test_candidate_manifest_is_train_only_and_checksum_bound(tmp_path: Path) -> None:
    """The candidate InputManifest contains only selected train frames."""
    source = _source(tmp_path)
    config = _config(tmp_path)
    manifest = build_input_manifest(config, source)
    verify_content_checksum(manifest, "input_manifest_checksum")
    assert len(manifest.files) == 2
    assert [item.original_name for item in manifest.files] == ["000000.png", "000001.png"]
    assert manifest.source_rights_attestation["usage_scope"] == "public_noncommercial_demo"
    assert manifest.source_rights_attestation["attested"] is False
    assert "2" not in {item.original_name.removesuffix(".png") for item in manifest.files}


def test_explicit_rights_record_binds_to_frozen_selection(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rights = _rights_record(tmp_path, source)
    config = replace(_config(tmp_path), rights_record=rights)
    manifest = build_input_manifest(config, source)
    assert manifest.source_rights_attestation["attested"] is True
    assert manifest.source_rights_attestation["selection_checksum"] == source.split.split_checksum
    inventory = build_frame_inventory(config, manifest, source)
    packet = build_privacy_review_packet(config, manifest, inventory)
    assert packet["rights_attested"] is True
    assert packet["inspected_frame_count"] == 0
    assert packet["privacy_report_result"] == "NOT_ISSUED"


def test_rights_record_for_other_selection_fails(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rights = _rights_record(tmp_path, source, "sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="different frame selection"):
        build_input_manifest(replace(_config(tmp_path), rights_record=rights), source)


def test_inventory_binds_frame_ids_checksums_and_heldout_count(tmp_path: Path) -> None:
    """Inventory makes the train/held-out boundary auditable."""
    source = _source(tmp_path)
    config = _config(tmp_path)
    manifest = build_input_manifest(config, source)
    inventory = build_frame_inventory(config, manifest, source)
    assert inventory["selected_frame_count"] == 2
    assert inventory["held_out_frame_count"] == 1
    assert [row["frame_id"] for row in inventory["frames"]] == [0, 1]
    assert canonical_content_checksum(inventory, "inventory_checksum") == inventory["inventory_checksum"]


def test_privacy_packet_records_unreviewed_state(tmp_path: Path) -> None:
    """Usage scope alone cannot claim privacy inspection or clearance."""
    source = _source(tmp_path)
    config = _config(tmp_path)
    manifest = build_input_manifest(config, source)
    inventory = build_frame_inventory(config, manifest, source)
    packet = build_privacy_review_packet(config, manifest, inventory)
    assert packet["status"] == "PENDING_FRAME_INSPECTION_AND_RIGHTS_ATTESTATION"
    assert packet["selected_frame_count"] == 2
    assert packet["inspected_frame_count"] == 0
    assert packet["findings_status"] == "UNKNOWN_UNTIL_INSPECTION"
    assert packet["rights_attested"] is False
    assert packet["qa_accepted"] is False
    assert packet["privacy_report_result"] == "NOT_ISSUED"
    assert canonical_content_checksum(packet, "packet_checksum") == packet["packet_checksum"]


def test_candidate_cannot_issue_privacy_report(tmp_path: Path) -> None:
    """A candidate manifest fails closed even if a caller claims inspection."""
    source = _source(tmp_path)
    config = _config(tmp_path)
    manifest = build_input_manifest(config, source)
    evidence = PrivacyInspectionEvidence(
        scope=PrivacyInspectionScope.ALL_SELECTED_FRAMES,
        selected_frame_count=2,
        inspected_frame_count=2,
        unresolved_findings=(),
        evidence_checksum="sha256:" + "0" * 64,
    )
    evidence = replace(evidence, evidence_checksum=canonical_content_checksum(asdict(evidence), "evidence_checksum"))
    with pytest.raises(ValueError, match="Source rights are not attested"):
        RGBPrivacyGate().evaluate(PrivacyReviewRequest(manifest, evidence))


def _issue_paths(root: Path) -> IssuePaths:
    source = _source(root)
    config = replace(_config(root), rights_record=_rights_record(root, source))
    manifest = build_input_manifest(config, source)
    inventory = build_frame_inventory(config, manifest, source)
    packet = build_privacy_review_packet(config, manifest, inventory)
    review = root / "review"
    review.mkdir()
    for name, payload in (
        ("input_manifest.json", manifest.model_dump(mode="json")),
        ("frame_inventory.json", inventory),
        ("privacy_review_packet.json", packet),
    ):
        (review / name).write_text(json.dumps(payload))
    split_path = root / "derived/aisle_cw/benchmark_split.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text(source.split.model_dump_json())
    return IssuePaths(root, review, review / "authorization.json", root / "artifacts", "rec02-test")


def _write_qa_review(paths: IssuePaths, inspected: int) -> dict[str, object]:
    review = paths.review_dir
    manifest = json.loads((review / "input_manifest.json").read_text())
    inventory = json.loads((review / "frame_inventory.json").read_text())
    packet = json.loads((review / "privacy_review_packet.json").read_text())
    record = {
        "traversal_id": "Aisle_CW",
        "usage_scope": "public_noncommercial_demo",
        "selection_checksum": inventory["selection_checksum"],
        "input_manifest_checksum": manifest["input_manifest_checksum"],
        "frame_inventory_checksum": inventory["inventory_checksum"],
        "privacy_packet_checksum": packet["packet_checksum"],
        "input_manifest_path": str(review / "input_manifest.json"),
        "frame_inventory_path": str(review / "frame_inventory.json"),
        "inspection_scope": "all_selected_frames",
        "selected_frame_count": 2,
        "inspected_frame_count": inspected,
        "unresolved_findings": [],
        "approved_copy_checksum": None,
        "qa_accepted": True,
        "acceptance_reference": "qa-user-fixture",
        "record_checksum": "sha256:" + "0" * 64,
    }
    record["record_checksum"] = canonical_content_checksum(record, "record_checksum")
    (review / "qa_privacy_acceptance.user_attested.json").write_text(json.dumps(record))
    return record


def _write_qa_authorization(paths: IssuePaths, record: dict[str, object], authorized: bool) -> None:
    manifest = json.loads((paths.review_dir / "input_manifest.json").read_text())
    authorization = {
        "review_record_checksum": record["record_checksum"],
        "input_manifest_checksum": manifest["input_manifest_checksum"],
        "acceptance_reference": "qa-user-fixture",
        "report_issuance_authorized": authorized,
        "user_qa_approval": True,
        "public_dispatch_authorized": False,
        "user_confirmation_reference": "fixture-approval",
        "authorization_checksum": "sha256:" + "0" * 64,
    }
    authorization["authorization_checksum"] = canonical_content_checksum(authorization, "authorization_checksum")
    paths.authorization_path.write_text(json.dumps(authorization))


def _write_qa_records(paths: IssuePaths, inspected: int = 2, authorized: bool = True) -> None:
    record = _write_qa_review(paths, inspected)
    _write_qa_authorization(paths, record, authorized)


def test_authorized_review_issues_resolvable_verified_report(tmp_path: Path) -> None:
    paths = _issue_paths(tmp_path)
    _write_qa_records(paths)
    report, uri = TorwicPrivacyIssuer(paths).issue()
    assert report.result == PrivacyResult.VERIFIED_ANONYMIZED
    assert report.selected_frame_count == 2
    assert (
        json.loads((paths.review_dir / "privacy_report.json").read_text())["report_checksum"] == report.report_checksum
    )
    assert (
        json.loads(ArtifactResolver(paths.artifact_root).resolve(uri).read_text())["report_checksum"]
        == report.report_checksum
    )
    receipt = json.loads((paths.review_dir / "privacy_issuance_receipt.json").read_text())
    assert receipt["public_dispatch_authorized"] is False


@pytest.mark.parametrize("inspected,authorized", [(2, False), (1, True)])
def test_issuance_rejects_missing_approval_or_incomplete_review(
    tmp_path: Path, inspected: int, authorized: bool
) -> None:
    paths = _issue_paths(tmp_path)
    _write_qa_records(paths, inspected=inspected, authorized=authorized)
    with pytest.raises(ValueError):
        TorwicPrivacyIssuer(paths).issue()
    assert not (paths.review_dir / "privacy_report.json").exists()
    assert not paths.artifact_root.exists()


def test_immutable_evidence_writer_refuses_changed_record(tmp_path: Path) -> None:
    """Reusing an evidence path cannot silently change prior evidence."""
    path = tmp_path / "evidence.json"
    payload = {"value": "first"}
    _write_immutable(path, payload)
    _write_immutable(path, payload)
    with pytest.raises(ValueError, match="differs"):
        _write_immutable(path, {"value": "second"})
