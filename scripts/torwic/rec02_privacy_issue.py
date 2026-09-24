"""Issue a TorWIC privacy report from an exact human review and later approval."""

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.torwic import prepare_dataset as prep
from scripts.torwic.rec02_evidence import _write_immutable
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import InputManifest, PrivacyInspectionScope, PrivacyResult, PrivacyValidationReport
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.rgb.privacy import (
    PrivacyDispatchProof,
    PrivacyInspectionEvidence,
    PrivacyQAAcceptance,
    PrivacyReviewRequest,
    RGBPrivacyGate,
)
from src.services.reconstruction.rgb.publication import RGBPreflightPublisher, VerifiedPrivacyPublication


@dataclass(frozen=True)
class IssuePaths:
    dataset_root: Path
    review_dir: Path
    authorization_path: Path
    artifact_root: Path
    job_id: str


@dataclass(frozen=True)
class ReviewState:
    manifest: InputManifest
    inventory: dict[str, object]
    record: dict[str, object]
    authorization: dict[str, object]


class TorwicPrivacyIssuer:
    """Bind user QA acceptance to exact bytes before report publication."""

    def __init__(self, paths: IssuePaths) -> None:
        self.paths = paths

    @staticmethod
    def _read_record(path: Path, checksum_field: str) -> dict[str, object]:
        record = json.loads(path.read_text())
        if not isinstance(record, dict) or record.get(checksum_field) != canonical_content_checksum(
            record, checksum_field
        ):
            raise ValueError(f"Invalid {checksum_field}")
        return record

    def _load(self) -> ReviewState:
        review = self.paths.review_dir
        manifest = InputManifest.model_validate_json((review / "input_manifest.json").read_text())
        verify_content_checksum(manifest, "input_manifest_checksum")
        inventory = self._read_record(review / "frame_inventory.json", "inventory_checksum")
        packet = self._read_record(review / "privacy_review_packet.json", "packet_checksum")
        record = self._read_record(review / "qa_privacy_acceptance.user_attested.json", "record_checksum")
        authorization = self._read_record(self.paths.authorization_path, "authorization_checksum")
        state = ReviewState(manifest, inventory, record, authorization)
        self._verify_identity(state, packet)
        self._verify_selection(manifest, inventory)
        self._verify_authorization(manifest, record, authorization)
        return state

    def _verify_identity(self, state: ReviewState, packet: dict) -> None:
        review = self.paths.review_dir
        manifest, inventory, record = state.manifest, state.inventory, state.record
        expected = (manifest.input_manifest_checksum, inventory["inventory_checksum"], packet["packet_checksum"])
        actual = (
            record.get("input_manifest_checksum"),
            record.get("frame_inventory_checksum"),
            record.get("privacy_packet_checksum"),
        )
        if actual != expected or inventory.get("input_manifest_checksum") != expected[0]:
            raise ValueError("QA record does not match the REC-02 candidate")
        if record.get("input_manifest_path") != str(review / "input_manifest.json"):
            raise ValueError("QA record points to another InputManifest")
        if record.get("frame_inventory_path") != str(review / "frame_inventory.json"):
            raise ValueError("QA record points to another frame inventory")
        self._verify_rights(manifest)
        if (
            record.get("traversal_id") != "Aisle_CW"
            or record.get("usage_scope") != "public_noncommercial_demo"
            or record.get("selection_checksum") != inventory.get("selection_checksum")
            or record.get("selected_frame_count") != len(inventory["frames"])
        ):
            raise ValueError("QA review scope differs from the frozen selection")
        if packet.get("privacy_report_result") != "NOT_ISSUED":
            raise ValueError("Candidate packet is not pending issuance")

    @staticmethod
    def _verify_rights(manifest: InputManifest) -> None:
        rights = manifest.source_rights_attestation
        if rights.get("attested") is not True or rights.get("usage_scope") != "public_noncommercial_demo":
            raise ValueError("Source rights do not cover this demo")
        if rights.get("attestation_checksum") != canonical_content_checksum(rights, "attestation_checksum"):
            raise ValueError("Source rights attestation checksum mismatch")

    def _verify_selection(self, manifest: InputManifest, inventory: dict) -> None:
        split_path = self.paths.dataset_root / "derived/aisle_cw/benchmark_split.json"
        split = prep.BenchmarkSplit.model_validate_json(split_path.read_text())
        verify_content_checksum(split, "split_checksum")
        rows = inventory["frames"]
        ids = [row["frame_id"] for row in rows]
        if ids != split.train_frame_ids or set(ids) & set(split.held_out_frame_ids):
            raise ValueError("QA inventory differs from frozen reconstruction split")
        if len(rows) != len(manifest.files) or inventory["selection_checksum"] != split.split_checksum:
            raise ValueError("QA inventory differs from InputManifest selection")
        for row, file in zip(rows, manifest.files, strict=True):
            self._verify_frame(row, file)

    def _verify_frame(self, row: dict, file: object) -> None:
        name = f"{row['frame_id']:06d}.png"
        if (
            file.original_name != name
            or row["checksum"] != file.checksum
            or row["artifact_uri"] != file.artifact_uri
            or row["size_bytes"] != file.size_bytes
        ):
            raise ValueError("QA frame identity differs from InputManifest")
        path = self.paths.dataset_root / "normalized/aisle_cw/rgb_frames" / name
        if not path.is_file() or path.stat().st_size != file.size_bytes:
            raise ValueError(f"QA frame bytes are missing or changed: {name}")
        with path.open("rb") as stream:
            checksum = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != file.checksum:
            raise ValueError(f"QA frame checksum differs: {name}")

    @staticmethod
    def _verify_authorization(manifest: InputManifest, record: dict, authorization: dict) -> None:
        expected = (record["record_checksum"], manifest.input_manifest_checksum, record["acceptance_reference"])
        actual = (
            authorization.get("review_record_checksum"),
            authorization.get("input_manifest_checksum"),
            authorization.get("acceptance_reference"),
        )
        if actual != expected or authorization.get("report_issuance_authorized") is not True:
            raise ValueError("Explicit report issuance authorization is missing or mismatched")
        if authorization.get("user_qa_approval") is not True or record.get("qa_accepted") is not True:
            raise ValueError("QA acceptance has not been confirmed")
        if authorization.get("public_dispatch_authorized") is not False:
            raise ValueError("Report issuance cannot authorize public dispatch")
        if not authorization.get("user_confirmation_reference"):
            raise ValueError("Report issuance has no user confirmation reference")

    @staticmethod
    def _inspection(record: dict) -> PrivacyInspectionEvidence:
        if record.get("inspection_scope") != PrivacyInspectionScope.ALL_SELECTED_FRAMES.value:
            raise ValueError("QA inspection must cover all selected frames")
        count = record.get("selected_frame_count")
        if count < 1 or record.get("inspected_frame_count") != count:
            raise ValueError("QA inspection count is incomplete")
        if record.get("unresolved_findings") != [] or record.get("approved_copy_checksum") is not None:
            raise ValueError("QA findings/copy require a separate review path")
        evidence = PrivacyInspectionEvidence(
            PrivacyInspectionScope.ALL_SELECTED_FRAMES, count, count, (), "sha256:" + "0" * 64
        )
        values = asdict(evidence)
        values["evidence_checksum"] = canonical_content_checksum(values, "evidence_checksum")
        return PrivacyInspectionEvidence(**values)

    def issue(self) -> tuple[PrivacyValidationReport, str]:
        state = self._load()
        evidence = self._inspection(state.record)
        acceptance = PrivacyQAAcceptance(
            state.manifest.input_manifest_checksum, evidence.evidence_checksum, state.record["acceptance_reference"]
        )
        gate = RGBPrivacyGate(lambda item: item == acceptance)
        report = gate.evaluate(PrivacyReviewRequest(state.manifest, evidence, acceptance))
        if report.result != PrivacyResult.VERIFIED_ANONYMIZED:
            raise ValueError("QA record did not yield a verified privacy report")
        proof = PrivacyDispatchProof(report, evidence, acceptance)
        store = FilesystemArtifactStore(ArtifactResolver(self.paths.artifact_root))
        publisher = RGBPreflightPublisher(store, gate)
        ref = publisher.publish_verified_privacy(VerifiedPrivacyPublication(state.manifest, proof, self.paths.job_id))
        _write_immutable(self.paths.review_dir / "privacy_report.json", report.model_dump(mode="json"))
        self._write_receipt(state, report, ref.artifact_uri)
        return report, ref.artifact_uri

    def _write_receipt(self, state: ReviewState, report: PrivacyValidationReport, uri: str) -> None:
        payload = {
            "schema_version": "1.0",
            "record_type": "rec02-privacy-issuance-receipt",
            "input_manifest_checksum": state.manifest.input_manifest_checksum,
            "review_record_checksum": state.record["record_checksum"],
            "authorization_checksum": state.authorization["authorization_checksum"],
            "inspection_evidence_checksum": self._inspection(state.record).evidence_checksum,
            "privacy_report_checksum": report.report_checksum,
            "privacy_report_uri": uri,
            "public_dispatch_authorized": False,
            "receipt_checksum": "sha256:" + "0" * 64,
        }
        payload["receipt_checksum"] = canonical_content_checksum(payload, "receipt_checksum")
        _write_immutable(self.paths.review_dir / "privacy_issuance_receipt.json", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue REC-02 privacy report after exact user QA approval")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    paths = IssuePaths(args.dataset_root, args.review_dir, args.authorization, args.artifact_root, args.job_id)
    report, uri = TorwicPrivacyIssuer(paths).issue()
    print(json.dumps({"result": report.result.value, "report_checksum": report.report_checksum, "artifact_uri": uri}))


if __name__ == "__main__":
    main()
