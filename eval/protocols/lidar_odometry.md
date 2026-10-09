# Đo drift của LiDAR odometry

Evaluator so sánh một `EstimatedTrajectoryArtifact` với quỹ đạo tham chiếu độc lập. Reference chỉ được đọc sau khi estimate đã tạo; evaluator không ghi lại artifact hoặc thay đổi product decision.

```bash
.venv/bin/python -m eval.pose.lidar_odometry_error \
  --estimate /path/to/estimated-trajectory.json \
  --reference /path/to/reference.tum \
  --reference-pose-frame lidar \
  --reference-distance-unit m \
  --reference-timestamp-unit seconds \
  --reference-clock-relation known_offset \
  --reference-clock-offset-seconds 0.012 \
  --maximum-interpolation-gap-seconds 0.1 \
  --output /path/to/lidar-odometry-evaluation.json
```

`--reference-pose-frame` must identify the same physical sensor frame as the estimated artifact. Declare reference translation and timestamp units explicitly. For `known_offset`, the offset means `estimate timestamp - reference timestamp`; for `same_clock`, omit the offset or use zero. The evaluator rejects unknown clock relations, frame mismatches, invalid checksums, extrapolation, and reference intervals larger than the configured maximum.

ATE applies a rigid transform derived from the first matched pose only. It does not fit scale or align the full path, so accumulated drift remains visible. RPE compares local relative transforms only for adjacent estimated scans that both have matched reference poses. Coverage and unmatched scan indices remain in the report. Fewer than two matches yields `inconclusive`.

The report records both input checksums, declared frame and units, alignment method, ATE/RPE summaries, coverage, and the estimate's runtime qualification status. It sets `product_solver_used_reference` to `false`; an evaluation report never qualifies R5 or marks an estimated trajectory as ground truth. No acceptance threshold is defined until held-out sensor traversals are measured.
