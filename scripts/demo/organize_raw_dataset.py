"""Tổ chức bộ dữ liệu thô TorWIC-SLAM thành các thư mục kịch bản trực quan,
mỗi thư mục chứa độc lập video và các dữ liệu thô tương ứng (LiDAR scans,
trajectory ground truth, frame_times, calibrations).
"""

import json
import os
from pathlib import Path


def main() -> None:
    raw_root = Path("/media/usb/AI20K/TorWIC SLAM Dataset")
    demo_vids = Path("/media/usb/AI20K/P-087 demo videos")
    dest_root = Path("/media/usb/AI20K/TorWIC_Raw_Scenes")

    dest_root.mkdir(parents=True, exist_ok=True)
    calib_src = raw_root / "calibrations.txt"

    scenes = [
        {
            "folder": "01_LoiDi_Kho_Thuan_Aisle_CW",
            "title": "Lối đi nhà kho (Chiều kim đồng hồ)",
            "traversal": "Aisle_CW",
            "raw_dir": raw_root / "Aisle_CW",
            "video_src": demo_vids / "Aisle_CW__left.mp4",
            "fps": 30.0,
        },
        {
            "folder": "02_HanhLang_Thang_Hallway_Straight_CW",
            "title": "Hành lang thẳng khu văn phòng",
            "traversal": "Hallway_Straight_CW",
            "raw_dir": raw_root / "Hallway_Straight_CW",
            "video_src": demo_vids / "Hallway_Straight_CW__left.mp4",
            "fps": 30.0,
        },
        {
            "folder": "03_LoiDi_Kho_Nguoc_Aisle_CCW",
            "title": "Lối đi nhà kho (Ngược chiều kim đồng hồ)",
            "traversal": "Aisle_CCW",
            "raw_dir": raw_root / "Aisle_CCW",
            "video_src": demo_vids / "Aisle_CCW__left.mp4",
            "fps": 30.0,
        },
        {
            "folder": "04_HanhLang_ToanKhu_Hallway_Full_CW",
            "title": "Hành lang toàn khu văn phòng (Vòng lặp kín)",
            "traversal": "Hallway_Full_CW_Run_1__2022-10-12",
            "raw_dir": raw_root / "Hallway_Full_CW_Run_1__2022-10-12" / "Hallway_Full_CW_Run_1",
            "video_src": demo_vids / "Hallway_Full_CW_Run_1_2022_10_12__left.mp4",
            "fps": 30.0,
        },
        {
            "folder": "05_LoiDi_Kho_Dot2_Aisle_CW_Run1",
            "title": "Lối đi nhà kho (Đợt quay 2 - 2022-06-15)",
            "traversal": "Aisle_CW_Run_1__2022-06-15",
            "raw_dir": raw_root / "Aisle_CW_Run_1__2022-06-15" / "Aisle_CW_Run_1",
            "video_src": demo_vids / "Aisle_CW_Run_1_2022_06_15__left.mp4",
            "fps": 30.0,
        },
    ]

    summary = []

    for sc in scenes:
        folder_name = sc["folder"]
        sc_dir = dest_root / folder_name
        sc_dir.mkdir(parents=True, exist_ok=True)

        # 1. Video
        dest_video = sc_dir / "video.mp4"
        if not dest_video.exists():
            os.link(sc["video_src"], dest_video)

        # 2. traj_gt.txt
        dest_traj = sc_dir / "traj_gt.txt"
        src_traj = sc["raw_dir"] / "traj_gt.txt"
        if not dest_traj.exists():
            os.link(src_traj, dest_traj)

        # 3. frame_times.txt
        dest_times = sc_dir / "frame_times.txt"
        src_times = sc["raw_dir"] / "frame_times.txt"
        if not dest_times.exists():
            os.link(src_times, dest_times)

        # 4. calibrations.txt
        dest_calib = sc_dir / "calibrations.txt"
        if not dest_calib.exists():
            os.link(calib_src, dest_calib)

        # 5. lidar_scans symlink
        dest_lidar = sc_dir / "lidar_scans"
        src_lidar = sc["raw_dir"] / "lidar"
        if not dest_lidar.exists() and not dest_lidar.is_symlink():
            dest_lidar.symlink_to(src_lidar)

        # Count frames & scans
        num_frames = len(dest_times.read_text(encoding="utf-8").strip().splitlines())
        num_scans = len(list(src_lidar.glob("*.pcd")))

        meta = {
            "title": sc["title"],
            "traversal_id": sc["traversal"],
            "fps": sc["fps"],
            "frame_count": num_frames,
            "duration_seconds": round(num_frames / sc["fps"], 2),
            "lidar_scan_count": num_scans,
            "files": {
                "video": "video.mp4",
                "trajectory": "traj_gt.txt",
                "frame_times": "frame_times.txt",
                "calibration": "calibrations.txt",
                "lidar_scans_dir": "lidar_scans/",
            },
        }

        (sc_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        summary.append(meta)
        print(f"Done: {folder_name} ({num_frames} frames, {num_scans} scans)")

    manifest = {
        "dataset_name": "TorWIC-SLAM Raw Scenes",
        "description": "Tập hợp các video và dữ liệu cảm biến thô (unregistered LiDAR, trajectory GT, calibrations)",
        "total_scenes": len(summary),
        "scenes": summary,
    }
    (dest_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    readme_content = f"""# TorWIC-SLAM Raw Scenes (Dữ liệu thô chưa qua xử lý)

Thư mục này tập hợp toàn bộ dữ liệu gốc từ bộ dữ liệu TorWIC-SLAM, được phân tách độc lập theo từng kịch bản video để phục vụ thử nghiệm và đánh giá pipeline.

## Cấu trúc từng thư mục kịch bản:
- `video.mp4`: Video RGB từ camera trái (chuẩn hóa MP4, 30 FPS).
- `lidar_scans/`: Thư mục chứa các file scan `.pcd` thô chưa qua đăng ký (unregistered LiDAR) từ cảm biến Ouster OS1. Mỗi scan tương ứng với 1 mốc thời gian.
- `traj_gt.txt`: Quỹ đạo di chuyển thực tế của robot (Ground Truth Trajectory). Định dạng: `timestamp x y z qx qy qz qw`.
- `frame_times.txt`: Mốc thời gian (timestamp) của từng khung hình camera, dùng để đồng bộ 1-1 với LiDAR scans.
- `calibrations.txt`: Ma trận hiệu chuẩn giữa camera và LiDAR (`T_cam_os`, `T_os_cam`, camera intrinsics).
- `metadata.json`: Thông số kỹ thuật của kịch bản (số frame, độ dài giây, số scan).

## Danh sách 5 kịch bản:
1. `01_LoiDi_Kho_Thuan_Aisle_CW`: {summary[0]["frame_count"]} frames (~{summary[0]["duration_seconds"]}s), {summary[0]["lidar_scan_count"]} scans
2. `02_HanhLang_Thang_Hallway_Straight_CW`: {summary[1]["frame_count"]} frames (~{summary[1]["duration_seconds"]}s), {summary[1]["lidar_scan_count"]} scans
3. `03_LoiDi_Kho_Nguoc_Aisle_CCW`: {summary[2]["frame_count"]} frames (~{summary[2]["duration_seconds"]}s), {summary[2]["lidar_scan_count"]} scans
4. `04_HanhLang_ToanKhu_Hallway_Full_CW`: {summary[3]["frame_count"]} frames (~{summary[3]["duration_seconds"]}s), {summary[3]["lidar_scan_count"]} scans
5. `05_LoiDi_Kho_Dot2_Aisle_CW_Run1`: {summary[4]["frame_count"]} frames (~{summary[4]["duration_seconds"]}s), {summary[4]["lidar_scan_count"]} scans
"""
    (dest_root / "README.md").write_text(readme_content, encoding="utf-8")
    print("All 5 raw scenes organized successfully and README.md created!")


if __name__ == "__main__":
    main()
