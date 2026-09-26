# Execution Plan: EX-REC track

Date: 2026-09-24

## Status

Active — REC-01/02/02A/03/04 task gates complete. REC-04 real Brush GPU smoke,
SOG roundtrip and render sample verified 2026-09-26. REC-05 audit/implementation
next; real metric spike requires REC-06 confirmed anchor and robot config.

## Outcome

Complete the locked EX-REC tasks one at a time, with independent source review,
task-level proof, and a real `InputManifest` → `ReconstructionBundle` → EX-SCENE
handoff that requires no manual artifact conversion.

## Context and authority

- Current checkout: `feat/ex-rec`; `git status --short` empty at onboarding.
- `AGENTS.md` and `docs/WORKFLOW.md` are the current harness entrypoints.
  `docs/harness/FEATURE_INTAKE.md`, `docs/harness/CONTEXT_RULES.md`, and a
  harness query matrix do not exist in this checkout; user chose the current
  harness on 2026-09-24. Do not invent those missing sources.
- Scope/acceptance: `docs/PRD.md`; dataset/split/leakage:
  `docs/DATASET_PLAYBOOK.md`; shared artifacts/runtime:
  `docs/execution/TEAM_EXECUTION_CONTRACT.md`; placement: `ARCHITECTURE.md`;
  tools/strategy: `docs/execution/INTEGRATION_PLAYBOOK.md`; task IDs/scope:
  `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md`; milestone/owner:
  `docs/execution/TEAM_EXECUTION_PLAN.md`; track/task execution records:
  `docs/execution/tracks/ex_rec/TRACK.md` and its `tasks/REC-*.md`.
- Existing `2026-09-23-integration-foundation.md` is a separate Foundation
  record. Synthetic fixture proof there is not real EX-REC acceptance.
- Baseline: contracts and artifact-store fixtures exist; `src/services/reconstruction/`
  and `tests/test_reconstruction/` have no task implementation, while
  `scripts/torwic/` contains entrypoint placeholders. All 12 REC task files
  currently say `TODO`.

## Input, output, and invariants

- RGB input: moving-camera video or validated frame set via `InputManifest`,
  source-rights attestation, and `PrivacyValidationReport`.
- LiDAR input: registered/fused PLY/PCD. Raw TorWIC scans are limited to offline
  prefusion; product runtime must not read evaluation-only GT.
- Outputs: normalized frames, poses, real Brush visual, voxel RGB geometry (OpenMVS fallback),
  metric/canonical records, optional LiDAR/alignment, and a versioned published
  `ReconstructionBundle` that EX-SCENE resolves directly.
- Canonical: meter, Z-up, right-handed, `world`, `parent_from_local`, quaternion
  `xyzw`, radian. Convert external conventions at adapter boundaries.
- Product artifacts use logical `artifact://jobs/...` URIs, typed data classes,
  atomic immutable publication, SHA-256 byte refs, and canonical-content
  checksums for logical manifests/bundles. GT-assisted LiDAR provenance must
  survive into mixed composition; alignment is a separate confirmed record.
- Do not copy whole research repositories, mix their dependency graphs, change
  shared contracts for convenience, import another track's internals, or claim
  fixture/GPU/real acceptance from a different proof layer.

## Dependency and acceptance map

| Task | Dependency | Minimum task gate from task file |
| --- | --- | --- |
| REC-01 | locked `Aisle_CW` source | Reproducible immutable raw → normalized data, split/calibration/timestamps/checksums and real small preparation smoke. |
| REC-02 | REC-01 for TorWIC; uploads may enter directly | Reject bad/static RGB, publish checksum-bound privacy report, enforce public/demo gate. |
| REC-02A | REC-02 | Deterministic FFmpeg frame artifact with IDs/timestamps/SHA-256; REC-03 consumes it without manual conversion. |
| REC-03 | REC-02A | Real COLMAP small-scene smoke, deterministic model selection, normalized pose/intrinsics with refs and provenance. |
| REC-04 | REC-03 + Brush runtime | Real Brush GPU smoke and resolvable checksummed 3DGS visual artifact; never use it as collider. |
| REC-05 | REC-04 + REC-06 anchor phase; REC-03 fallback | Metric voxel/capsule geometry and Aisle_CW resolution spike; OpenMVS fallback qualification. |
| REC-06 | REC-03/04/05 + locked anchor | Confirm scale only after anchor workflow; propagate same scale to pose/visual/geometry; verify independent distance. |
| REC-07 | REC-01 + declared poses | Offline reproducible registered LiDAR PLY; preserve GT-assistance and checksums if `traj_gt` is used. |
| REC-08 | registered LiDAR or REC-07 | Validate unit/frame/nonempty cloud; immutable resolvable LiDAR artifact and typed dependency provenance. |
| REC-09 | REC-06/08 + confirmed transform | Verify same-scene/checksum binding; separate confirmed alignment; reject unconfirmed/different-scene inputs. |
| REC-10 | REC-02A/03/04/05/06; REC-08/09 when mixed | Publish schema-valid bundle for RGB, optional depth, and mixed configurations; EX-SCENE consumes refs directly. |
| REC-11 | REC-10 + job lifecycle | Stable worker command, structured failures/retry lineage, no false SUCCEEDED or manual path patch. |

One valid serial order is REC-01 → REC-02 → REC-02A → REC-03 → REC-04 →
REC-06 anchor phase → REC-05 → REC-06 final verification → REC-07 → REC-08 →
REC-09 → REC-10 → REC-11. REC-07/08 are otherwise independent of the RGB branch
after REC-01. Mixed alignment is conditional, not a dependency
of RGB-only publication. REC-10 and REC-11 still require their own task gates.

## External source audit queue

Audit only the source needed immediately before each task. Codex records
upstream URL, exact local commit/tag, license, runtime requirements, exact
source file/function I/O, REUSE/ADAPT/REFERENCE/REJECT decision, adapter
boundary, and risks before implementation. Owner canceled Antigravity.

1. REC-01: TorWIC source structure and local `TorWICDataset` utilities;
   FFmpeg/Open3D only for primitives actually needed by preparation. No full
   research-repo audit for unrelated reconstruction stages.
2. REC-02/02A: installed FFmpeg/ffprobe command behavior and the relevant
   `video_to_gsplat.sh` reference, then project-owned probe/extraction adapters.
3. REC-03: pinned `colmap/colmap` CLI, model format, and the relevant
   `colmap_undistorted_sfm_export.sh` reference. Prefer external process reuse.
4. REC-04: pinned Brush training/export entrypoint, COLMAP input support,
   visual payload/format, license, GPU limits. Prefer external process reuse.
5. REC-05: splat-transform 3.6.6 GPU voxelization, capsule carving, collision GLB
   and coordinate boundary; pinned OpenMVS import/densify/mesh fallback.
   Prefer external process reuse.
6. REC-07/08/09: pinned Open3D PCD/PLY I/O, transforms, filtering and
   registration primitives only; project owns provenance/validation/alignment.
7. REC-06/10/11: project contracts, artifact store, and worker conventions;
   no external source by default unless the task proves a need.

System references such as Re3Sim or `video-3d-reconstruction-gsplat` do not
become runtime dependencies by default. SAM2/object extraction, OpenUSD and
Isaac internals belong to other tracks and are not EX-REC source-audit targets.

## Delegation and validation loop

For each task: audit the generated task against PRD, Integration Playbook,
Track Implementation Guide, Team Execution Contract, Team Execution Plan and
the applicable dataset/track authority; amend task-local detail when those
sources expose a gap, without changing higher-level contracts → bootstrap its
Task Capsule and status/Implementation Plan → Codex directly audits relevant
external source and chooses adapter strategy → implement only task-owned paths
→ inspect diff/code, run focused static/unit/contract/integration and real
small smoke as applicable → correct failures before advancing → update task
Result/Evidence and status → create a task-scoped commit after checking diff,
ignored secrets and Git state. Owner stopped Antigravity delegation on
2026-09-24; do not invoke it again for this track.

## Open decisions and risks

- Owner selected all 1,092 `Aisle_CW` frames as the REC-01 source sequence on
  2026-09-24. Owner then selected deterministic temporal block split of about
  10% after timestamp ordering and fixed-rule invalid frame exclusion, with
  blocks across the beginning/middle/end and the frozen split at
  `derived/Aisle_CW/benchmark_split.json`. Proposed exact valid-sequence
  intervals are `118-153`, `528-564`, `937-972` (109 frames), selected by
  12.5%/50%/87.5% centers. No metric has been inspected. Full source integrity
  check and split publication remain pending. The split artifact must remain
  evaluation-only by data class even in `derived/`.
  `docs/PRD.md` still says Primary Demo range TBD; sync this owner decision
  through the appropriate document-owner review, not a task-local PRD rewrite.
- RGB metric anchor and independent test distances are not supplied. REC-06
  cannot claim confirmed scale or complete its DoD without them.
- Source checkout does not establish executable availability. Current COLMAP,
  Brush, OpenMVS and Open3D runtime/build compatibility must be verified per
  task; GPU smoke must name the actual machine and versions.
- Existing Foundation plan still lacks observed repository-wide Python 3.11 CI
  proof; do not import its claimed readiness into task completion.

## Progress and recovery

REC-02 checkpoint 2026-09-24: full 1,092-frame input-only probe in
`eval/results/rec02_aisle_cw_quality_probe.json`; semantics/quantiles and
owner decision in REC-02 §9. Owner approved only Aisle_CW blur exclusion
`>8.5`, with 70%/60-frame motion values as warnings; generic 900-frame floor
was rejected. REC-02 code and tests now cover FFmpeg frame/video probes,
InputManifest frame/video adapters, immutable quality reports, privacy gate
with injected QA verifier and artifact-store publication. Real offline
`Aisle_CW` quality report selected 983, excluded 29, effective 954; no
held-out frame was decoded by quality probe or selected for reconstruction.
User selected public noncommercial demo scope. A concurrent REC-02 evidence
generator created a purported `VERIFIED_ANONYMIZED` artifact under
`data/torwic_slam/derived/aisle_cw/rec02_review_verified/`. Codex audit found
that its CLI could issue verified state from arbitrary reference strings and
fabricated `inspected=983` without checking an external QA record. The unsafe
issuance path was removed; existing generated records were preserved for
review, not accepted as clearance. A new candidate packet under
`rec02_review_pending/` records 983 train IDs with no inferred attestation.
User then explicitly authorized TorWIC public noncommercial demo use for the
983 reconstruction frames. A checksummed rights record and new candidate
under `rec02_review_rights_confirmed/` bind that scope to the frozen split;
the packet still says `inspected=0`, QA pending and `NOT_ISSUED`. Focused
REC-02 tests: 27 passed; full suite: 185 passed; Ruff check/format pass.
User supplied the other agent's exact 983-frame QA attestation and then
explicitly authorized report issuance/completion. Codex verified the record,
manifest, inventory, split and 983 source PNG checksums; a separate addendum
binds the authorization without changing the original record's false flags.
The real `VERIFIED_ANONYMIZED` report was published/resolved with checksum;
its receipt says `public_dispatch_authorized=false`. Local 983-ref handoff,
focused tests (30), full suite (188), Ruff check/format and AST audit passed.
REC-02 is DONE at its own boundary; REC-02A is next. Human inspection is
user-attested and was not repeated by Codex; actual EX-PRODUCT public dispatch
is a later gate. Raw, normalized RGB, held-out split and unrelated migration
scripts were untouched.

REC-02A checkpoint (2026-09-24): FFmpeg 6.1.1 and the pinned MIT
`video_to_gsplat.sh` reference were audited; FFmpeg is reused through a
project-owned process adapter, upstream shell code is not copied. Added
`frame_extraction.py`, `frame_set.py`, a TorWIC-only source resolver and focused
tests. Real REC-02 evidence produced a checksummed 954-frame inventory at
`artifact://jobs/torwic-aisle-cw-rec02a/rec02a/frame_set.json`; all images
resolve from the canonical normalized store, with zero held-out overlap.
The quality report's REC-01 preparation checksum differs from the later
rights-attested InputManifest checksum; the adapter accepts only the explicit
preparation/split lineage plus exact per-frame bytes/timestamps. Focused 5,
full suite 193, Ruff and format pass. REC-03 `ColmapInputAdapter` then consumed
the published frame-set directly, automatically created 954 temporary workspace
PNGs and verified copy inode independence from canonical source. REC-02A is
DONE at the producer/consumer handoff. COLMAP execution belongs to REC-03.
Unrelated `merge.py` and `merge_rec01.sh` remain untracked and untouched.

- [x] Read current harness, authority sections, track, and all 12 task files.
- [x] Inspect current contracts/scaffold and local external checkout inventory.
- [x] Build dependency/acceptance map and staged audit queue.
- [x] Delegate REC-01 read-only source audit; inspect cited source and approve strategy.
- [x] Execute and validate REC-01 with full frozen artifact; continue remaining tasks one at a time.
- [ ] Run real REC → SCENE handoff and closure audit before track completion.

At every handoff, record changed files, exact commands/results, blockers,
decisions, and the next executable step here and in the active task file.

## Validation

Onboarding only: repository status, source documents, task files, contracts,
and external checkout presence inspected. No implementation tests or runtime
smoke have been run for EX-REC in this plan.

REC-01 source audit: Antigravity inspected `TorWICDataset` at
`5e1839f8db73dee784737c53103a4fb06a3fed1d`, then revised two inaccurate
reports after Codex checked actual source. Codex verified `utils/data_loader.py`
lines 18-25 use the Mapping `Scenario_<id>` layout; `utils/laser.py` lines 31-38
produce a 2D ROS `LaserScan`; `utils/pose.py` lines 20-22 use split seconds and
nanoseconds; `utils/calibration.py` lines 10-18 and 71-74 hardcode the old
camera transform/intrinsics. Dataset terms are CC BY-NC 4.0 plus additional
terms in `License/ReadMe.md`. Local SLAM calibration exists and uses both `=`
and `:` separators; Codex caught this while checking the real file after the
helper's final audit. Treat its "key=value" description as corrected here.
No external source module is approved for direct reuse or adaptation in REC-01;
the upstream README/layout is reference only. Project-owned offline file I/O
and parsers are approved. No ROS, Open3D, or upstream utility code is approved
as a new REC-01 dependency. Runtime FFmpeg is conditional on a demo-video step.

REC-01 task audit on 2026-09-24: matched it to PRD §11, Integration Playbook
§2.1, Track Implementation Guide §2.5, Team Execution Contract Ch.5/§3.3,
Team Execution Plan §4.1.1 and Dataset Playbook §12–14. The generated task did
not specify the observed flat SLAM source layout, distinct evaluation-only
output path, resolvable offline relative refs, or the REC-01/REC-02 validation
boundary. Those details are now explicit in the task file. First Antigravity
implementation review failed due invented source layout and incomplete
checksums/selection isolation; second review found source layout fixed but
still incomplete structure checks, non-resolvable file keys, temp-dir reuse,
and missing negative evidence. A third implementation check ran
`.venv/bin/ruff check scripts/torwic tests/test_reconstruction` (pass),
`.venv/bin/ruff format --check scripts/torwic tests/test_reconstruction`
(fail: `prepare_dataset.py:376`), and focused pytest (7 pass). The real small
manifest had valid canonical checksums but marked `benchmark_split.json` as
`product_input`; source code also defaulted missing transform components to
zero. Codex returned these to Antigravity; REC-01 remains IN_PROGRESS, not
accepted. User selected all 1,092 source frames; held-out partition awaits
answer. Next: wait for revision, inspect every changed function/test, rerun
checks and real smoke, then lock full split and complete task gate.

Later REC-01 audit checkpoint: Codex ran fresh real 4-frame smoke under
`/tmp/ex-rec01-codex-smoke-a` and `validate_manifest_offline` succeeded; script
SHA matched the current code. A subprocess probe with absolute dataset root
confirmed an error-path private-root leak, then the next Antigravity revision
removed it (same probe: `private_path_leaked=False`). The revision also made
source timestamps exact strings and separated the source-axis hypothesis from
the canonical target. Codex reran focused pytest (11 passed) and format (pass),
but Ruff check failed on an unused import. AST inspection found two functions
over the 30-line limit; the manifest validator also did not enforce
evaluation-only class for metadata entries. Antigravity is fixing these now.
Do not use helper-reported `/tmp/real_smoke_rec01_v2` as new evidence: its
manifest was from a prior revision and lacked the reported script hash.

REC-01 audit continuation: Codex reran Ruff check/format (pass), focused pytest
(17 pass), AST 30-line/3-parameter check (pass), and independently validated
the real 4-frame `/tmp/real_smoke_rec01_v6` manifest with matching script hash.
Adversarial copies with recomputed file and canonical manifest checksums now
reject duplicate frame entries, altered timestamps and missing mandatory
metadata references. A further adversarial copy proved that altering
`normalized/calibration.json` while rebinding its checksum still passed
validation; another proved that swapping two generated `frame_id`/timestamp
labels while preserving file paths still passed. Antigravity is correcting
source-to-normalized semantic calibration and split provenance now; the
frame-to-path relation remained an open validation defect at that checkpoint.
No full 1,092-frame split has been published yet.

REC-01 continuation: Antigravity revision v9 passed Codex-run Ruff check,
format, 23 focused tests, AST 30-line/3-parameter check, and real 4-frame
manifest validation with a matching current script hash. Codex independently
confirmed adversarial copies now reject wrong CSV timestamp, missing or
duplicate metadata, duplicate split ID, swapped frame labels and modified
generated image bytes with recomputed checksums. The first two actual raw RGB
files have identical SHA-256, so the image-byte negative proof uses frames 0
and 2, whose bytes differ. REC-01 remains open for owner-selected full split,
structural invalid-frame rule, requested derived split placement and broader
contract checks.

## Result

Owner stopped Antigravity and requested direct Codex implementation for the
entire EX-REC track. The last helper session was interrupted after editing
REC-01 files. Codex verified current worktree contains only REC-01 script/test
and task/plan records, 24 focused tests pass, Ruff check/format pass, and AST
30-line/3-parameter check passes. This is a recovery checkpoint only; source
audit, full 1,092-frame output and task gate are still pending. Continue by
inspecting all current REC-01 code and tests, then run the real full split.

REC-01 final gate (2026-09-24): Codex removed two silent `pass` bypasses for
incomplete selection, introduced explicit `complete`/`sample` modes, restored
strict range parsing/extra-frame checks, and added valid PNG, raw immutability,
atomic refusal, private-path and adversarial tests. Direct source audit of
`TorWICDataset` confirmed no upstream module reuse for the SLAM layout. Full
1,092-frame preparation produced 983 normalized train images and 109 held-out
images in three frozen temporal blocks; no structural invalid frames. Durable
prepared output on the Elements volume was validated after copy and marked
read-only. The source-file SHA-256 list of 1,094 files was identical before
and after. Script SHA, manifest/split canonical and byte checksums are in
`tasks/REC-01.md`. Focused pytest 34 passed; contract/integration pytest 96
passed; Ruff check/format and `git diff --check` passed. REC-01 task marked
DONE; next task is REC-02 authority/task audit and FFmpeg source/runtime audit.

The earlier REC-01 result above is historical proof for the flat external
download and was reopened after owner corrected canonical storage policy.
Canonical source/output are both `data/torwic_slam/`; 1,092 normalized RGB
files live once under `normalized/aisle_cw/rgb_frames/`. Frozen split at
`derived/aisle_cw/benchmark_split.json` gives 983 reconstruction and 109
held-out IDs. Dataset-level YAML and traversal preparation JSON are distinct,
checksum-bound records. Codex added an in-place publisher that refuses a
second output root and migrated the existing stale manifest after verifying
source inventory. Full real validator passed 1,094 source + 1,096 generated
refs; raw SHA-256 list before/after unchanged. Focused tests 41 pass,
contract/integration 96 pass, Ruff check/format pass. Details and hashes are
in `tasks/REC-01.md`. The evaluation-only GT symlink was corrected; the
untracked migration scripts were left untouched. REC-02A/REC-03 must enforce
the reconstruction IDs at runtime; evaluator use of held-out IDs is separate.

REC-02 through REC-11 and the cross-track closure audit remain. Do not report
`EX-REC COMPLETE` until real artifacts, checksums/provenance, consumer handoff,
and all applicable task-level evidence are observed.
