# 0018 Opt-in LiDAR odometry cho scan sequence thiếu trajectory

Date: 2026-10-07

## Status

Accepted for the contract and provider candidate; production execution remains
blocked until the isolated adapter, dependencies and sensor envelope are qualified.

## Context

Input detector hiện reject gói không trajectory. LiDAR odometry là khả thi,
không phải technology impossibility. Odometry có drift/degeneracy; KISS-ICP không
là guarantee globally correct SLAM, FAST-LIO cần LiDAR/IMU/timing phù hợp.

## Decision

1. Thêm mode explicit estimate_lidar_odometry cho ordered timestamped raw scans;
   default supplied trajectory không đổi ngầm. Camera↔LiDAR calibration/timing
   cho RGB integration vẫn cần, odometry không giải chúng.
2. Pin the initial worker candidate to `kiss-icp==1.3.0`, run it in a separate
   process/runtime image, and use its Python API behind a versioned adapter protocol.
   The tagged upstream source declares MIT and exposes `KissICP.register_frame`;
   check the transitive dependency licenses and the build/runtime envelope before
   shipping the image. Do not add the provider to the Studio API environment.
3. Estimated trajectory/fused map là DERIVED, có provider/version/config/raw
   input checksum và quality diagnostics. Không gắn ground_truth origin.
4. Fail/degenerate run trả reason và diagnostics; không tạo fake identity trajectory.
   User có thể cung cấp trajectory thay thế; metric/alignment confirmation vẫn áp dụng.
5. Initial scope local odometry, không implement loop closure/global optimization/
   localization stack hoặc FAST-LIO adapter thiếu IMU.
6. Scan sidecar timestamps are one timestamp per scan and define pose/output time.
   They are not per-point timing. KISS-ICP's frame API uses per-point relative time
   for deskew, and its tagged configuration defaults deskew on. Until S2 proves a
   supported per-point timing profile, disable deskew or reject that input profile;
   never substitute one scan timestamp for every point and claim motion compensation.

## Data contract

AUD-17.S1 adds a neutral `timestamp_rows` format, explicit `rgb_frame_times` and
`lidar_scan_times` bindings, and separate RGB/LiDAR units while retaining the legacy
shared `timestamp_unit` only for backward compatibility. The resolver requires an
explicit raw-scan sequence declaration, accepted scan order, one LiDAR timestamp per
scan, matching counts, metric units and frame declaration. It leaves R5 pending while
the provider is `WIRED_UNQUALIFIED`.

`EstimatedTrajectoryArtifact` binds assembly revision/checksum, recipe checksum,
provider/protocol/runtime/config identities, timestamp-file checksum, source scan IDs
and checksums, monotonic per-scan seconds, ordered `map_from_sensor` SE(3) poses in
meters, coverage/gap diagnostics and an explicit `absolute_drift_status=not_measured`.
An optional `world_from_map` cannot be inferred from local odometry. ZIP/header checks
remain unchanged. Downstream consumes the derived artifact through the LiDAR adapter;
the system never rewrites an uploaded trajectory as if the user supplied it.

## Alternatives Considered

1. Giữ permanent rejection: kỹ thuật làm được, owner đã yêu cầu plan mở rộng.
2. Always run SLAM: tốn tài nguyên, đổi input contract và trajectory người dùng.
3. FAST-LIO cho scan-only data: thiếu required IMU/sync; không chọn baseline.

## Consequences

Positive: hỗ trợ input scan sequence mới. Tradeoffs: drift QA/qualification,
estimated provenance và worker resource cost phải được expose.

## Follow-Up

- [AUD-17](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-17-lidar-odometry.md).
- [KISS-ICP v1.3.0 release](https://github.com/PRBonn/kiss-icp/releases),
  [tagged Python API](https://github.com/PRBonn/kiss-icp/blob/v1.3.0/python/kiss_icp/kiss_icp.py),
  [tagged configuration](https://github.com/PRBonn/kiss-icp/blob/v1.3.0/python/kiss_icp/config/config.py),
  [MIT license](https://github.com/PRBonn/kiss-icp/blob/v1.3.0/LICENSE),
  [Python package setup](https://github.com/PRBonn/kiss-icp/blob/main/python/README.md),
  [FAST-LIO](https://github.com/hku-mars/FAST_LIO).
