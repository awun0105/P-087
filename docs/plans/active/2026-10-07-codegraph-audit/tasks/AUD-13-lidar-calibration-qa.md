# AUD-13 — LiDAR package QA về calibration, timing và projection

## Metadata và goal

- PLANNED; P1; EX-REC QA, PRODUCT preflight/status consumer.
- Canonical REC-08/09, PRODUCT-04/08. SELF-CODE typed QA; REUSE camera projection/
  transform/math ports, optional qualified OpenCV edge/depth checks.
- Goal: structural checks + scored observation QA + remediation; reject strong
  inconsistent calibration và báo INCONCLUSIVE khi dữ liệu không đủ.
- [Agent guide](../AGENT_GUIDE.md), [technology limits](../TECHNOLOGY_LIMITS.md),
  [ADR 0016](../../../../decisions/0016-collision-quality-and-lidar-selection.md).

## Baseline và scope

detect/package kiểm files/header/counts/trajectory/transforms. Current LiDAR
overlay là xyz cloud đã alignment trong world; không có quantitative 2D projection
calibration validator. Không dùng existing overlay existence làm QA evidence.
CodeGraph: detect._detect_lidar_package, lidar.package/camera_priors/world_alignment,
views.lidar_overlay_points và orchestration/jobs/lidar_overlay.py.

Owned: reconstruction/lidar/ QA module, typed package QA port, orchestration
preflight glue/API projection, frontend metadata/QA panel và corresponding tests.
Không xây arbitrary blind calibration solver, tự overwrite extrinsic hoặc
claim mọi 1°/5 cm miscalibration có thể được đo chính xác từ RGB/LiDAR bất kỳ.
Independent registered-map alignment trong AUD-19 không là sensor-calibration
task; thiếu rig metadata không là blanket rejection của geometric registration.

## Input / output / data contract

Input: calibration ref/convention, intrinsics+distortion hoặc qualified source,
raw/registered cloud + trajectory, scan/frame timestamps, sampled RGB frames,
camera model và QA config. Intrinsics/timing thiếu không tự giả identity/default.
Output proposed LidarCalibrationQAReport: version, input/calibration/timing/
intrinsics/config checksums, sampled frame IDs/counts, observability/coverage,
metrics/threshold profile, status PASS/FAIL/INCONCLUSIVE, reasons và overlay refs.

Structural FAIL như nonfinite/non-SE(3), impossible counts/units bị reject.
Observation QA dùng supported depth/edge/overlap metrics, robust aggregation;
textureless/sparse/dynamic/poor overlap hoặc confounded timing báo INCONCLUSIVE.
Không serialize angular/translation “error” số thật khi không có reference.
1°/5° và 5 cm là perturbation fixtures với known extrinsic, không production guarantee.

QA trước heavy alignment/training khi supplied intrinsics/timing đủ; nếu
intrinsics từ COLMAP, run sau pose và trước Brush/final collision. Legacy supplied
package vẫn ingest theo supported mode nhưng insufficient sensor QA không eligible
sensor-package collision source AUD-12. Independent static-map source có AUD-19
registration QA riêng; không claim calibration/timing PASS từ map fit. Geometry
alignment confirmation không tự là sensor QA PASS.

## Dependencies

S1 độc lập; S2 yêu cầu available sensor/calibration data hoặc synthetic rig known
reference. S3 integrates source gate using AUD-12.S1 contract/fixtures; không
đợi AUD-12.S3 implementation. Không block planning do chưa có
hardware; record real-data qualification pending và supported envelope.

## Sprint AUD-13.S1 — QA config/report và observability checks

**Input:** current package models + calibrated and malformed fixtures.
**Output:** typed QA report/config, structural/availability checks và consumer fixture.
**Contract:** reference frame/direction/unit/time identities explicit; missing data
INCONCLUSIVE hoặc structural FAIL đúng loại; old artifacts read-compatible.

Implement: inspect calibration direction (lidar_from_camera), inversion/projection
conventions, distortion, scan/frame matching and timestamp bounds. Define supported
sampling/overlap minimums từ QA profile, không hardcode angle-error guarantee.
Tests: wrong transform direction, meters vs millimeters, bad rotation/determinant,
NaN, missing K/distortion/time offset, unsorted times, sparse/no-overlap frames.
**Exit:** [ ] schema/consumer fixtures; [ ] QA never fake-pass missing observations.

## Sprint AUD-13.S2 — Projection metrics và perturbation qualification

**Input:** frames/cloud/trajectory/K/extrinsics + QA profile S1.
**Output:** per-frame/aggregate projection consistency metrics và overlay artifacts.
**Contract:** transformed points from correct pose/time, behind-camera/occlusion
handled; score confidence separated from true extrinsic error; no calibration mutation.

Implement: projection/depth buffering, robust edge/depth alignment where applicable,
multi-frame aggregation và uncertainty/degeneracy diagnostics. Freeze thresholds
using training/qualification data; no optimizing on held-out acceptance.
Tests: correct synthetic rig; ±1°/5°/5 cm perturbations across axes, timestamp shift,
textureless/wall ambiguity, sparse returns/occlusion/dynamic confounder; real held-out
calibrated sequence when available, detect regressions without absolute claim.
**Exit:** [ ] known perturbations differentiated in supported fixtures;
[ ] degenerate/confounded observations yield INCONCLUSIVE.

## Sprint AUD-13.S3 — Preflight, remediation UI và source consumer

**Input:** QA report + selected RGB/LiDAR collision path.
**Output:** persisted report/status, inspectable overlays and explicit next action.
**Contract:** failed QA not silently accepted; inconclusive not verified; explicit
new calibration upload generates new identity and rerun, never overwrites old refs.

Implement: route structural/observation outcomes into current preflight UI; offer
inspect overlay/provide intrinsics/timing/new calibration; resource-gated background
QA when heavy. AUD-12 only consumes qualified alignment/QA source. Preserve
unrelated RGB-only path; no user checkbox that forges sensor QA PASS.
Tests: API stale refs/permissions, missing/corrupt report, UI pending/failure/uncertain,
replacement calibration invalidates derived alignment/collision; browser overlay QA.
**Exit:** [ ] source gate consumes report correctly; [ ] real versus synthetic QA proof recorded.

## Verification và DoD

Existing suites: tests/test_reconstruction/test_lidar_package.py,
test_rec08_payload_guards.py, test_rec09_guards.py, test_lidar_world_alignment.py,
test_lidar_overlay.py. Planned tests/test_reconstruction/test_lidar_calibration_qa.py.
Frontend affected tests/lidar-metric-confirm.test.tsx, tests/studio-inspection.test.tsx.
DONE cần structural/perturbation/degeneracy/consumer proof và real supported-data
qualification; general blind calibration remains noted as research/observability limit.

## Result / Evidence

Pending — calibration/input/config/report refs, sampling/coverage, scored metrics,
perturbation labels, uncertain cases và real-data supported envelope.
