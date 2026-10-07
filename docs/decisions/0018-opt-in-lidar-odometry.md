# 0018 Opt-in LiDAR odometry cho scan sequence thiếu trajectory

Date: 2026-10-07

## Status

Proposed — scope mở rộng theo yêu cầu owner; supplied-trajectory mode hiện tại
giữ nguyên cho tới khi adapter/config/schema đã được qualified.

## Context

Input detector hiện reject gói không trajectory. LiDAR odometry là khả thi,
không phải technology impossibility. Odometry có drift/degeneracy; KISS-ICP không
là guarantee globally correct SLAM, FAST-LIO cần LiDAR/IMU/timing phù hợp.

## Decision đề xuất

1. Thêm mode explicit estimate_lidar_odometry cho ordered timestamped raw scans;
   default supplied trajectory không đổi ngầm. Camera↔LiDAR calibration/timing
   cho RGB integration vẫn cần, odometry không giải chúng.
2. Baseline adapter candidate KISS-ICP process-isolated/pinned; qualify input
   sensor conditions, unit/frame/timestamp, performance và license trước rollout.
3. Estimated trajectory/fused map là DERIVED, có provider/version/config/raw
   input checksum và quality diagnostics. Không gắn ground_truth origin.
4. Fail/degenerate run trả reason và diagnostics; không tạo fake identity trajectory.
   User có thể cung cấp trajectory thay thế; metric/alignment confirmation vẫn áp dụng.
5. Initial scope local odometry, không implement loop closure/global optimization/
   localization stack hoặc FAST-LIO adapter thiếu IMU.

## Data contract

AUD-17.S1 mở input classification cho unsupported-with-reason hoặc supported
raw-with-odometry-mode bằng typed detection evidence; không bỏ safety ZIP/header
checks. EstimatedTrajectoryArtifact bind timestamps/scan indices, transform
semantics và provenance. Downstream consume qua LiDAR package adapter, không
giả user upload gốc chứa một trajectory tự tạo.

## Alternatives Considered

1. Giữ permanent rejection: kỹ thuật làm được, owner đã yêu cầu plan mở rộng.
2. Always run SLAM: tốn tài nguyên, đổi input contract và trajectory người dùng.
3. FAST-LIO cho scan-only data: thiếu required IMU/sync; không chọn baseline.

## Consequences

Positive: hỗ trợ input scan sequence mới. Tradeoffs: drift QA/qualification,
estimated provenance và worker resource cost phải được expose.

## Follow-Up

- [AUD-17](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-17-lidar-odometry.md).
- Primary sources: [KISS-ICP](https://github.com/PRBonn/kiss-icp),
  [FAST-LIO](https://github.com/hku-mars/FAST_LIO).
