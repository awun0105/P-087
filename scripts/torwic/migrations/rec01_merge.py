import csv
import json
import shutil
from pathlib import Path


def main():
    rec01 = Path("data/torwic_slam_rec01/aisle_cw")
    out_norm = Path("data/torwic_slam/normalized/aisle_cw")
    out_deri = Path("data/torwic_slam/derived/aisle_cw")

    # 3. Create unified timestamps.csv
    times = Path("data/torwic_slam/raw/traversals/aisle_cw/frame_times.txt").read_text().splitlines()
    split_file = rec01 / "derived" / "Aisle_CW" / "benchmark_split.json"
    split_data = json.loads(split_file.read_text())
    valid_ids = sorted(split_data["train_frame_ids"] + split_data["held_out_frame_ids"])

    with (out_norm / "timestamps.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_id", "timestamp_sec"])
        for fid in valid_ids:
            writer.writerow([f"{fid:06d}", times[fid]])

    # 4. Move benchmark_split.json
    shutil.move(split_file, out_deri / "benchmark_split.json")

    # 5. Move manifest.json to derived/preparation_manifest.json
    manifest_file = rec01 / "manifest.json"
    if manifest_file.exists():
        shutil.move(manifest_file, out_deri / "preparation_manifest.json")


if __name__ == "__main__":
    main()
