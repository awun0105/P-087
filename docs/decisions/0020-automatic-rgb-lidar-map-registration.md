# 0020 Automatic RGB–LiDAR map registration với floor, BEV, constrained ICP và QA

Date: 2026-10-07

## Status

Proposed — owner đã đồng ý đưa cải tiến vào plan; input/schema/QA/runtime choices
chốt và qualify trong AUD-19.S1–S3. Không tự đánh dấu runtime Implemented/qualified.

## Context

Current trajectory/calibration package đã có no-point metric proposal và
camera-center alignment sau confirmation. Independent RGB/LiDAR maps thiếu
trajectory/camera extrinsic là input extension khác, có thể đăng ký bằng geometry
nếu đủ overlap/scale/floor structure. Docs cũ không là lý do loại feature này.

Floor evidence có thể giảm search dimensions; không làm scale của MoGe chính xác
tuyệt đối. relative_uncertainty hiện không gồm model systematic bias. Warehouse
racks/symmetry/partial overlap có thể tạo nhiều plausible alignments; ICP là local
refinement, thấp residual không tự là true transform hoặc safe collision.

## Decision đề xuất

1. Automatic registration là default proposal action, ưu tiên trusted trajectory
   path hiện có; independent registered maps dùng geometric path. Manual landmarks
   là fallback và không mặc định bắt user chọn đúng ba điểm.
2. Static-map input dùng unit/frame/capture-context/geometry checks, không yêu cầu
   user fabricate calibration/trajectory. Sensor-package fusion vẫn dùng calibration/
   timing QA AUD-13; raw scans cần supplied/estimated trajectory trước map registration.
3. Floor + metric evidence xác định search: known metric/floor dùng yaw/x/y;
   uncertain RGB scale cần thêm scale hypotheses và new REC-06 confirmation/
   canonicalization. Final AlignmentRecord giữ rigid SE(3), no scale in Transform.
4. Structural BEV multi-candidate search rồi constrained robust ICP trên supported
   surfaces/normals. Không force yaw solution từ corridor/symmetric/floor-only input
   hoặc use arbitrary Gaussian centers như chính xác physical surface.
5. Registration QA độc lập sensor-calibration QA: coverage/overlap, per-region
   residuals, floor/scale consistency, observability/candidate ambiguity. PASS chỉ
   trong qualified conditions; FAIL/INCONCLUSIVE có explicit fallback/remediation.
6. Proposal và QA bất biến, operation leased/admitted. Confirmation bind exact
   source/target/config/report/transform; publish qua verifier và scene CAS. New
   source/metric/revision invalidates old proof; existing user edits không rescale ngầm.
7. Preserve same-job/ownership checks: incoming independent asset được re-ingest/
   bind hợp lệ với original lineage, không chỉ rewrite metadata cho qua verifier.
   Registered-map QA có thể qualify LiDAR collision AUD-12; không forge calibration PASS.

## Data contract

AUD-19.S1 chốt proposed RegistrationProposalArtifact/RegistrationQAReport và
input mode/profile. Reuse AlignmentRequest/AlignmentRecord, ArtifactResolver,
REC-06 confirmation và existing derived geometry. Report phải ghi source/target/
config/tool/floor/metric checksums, frame direction, overlap/coverage, ambiguity,
observed consistency vs independent reference error. Old refs/checksums read-compatible.

## Alternatives Considered

1. Chấm điểm cho mọi input: unnecessary trên current trajectory path và supported geometric path.
2. BEV + unconstrained ICP luôn auto-confirm: thiếu ambiguity/scale/coverage protection.
3. Bắt calibration cho hai maps độc lập: lẫn map registration với rig calibration.
4. Gắn ICP RMSE vào absolute accuracy/safety: nearest-neighbor consistency không đủ proof.
5. Global universal blind-calibration solver: khác scope và không cần để làm extension này.

## Consequences

Positive: giảm thao tác, mở supported input, giữ existing trajectory path và
quality diagnostics rõ. Tradeoffs: search/runtime budget, scale/floor qualification,
registered-cloud binding và held-out/browser consumer acceptance.

## Follow-Up

- [AUD-19](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-19-automatic-rgb-lidar-registration.md).
- [AUD-12 collision consumer](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-12-collision-quality.md),
  [AUD-13 sensor QA](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-13-lidar-calibration-qa.md).
- Primary: [MoGe-2](https://arxiv.org/abs/2507.02546),
  [BVMatch](https://arxiv.org/abs/2109.00317),
  [Open3D global registration/local refinement](https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html).
  BVMatch là LiDAR BEV study; nguồn này không tự chứng minh RGB–LiDAR project acceptance.
