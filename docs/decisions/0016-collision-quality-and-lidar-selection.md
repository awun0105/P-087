# 0016 Collision quality và lựa chọn nguồn RGB/LiDAR có evidence

Date: 2026-10-07

## Status

Proposed — theo yêu cầu owner bổ sung remediation Gemini. ADR 0009 ngày 03/10
đang giữ canonical RGB geometry; plan này đề xuất selectable collision source
riêng, không giả rằng quyết định cũ đã bị supersede hoặc LiDAR path đã implement.

## Context

3DGS mesh log có 33/50 blocked positions ở 0,05 m. LiDAR registered cloud dùng
nguyên trạng chặn 100/100; 0/100 chỉ khi raw scans filter gần sensor ≥2 m và
floor band 0,15 m. Test chưa đo obstacle misses hoặc physics Isaac. Deleting
mọi điểm sát sàn/robot path có thể làm metric tốt nhưng scene vật lý sai.

## Decision đề xuất

1. Collision quality pipeline versioned: source cleanup, adaptive floor,
   occupancy/mesh generation, static QA và exact-candidate Isaac handoff.
2. Cho phép opt-in RGB cleaned hoặc LiDAR-derived collision; visual/canonical
   reconstruction geometry không đổi ngầm. Source selection là explicit config
   có checksum/quality report/confirmed alignment, không automatic silent fallback.
3. LiDAR dùng đúng world frame và alignment được xác nhận. Sensor package dùng
   calibration/timing QA AUD-13; independent static maps dùng registration QA
   AUD-19, không bắt fabricate camera extrinsic. Không coi aligned centers hoặc
   GT demo là độc lập reference accuracy; map fit không chứng minh rig calibration.
4. Filter near-sensor theo sensor frame/self-geometry mask có provenance; không
   drop bán kính 2 m quanh robot trong final map hoặc xóa low obstacles hàng loạt.
5. Kiểm cả free-space consistency và real-obstacle retention/support. Unknown/
   inferred/unobserved regions báo rõ; không claim safe physics từ visual inpainting.
6. Background/object ownership AUD-01 bind selected collision geometry checksum;
   không giữ membership indices của RGB mesh rồi áp vào mesh LiDAR khác.

## Data contract

Proposed CollisionSourceSelection/CollisionQualityReport bind source refs,
modality, alignment/QA/config/profile checksums, effective filters/resolution,
output collision ref, tested coverage và observed metrics. Ghi source input/
registration mode để dispatch đúng QA; không tráo sensor/map reports. Reuse
SceneEnvironment geometry/collider refs theo producer-consumer decision AUD-12.S1; không thêm
competing ReconstructionBundle hoặc rewrite canonical RGB artifact.

## Alternatives Considered

1. Luôn thay canonical RGB bằng LiDAR: không đúng mọi input và phá source contract.
2. Giữ RGB mesh dù QA fail: không đạt collision usefulness; cần cleanup/blocker.
3. Xóa 15 cm sàn hoặc carve robot path để đạt 0%: có thể bỏ obstacle thật.
4. Đòi một filter universal: khác sensors/noise/coverage, phải qualify profile.

## Consequences

Positive: nguồn collision và quality rõ, regression có obstacle negative proof.
Tradeoffs: thêm quality/config contract, LiDAR builder qualification và held-out
data; initial opt-in rollout cần ghi supported conditions.

## Follow-Up

- [AUD-12](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-12-collision-quality.md),
  [AUD-13](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-13-lidar-calibration-qa.md),
  [AUD-14](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-14-adaptive-floor.md).
- [Evidence/caveats](../plans/active/2026-10-07-codegraph-audit/GEMINI_FINDINGS.md).

## AUD-12.S1 implementation note — 2026-10-08

The ADR remains **Proposed**; this note does not accept or enable the source
selection in production. S1 added internal version 1.0 Pydantic contracts for
`CollisionSourceSelection` and `CollisionQualityReport`. They bind source,
profile/config, mode-specific QA kind, effective resolution, output collision,
hardware/robot profiles, support retention, independent obstacle evidence,
coverage states, a frozen acceptance-profile result and simulator contact
evidence. A physics claim requires a PASS under that exact profile. The selected
output is checked against the existing
`SceneEnvironment.collider_ref`; no competing reconstruction bundle or SceneIR
field was added.

Saved JSONL rows are parsed as free-space proxies with source provenance gaps
preserved. LiDAR rows that declare `trajectory_origin=ground_truth` remain
GT-assisted. Synthetic fixture thresholds are pinned in
`eval/protocols/collision_path_clearance.md`; no production threshold was inferred
from the single traversal. Actual producer/API/USD/Isaac consumers, held-out
capture, independent obstacle recall and exact-candidate contact validation
remain follow-up implementation/qualification work.

## AUD-13.S1 implementation note — 2026-10-08

The ADR remains **Proposed** and no collision-source selection is enabled by this
note. New LiDAR package records use schema 1.1 and retain the extracted
calibration bytes by artifact ref/checksum; the reader continues to accept 1.0
records, whose missing calibration/distortion provenance stays unknown. The
calibration QA profile/report makes transform direction, metric unit, clock
relation/offset, intrinsics, sampled frame map and overlap availability explicit.
Structural mismatches fail and unavailable evidence is inconclusive. S1 cannot
produce PASS: enough observations only means ready for projection scoring. The
existing reconstruction/alignment flow is not yet gated by this report.
Projection scoring, perturbation qualification and the product source gate remain
AUD-13.S2/S3 work; real calibration data and supported thresholds are unqualified.

## AUD-12.S2 implementation note — 2026-10-08

The ADR remains **Proposed**; RGB cleanup is not qualified for physics use. New
`GeometryArtifact` 1.2 records the exact cleanup config/checksum, raw source hash,
metric input and filtered PLY hashes, collision mesh hash, and Gaussian counts
before/after cleanup. The contract checks checksum identity and count conservation
and labels this evidence `diagnostic_only`. Legacy 1.0/1.1 artifacts remain readable.

The finalizer no longer increases requested voxel or cleanup resolution to fit a
large crop. It preserves the selected profile or fails with a capacity diagnostic.
The initial finalizer has no source-bound floor/noise model; current
`FloorFitEvidence` is produced later in scene extraction/objectify. No plane-based
point deletion or new SOR filter was enabled without obstacle-retention evidence.
The saved Aisle_CW source/final mesh lacks the intermediate cleanup artifacts and
the old collision log lacks a bound profile, so ghost-block reduction and
thin-obstacle retention remain **Pending**. Held-out collision and Isaac proof
remain required by AUD-12.S4.
