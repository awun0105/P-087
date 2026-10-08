# AUD-17 — Opt-in LiDAR odometry cho raw scan sequence

## Metadata và goal

- IN PROGRESS — S1 typed contract/resolver/UI implemented; provider qualification and S2 worker remain open. P2 extension theo yêu cầu owner; EX-REC + EX-PRODUCT.
- Canonical REC-08/06, PRODUCT-02/08/09; bổ sung task-local scope, không đổi crosswalk.
- ADAPT qualified process-isolated KISS-ICP adapter; REUSE LiDAR ingest/metric/
  alignment contracts và durable admission. Technically feasible, không loại trừ
  chỉ vì old MVP không làm SLAM.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0018](../../../../decisions/0018-opt-in-lidar-odometry.md).

## Baseline và scope

detect._detect_lidar_package yêu cầu trajectory/calibration/timestamps; chưa có
odometry producer. Legacy supplied-trajectory APIs giữ behavior. Estimate mode là
explicit resolved config cho ordered timestamped raw scans; AUD-24 có thể tự chọn
recipe này và hiển thị trước Run, không bắt user chọn mode ở màn hình riêng.

CodeGraph: _detect_lidar_package, LiDAR package/models/fusion/ingest,
camera_priors/coordinate_bridge, metric/world_alignment, input kinds và job dispatch.
Owned: REC worker adapter, typed derived trajectory/package binding, input routing,
PRODUCT durable operation/config/API diagnostics và tests/eval protocol.
Initial scope local odometry; global loop closure/map optimization/localization
stack là future scope. FAST-LIO cần qualified IMU/sensor/timing inputs, không gắn
vào scan-only pipeline. Odometry không giải blind camera↔LiDAR calibration.

## Input / output / data contract

Input: safe scan package, unit/frame convention, ordered scan indices/timestamps,
explicit estimate profile. RGB fusion còn cần calibration, camera timing/offset
và intrinsics đúng contract; scan-only estimation không tự tạo chúng.
Output proposed EstimatedTrajectoryArtifact + diagnostics, optional fused cloud
qua existing ingest và metric/alignment proposal cho user confirm.

Trajectory contract: schema/provider/runtime version, exact assembly/revision/recipe
checksums, timestamp-file checksum, per-scan source file ID/checksum and timestamp
in seconds, ordered `map_from_sensor` SE(3) poses in meters, origin=estimated,
coverage/gap and optional convergence/degeneracy diagnostics. Absolute drift is
`not_measured` unless a separate reference evaluator proves it. `world_from_map` is
optional and must be confirmed before canonical world/Z-up ingestion. S1 stores
this derived artifact contract without claiming that a producer is installed.
Never tag ground_truth, create identity poses on failure hoặc modify original ZIP.
Missing ground truth nghĩa absolute drift unknown, không là zero.

Odometry map khởi tạo ở sensor pose không tự là canonical world/Z-up. Integration
phải có declared/confirmed world_from_map từ supported sensor up/floor prior hoặc
qualified floor evidence. Persist transform/provenance; thiếu up/floor support thì
trajectory vẫn có diagnostics nhưng metric/canonical fusion bị block. Không truyền
arbitrary first-scan frame vào estimate_floor vốn giả định Z-up; không rotate lại
existing SceneIR để hợp thức hóa output. AUD-14.S1 có thể cung cấp fitted-plane evidence.

Scan-native trajectory khác poses tại RGB frame_times. Consumer mapping cần explicit
clock offset, interpolation method/bounds, available interval và provenance.
Nếu supported: translation interpolation + quaternion SLERP với bounded gap,
no unconstrained extrapolation; persist derived RGB pose mapping separately.
Không claim point-cloud deskew nếu sensor package thiếu per-point time/capability.
New estimated or user-supplied trajectory tạo new identity; downstream QA/alignment/
collision phải invalidate evidence cũ và confirm lại theo existing workflow.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Estimated trajectory mode khác supplied trajectory.
Cần sửa đồng bộ: input detection/routing, safe scan ingest, odometry worker/provider/version, trajectory/frame bindings, RGB priors/metric/alignment và QA consumers.
Acceptance xuyên consumer: Explicit supplied/estimated modes, unsupported/drift diagnostics và timestamps giữ identity; estimated trajectory không tự tạo calibration PASS.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập để qualify adapter/input contract. S2 dùng AUD-07 admission/lease pattern.
AUD-24.S1 cung cấp grouped assembly/recipe port; reuse trong unified path, không
đợi whole AUD-24 để implement odometry. Legacy missing-trajectory request khác
valid assembly có accepted estimated recipe; không auto estimate từ file ambiguous.
Contract port: `sensor_trajectory` khác `camera_trajectory`; each supplied or
estimated scan pose binds exact scan refs/timestamps and uses `world_from_sensor`
in a declared world frame, metres, quaternion `xyzw`. Estimated output retains
source scan refs and `estimated` provenance; it is never inserted as a supplied
TUM upload. The existing TUM parser checks row ordering/pose shape but does not
establish RGB clock synchronization.
S3 dùng AUD-13 calibration/timing QA cho RGB integration; AUD-14.S1 khi cần fit
floor/up normalization; AUD-12 cho collision selection, không auto-enable LiDAR
collision từ trajectory vừa estimate.

## Sprint AUD-17.S1 — Input mode và runtime qualification

**Input:** current package detector/schema + timestamped scan fixtures/real sensor sample.
**Output:** explicit supplied/estimate modes, derived trajectory contract, neutral timestamp role/unit declarations and a pinned adapter candidate envelope.
**Contract:** supplied mode unchanged; ZIP/header/path/count checks preserved;
unsupported sensor/timestamps báo reason; estimated output không là upload/ground truth.

Implement: preserve supplied trajectory behavior; classify one-column numeric time
rows as role-ambiguous until the user assigns RGB or LiDAR; keep separate timestamp
units while reading legacy shared `timestamp_unit`. An explicit R5 estimate candidate
requires one ordered scan timestamp per scan, matching row count, declared time unit,
declared scan order, metric unit and sensor frame. Bind the exact scan/time refs and
checksum them in `EstimatedTrajectoryArtifact`; incomplete inputs stay `NEEDS_INPUT`
and wired-unqualified runtime stays pending. Normalize derived pose translations to
meters; do not treat the local odometry map as canonical world.

Adapter candidate: pin `kiss-icp==1.3.0` in the future isolated worker image and use
its Python `KissICP.register_frame` API. Upstream release is MIT. The API consumes
per-point relative timestamps for deskew; the sidecar accepted here contains per-scan
timestamps only and must never be passed off as per-point timing. S2 must disable
deskew or reject inputs without verified per-point timing, then test this behavior.
The provider package is not installed in the Studio runtime; the transitive license
inventory, worker image, supported point attributes, real-sensor sample, and memory/
performance envelope remain unqualified. R5 stays `WIRED_UNQUALIFIED`.

Tests: legacy shared-unit payload/checksum compatibility; ambiguous timestamp probe;
explicit R5 binding, scan-count mismatch, invalid ordering, artifact pose/frame/lineage
invariants; UI requires explicit role selection, preserves distinct RGB/LiDAR units,
and clears stale bindings when the selected input changes. Keep unsafe ZIP/header
checks and supplied trajectory paths unchanged.
**Exit:** [x] mode/schema/runtime candidate envelope agreed; [x] validation not weakened;
[ ] isolated provider/dependency license qualification; [ ] supported sensor sample,
memory/performance and per-point timing behavior qualified.

## Sprint AUD-17.S2 — Durable odometry worker và trajectory publication

**Input:** validated scan refs/config + admitted operation/lease.
**Output:** immutable estimated trajectory/diagnostics and verified ingest binding.
**Contract:** subprocess isolated/cancellable; lease fences publication; finite
SE(3)/monotonic time/coverage checked; degeneracy not fabricated success.

Implement: decode supported scans, run pinned adapter, classify convergence/input/
runtime failures, validate output and publish through resolver. Build explicit
scan-native mapping, bounded RGB interpolation only when timing contract supports
it; preserve scan and frame identities. Use actual resource measurement and retry
policy; partial artifacts retained for diagnosis, not consumed as complete trajectory.
Tests: known-motion fixture, static/low-overlap/sparse/degenerate sequence, timestamp
gap/boundary/rotation interpolation, restart/cancel/timeout, stale lease, corrupt output.
**Exit:** [ ] valid estimated producer path; [ ] failed/cancelled results remain truthful.

## Sprint AUD-17.S3 — Integration, drift QA và product diagnostics

**Input:** derived trajectory + calibration/timing/metric evidence and real traversals.
**Output:** ingest/alignment consumers, selectable fallback và qualified quality report/UI.
**Contract:** user sees estimated provenance/uncertainty; no automatic GT status;
supplied replacement or timing/calib change invalidates dependent evidence.

Implement: connect existing ingest/fusion/metric ports; display actionable quality
diagnostics and allow explicit supplied trajectory fallback with new identity.
Evaluate supported sensor conditions over separate traversals; independent reference
trajectory chỉ dùng evaluator, không leak vào product solver. Record relative/absolute
pose error where reference exists, degeneracy/coverage and downstream obstacle retention.
Confirm source-map→world transform trước canonical ingest; giữ original scan poses.
Tests: supplied/estimated consumer parity, stale calibration/trajectory binding,
clock mismatch, tilted first-scan frame/up normalization, missing floor support,
UI mode/failure/fallback, real odometry benchmark và held-out quality.
**Exit:** [ ] supported envelope/drift measured; [ ] integrations and fallback verified.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_reconstruction/test_input_detection.py tests/test_reconstruction/test_lidar_package.py tests/test_reconstruction/test_lidar_fusion.py tests/test_reconstruction/test_rec08_lidar_ingest.py tests/test_reconstruction/test_rec06_lidar_metric.py tests/test_reconstruction/test_lidar_world_alignment.py tests/test_orchestration/test_upload_input_kinds.py -q
```

Planned tests/test_reconstruction/test_lidar_odometry.py và opt-in API/UI tests.
DONE cần actual adapter runs/quality envelope/integration, không chỉ mocked poses;
không claim drift-free SLAM. Primary: [KISS-ICP](https://github.com/PRBonn/kiss-icp),
[FAST-LIO](https://github.com/hku-mars/FAST_LIO).

## Result / Evidence

Partial — S1 code implements neutral timestamp roles and separate units, exact ordered
scan/time bindings, resolver prerequisites, and immutable estimated-pose lineage. It
also rejects non-finite pose/map translations; the existing raw-sequence resolver gate
requires at least two scans. R5 remains `WIRED_UNQUALIFIED`; no estimated trajectory
is dispatchable.

Verification before commit:
- Backend focused regression command (input detection/package/fusion/ingest/metric,
  resolver/contracts, upload API paths): 153 passed. Resolver rejects a timestamp
  file bound to both RGB and LiDAR roles.
- `.venv/bin/ruff check src/ tests/` and `.venv/bin/ruff format --check src/ tests/`:
  passed; 537 files already formatted.
- Frontend `unified-input-flow` and `studio-inspection` tests: 21 passed; TypeScript
  typecheck and focused ESLint: passed.
- Chrome DevTools Reviewer session: `/new` and `/api/v1/auth/me` returned 200 with no
  console warnings/errors; mocked upload interaction covered explicit timestamp-role
  selection, separate units, duplicate-role prevention and clearing stale selections.
  No upload/job was created. The separate QA stage URL was also inspected: its old job
  is RUNNING at metric confirmation and has no `ST-LIDAR-CALIBRATION-QA` stage, so the
  page correctly shows the incomplete-stage state. This does not verify rendering a
  completed QA report.

Runtime execution, transitive license inventory, real-sensor timing/memory/performance,
S2 worker publication and S3 drift/consumer QA remain pending.
