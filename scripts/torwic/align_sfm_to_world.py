"""Chuẩn bị offline: căn chỉnh SfM của một job Aisle_CW sang `world` (mét) qua quỹ đạo camera.

REC-09, ADR 0004 §5 (demo hướng anchor người dùng lấy số đo từ LiDAR). Dataset
preparation, không phải runtime: đọc `traj_gt.txt` nên kết quả là **GT-assisted**
(DATASET_PLAYBOOK §Phân loại tài nguyên). Chỉ dùng cho demo/integration, không claim
độ chính xác RGB-only độc lập.

Các bước:
1. Ghép frame của job (trích từ video) với ảnh `image_left` theo nội dung ảnh thu nhỏ,
   rồi kiểm các chỉ số ghép được nằm đúng trên một quan hệ tuyến tính nguyên
   (video dựng từ dãy ảnh liên tiếp/cách đều); lệch thì dừng, không đoán.
2. Tâm camera trong map = T_map_from_os(i) · t_os_from_cam (chuỗi camera đã verify ở REC-09).
3. map → world qua cầu nối tọa độ owner đã chốt (sàn về z = 0).
4. Fit đồng dạng SfM → world (Umeyama) trên tâm camera, báo residual.

Ví dụ:
    python -m scripts.torwic.align_sfm_to_world \\
        --poses <store>/jobs/<job>/attempts/<attempt>/rec03/camera_poses.json \\
        --frames <store>/jobs/<job>/rec02a/frames \\
        --traversal data/torwic_slam/raw/traversals/aisle_cw \\
        --coordinates data/torwic_slam/normalized/aisle_cw/coordinate_metadata.json \\
        --bridge configs/datasets/torwic_aisle_cw/coordinate_bridge.json \\
        --output data/torwic_slam/derived/aisle_cw/rec09_alignment_<job>/alignment.json
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from src.models.contracts.coordinates import Transform
from src.services.reconstruction.alignment.similarity import fit_similarity
from src.services.reconstruction.alignment.transforms import compose_transforms
from src.services.reconstruction.lidar.coordinate_bridge import load_bridge_decision
from src.services.reconstruction.rgb.canonical.metric_math import rotate

THUMB_W, THUMB_H = 80, 45
#: Frame ghép phải tốt hơn hẳn ứng viên không liền kề (tỉ lệ sai số).
MATCH_MARGIN = 0.5


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def _thumbnails(pattern_args: list[str], count_hint: int | None = None) -> np.ndarray:
    """Giải ảnh bằng ffmpeg thành ảnh xám 80×45 (không cần Pillow/OpenCV)."""
    command = [
        "ffmpeg",
        "-loglevel",
        "error",
        *pattern_args,
        "-vf",
        f"scale={THUMB_W}:{THUMB_H}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    raw = subprocess.run(command, check=True, capture_output=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, THUMB_H * THUMB_W).astype(np.float32)
    if count_hint is not None and len(frames) != count_hint:
        raise ValueError(f"ffmpeg trả {len(frames)} ảnh, cần {count_hint}")
    frames -= frames.mean(axis=1, keepdims=True)
    frames /= np.linalg.norm(frames, axis=1, keepdims=True) + 1e-6
    return frames


def match_frames(job_frames: Path, dataset_images: Path) -> dict[int, int]:
    """frame_id của job → chỉ số ảnh dataset; kiểm quan hệ tuyến tính nguyên."""
    names = sorted(job_frames.glob("*.png"))
    if not names:
        raise ValueError("job không có frame PNG")
    job_ids = [int(path.stem) for path in names]
    dataset_count = len(list(dataset_images.glob("*.png")))
    job = _thumbnails(["-pattern_type", "glob", "-i", str(job_frames / "*.png")], len(names))
    data = _thumbnails(["-framerate", "1", "-i", str(dataset_images / "%06d.png")], dataset_count)
    distance = 2.0 - 2.0 * job @ data.T  # khoảng cách bình phương của vector chuẩn hóa
    best = distance.argmin(axis=1)
    for row, index in enumerate(best):
        far = np.abs(np.arange(dataset_count) - index) > 5
        if distance[row, index] > MATCH_MARGIN * distance[row, far].min():
            raise ValueError(f"frame {job_ids[row]} không ghép rõ ràng với ảnh dataset nào")
    slope, intercept = np.polyfit(job_ids, best, 1)
    step, offset = round(slope), round(intercept)
    predicted = [step * frame_id + offset for frame_id in job_ids]
    mismatched = [fid for fid, got, want in zip(job_ids, best, predicted, strict=True) if got != want]
    if step < 1 or mismatched:
        raise ValueError(f"frame ghép không theo dãy đều (step={slope:.3f}); lệch ở {mismatched[:10]}")
    return dict(zip(job_ids, (int(value) for value in best), strict=True))


def _map_camera_centers(traj: Path, times: Path, coordinates: Path) -> list[tuple[float, float, float]]:
    """Tâm camera trong map cho từng ảnh; pose i ↔ ảnh i theo cùng timestamp."""
    poses = [line.split() for line in traj.read_text().splitlines() if line.strip()]
    stamps = [float(line) for line in times.read_text().splitlines() if line.strip()]
    metadata = json.loads(coordinates.read_text())
    extrinsic = Transform.model_validate(metadata["source_calibration"]["transforms"][0])
    if (extrinsic.parent_frame, extrinsic.local_frame) != ("os_sensor", "azure_left_camera"):
        raise ValueError("extrinsic phải là T_os_from_cam")
    centers = []
    for index, values in enumerate(poses):
        if abs(float(values[0]) - stamps[index]) > 1e-6:
            raise ValueError(f"timestamp pose {index} khác frame_times")
        map_from_os = Transform(
            parent_frame="torwic_map",
            local_frame="os_sensor",
            translation_xyz=tuple(float(v) for v in values[1:4]),
            rotation_quaternion_xyzw=tuple(float(v) for v in values[4:8]),
        )
        centers.append(compose_transforms(map_from_os, extrinsic).translation_xyz)
    return centers


def align(args: argparse.Namespace) -> dict:
    """Chạy đủ 4 bước, trả payload JSON (chưa ghi)."""
    poses_doc = json.loads(args.poses.read_text())
    if poses_doc.get("transform_semantics") != "parent_from_local" or poses_doc.get("parent_frame") != "sfm_world":
        raise ValueError("camera_poses phải là sfm_world_from_camera")
    matches = match_frames(args.frames, args.traversal / "image_left")
    centers_map = _map_camera_centers(
        args.traversal / "traj_gt.txt", args.traversal / "frame_times.txt", args.coordinates
    )
    bridge = load_bridge_decision(args.bridge)
    world_from_map = bridge.transform()

    def to_world(point: tuple[float, float, float]) -> tuple[float, float, float]:
        rotated = rotate(point, world_from_map.rotation_quaternion_xyzw)
        return tuple(a + b for a, b in zip(rotated, world_from_map.translation_xyz, strict=True))  # type: ignore[return-value]

    pairs = [
        (pose["frame_id"], tuple(pose["translation"]), to_world(centers_map[matches[pose["frame_id"]]]))
        for pose in poses_doc["poses"]
    ]
    fit = fit_similarity([pair[1] for pair in pairs], [pair[2] for pair in pairs])
    return {
        "schema_version": "1.0",
        "artifact_type": "SfmWorldTrajectoryAlignment",
        "method": "camera_trajectory_umeyama",
        "target_frame": "world",
        "source_frame": "sfm_world",
        "ground_truth_assisted": True,
        "assistance": "traj_gt.txt dùng cho dataset preparation (DATASET_PLAYBOOK); không phải độ chính xác RGB-only",
        "fit": fit.model_dump(mode="json"),
        "frame_matches": [
            {"frame_id": fid, "dataset_index": matches[fid], "residual_m": res}
            for (fid, _, _), res in zip(pairs, fit.residuals, strict=True)
        ],
        "inputs": {
            "camera_poses_checksum": _sha256(args.poses),
            "camera_poses_artifact_checksum": poses_doc.get("artifact_checksum"),
            "traj_gt_checksum": _sha256(args.traversal / "traj_gt.txt"),
            "frame_times_checksum": _sha256(args.traversal / "frame_times.txt"),
            "coordinate_metadata_checksum": _sha256(args.coordinates),
            "coordinate_bridge_checksum": bridge.checksum(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI offline; in tóm tắt residual, ghi JSON bất biến (không ghi đè)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("poses", "frames", "traversal", "coordinates", "bridge", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = align(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    fit = payload["fit"]
    print(
        json.dumps(
            {
                "pairs": fit["pair_count"],
                "scale_m_per_sfm_unit": fit["scale"],
                "rms_residual_m": fit["rms_residual"],
                "max_residual_m": fit["max_residual"],
                "output_checksum": _sha256(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
