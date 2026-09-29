"""Publish REC-01 vào đúng một TorWIC dataset store đã được sắp xếp."""

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.torwic import prepare_dataset as prep
from src.models.contracts.artifacts import ArtifactDataClass
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum


@dataclass(frozen=True)
class CanonicalValidationContext:
    """Nguồn raw và target normalized để xác minh cùng một traversal."""

    source: prep.TorwicSourceLayout
    output_root: Path
    times: list[str]


def _traversal_dir(traversal_id: str) -> str:
    """Tên traversal chuẩn trong dataset store."""
    prep.check_safe_path(traversal_id)
    return traversal_id.lower()


def _paths(traversal_id: str) -> tuple[str, str, str]:
    """Ba relative roots của cùng một traversal."""
    name = _traversal_dir(traversal_id)
    return f"normalized/{name}", f"derived/{name}", f"evaluation_only/{name}"


def _entry(path: str, root: Path, data_class: ArtifactDataClass) -> prep.ManifestFileEntry:
    """Tạo checksum-bound relative ref."""
    return prep.ManifestFileEntry(
        relative_path=path, artifact_checksum=prep.compute_sha256(root / path), data_class=data_class
    )


def _write_json(path: Path, value: object) -> None:
    """Ghi JSON deterministically vào staging area."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _dataset_record(manifest: prep.TorwicPreparationManifest) -> dict:
    """Dataset-level index; JSON là YAML 1.2 hợp lệ, không thêm dependency."""
    norm, derived, eval_root = _paths(manifest.traversal_id)
    record = {
        "schema_version": "1.0",
        "dataset_name": "TorWIC-SLAM",
        "source_repo": "https://github.com/Viky397/TorWICDataset",
        "source_version": None,
        "license": "CC-BY-NC-4.0-plus-dataset-terms",
        "roots": {"raw": "raw", "normalized": "normalized", "derived": "derived", "evaluation_only": "evaluation_only"},
        "traversals": [
            {
                "traversal_id": manifest.traversal_id,
                "raw_root": f"raw/traversals/{_traversal_dir(manifest.traversal_id)}",
                "normalized_root": norm,
                "derived_root": derived,
                "evaluation_only_root": eval_root,
                "usable_frame_count": manifest.frame_count,
                "preparation_manifest": f"{derived}/preparation_manifest.json",
                "preparation_checksum": manifest.manifest_checksum,
            }
        ],
        "dataset_manifest_checksum": prep.DUMMY_CHK,
    }
    record["dataset_manifest_checksum"] = canonical_content_checksum(record, "dataset_manifest_checksum")
    return record


class CanonicalDatasetPreparer:
    """Stage, validate và publish vào canonical tree mà không đụng raw/GT."""

    def __init__(self, config: prep.PrepConfig) -> None:
        """Giữ config tường minh cho một traversal."""
        self.config = config
        self.source = prep.resolve_source_layout(config.ds_root, config.trav_id)
        self.norm, self.derived, _ = _paths(config.trav_id)

    def _stage_images(self, stage: Path, context: prep.PrepContext) -> tuple[list, list]:
        """Copy mỗi usable frame một lần; role chỉ nằm trong split."""
        ids = sorted(self.config.train_ids + self.config.held_ids)
        target = stage / self.norm / "rgb_frames"
        src_hashes, dst_hashes = prep.copy_images((self.source.image_dir, target), ids)
        source_entries, generated_entries = [], []
        for idx, frame_id in enumerate(ids):
            name = f"{frame_id:06d}.png"
            fields = {
                "data_class": ArtifactDataClass.PRODUCT_INPUT,
                "frame_id": frame_id,
                "timestamp_sec": context.timestamps[frame_id],
            }
            source_entries.append(
                prep.ManifestFileEntry(
                    relative_path=f"{self.source.traversal_ref}/image_left/{name}",
                    artifact_checksum=src_hashes[idx],
                    **fields,
                )
            )
            generated_entries.append(
                prep.ManifestFileEntry(
                    relative_path=f"{self.norm}/rgb_frames/{name}", artifact_checksum=dst_hashes[idx], **fields
                )
            )
        return source_entries, generated_entries

    def _stage_metadata(self, stage: Path, context: prep.PrepContext) -> list:
        """Ghi calibration/timestamps và split theo canonical relative paths."""
        ids = sorted(self.config.train_ids + self.config.held_ids)
        prep.write_timestamps_csv(stage / self.norm, context.timestamps, ids)
        _write_json(stage / self.norm / "calibration.json", prep.build_calibration_payload(context.calib))
        _write_json(stage / self.norm / "coordinate_metadata.json", prep.build_coordinate_payload(context.calib))
        split = prep.BenchmarkSplit(train_frame_ids=self.config.train_ids, held_out_frame_ids=self.config.held_ids)
        split.split_checksum = canonical_content_checksum(split, "split_checksum")
        split_path = stage / self.derived / "benchmark_split.json"
        split_path.parent.mkdir(parents=True, exist_ok=True)
        split_path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
        refs = ["timestamps.csv", "calibration.json", "coordinate_metadata.json"]
        entries = [_entry(f"{self.norm}/{name}", stage, ArtifactDataClass.PRODUCT_INPUT) for name in refs]
        entries.append(_entry(f"{self.derived}/benchmark_split.json", stage, ArtifactDataClass.EVALUATION_ONLY))
        return entries

    def _stage_manifest(self, stage: Path, context: prep.PrepContext) -> prep.TorwicPreparationManifest:
        """Bind mọi relative ref vào cùng source và một publisher version."""
        source_entries, generated_entries = self._stage_images(stage, context)
        generated_entries.extend(self._stage_metadata(stage, context))
        source_entries.extend(
            [
                _entry(self.source.calibration_ref, self.config.ds_root, ArtifactDataClass.PRODUCT_INPUT),
                _entry(
                    f"{self.source.traversal_ref}/frame_times.txt", self.config.ds_root, ArtifactDataClass.PRODUCT_INPUT
                ),
            ]
        )
        manifest = prep.create_manifest(self.config, context, (source_entries, generated_entries))
        manifest.provenance["canonical_publisher_sha256"] = prep.compute_sha256(Path(__file__))
        manifest.manifest_checksum = canonical_content_checksum(manifest, "manifest_checksum")
        (stage / self.derived).mkdir(parents=True, exist_ok=True)
        (stage / self.derived / "preparation_manifest.json").write_text(manifest.model_dump_json(indent=2))
        _write_json(stage / "dataset_manifest.yaml", _dataset_record(manifest))
        return manifest

    def _preflight_publication(self, stage: Path, manifest: prep.TorwicPreparationManifest) -> None:
        """Không overwrite output khác bytes hoặc manifest không rõ lineage."""
        root = self.config.ds_root
        for entry in manifest.generated_files:
            target = root / entry.relative_path
            if target.exists() and prep.compute_sha256(target) != entry.artifact_checksum:
                raise ValueError(f"Canonical output differs: {entry.relative_path}")
        old = root / self.derived / "preparation_manifest.json"
        staged_manifest = stage / self.derived / "preparation_manifest.json"
        if (
            old.exists()
            and old.read_bytes() != staged_manifest.read_bytes()
            and not _legacy_manifest_matches(old, manifest)
        ):
            raise ValueError("Existing preparation manifest is not the expected legacy record")
        dataset_file = root / "dataset_manifest.yaml"
        staged_dataset = stage / "dataset_manifest.yaml"
        if dataset_file.exists() and not _dataset_record_matches(dataset_file, staged_dataset, old):
            raise ValueError("Existing dataset manifest differs")

    def _publish(self, stage: Path, manifest: prep.TorwicPreparationManifest) -> None:
        """Preflight toàn bộ targets; manifest là commit marker cuối cùng."""
        self._preflight_publication(stage, manifest)
        root = self.config.ds_root
        old = root / self.derived / "preparation_manifest.json"
        staged_manifest = stage / self.derived / "preparation_manifest.json"
        dataset_file = root / "dataset_manifest.yaml"
        staged_dataset = stage / "dataset_manifest.yaml"
        self._backup_markers(stage)
        created = []
        try:
            for entry in manifest.generated_files:
                target = root / entry.relative_path
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    (stage / entry.relative_path).replace(target)
                    created.append(target)
            old.parent.mkdir(parents=True, exist_ok=True)
            if not old.exists() or old.read_bytes() != staged_manifest.read_bytes():
                staged_manifest.replace(old)
            if not dataset_file.exists() or dataset_file.read_bytes() != staged_dataset.read_bytes():
                staged_dataset.replace(dataset_file)
        except OSError:
            for target in created:
                target.unlink(missing_ok=True)
            self._restore_markers(stage)
            raise

    def _backup_markers(self, stage: Path) -> None:
        """Lưu marker cũ để rollback nếu publication fail giữa chừng."""
        root = self.config.ds_root
        old = root / self.derived / "preparation_manifest.json"
        dataset_file = root / "dataset_manifest.yaml"
        if old.exists():
            shutil.copy2(old, stage / ".prior_preparation_manifest")
        if dataset_file.exists():
            shutil.copy2(dataset_file, stage / ".prior_dataset_manifest")

    def _restore_markers(self, stage: Path) -> None:
        """Khôi phục cả hai marker cũ nếu bước publish không hoàn tất."""
        root = self.config.ds_root
        markers = (
            (stage / ".prior_preparation_manifest", root / self.derived / "preparation_manifest.json"),
            (stage / ".prior_dataset_manifest", root / "dataset_manifest.yaml"),
        )
        for backup, target in markers:
            if backup.exists():
                backup.replace(target)
            else:
                target.unlink(missing_ok=True)

    def run(self) -> None:
        """Không chấp nhận output root thứ hai cho canonical source."""
        if self.config.out_root.resolve() != self.config.ds_root.resolve():
            raise ValueError("Canonical TorWIC output must be the dataset root")
        context = prep._read_and_validate_inputs(self.config)
        stage = Path(tempfile.mkdtemp(dir=self.config.ds_root.parent, prefix=".torwic_rec01_stage_"))
        try:
            manifest = self._stage_manifest(stage, context)
            validate_canonical_manifest(stage / self.derived / "preparation_manifest.json", self.config.ds_root, stage)
            self._publish(stage, manifest)
            validate_canonical_manifest(
                self.config.ds_root / self.derived / "preparation_manifest.json",
                self.config.ds_root,
                self.config.ds_root,
            )
        finally:
            shutil.rmtree(stage)


def _legacy_manifest_matches(path: Path, expected: prep.TorwicPreparationManifest) -> bool:
    """Chỉ migrate record cũ có đúng split và nguồn; không nhận JSON bất kỳ."""
    try:
        previous = prep.TorwicPreparationManifest(**json.loads(path.read_text()))
        verify_content_checksum(previous, "manifest_checksum")
    except (ValueError, OSError, json.JSONDecodeError):
        return False
    previous_frames = {
        f.frame_id: (f.relative_path, f.artifact_checksum, f.timestamp_sec)
        for f in previous.source_files
        if f.frame_id is not None
    }
    expected_frames = {
        f.frame_id: (f.relative_path, f.artifact_checksum, f.timestamp_sec)
        for f in expected.source_files
        if f.frame_id is not None
    }
    return (
        previous.traversal_id == expected.traversal_id
        and previous.frame_count == expected.frame_count
        and previous.provenance.get("train_ids") == expected.provenance.get("train_ids")
        and previous.provenance.get("held_ids") == expected.provenance.get("held_ids")
        and previous_frames == expected_frames
    )


def _dataset_record_matches(existing: Path, staged: Path, previous_manifest: Path) -> bool:
    """Chỉ cho cập nhật dataset index khi preparation lineage đã đổi."""
    if not existing.read_bytes() or existing.read_bytes() == staged.read_bytes():
        return True
    try:
        current = json.loads(existing.read_text())
        expected = json.loads(staged.read_text())
        previous = prep.TorwicPreparationManifest(**json.loads(previous_manifest.read_text()))
        verify_content_checksum(previous, "manifest_checksum")
        if current["dataset_manifest_checksum"] != canonical_content_checksum(current, "dataset_manifest_checksum"):
            return False
        expected["traversals"][0]["preparation_checksum"] = previous.manifest_checksum
        expected["dataset_manifest_checksum"] = canonical_content_checksum(expected, "dataset_manifest_checksum")
        return current == expected
    except (ValueError, OSError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return False


def validate_canonical_manifest(
    manifest_path: Path, source_root: Path, output_root: Path
) -> prep.TorwicPreparationManifest:
    """Đọc lại source/output, split và dataset index; chặn refs/class giả."""
    manifest = prep.TorwicPreparationManifest(**json.loads(manifest_path.read_text()))
    verify_content_checksum(manifest, "manifest_checksum")
    norm, derived, _ = _paths(manifest.traversal_id)
    source = prep.resolve_source_layout(source_root, manifest.traversal_id)
    context = CanonicalValidationContext(source, output_root, prep.read_timestamps(source.timestamps_file))
    split = prep.BenchmarkSplit(**json.loads((output_root / derived / "benchmark_split.json").read_text()))
    verify_content_checksum(split, "split_checksum")
    _check_canonical_inventory(manifest, split, source)
    _check_canonical_metadata(manifest, split, context)
    prep._verify_all_checksums(manifest, source_root, output_root)
    record = json.loads((output_root / "dataset_manifest.yaml").read_text())
    if record != _dataset_record(manifest):
        raise ValueError("Dataset manifest scope, roots or checksum mismatch")
    return manifest


def _check_canonical_inventory(
    manifest: prep.TorwicPreparationManifest, split: prep.BenchmarkSplit, source: prep.TorwicSourceLayout
) -> None:
    """Một physical RGB set, train/held-out chỉ là disjoint ID sets."""
    train, held = split.train_frame_ids, split.held_out_frame_ids
    ids = sorted(train + held)
    if not train or not held or ids != sorted(set(ids)) or len(ids) != manifest.frame_count:
        raise ValueError("Invalid canonical split coverage")
    if train != sorted(train) or held != sorted(held):
        raise ValueError("Canonical split must be timestamp ordered")
    norm, derived, _ = _paths(manifest.traversal_id)
    src = [f for f in manifest.source_files if f.frame_id is not None]
    gen = [f for f in manifest.generated_files if f.frame_id is not None]
    if [f.frame_id for f in src] != ids or [f.frame_id for f in gen] != ids:
        raise ValueError("Canonical frame inventory mismatch")
    for source_entry, generated_entry in zip(src, gen, strict=True):
        frame_id = source_entry.frame_id
        expected_src = f"{source.traversal_ref}/image_left/{frame_id:06d}.png"
        expected_gen = f"{norm}/rgb_frames/{frame_id:06d}.png"
        if source_entry.relative_path != expected_src or generated_entry.relative_path != expected_gen:
            raise ValueError("Canonical frame path mismatch")
        if (
            source_entry.data_class != ArtifactDataClass.PRODUCT_INPUT
            or generated_entry.data_class != ArtifactDataClass.PRODUCT_INPUT
        ):
            raise ValueError("RGB observation class mismatch")
        if source_entry.artifact_checksum != generated_entry.artifact_checksum:
            raise ValueError("Normalized RGB differs from source")
    _check_canonical_aux_refs(manifest, source)


def _check_canonical_aux_refs(manifest: prep.TorwicPreparationManifest, source: prep.TorwicSourceLayout) -> None:
    """Metadata refs chỉ gồm calibration, timestamps, coordinate và split."""
    norm, derived, _ = _paths(manifest.traversal_id)
    source_meta = [f for f in manifest.source_files if f.frame_id is None]
    expected_source = {source.calibration_ref, f"{source.traversal_ref}/frame_times.txt"}
    if {f.relative_path for f in source_meta} != expected_source or len(source_meta) != 2:
        raise ValueError("Canonical source metadata mismatch")
    generated_meta = [f for f in manifest.generated_files if f.frame_id is None]
    expected_gen = {f"{norm}/{x}" for x in ("timestamps.csv", "calibration.json", "coordinate_metadata.json")}
    expected_gen.add(f"{derived}/benchmark_split.json")
    if {f.relative_path for f in generated_meta} != expected_gen or len(generated_meta) != 4:
        raise ValueError("Canonical generated metadata mismatch")
    for entry in source_meta + generated_meta:
        is_split = entry.relative_path == f"{derived}/benchmark_split.json"
        expected_class = ArtifactDataClass.EVALUATION_ONLY if is_split else ArtifactDataClass.PRODUCT_INPUT
        if entry.data_class != expected_class:
            raise ValueError("Canonical metadata class mismatch")


def _check_canonical_metadata(
    manifest: prep.TorwicPreparationManifest, split: prep.BenchmarkSplit, context: CanonicalValidationContext
) -> None:
    """Đối chiếu timestamp, calibration và provenance với raw source."""
    source, times = context.source, context.times
    calib = prep.parse_calibrations(source.calibration_file)
    ids = set(split.train_frame_ids + split.held_out_frame_ids)
    if any(frame_id < 0 or frame_id >= len(times) for frame_id in ids):
        raise ValueError("Canonical split has frame outside source timeline")
    excluded = prep.preflight_images(
        source.image_dir, len(times), (int(calib["Camera1.width"]), int(calib["Camera1.height"]))
    )
    if manifest.selection_mode == "complete" and len(ids) + len(excluded) != len(times):
        raise ValueError("Canonical complete selection does not cover source")
    if ids.intersection(int(x) for x in excluded):
        raise ValueError("Excluded frame selected")
    if (
        manifest.provenance.get("train_ids") != split.train_frame_ids
        or manifest.provenance.get("held_ids") != split.held_out_frame_ids
    ):
        raise ValueError("Canonical split provenance mismatch")
    if manifest.provenance.get("excluded_frames") != excluded:
        raise ValueError("Canonical exclusion provenance mismatch")
    _check_normalized_metadata(manifest, context)


def _check_normalized_metadata(manifest: prep.TorwicPreparationManifest, context: CanonicalValidationContext) -> None:
    """Xác minh metadata generated với raw và từng frame timestamp."""
    norm, _, _ = _paths(manifest.traversal_id)
    calib = prep.parse_calibrations(context.source.calibration_file)
    ids = {entry.frame_id for entry in manifest.generated_files if entry.frame_id is not None}
    prep._check_csv_exact(context.output_root / norm / "timestamps.csv", ids, context.times)
    for entry in manifest.source_files + manifest.generated_files:
        if entry.frame_id is not None and entry.timestamp_sec != context.times[entry.frame_id]:
            raise ValueError("Canonical frame timestamp mismatch")
    if json.loads((context.output_root / norm / "calibration.json").read_text()) != prep.build_calibration_payload(
        calib
    ):
        raise ValueError("Canonical calibration mismatch")
    expected_coordinate = json.loads(json.dumps(prep.build_coordinate_payload(calib)))
    if json.loads((context.output_root / norm / "coordinate_metadata.json").read_text()) != expected_coordinate:
        raise ValueError("Canonical coordinate metadata mismatch")
