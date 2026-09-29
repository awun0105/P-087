#!/bin/bash
set -e

# Target directories
NORM="data/torwic_slam/normalized/aisle_cw"
DERI="data/torwic_slam/derived/aisle_cw"
EVAL="data/torwic_slam/evaluation_only/aisle_cw"
REC01="data/torwic_slam_rec01/aisle_cw"

echo "Creating rgb_frames..."
mkdir -p "$NORM/rgb_frames"

echo "Moving train PNGs..."
find "$REC01/normalized" -name "*.png" -exec mv {} "$NORM/rgb_frames/" \;

echo "Moving held-out PNGs..."
find "$REC01/evaluation_only" -name "*.png" -exec mv {} "$NORM/rgb_frames/" \;

echo "Moving JSON and CSVs..."
mv "$REC01/normalized/calibration.json" "$NORM/"
mv "$REC01/normalized/coordinate_metadata.json" "$NORM/"

echo "Merging timestamps.csv..."
# The timestamps in REC01 are split. We want all of them.
# The original frame_times.txt has all times, we can just rewrite or merge.
# Wait, let's just use the original frame_times.txt to create one timestamps.csv.
# We have 1092 usable frames. The IDs are exactly those in train + held_out.
# Let's write a python script to merge them properly.
