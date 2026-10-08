# AUD-13 — LiDAR package QA về calibration, timing và projection

## Metadata và goal

- IN PROGRESS; P1; S1/S2 diagnostic implementation slices are present locally;
  real-data qualification and the S3 PRODUCT consumer remain pending.
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

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Sensor QA dùng exact calibration/timing/image convention.
Cần sửa đồng bộ: LiDAR ingest, intrinsics/frame-map/pixel transforms AUD-23, projection overlay, sensor-source selection gate, diagnostics/UI và held-out evaluation.
Acceptance xuyên consumer: Rotated/resized/downsampled RGB projection đúng, missing metadata INCONCLUSIVE; sensor QA không bị dùng để reject independent-map registration.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

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
**Exit:** [x] schema/consumer fixtures; [x] QA never fake-pass missing observations.

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
**Exit:** [x] known perturbations are differentiated in the supported synthetic
fixture; [x] degenerate observations yield INCONCLUSIVE; [ ] production profile
thresholds are qualified on a held-out calibrated sequence; [ ] persisted RGB
overlay artifact is rendered and inspected by the S3 consumer.

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

### AUD-13.S1 — complete locally; projection qualification pending

- **Commit base:** `7e28539` (`AUD-12.S1`).
- **Logic before → after:** LidarPackageRecord retained the parsed transform but not
  the exact calibration bytes; missing distortion was represented as zero with no
  provenance. New records use schema 1.1 with a checksum-bound calibration artifact
  ref and distortion availability (`declared`, `partial`, `missing`). The reader
  still accepts schema 1.0; its absent calibration ref and distortion source remain
  unknown, never upgraded to QA evidence. Existing ingest and COLMAP fallback stay
  usable; the QA result separately says INCONCLUSIVE when evidence is insufficient.
- **Contract:** Added explicit profile thresholds, sampled RGB/LiDAR frame/time
  pairs, unit/clock declarations, source checksums, observability and findings to
  the version 1.0 QA config/report. The transform must be
  `T_lidar_sensor_from_camera` in meters with a proper normalized xyzw rotation.
  Timestamp comparison uses `rgb_time = lidar_time + offset`. Matched IDs and
  timestamps must be ordered, unique and within the trajectory inventory.
- **Consumer behavior:** Structural direction/unit/SE(3)/timestamp errors produce
  FAIL. Missing calibration ref, K, declared distortion, clock relation/offset,
  mapped samples or overlap produce INCONCLUSIVE. Enough observations produce
  READY_FOR_SCORING but still INCONCLUSIVE with `PROJECTION_SCORING_PENDING`;
  this sprint has no path that emits PASS. The serialized consumer fixture rejects
  use of that report as a sensor-package collision source.
- **Files changed:** `src/services/reconstruction/lidar/package.py`,
  `src/services/reconstruction/lidar/calibration_qa.py`,
  `src/models/contracts/lidar_calibration_qa.py`,
  `src/models/contracts/__init__.py`,
  `tests/test_reconstruction/test_lidar_package.py`,
  `tests/test_reconstruction/test_lidar_calibration_qa.py`,
  `tests/test_contracts/test_lidar_calibration_qa.py`,
  `tests/fixtures/contracts/lidar_calibration_qa_v1.json`, this task, README and
  ADR 0016.
- **Verification:** 61 focused reconstruction/contract/finalize consumer tests
  passed; `ruff check src/ tests/` passed; `ruff format --check src/ tests/`
  reported 512 files formatted; contract mirror passed (5 enum, 5 model); CodeGraph
  index is current at 842 files, 16,463 nodes and 48,175 edges.
- **Pending:** No projection metric, calibrated rig perturbation scoring, real
  held-out sequence, production threshold qualification, API persistence or UI
  gate is included. Those belong to AUD-13.S2/S3; no production calibration PASS
  or sensor-source acceptance is claimed by S1.

### AUD-13.S2 — diagnostic projection scorer implemented locally; field qualification pending

- **Logic before → after:** S1 could establish structural readiness but deliberately
  stopped at `PROJECTION_SCORING_PENDING`. S2 now projects paired sensor-frame
  LiDAR points through the declared `T_lidar_sensor_from_camera` and camera model,
  including the declared Brown–Conrady distortion terms. Projection uses the exact
  declared RGB pixel basis; source-video intrinsics are mapped to prepared RGB only
  through a server-verified video-preparation transform. Depth buffering keeps the
  nearest return per image pixel before edge-distance scoring.
- **Contract/output:** Added checksummed projection profile and evidence contracts
  with source refs, the effective projection model, frame/scan/sample checksums,
  timestamp residuals, front-facing/in-frame/visible/edge-overlap counts,
  edge-distance distribution, orientation/span observability, diagnostics and a
  bounded set of projected overlay samples. These samples are renderer-ready
  coordinates, not a rendered/persisted image artifact. `SCORED` means the
  diagnostic metrics meet the configured sample/observability requirements;
  `qualification_status` is fixed to `diagnostic_only`. The scorer does not fit,
  optimize or mutate calibration and never emits calibration PASS.
- **Synthetic evidence:** The known-rig 320×240 fixture yields a zero-pixel
  reference p90. Tests distinguish ±1° and ±5° rotations around all three axes and
  ±5 cm translations on all three axes by more than 0.25 px in the p90 frame score.
  Textureless, single-orientation/wall-like and sparse fixtures remain
  INCONCLUSIVE. A farther duplicate on the same projected pixel is removed by the
  depth buffer. Cross-frame score spread is reported as a confounder; it does not
  identify moving objects or establish motion compensation.
- **Pixel basis:** A verified source-video-to-prepared-RGB transform fixture checks
  the mapped dimensions and transform checksum. Missing camera intrinsics now
  report `CAMERA_INTRINSICS_MISSING` without incorrectly calling the pixel basis
  unknown; unavailable transforms and mismatched frame bases remain inconclusive.
- **Files changed:** `src/models/contracts/lidar_projection_qa.py`,
  `src/models/contracts/__init__.py`,
  `src/services/reconstruction/lidar/projection_qa.py`,
  `tests/test_reconstruction/test_lidar_calibration_qa.py`, this task, the audit
  index and ADR 0016.
- **Verification:** 46 focused reconstruction/contract tests passed. Full-repo
  Ruff, formatting, contract-mirror, CodeGraph and diff checks are recorded in the
  sprint commit report.
- **Pending:** No real held-out calibrated sequence or qualified production
  threshold profile is available. RGB edge extraction/frame artifact loading,
  report persistence/API preflight, rendered overlay and Studio remediation/source
  gating remain AUD-13.S3. Synthetic perturbation separation does not prove real
  calibration accuracy or a universal 1°/5 cm detection guarantee.
