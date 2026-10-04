"""Build REC-02 review evidence for the TorWIC reconstruction frame set."""

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.torwic import prepare_dataset as prep
from scripts.torwic.canonical_dataset import validate_canonical_manifest
from src.models.contracts.artifacts import ArtifactDataClass
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import (
    InputConfiguration,
    InputFile,
    InputManifest,
    SourceType,
)


@dataclass(frozen=True)
class EvidenceConfig:
    """Explicit inputs for a pending REC-02 review packet."""

    dataset_root: Path
    traversal_id: str
    job_id: str
    received_at: datetime
    rights_record: Path | None = None


@dataclass(frozen=True)
class CanonicalSource:
    """Validated REC-01 records used to derive the product selection."""

    preparation: prep.TorwicPreparationManifest
    split: prep.BenchmarkSplit
    dataset_manifest_checksum: str


def _load_source(config: EvidenceConfig) -> CanonicalSource:
    """Load and verify canonical preparation, split and dataset index."""
    traversal = config.traversal_id.lower()
    derived = config.dataset_root / "derived" / traversal
    preparation = validate_canonical_manifest(
        derived / "preparation_manifest.json", config.dataset_root, config.dataset_root
    )
    split = prep.BenchmarkSplit.model_validate_json((derived / "benchmark_split.json").read_text())
    verify_content_checksum(split, "split_checksum")
    dataset = json.loads((config.dataset_root / "dataset_manifest.yaml").read_text())
    expected = canonical_content_checksum(dataset, "dataset_manifest_checksum")
    if dataset["dataset_manifest_checksum"] != expected:
        raise ValueError("Dataset manifest checksum mismatch")
    return CanonicalSource(preparation, split, dataset["dataset_manifest_checksum"])


def _selected_entries(source: CanonicalSource) -> tuple[prep.ManifestFileEntry, ...]:
    """Return only frozen train/reconstruction entries and reject overlap."""
    entries = {item.frame_id: item for item in source.preparation.generated_files if item.frame_id is not None}
    train = source.split.train_frame_ids
    held_out = source.split.held_out_frame_ids
    if len(train) != len(set(train)) or set(train).intersection(held_out):
        raise ValueError("Invalid REC-02 train selection")
    if any(frame_id not in entries for frame_id in train):
        raise ValueError("Train frame is missing from preparation manifest")
    return tuple(entries[frame_id] for frame_id in train)


def _file_ref(config: EvidenceConfig, entry: prep.ManifestFileEntry) -> InputFile:
    """Create one logical product input ref and verify its source bytes."""
    prep.check_safe_path(entry.relative_path)
    path = config.dataset_root / entry.relative_path
    if not path.is_file() or prep.compute_sha256(path) != entry.artifact_checksum:
        raise ValueError(f"Selected frame bytes do not match preparation manifest: {entry.frame_id}")
    name = Path(entry.relative_path).name
    return InputFile(
        original_name=name,
        media_type="image/png",
        size_bytes=path.stat().st_size,
        checksum=entry.artifact_checksum,
        artifact_uri=f"artifact://jobs/{config.job_id}/input/frames/{name}",
        data_class=ArtifactDataClass.PRODUCT_INPUT,
    )


def _rights_attestation(config: EvidenceConfig, source: CanonicalSource) -> dict[str, object]:
    """Bind explicit operator attestation to the frozen reconstruction split."""
    if config.rights_record is None:
        return {"attested": False, "usage_scope": "public_noncommercial_demo", "status": "PENDING_OWNER_ATTESTATION"}
    record = json.loads(config.rights_record.read_text())
    if not isinstance(record, dict) or record.get("attestation_checksum") != canonical_content_checksum(
        record, "attestation_checksum"
    ):
        raise ValueError("Source-rights attestation checksum is invalid")
    expected = (source.split.split_checksum, len(_selected_entries(source)), len(source.split.held_out_frame_ids))
    actual = (
        record.get("selection_checksum"),
        record.get("selected_frame_count"),
        record.get("excluded_held_out_frame_count"),
    )
    if actual != expected or record.get("traversal_id") != config.traversal_id:
        raise ValueError("Source-rights attestation covers a different frame selection")
    if record.get("attested") is not True or record.get("usage_scope") != "public_noncommercial_demo":
        raise ValueError("Source-rights attestation does not authorize this demo scope")
    if not isinstance(record.get("reference"), str) or not record["reference"].strip():
        raise ValueError("Source-rights attestation has no reviewable reference")
    return record


def _preparation_provenance(
    config: EvidenceConfig, source: CanonicalSource, entries: tuple[prep.ManifestFileEntry, ...]
) -> dict[str, object]:
    """Encode the REC-01 lineage used by the candidate manifest."""
    return {
        "scope": "reconstruction_train",
        "traversal_id": config.traversal_id,
        "selected_frame_count": len(entries),
        "held_out_frame_count": len(source.split.held_out_frame_ids),
        "preparation_manifest_checksum": source.preparation.manifest_checksum,
        "split_checksum": source.split.split_checksum,
        "artifact_publication": "pending_rec02a",
    }


def build_input_manifest(config: EvidenceConfig, source: CanonicalSource) -> InputManifest:
    """Build a contract-shaped candidate manifest for REC-02A/QA review."""
    entries = _selected_entries(source)
    manifest = InputManifest(
        schema_version="1.0",
        source_type=SourceType.DATASET,
        received_at=config.received_at,
        files=[_file_ref(config, entry) for entry in entries],
        input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
        source_rights_attestation=_rights_attestation(config, source),
        dataset_manifest_checksum=source.dataset_manifest_checksum,
        preparation_provenance=_preparation_provenance(config, source, entries),
        input_manifest_checksum="sha256:" + "0" * 64,
    )
    payload = manifest.model_dump(mode="json")
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    return InputManifest.model_validate(payload)


def _frame_rows(config: EvidenceConfig, source: CanonicalSource) -> list[dict[str, object]]:
    """Return one checksum-bound inventory row per selected frame."""
    rows = []
    for entry in _selected_entries(source):
        file_ref = _file_ref(config, entry)
        rows.append(
            {
                "frame_id": entry.frame_id,
                "timestamp_sec": entry.timestamp_sec,
                "artifact_uri": file_ref.artifact_uri,
                "checksum": file_ref.checksum,
                "size_bytes": file_ref.size_bytes,
                "role": "reconstruction",
            }
        )
    return rows


def build_frame_inventory(
    config: EvidenceConfig, manifest: InputManifest, source: CanonicalSource
) -> dict[str, object]:
    """Build the auditable 983-frame ID/checksum inventory."""
    frames = _frame_rows(config, source)
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "record_type": "rec02-frame-inventory",
        "status": "PREPARED_FOR_QA_REVIEW",
        "traversal_id": config.traversal_id,
        "usage_scope": "public_noncommercial_demo",
        "input_manifest_checksum": manifest.input_manifest_checksum,
        "selection_checksum": source.split.split_checksum,
        "selected_frame_count": len(frames),
        "held_out_frame_count": len(source.split.held_out_frame_ids),
        "frames": frames,
        "inventory_checksum": "sha256:" + "0" * 64,
    }
    payload["inventory_checksum"] = canonical_content_checksum(payload, "inventory_checksum")
    return payload


def build_privacy_review_packet(
    config: EvidenceConfig, manifest: InputManifest, inventory: dict[str, object]
) -> dict[str, object]:
    """Record review work still required before privacy clearance."""
    rights_attested = manifest.source_rights_attestation.get("attested") is True
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "record_type": "rec02-privacy-review-packet",
        "status": "PENDING_FRAME_INSPECTION_AND_QA_ACCEPTANCE"
        if rights_attested
        else "PENDING_FRAME_INSPECTION_AND_RIGHTS_ATTESTATION",
        "traversal_id": config.traversal_id,
        "input_manifest_checksum": manifest.input_manifest_checksum,
        "frame_inventory_checksum": inventory["inventory_checksum"],
        "proposed_inspection_scope": "all_selected_frames",
        "selected_frame_count": len(manifest.files),
        "inspected_frame_count": 0,
        "findings_status": "UNKNOWN_UNTIL_INSPECTION",
        "rights_attested": rights_attested,
        "qa_accepted": False,
        "usage_scope": "public_noncommercial_demo",
        "privacy_report_result": "NOT_ISSUED",
        "verification_note": "Candidate only; no frame inspection or QA acceptance is claimed.",
        "packet_checksum": "sha256:" + "0" * 64,
    }
    payload["packet_checksum"] = canonical_content_checksum(payload, "packet_checksum")
    return payload


def _parse_datetime(value: str) -> datetime:
    """Parse an explicit timezone-aware receipt timestamp."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("received-at must include a timezone")
    return parsed.astimezone(UTC)


def _write_immutable(path: Path, payload: dict[str, object]) -> None:
    """Write a deterministic JSON record once and refuse changed reuse."""
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"Existing REC-02 evidence differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".rec02_evidence_")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    """Parse explicit evidence-generation inputs."""
    parser = argparse.ArgumentParser(description="Build REC-02 Aisle_CW review evidence")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--traversal-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--received-at", required=True)
    parser.add_argument("--rights-record", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def _config_from_args(args: argparse.Namespace) -> EvidenceConfig:
    """Convert explicit CLI values into the typed evidence configuration."""
    return EvidenceConfig(
        args.dataset_root.resolve(),
        args.traversal_id,
        args.job_id,
        _parse_datetime(args.received_at),
        args.rights_record,
    )


def _write_records(output_root: Path, records: dict[str, dict[str, object]]) -> None:
    """Write all generated records through the immutable writer."""
    for name, payload in records.items():
        _write_immutable(output_root / name, payload)


def _print_summary(manifest: InputManifest, inventory: dict[str, object], packet: dict[str, object]) -> None:
    """Print stable identities for the generated evidence."""
    print(
        json.dumps(
            {
                "input_manifest_checksum": manifest.input_manifest_checksum,
                "selected_frame_count": len(manifest.files),
                "inventory_checksum": inventory["inventory_checksum"],
                "privacy_packet_checksum": packet["packet_checksum"],
                "privacy_report_result": packet["privacy_report_result"],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    """Generate candidate records without fabricating approval or inspection."""
    args = _parse_args()
    config = _config_from_args(args)
    source = _load_source(config)
    manifest = build_input_manifest(config, source)
    inventory = build_frame_inventory(config, manifest, source)
    packet = build_privacy_review_packet(config, manifest, inventory)
    records = {
        "input_manifest.json": manifest.model_dump(mode="json"),
        "frame_inventory.json": inventory,
        "privacy_review_packet.json": packet,
    }
    _write_records(args.output_root, records)
    _print_summary(manifest, inventory, packet)


if __name__ == "__main__":
    main()
