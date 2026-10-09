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

## AUD-13.S2 implementation note — 2026-10-08

The proposal remains **Proposed** and no collision-source selection is enabled.
S2 adds source-bound RGB/LiDAR projection diagnostics with a declared pixel basis,
verified video-preparation mapping, nearest-return z-buffering, edge support and
bounded overlay samples. Its `SCORED` state only reports diagnostic metric
availability; qualification is permanently `diagnostic_only`, with no calibration
optimization or PASS path. Synthetic known-rig tests distinguish the specified
rotation and translation perturbations, while textureless, wall-like and sparse
observations remain inconclusive. Real held-out threshold qualification, persisted
rendered overlays, API preflight and collision-source gating are still pending.

## AUD-13.S3 implementation note — 2026-10-08

The proposal remains **Proposed** and no collision-source selection is enabled.
The worker now persists a job-bound QA report before COLMAP. A structural `FAIL`
ends the job at the QA stage with a non-retryable remediation error and stops
before COLMAP/Brush. `INCONCLUSIVE` continues the RGB reconstruction path, but
never enables the LiDAR package as a collision source. The report and verified
nested diagnostic artifacts stay inspectable after failure; report/stage result
mismatches, cross-job refs, corrupt checksums, `PASS`, and production evidence are
rejected. Studio exposes the failed QA stage from the timeline and shows the
finding/remediation with collision eligibility set to `no`.

The exercised failure and browser fixture are synthetic/local. No held-out real
calibration sequence or production threshold profile is qualified, and S3 does not
establish universal 1°/5 cm detection accuracy or authorize collision-source use.

## AUD-12.S3b implementation note — 2026-10-09

The ADR remains **Proposed** and no collision-source path is enabled. `SceneEnvironment`
now has optional, checksum-compatible refs for the selected collision candidate and
its `CollisionSourceSelection` record. `collider_ref` remains the effective collider,
so a carved result does not erase which source was selected. Scene artifact closure
retains both refs. Because the simulation composer still uses RGB-bound source
triangle ownership and the current calibration projection evidence is
`diagnostic_only`, package composition explicitly blocks a selected source instead
of silently exporting RGB. Candidate publication, QA qualification, LiDAR ownership
mapping, viewer selection, held-out retention and Isaac acceptance remain pending.

## AUD-12.S3c implementation note — 2026-10-09

The ADR remains **Proposed**; no LiDAR collision source is selectable. A pure
eligibility assessment now requires the mixed bundle's exact RGB/LiDAR geometry and
confirmed alignment, the matching scan-package calibration/timing report, and a
scored production-qualified projection receipt. It also binds the world-meter point
checksum/count to that alignment, then requires floor and sensor-frame self-mask
evidence for the same point receipt and a bounded profile. A diagnostic projection,
even when paired with a synthetic or inconsistent PASS report, returns blockers;
registered maps remain blocked pending AUD-19 QA. No candidate publisher, worker/API
route or SceneIR selection caller was added. Production calibration qualification,
collision-source publication, source-aware object ownership, held-out retention and
Isaac acceptance remain open.
