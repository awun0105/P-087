import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

import pytest

from scripts.torwic.prepare_dataset import (
    BenchmarkSplit,
    PrepConfig,
    TorwicPreparationManifest,
    compute_sha256,
    main,
    parse_id_list,
    run_safely,
    validate_manifest_offline,
)


def _png_rgba(value: int) -> bytes:
    """Tạo PNG thật với pixel khác nhau để kiểm tra checksum ảnh."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixel = zlib.compress(bytes((0, value, 0, 0, 255)))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


def _setup_mock_dataset(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    calib = root / "calibrations.txt"
    calib.write_text(
        "Camera1.fx: 100.0\nCamera1.cx: 50.0\nCamera1.fy: 100.0\nCamera1.cy: 50.0\n"
        "Camera1.width: 1\nCamera1.height: 1\nCamera1.D: [0,0,0,0,0]\n"
        'Camera1.parent_frame_id: "os_sensor"\nCamera1.frame_id: "azure_left_camera"\n'
        "T_cam1_os.px: 0\nT_cam1_os.py: 0\nT_cam1_os.pz: 0\n"
        "T_cam1_os.qx: 0\nT_cam1_os.qy: 0\nT_cam1_os.qz: 0\nT_cam1_os.qw: 1\n"
    )
    trav_dir = root / "Aisle_CW"
    trav_dir.mkdir(parents=True, exist_ok=True)
    (trav_dir / "frame_times.txt").write_text("0.0\n0.1\n0.2\n0.3\n")
    img_dir = trav_dir / "image_left"
    img_dir.mkdir(exist_ok=True)
    for i in range(4):
        (img_dir / f"{i:06d}.png").write_bytes(_png_rgba(i))
    return root


def _setup_canonical_dataset(root: Path) -> Path:
    """Dựng layout raw/global + raw/traversals giống data/torwic_slam."""
    _setup_mock_dataset(root)
    global_dir = root / "raw" / "global"
    traversal_dir = root / "raw" / "traversals"
    global_dir.mkdir(parents=True)
    traversal_dir.mkdir(parents=True)
    (root / "calibrations.txt").rename(global_dir / "calibrations.txt")
    (root / "Aisle_CW").rename(traversal_dir / "aisle_cw")
    return root


def test_prepare_canonical_layout_and_validate(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    out = root
    before = [compute_sha256(path) for path in sorted((root / "raw").rglob("*")) if path.is_file()]
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    manifest = validate_manifest_offline(out / "derived/aisle_cw/preparation_manifest.json", root, out)
    refs = {entry.relative_path for entry in manifest.source_files}
    assert "raw/global/calibrations.txt" in refs
    assert "raw/traversals/aisle_cw/frame_times.txt" in refs
    assert "raw/traversals/aisle_cw/image_left/000000.png" in refs
    assert len(list((root / "normalized/aisle_cw/rgb_frames").glob("*.png"))) == 4
    assert not list((root / "evaluation_only").rglob("*.png"))
    assert (root / "dataset_manifest.yaml").is_file()
    assert {f.data_class.value for f in manifest.generated_files if f.frame_id is not None} == {"product_input"}
    split = json.loads((root / "derived/aisle_cw/benchmark_split.json").read_text())
    assert split["train_frame_ids"] == [0, 1, 2]
    assert split["held_out_frame_ids"] == [3]
    assert (root / "normalized/aisle_cw/rgb_frames/000003.png").exists()
    assert before == [compute_sha256(path) for path in sorted((root / "raw").rglob("*")) if path.is_file()]


def test_canonical_layout_missing_calibration_fails_closed(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    (root / "raw" / "global" / "calibrations.txt").unlink()
    cfg = PrepConfig(ds_root=root, out_root=root, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(FileNotFoundError):
        run_safely(cfg)


def test_canonical_layout_rejects_second_output_root(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    out = tmp_path / "duplicate"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="dataset root"):
        run_safely(cfg)
    assert not out.exists()


def test_canonical_run_is_idempotent(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    cfg = PrepConfig(ds_root=root, out_root=root, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    manifest_path = root / "derived/aisle_cw/preparation_manifest.json"
    before = compute_sha256(manifest_path)
    run_safely(cfg)
    assert compute_sha256(manifest_path) == before
    assert len(list((root / "normalized/aisle_cw/rgb_frames").glob("*.png"))) == 4


def test_canonical_existing_rgb_difference_is_rejected(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    cfg = PrepConfig(ds_root=root, out_root=root, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    image = root / "normalized/aisle_cw/rgb_frames/000000.png"
    image.write_bytes(_png_rgba(99))
    before = compute_sha256(image)
    with pytest.raises(ValueError, match="Canonical output differs"):
        run_safely(cfg)
    assert compute_sha256(image) == before


def test_canonical_rejects_forged_heldout_frame_path(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    cfg = PrepConfig(ds_root=root, out_root=root, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    manifest_path = root / "derived/aisle_cw/preparation_manifest.json"
    data = json.loads(manifest_path.read_text())
    data["generated_files"][3]["relative_path"] = "evaluation_only/aisle_cw/rgb_frames/000003.png"
    from src.models.contracts.identity import canonical_content_checksum

    data["manifest_checksum"] = canonical_content_checksum(TorwicPreparationManifest(**data), "manifest_checksum")
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Canonical frame path mismatch"):
        validate_manifest_offline(manifest_path, root, root)


def test_canonical_rejects_modified_dataset_index(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    cfg = PrepConfig(ds_root=root, out_root=root, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    dataset_file = root / "dataset_manifest.yaml"
    index = json.loads(dataset_file.read_text())
    index["traversals"][0]["usable_frame_count"] = 3
    dataset_file.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="Dataset manifest"):
        validate_manifest_offline(root / "derived/aisle_cw/preparation_manifest.json", root, root)


def test_prepare_dataset_synthetic_and_validate(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    raw_hashes = [compute_sha256(path) for path in sorted(root.rglob("*")) if path.is_file()]
    run_safely(cfg)
    m_path = out / "manifest.json"
    assert m_path.exists()
    manifest = validate_manifest_offline(m_path, root, out)
    assert manifest.selection_mode == "complete"
    assert manifest.frame_count == 4
    assert [compute_sha256(path) for path in sorted(root.rglob("*")) if path.is_file()] == raw_hashes
    assert not (out / "normalized" / "000003.png").exists()
    assert (out / "evaluation_only" / "000003.png").exists()
    split_ref = next(f for f in manifest.generated_files if f.relative_path.endswith("benchmark_split.json"))
    assert split_ref.data_class.value == "evaluation_only"


def test_negative_wrong_layout_missing_component(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    (root / "calibrations.txt").unlink()
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(FileNotFoundError):
        run_safely(cfg)


def test_negative_tampered_split_checksum(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    s_path = out / "derived" / "Aisle_CW" / "benchmark_split.json"
    s_data = json.loads(s_path.read_text())
    s_data["train_frame_ids"] = [0, 1]
    s_path.write_text(json.dumps(s_data))
    from src.models.contracts.identity import canonical_content_checksum

    s_model = BenchmarkSplit(**s_data)
    s_data["split_checksum"] = canonical_content_checksum(s_model, "split_checksum")
    s_path.write_text(json.dumps(s_data))
    new_chk = compute_sha256(s_path)
    for f in m_data["generated_files"]:
        if f["relative_path"].endswith("benchmark_split.json"):
            f["artifact_checksum"] = new_chk
    m_model = TorwicPreparationManifest(**m_data)
    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Invalid frame_count or disjointness"):
        validate_manifest_offline(m_path, root, out)


def test_negative_wrong_frame_timestamp(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    for f in m_data["generated_files"]:
        if f["frame_id"] == 0:
            f["timestamp_sec"] = "999999"
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Timestamp mismatch for frame 0"):
        validate_manifest_offline(m_path, root, out)


def test_parse_multiple_ranges() -> None:
    assert parse_id_list("1,2-5,7") == [1, 2, 3, 4, 5, 7]
    assert parse_id_list("118-153, 528-564, 937-972") == list(range(118, 154)) + list(range(528, 565)) + list(
        range(937, 973)
    )


def test_negative_excluded_frame(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    (root / "Aisle_CW" / "image_left" / "000003.png").unlink()
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="selection includes excluded frames"):
        run_safely(cfg)
    cfg2 = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1], held_ids=[2])
    run_safely(cfg2)
    m_data = json.loads((out / "manifest.json").read_text())
    assert m_data["provenance"]["excluded_frames"] == {"3": "missing"}


def test_negative_split_metadata_not_eval_only(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    for f in m_data["generated_files"]:
        if f["relative_path"].endswith("benchmark_split.json"):
            f["data_class"] = "product_input"
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Mislabeled data class eval"):
        validate_manifest_offline(m_path, root, out)


def test_negative_missing_source_calibrations_entry(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    m_data["source_files"] = [f for f in m_data["source_files"] if f["relative_path"] != "calibrations.txt"]
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Invalid source metadata refs"):
        validate_manifest_offline(m_path, root, out)


def test_negative_missing_generated_coordinate_metadata(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    m_data["generated_files"] = [
        f for f in m_data["generated_files"] if f["relative_path"] != "normalized/coordinate_metadata.json"
    ]
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Invalid generated metadata refs"):
        validate_manifest_offline(m_path, root, out)


def test_negative_duplicate_split_id(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    s_path = out / "derived" / "Aisle_CW" / "benchmark_split.json"
    s_data = json.loads(s_path.read_text())
    s_data["train_frame_ids"].append(0)
    s_model = BenchmarkSplit(**s_data)
    from src.models.contracts.identity import canonical_content_checksum

    s_data["split_checksum"] = canonical_content_checksum(s_model, "split_checksum")
    s_path.write_text(json.dumps(s_data))
    new_chk = compute_sha256(s_path)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    for f in m_data["generated_files"]:
        if f["relative_path"].endswith("benchmark_split.json"):
            f["artifact_checksum"] = new_chk
    m_model = TorwicPreparationManifest(**m_data)
    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Splits contain duplicates"):
        validate_manifest_offline(m_path, root, out)


def test_negative_swapped_frame_ids(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    e0, e1 = None, None
    for f in m_data["generated_files"]:
        if f["frame_id"] == 0:
            e0 = f
        if f["frame_id"] == 1:
            e1 = f
    e0["frame_id"], e1["frame_id"] = e1["frame_id"], e0["frame_id"]
    e0["timestamp_sec"], e1["timestamp_sec"] = e1["timestamp_sec"], e0["timestamp_sec"]
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Generated path mapping mismatch"):
        validate_manifest_offline(m_path, root, out)


def test_negative_duplicate_metadata_entry(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    for f in m_data["generated_files"]:
        if f["relative_path"] == "normalized/calibration.json":
            m_data["generated_files"].append(dict(f))
            break
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Duplicate generated metadata"):
        validate_manifest_offline(m_path, root, out)


def test_negative_semantic_calibration_mismatch(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    c_path = out / "normalized" / "calibration.json"
    c_data = json.loads(c_path.read_text())
    c_data["camera_matrix"][0][0] = 999.0
    c_path.write_text(json.dumps(c_data))
    new_chk = compute_sha256(c_path)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    for f in m_data["generated_files"]:
        if f["relative_path"] == "normalized/calibration.json":
            f["artifact_checksum"] = new_chk
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Semantic mismatch in calibration.json"):
        validate_manifest_offline(m_path, root, out)


def test_negative_provenance_split_mismatch(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    m_data["provenance"]["train_ids"] = [0, 1]
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Provenance split mismatch"):
        validate_manifest_offline(m_path, root, out)


def test_negative_image_bytes_mismatch(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    img0 = out / "normalized" / "000000.png"
    img1 = out / "normalized" / "000001.png"
    shutil.copy2(img1, img0)
    new_chk = compute_sha256(img0)
    for f in m_data["generated_files"]:
        if f["relative_path"] == "normalized/000000.png":
            f["artifact_checksum"] = new_chk
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Image checksum mismatch for frame 0"):
        validate_manifest_offline(m_path, root, out)


def test_negative_duplicate_generated_frame_entry(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    e0 = next(f for f in m_data["generated_files"] if f["frame_id"] == 0)
    m_data["generated_files"].append(dict(e0))
    m_model = TorwicPreparationManifest(**m_data)
    from src.models.contracts.identity import canonical_content_checksum

    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Selected frame IDs do not match split sets exactly"):
        validate_manifest_offline(m_path, root, out)


def test_negative_train_held_not_disjoint(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1], held_ids=[1, 2])
    with pytest.raises(ValueError, match="train and held-out sets must be disjoint"):
        run_safely(cfg)


def test_negative_missing_frame_times(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    (root / "Aisle_CW" / "frame_times.txt").unlink()
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(FileNotFoundError):
        run_safely(cfg)


def test_negative_wrong_png_signature(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    (root / "Aisle_CW" / "image_left" / "000000.png").write_bytes(b"wrong_signature_header1234567890")
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1], held_ids=[2])
    with pytest.raises(ValueError, match="selection includes excluded frames"):
        run_safely(cfg)

    # check reason
    cfg2 = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[1, 2], held_ids=[3])
    run_safely(cfg2)
    m_data = json.loads((out / "manifest.json").read_text())
    assert m_data["provenance"]["excluded_frames"]["0"] == "bad_signature"


def test_negative_wrong_png_resolution(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    # width 2, height 2
    valid_png_2x2 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\x99c\xf8\x0f\x04\x00\x09\xfb\x03\xfd\xe3U\xf2\x9c\x00\x00\x00\x00IEND\xaeB`\x82"
    (root / "Aisle_CW" / "image_left" / "000000.png").write_bytes(valid_png_2x2)
    cfg2 = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[1, 2], held_ids=[3])
    run_safely(cfg2)
    m_data = json.loads((out / "manifest.json").read_text())
    assert m_data["provenance"]["excluded_frames"]["0"] == "wrong_resolution"


def test_negative_non_strictly_increasing_timestamps(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    (root / "Aisle_CW" / "frame_times.txt").write_text("0.0\n0.1\n0.1\n0.3\n")
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="Timestamps not strictly increasing"):
        run_safely(cfg)


def test_negative_unsorted_split_ids(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(cfg)
    m_path = out / "manifest.json"
    m_data = json.loads(m_path.read_text())
    s_path = out / "derived" / "Aisle_CW" / "benchmark_split.json"
    s_data = json.loads(s_path.read_text())
    s_data["train_frame_ids"] = [1, 0, 2]  # Unsorted
    from src.models.contracts.identity import canonical_content_checksum

    s_model = BenchmarkSplit(**s_data)
    s_data["split_checksum"] = canonical_content_checksum(s_model, "split_checksum")
    s_path.write_text(json.dumps(s_data))
    new_chk = compute_sha256(s_path)
    for f in m_data["generated_files"]:
        if f["relative_path"].endswith("benchmark_split.json"):
            f["artifact_checksum"] = new_chk
    m_model = TorwicPreparationManifest(**m_data)
    m_data["manifest_checksum"] = canonical_content_checksum(m_model, "manifest_checksum")
    m_path.write_text(json.dumps(m_data))
    with pytest.raises(ValueError, match="Splits must be sorted"):
        validate_manifest_offline(m_path, root, out)


def test_negative_too_many_frames(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3, 4])
    with pytest.raises(ValueError, match="selection contains missing frame IDs"):
        run_safely(cfg)


def test_negative_invalid_intrinsics(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    calib = root / "calibrations.txt"
    txt = calib.read_text()
    calib.write_text(txt.replace("Camera1.fx: 100.0", "Camera1.fx: -100.0"))
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="Invalid intrinsic Camera1.fx"):
        run_safely(cfg)


def test_sample_mode_is_explicit_and_cannot_claim_complete(tmp_path: Path) -> None:
    """Subset smoke phải có mode riêng, không được giả split benchmark đầy đủ."""
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0], held_ids=[1])
    with pytest.raises(ValueError, match="Complete split does not cover"):
        run_safely(cfg)
    cfg.sample = True
    run_safely(cfg)
    manifest_path = out / "manifest.json"
    manifest = validate_manifest_offline(manifest_path, root, out)
    assert manifest.selection_mode == "sample"

    data = json.loads(manifest_path.read_text())
    data["selection_mode"] = "complete"
    from src.models.contracts.identity import canonical_content_checksum

    data["manifest_checksum"] = canonical_content_checksum(TorwicPreparationManifest(**data), "manifest_checksum")
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Complete split does not cover"):
        validate_manifest_offline(manifest_path, root, out)


def test_unexpected_image_id_fails_before_publication(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    (root / "Aisle_CW" / "image_left" / "000004.png").write_bytes(_png_rgba(4))
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="Unexpected frame"):
        run_safely(cfg)
    assert not out.exists()


@pytest.mark.parametrize("ids", ["0,0", "0-2,2", "3-1", "1,,2", "-1"])
def test_invalid_id_range_rejected(ids: str) -> None:
    with pytest.raises(ValueError):
        parse_id_list(ids)


def test_cli_missing_component_does_not_leak_source_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "private_source"
    root.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_dataset",
            "--dataset-root",
            str(root),
            "--traversal-id",
            "Aisle_CW",
            "--output-root",
            str(tmp_path / "out"),
            "--frame-ids",
            "0",
            "--held-out-ids",
            "1",
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert "calibrations.txt" in str(error.value)
    assert str(root) not in str(error.value)


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "owner_data.txt"
    marker.write_text("preserve")
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="Output already exists"):
        run_safely(cfg)
    assert marker.read_text() == "preserve"


def test_failed_preparation_leaves_no_partial_output(tmp_path: Path) -> None:
    root = _setup_mock_dataset(tmp_path / "dataset")
    calib = root / "calibrations.txt"
    calib.write_text(calib.read_text().replace("Camera1.fx: 100.0", "Camera1.fx: -100.0"))
    out = tmp_path / "out"
    cfg = PrepConfig(ds_root=root, out_root=out, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    with pytest.raises(ValueError, match="Invalid intrinsic Camera1.fx"):
        run_safely(cfg)
    assert not out.exists()
    assert not list(tmp_path.glob("out_tmp_*"))
