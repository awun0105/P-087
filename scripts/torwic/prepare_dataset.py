"""Script chuẩn bị TorWIC dataset offline."""

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, JsonObject, SchemaVersion
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum

DUMMY_CHK = "sha256:" + "0" * 64


class ManifestFileEntry(ContractModel):
    """Một file nguồn hoặc output với class và checksum bytes."""

    relative_path: str
    artifact_checksum: Checksum
    data_class: ArtifactDataClass
    frame_id: int | None = None
    timestamp_sec: str | None = None


class BenchmarkSplit(ContractModel):
    """Danh sách frame train/held-out đã được khóa theo thứ tự thời gian."""

    schema_version: SchemaVersion = "1.0"
    train_frame_ids: list[int]
    held_out_frame_ids: list[int]
    split_checksum: Checksum = DUMMY_CHK


class TorwicPreparationManifest(ContractModel):
    """Bản kê nguồn và output offline; sample không phải benchmark đã khóa."""

    schema_version: SchemaVersion = "1.0"
    traversal_id: str
    selection_mode: Literal["complete", "sample"]
    frame_count: int
    source_files: list[ManifestFileEntry]
    generated_files: list[ManifestFileEntry]
    provenance: JsonObject
    manifest_checksum: Checksum = DUMMY_CHK


@dataclass
class PrepConfig:
    """Cấu hình tường minh cho một lần chuẩn bị traversal."""

    ds_root: Path
    out_root: Path
    trav_id: str
    train_ids: list[int]
    held_ids: list[int]
    sample: bool = False


@dataclass
class PrepContext:
    """Metadata nguồn đã qua preflight cấu trúc."""

    w: int
    h: int
    timestamps: list[str]
    calib: dict[str, float | str | list[float]]
    excluded: dict[str, str]


@dataclass
class ValCtx:
    """Ngữ cảnh chỉ đọc để xác minh manifest offline."""

    m: TorwicPreparationManifest
    t_set: set[int]
    h_set: set[int]
    times: list[str]
    calib: dict[str, float | str | list[float]]


def compute_sha256(filepath: Path) -> Checksum:
    """Hash bytes của file; không suy checksum từ tên hoặc metadata."""
    h_obj = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(8192):
            h_obj.update(chunk)
    return f"sha256:{h_obj.hexdigest()}"


def _parse_val(v: str) -> float | str | list[float]:
    if v.startswith("[") and v.endswith("]"):
        return [float(x.strip()) for x in v[1:-1].split(",")]
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    return float(v)


def _parse_line(line: str) -> tuple[str, float | str | list[float]] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    idx_eq, idx_col = line.find("="), line.find(":")
    if idx_eq != -1 and idx_col != -1:
        sep = "=" if idx_eq < idx_col else ":"
    elif idx_eq != -1 or idx_col != -1:
        sep = "=" if idx_eq != -1 else ":"
    else:
        raise ValueError("Malformed line")
    k, v = line.split(sep, 1)
    return k.strip(), _parse_val(v.strip())


def parse_calibrations(calib_path: Path) -> dict[str, float | str | list[float]]:
    """Parse calibration TorWIC có cả dấu bằng và dấu hai chấm."""
    calib: dict[str, float | str | list[float]] = {}
    with calib_path.open("r", encoding="utf-8") as f:
        for line in f:
            parsed = _parse_line(line)
            if not parsed:
                continue
            k, v = parsed
            if k in calib:
                raise ValueError("Duplicate key")
            calib[k] = v
    return calib


def preflight_images(img_dir: Path, expected: int, dim: tuple[int, int]) -> dict[str, str]:
    """Liệt kê ảnh thiếu/sai header trước split; full decode thuộc REC-02."""
    excl = {}
    expected_names = {f"{i:06d}.png" for i in range(expected)}
    if {p.name for p in img_dir.glob("*.png")} - expected_names:
        raise ValueError("Unexpected frame outside timestamp sequence")
    for i in range(expected):
        p = img_dir / f"{i:06d}.png"
        if not p.exists():
            excl[str(i)] = "missing"
            continue
        with p.open("rb") as source:
            head = source.read(24)
        if len(head) < 24 or not head.startswith(b"\x89PNG\r\n\x1a\n"):
            excl[str(i)] = "bad_signature"
            continue
        sw, sh = struct.unpack(">LL", head[16:24])
        if (sw, sh) != dim:
            excl[str(i)] = "wrong_resolution"
    return excl


def read_timestamps(times_path: Path) -> list[str]:
    """Giữ chính xác chuỗi timestamp và thứ tự index nguồn."""
    lines = [x.strip() for x in times_path.read_text().splitlines()]
    if not lines or any(not line for line in lines):
        raise ValueError("Empty timestamp row")
    prev = -float("inf")
    for t_str in lines:
        t_float = float(t_str)
        if not math.isfinite(t_float) or t_float <= prev:
            raise ValueError("Timestamps not strictly increasing")
        prev = t_float
    return lines


def validate_intrinsics(calib: dict[str, float | str | list[float]]) -> None:
    """Từ chối nội tham số thiếu, không hữu hạn hoặc sai distortion model."""
    for k in ["Camera1.fx", "Camera1.fy", "Camera1.cx", "Camera1.cy", "Camera1.width", "Camera1.height"]:
        val = calib.get(k)
        if not isinstance(val, (float, int)) or not math.isfinite(val) or val <= 0:
            raise ValueError(f"Invalid intrinsic {k}")
    d = calib.get("Camera1.D")
    if not isinstance(d, list) or len(d) != 5:
        raise ValueError("Must have 5 distortion coeffs")
    for v in d:
        if not isinstance(v, (float, int)) or not math.isfinite(v):
            raise ValueError("Distortion coeff not finite")


def get_transform(calib: dict[str, float | str | list[float]]) -> Transform:
    """Chuyển nhãn TorWIC thành transform có chiều parent_from_local rõ ràng."""
    pfx = "T_cam1_os"
    if calib.get("Camera1.parent_frame_id") != "os_sensor":
        raise ValueError("Unexpected parent_frame_id")
    if calib.get("Camera1.frame_id") != "azure_left_camera":
        raise ValueError("Unexpected frame_id")

    t_list, r_list = [], []
    for k in ("px", "py", "pz"):
        val = calib.get(f"{pfx}.{k}")
        if not isinstance(val, (float, int)) or not math.isfinite(val):
            raise ValueError(f"Invalid translation {k}")
        t_list.append(float(val))
    for k in ("qx", "qy", "qz", "qw"):
        val = calib.get(f"{pfx}.{k}")
        if not isinstance(val, (float, int)) or not math.isfinite(val):
            raise ValueError(f"Invalid rotation {k}")
        r_list.append(float(val))
    return Transform(
        parent_frame="os_sensor",
        local_frame="azure_left_camera",
        translation_xyz=(t_list[0], t_list[1], t_list[2]),
        rotation_quaternion_xyzw=(r_list[0], r_list[1], r_list[2], r_list[3]),
    )


def build_calibration_payload(calib: dict[str, float | str | list[float]]) -> dict:
    """Tạo nội tham số normalized từ calibration nguồn."""
    return {
        "camera_matrix": [
            [calib["Camera1.fx"], 0, calib["Camera1.cx"]],
            [0, calib["Camera1.fy"], calib["Camera1.cy"]],
            [0, 0, 1],
        ],
        "distortion_coefficients": calib["Camera1.D"],
        "image_size": [int(calib["Camera1.width"]), int(calib["Camera1.height"])],
    }


def build_coordinate_payload(calib: dict[str, float | str | list[float]]) -> dict:
    """Giữ giả thuyết hệ trục nguồn tách khỏi đích canonical."""
    return {
        "source_frame_hypothesis": "os_sensor",
        "axis_verification_status": "UNVERIFIED",
        "source_calibration": {
            "raw_label": "T_cam1_os",
            "direction": "T_os_from_cam",
            "transforms": [get_transform(calib).model_dump()],
        },
        "canonical_target": CoordinateSystem().model_dump(),
    }


def parse_id_list(id_str: str) -> list[int]:
    """Parse danh sách ID/range và từ chối ID lặp hoặc range đảo."""
    if not id_str:
        return []
    res = []
    for part in id_str.split(","):
        part = part.strip()
        if not re.fullmatch(r"\d+(?:-\d+)?", part):
            raise ValueError("Invalid frame ID or range")
        if "-" in part:
            s, e = map(int, part.split("-"))
            if e < s:
                raise ValueError("Reversed frame range")
            res.extend(range(s, e + 1))
        else:
            res.append(int(part))
    if len(res) != len(set(res)):
        raise ValueError("Duplicate frame ID")
    return sorted(res)


def copy_images(dirs: tuple[Path, Path], ids: list[int]) -> tuple[list[Checksum], list[Checksum]]:
    """Copy selected frames và hash cả hai phía để kiểm lineage."""
    dirs[1].mkdir(parents=True, exist_ok=True)
    sc, gc = [], []
    for fid in ids:
        name = f"{fid:06d}.png"
        src, dst = dirs[0] / name, dirs[1] / name
        shutil.copy2(src, dst)
        sc.append(compute_sha256(src))
        gc.append(compute_sha256(dst))
    return sc, gc


def build_img_entries(
    ids: list[int], chks: tuple[list[Checksum], list[Checksum]], meta: tuple[ArtifactDataClass, str, list[str]]
) -> tuple[list[ManifestFileEntry], list[ManifestFileEntry]]:
    """Bind path, checksum, class, ID và timestamp cho từng ảnh."""
    s_list, g_list = [], []
    cls, pfx, ts = meta
    for i, fid in enumerate(ids):
        name = f"{fid:06d}.png"
        rel_dst = f"normalized/{name}" if cls == ArtifactDataClass.PRODUCT_INPUT else f"evaluation_only/{name}"
        s_list.append(
            ManifestFileEntry(
                relative_path=f"{pfx}/image_left/{name}",
                artifact_checksum=chks[0][i],
                data_class=cls,
                frame_id=fid,
                timestamp_sec=ts[fid],
            )
        )
        g_list.append(
            ManifestFileEntry(
                relative_path=rel_dst, artifact_checksum=chks[1][i], data_class=cls, frame_id=fid, timestamp_sec=ts[fid]
            )
        )
    return s_list, g_list


def write_timestamps_csv(out_dir: Path, ts: list[str], ids: list[int]) -> Checksum:
    """Ghi timestamp giữ nguyên chuỗi nguồn và thứ tự frame ID."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "timestamps.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_id", "timestamp_sec"])
        for fid in sorted(ids):
            writer.writerow([f"{fid:06d}", ts[fid]])
    return compute_sha256(csv_path)


def write_calibration(out_root: Path, calib: dict[str, float | str | list[float]]) -> Checksum:
    """Ghi calibration normalized và trả checksum bytes."""
    c_json = out_root / "normalized" / "calibration.json"
    with c_json.open("w") as f:
        json.dump(build_calibration_payload(calib), f, indent=2)
    return compute_sha256(c_json)


def write_coordinate_metadata(out_root: Path, calib: dict[str, float | str | list[float]]) -> Checksum:
    """Ghi nguồn transform cùng trạng thái kiểm chứng trục tọa độ."""
    m_json = out_root / "normalized" / "coordinate_metadata.json"
    with m_json.open("w") as f:
        json.dump(build_coordinate_payload(calib), f, indent=2)
    return compute_sha256(m_json)


def write_split(out_root: Path, cfg: PrepConfig) -> tuple[Checksum, BenchmarkSplit]:
    """Ghi split dưới derived với data class evaluation-only trong manifest."""
    split = BenchmarkSplit(train_frame_ids=cfg.train_ids, held_out_frame_ids=cfg.held_ids)
    split.split_checksum = canonical_content_checksum(split, "split_checksum")
    split_path = out_root / "derived" / cfg.trav_id / "benchmark_split.json"
    split_path.parent.mkdir(parents=True, exist_ok=True)
    with split_path.open("w") as f:
        f.write(split.model_dump_json(indent=2))
    return compute_sha256(split_path), split


def check_safe_path(p: str) -> None:
    """Chặn đường dẫn tuyệt đối hoặc thoát khỏi dataset/output root."""
    if ".." in p or p.startswith("/") or "\\" in p:
        raise ValueError("Unsafe path segment")


def setup_images(
    cfg: PrepConfig, ctx: PrepContext, tmp: Path
) -> tuple[list[ManifestFileEntry], list[ManifestFileEntry]]:
    """Tách train vào normalized và held-out vào evaluation-only."""
    sc1, gc1 = copy_images((cfg.ds_root / cfg.trav_id / "image_left", tmp / "normalized"), cfg.train_ids)
    s1, g1 = build_img_entries(
        cfg.train_ids, (sc1, gc1), (ArtifactDataClass.PRODUCT_INPUT, cfg.trav_id, ctx.timestamps)
    )
    sc2, gc2 = copy_images((cfg.ds_root / cfg.trav_id / "image_left", tmp / "evaluation_only"), cfg.held_ids)
    s2, g2 = build_img_entries(
        cfg.held_ids, (sc2, gc2), (ArtifactDataClass.EVALUATION_ONLY, cfg.trav_id, ctx.timestamps)
    )
    return s1 + s2, g1 + g2


def _write_ts_and_split(cfg: PrepConfig, ctx: PrepContext, tmp: Path) -> list[ManifestFileEntry]:
    g = []
    c1 = write_timestamps_csv(tmp / "normalized", ctx.timestamps, cfg.train_ids)
    g.append(
        ManifestFileEntry(
            relative_path="normalized/timestamps.csv", artifact_checksum=c1, data_class=ArtifactDataClass.PRODUCT_INPUT
        )
    )
    c2 = write_timestamps_csv(tmp / "evaluation_only", ctx.timestamps, cfg.held_ids)
    g.append(
        ManifestFileEntry(
            relative_path="evaluation_only/timestamps.csv",
            artifact_checksum=c2,
            data_class=ArtifactDataClass.EVALUATION_ONLY,
        )
    )
    c3, _ = write_split(tmp, cfg)
    g.append(
        ManifestFileEntry(
            relative_path=f"derived/{cfg.trav_id}/benchmark_split.json",
            artifact_checksum=c3,
            data_class=ArtifactDataClass.EVALUATION_ONLY,
        )
    )
    return g


def process_metadata(cfg: PrepConfig, ctx: PrepContext, tmp: Path) -> list[ManifestFileEntry]:
    """Ghi calibration, coordinate, timestamp và split artifacts."""
    g = _write_ts_and_split(cfg, ctx, tmp)
    c_calib = write_calibration(tmp, ctx.calib)
    g.append(
        ManifestFileEntry(
            relative_path="normalized/calibration.json",
            artifact_checksum=c_calib,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
    )
    c_coord = write_coordinate_metadata(tmp, ctx.calib)
    g.append(
        ManifestFileEntry(
            relative_path="normalized/coordinate_metadata.json",
            artifact_checksum=c_coord,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
    )
    return g


def create_manifest(
    cfg: PrepConfig, ctx: PrepContext, lists: tuple[list[ManifestFileEntry], list[ManifestFileEntry]]
) -> TorwicPreparationManifest:
    """Đóng manifest versioned với script, source và split provenance."""
    script_path = Path(__file__).resolve()
    prov = {
        "script": script_path.name,
        "script_sha256": compute_sha256(script_path),
        "traversal_id": cfg.trav_id,
        "train_ids": cfg.train_ids,
        "held_ids": cfg.held_ids,
        "excluded_frames": ctx.excluded,
    }
    manifest = TorwicPreparationManifest(
        traversal_id=cfg.trav_id,
        selection_mode="sample" if cfg.sample else "complete",
        frame_count=len(cfg.train_ids) + len(cfg.held_ids),
        source_files=lists[0],
        generated_files=lists[1],
        provenance=prov,
    )
    manifest.manifest_checksum = canonical_content_checksum(manifest, "manifest_checksum")
    return manifest


def _check_required_metadata(ctx: ValCtx) -> None:
    s_paths = [f.relative_path for f in ctx.m.source_files if f.frame_id is None]
    if len(s_paths) != len(set(s_paths)):
        raise ValueError("Duplicate source metadata paths")
    if set(s_paths) != {"calibrations.txt", f"{ctx.m.traversal_id}/frame_times.txt"}:
        raise ValueError("Invalid source metadata refs")

    g_paths = [f.relative_path for f in ctx.m.generated_files if f.frame_id is None]
    if len(g_paths) != len(set(g_paths)):
        raise ValueError("Duplicate generated metadata paths")
    req_g = {
        "normalized/calibration.json",
        "normalized/coordinate_metadata.json",
        "normalized/timestamps.csv",
        "evaluation_only/timestamps.csv",
        f"derived/{ctx.m.traversal_id}/benchmark_split.json",
    }
    if set(g_paths) != req_g:
        raise ValueError("Invalid generated metadata refs")


def _check_manifest_paths_and_classes(ctx: ValCtx) -> None:
    for f in ctx.m.generated_files:
        is_eval = f.relative_path.startswith("evaluation_only") or f.relative_path.startswith("derived")
        is_norm = f.relative_path.startswith("normalized")
        if is_eval and f.data_class != ArtifactDataClass.EVALUATION_ONLY:
            raise ValueError("Mislabeled data class eval")
        if is_norm and f.data_class != ArtifactDataClass.PRODUCT_INPUT:
            raise ValueError("Mislabeled data class norm")
        if f.frame_id is not None:
            ep = f"evaluation_only/{f.frame_id:06d}.png" if is_eval else f"normalized/{f.frame_id:06d}.png"
            if f.relative_path != ep:
                raise ValueError(f"Generated path mapping mismatch for frame {f.frame_id}")
            if f.frame_id in ctx.t_set and is_eval:
                raise ValueError(f"Train frame {f.frame_id} in eval")
            if f.frame_id in ctx.h_set and is_norm:
                raise ValueError(f"Held frame {f.frame_id} in norm")


def _check_source_classes_and_ids(ctx: ValCtx) -> None:
    src_fids, gen_fids, src_chks = [], [], {}
    for f in ctx.m.source_files:
        if f.frame_id is not None:
            src_fids.append(f.frame_id)
            src_chks[f.frame_id] = f.artifact_checksum
            exp_src = f"{ctx.m.traversal_id}/image_left/{f.frame_id:06d}.png"
            if f.relative_path != exp_src:
                raise ValueError(f"Source path mapping mismatch for frame {f.frame_id}")
            if f.frame_id in ctx.h_set and f.data_class != ArtifactDataClass.EVALUATION_ONLY:
                raise ValueError(f"Source held frame {f.frame_id} must be eval")
            if f.frame_id in ctx.t_set and f.data_class != ArtifactDataClass.PRODUCT_INPUT:
                raise ValueError(f"Source train frame {f.frame_id} must be norm")
    for f in ctx.m.generated_files:
        if f.frame_id is not None:
            gen_fids.append(f.frame_id)
            if f.artifact_checksum != src_chks.get(f.frame_id):
                raise ValueError(f"Image checksum mismatch for frame {f.frame_id}")

    req_fids = sorted(list(ctx.t_set | ctx.h_set))
    if sorted(src_fids) != req_fids or sorted(gen_fids) != req_fids:
        raise ValueError("Selected frame IDs do not match split sets exactly")


def _check_csv_exact(csv_path: Path, expected_set: set[int], times: list[str]) -> None:
    if not expected_set and not csv_path.exists():
        return
    with csv_path.open("r") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != ["frame_id", "timestamp_sec"]:
            raise ValueError("CSV header mismatch")
        rows = list(reader)
    if len(rows) != len(expected_set):
        raise ValueError("CSV row count mismatch")
    seen = set()
    for row in rows:
        if len(row) != 2:
            raise ValueError("CSV row length mismatch")
        fid = int(row[0])
        if fid not in expected_set or fid in seen:
            raise ValueError(f"Unexpected or duplicate frame {fid} in CSV")
        if row[1] != times[fid]:
            raise ValueError(f"CSV timestamp mismatch for frame {fid}")
        seen.add(fid)


def _check_split_and_times(ctx: ValCtx) -> None:
    if ctx.m.frame_count != len(ctx.t_set | ctx.h_set) or ctx.t_set.intersection(ctx.h_set):
        raise ValueError("Invalid frame_count or disjointness")
    if max(ctx.t_set | ctx.h_set, default=-1) >= len(ctx.times) or min(ctx.t_set | ctx.h_set, default=0) < 0:
        raise ValueError("split sets not within source sequence")

    for f in ctx.m.source_files + ctx.m.generated_files:
        if f.frame_id is not None and f.timestamp_sec != ctx.times[f.frame_id]:
            raise ValueError(f"Timestamp mismatch for frame {f.frame_id}")


def _check_semantic_and_provenance(ctx: ValCtx, out_root: Path, ds_root: Path) -> None:
    p = ctx.m.provenance
    if p.get("train_ids") != sorted(ctx.t_set) or p.get("held_ids") != sorted(ctx.h_set):
        raise ValueError("Provenance split mismatch")

    w, h = int(ctx.calib["Camera1.width"]), int(ctx.calib["Camera1.height"])
    excl = preflight_images(ds_root / ctx.m.traversal_id / "image_left", len(ctx.times), (w, h))
    if p.get("excluded_frames", {}) != excl:
        raise ValueError("Provenance excluded_frames mismatch")
    if set(ctx.t_set | ctx.h_set).intersection(int(x) for x in excl.keys()):
        raise ValueError("Selected frame in excluded set")
    if ctx.m.selection_mode == "complete" and len(ctx.t_set) + len(ctx.h_set) + len(excl) != len(ctx.times):
        raise ValueError("Complete split does not cover all valid frames")

    act_calib = json.loads((out_root / "normalized" / "calibration.json").read_text())
    if act_calib != json.loads(json.dumps(build_calibration_payload(ctx.calib))):
        raise ValueError("Semantic mismatch in calibration.json")
    act_coord = json.loads((out_root / "normalized" / "coordinate_metadata.json").read_text())
    if act_coord != json.loads(json.dumps(build_coordinate_payload(ctx.calib))):
        raise ValueError("Semantic mismatch in coordinate_metadata.json")


def _verify_all_checksums(m: TorwicPreparationManifest, ds_root: Path, out_root: Path) -> None:
    for f in m.source_files:
        check_safe_path(f.relative_path)
        if compute_sha256(ds_root / f.relative_path) != f.artifact_checksum:
            raise ValueError(f"Source checksum mismatch: {f.relative_path}")

    for f in m.generated_files:
        check_safe_path(f.relative_path)
        if compute_sha256(out_root / f.relative_path) != f.artifact_checksum:
            raise ValueError(f"Generated checksum mismatch: {f.relative_path}")


def validate_manifest_offline(manifest_path: Path, ds_root: Path, out_root: Path) -> TorwicPreparationManifest:
    """Xác minh checksum, phân lớp và đối chiếu output với nguồn TorWIC."""
    m = TorwicPreparationManifest(**json.loads(manifest_path.read_text()))
    check_safe_path(m.traversal_id)
    verify_content_checksum(m, "manifest_checksum")
    s_path = out_root / "derived" / m.traversal_id / "benchmark_split.json"
    split = BenchmarkSplit(**json.loads(s_path.read_text()))
    verify_content_checksum(split, "split_checksum")
    tl, hl = split.train_frame_ids, split.held_out_frame_ids
    if not tl or not hl or len(tl) != len(set(tl)) or len(hl) != len(set(hl)):
        raise ValueError("Splits contain duplicates or empty")
    if tl != sorted(tl) or hl != sorted(hl):
        raise ValueError("Splits must be sorted")
    times = read_timestamps(ds_root / m.traversal_id / "frame_times.txt")
    calib = parse_calibrations(ds_root / "calibrations.txt")
    ctx = ValCtx(m, set(tl), set(hl), times, calib)

    for fn in (
        _check_split_and_times,
        _check_required_metadata,
        _check_manifest_paths_and_classes,
        _check_source_classes_and_ids,
    ):
        fn(ctx)
    _check_csv_exact(out_root / "normalized" / "timestamps.csv", ctx.t_set, times)
    _check_csv_exact(out_root / "evaluation_only" / "timestamps.csv", ctx.h_set, times)
    _check_semantic_and_provenance(ctx, out_root, ds_root)
    _verify_all_checksums(m, ds_root, out_root)
    return m


def _read_and_validate_inputs(cfg: PrepConfig) -> PrepContext:
    calib = parse_calibrations(cfg.ds_root / "calibrations.txt")
    validate_intrinsics(calib)
    times_file = cfg.ds_root / cfg.trav_id / "frame_times.txt"
    timestamps = read_timestamps(times_file)
    w, h = int(calib["Camera1.width"]), int(calib["Camera1.height"])
    excl = preflight_images(cfg.ds_root / cfg.trav_id / "image_left", len(timestamps), (w, h))

    selected = cfg.train_ids + cfg.held_ids
    if any(x < 0 or x >= len(timestamps) for x in selected):
        raise ValueError("selection contains missing frame IDs")
    if set(cfg.train_ids).intersection(cfg.held_ids):
        raise ValueError("train and held-out sets must be disjoint")
    if len(selected) != len(set(selected)) or not cfg.train_ids or not cfg.held_ids:
        raise ValueError("selection invalid or empty")
    if cfg.train_ids != sorted(cfg.train_ids) or cfg.held_ids != sorted(cfg.held_ids):
        raise ValueError("Selection must be timestamp ordered")
    if any(str(x) in excl for x in selected):
        raise ValueError("selection includes excluded frames")
    if not cfg.sample and len(selected) + len(excl) != len(timestamps):
        raise ValueError("Complete split does not cover all valid frames")

    return PrepContext(w=w, h=h, timestamps=timestamps, calib=calib, excluded=excl)


def _do_prepare(cfg: PrepConfig, tmp_dir: Path) -> None:
    check_safe_path(cfg.trav_id)
    ctx = _read_and_validate_inputs(cfg)
    s_list, g_list = setup_images(cfg, ctx, tmp_dir)
    g_list.extend(process_metadata(cfg, ctx, tmp_dir))

    calib_chk = compute_sha256(cfg.ds_root / "calibrations.txt")
    s_list.append(
        ManifestFileEntry(
            relative_path="calibrations.txt", artifact_checksum=calib_chk, data_class=ArtifactDataClass.PRODUCT_INPUT
        )
    )
    times_chk = compute_sha256(cfg.ds_root / cfg.trav_id / "frame_times.txt")
    s_list.append(
        ManifestFileEntry(
            relative_path=f"{cfg.trav_id}/frame_times.txt",
            artifact_checksum=times_chk,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
    )

    manifest = create_manifest(cfg, ctx, (s_list, g_list))
    with (tmp_dir / "manifest.json").open("w") as f:
        f.write(manifest.model_dump_json(indent=2))
    validate_manifest_offline(tmp_dir / "manifest.json", cfg.ds_root, tmp_dir)


def run_safely(cfg: PrepConfig) -> None:
    """Publish nguyên tử; lỗi sẽ xóa vùng tạm và giữ nguyên nguồn."""
    if cfg.out_root.exists():
        raise ValueError("Output already exists")
    if cfg.out_root.resolve().is_relative_to(cfg.ds_root.resolve()):
        raise ValueError("Output within source root")
    cfg.out_root.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(dir=cfg.out_root.parent, prefix=cfg.out_root.name + "_tmp_"))
    try:
        _do_prepare(cfg, tmp_dir)
        tmp_dir.rename(cfg.out_root)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def parse_args() -> PrepConfig:
    """Nhận split tường minh; --sample chỉ dùng cho smoke subset."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--traversal-id", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--frame-ids", required=True)
    parser.add_argument("--held-out-ids", required=True)
    parser.add_argument("--sample", action="store_true")
    opts = parser.parse_args()
    return PrepConfig(
        ds_root=Path(opts.dataset_root),
        out_root=Path(opts.output_root),
        trav_id=opts.traversal_id,
        train_ids=parse_id_list(opts.frame_ids),
        held_ids=parse_id_list(opts.held_out_ids),
        sample=opts.sample,
    )


def main() -> None:
    """Entry point."""
    try:
        cfg = parse_args()
        run_safely(cfg)
    except FileNotFoundError as e:
        name = Path(e.filename).name if e.filename else "unknown"
        raise SystemExit(f"Missing required dataset component: {name}")


if __name__ == "__main__":
    main()
