# Execution Plan: Complete Integration Foundation

Date: 2026-09-23

## Status

Active

## Outcome

Hoàn thiện Integration Foundation đã được user khóa để bốn track phát triển song
song bằng synthetic fixtures: authority docs thống nhất, shared contracts typed,
artifact storage/resolution hoạt động, positive/negative tests và lightweight
cross-boundary proof pass, task catalog/crosswalk đồng bộ và readiness checker
trả kết quả rõ ràng.

## Context

- User Foundation decisions trong turn hiện tại là authority trực tiếp.
- `AGENTS.md`, `docs/WORKFLOW.md`: execution/quality/conflict rules.
- `docs/PRD.md`, `ARCHITECTURE.md`: product và placement authority.
- `docs/execution/TEAM_EXECUTION_CONTRACT.md`: normative shared contract.
- `docs/execution/INTEGRATION_PLAYBOOK.md`: technical projection.
- `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md`: task catalog.
- `docs/execution/TEAM_EXECUTION_PLAN.md`: ownership/milestones.
- Existing untracked contract/fixture scaffold thuộc current worktree và được
  tiếp tục, không xóa hoặc thay đổi unrelated user work.

## Scope

In scope:

- Đồng bộ ownership, coordinate/transform, SceneIR, REC-02A, path validation,
  artifact storage, 3DGS stretch status, TorWIC bring-up và runtime TBD vào docs.
- Typed Pydantic contracts cho coordinate, transform, stages/status/errors,
  mixed reconstruction, LiDAR/alignment, SceneIR, structured validation và
  conditional evaluation/release.
- Filesystem artifact store/resolver, SHA-256, atomic immutable publication,
  existence/schema validation.
- Synthetic resolvable fixtures, invalid fixtures, contract/integration tests,
  revision invalidation và evaluation-data-isolation proof.
- CI PR target `develop`, partial CODEOWNERS with known handle/TODO, Foundation
  readiness checker và affected track/task docs.

Out of scope:

- PostgreSQL hoặc production database.
- Real TorWIC normalization/reconstruction.
- Real COLMAP/Brush/OpenMVS/SAM2/Isaac execution.
- Browser Gaussian renderer/WebGPU hoặc production Brush-format claim.
- Final benchmark coordinates/labels và full E2E product.
- Commit, push, PR hoặc branch mutation.

## Approach

1. Update authority docs and remove known semantic conflicts.
2. Implement typed contracts and lifecycle invariants.
3. Implement artifact store/resolver and development setting.
4. Materialize synthetic payloads/manifests with real referenced-file SHA-256.
5. Add positive/negative, handoff, invalidation and isolation tests.
6. Add readiness checker, CI/develop and CODEOWNERS guidance.
7. Synchronize REC-02A and all affected task/track documentation.
8. Run focused/full validation, consistency audit and complete this plan.

## Risks And Recovery

- Dirty worktree contains user changes: edit only authorized overlapping files
  and additive Foundation paths; do not stage or revert unrelated changes.
- Self-identifying manifest checksums are not used as byte-level resolver proof;
  external `ArtifactRef` checksums verify exact bytes. Document that distinction.
- Synthetic visual payload is explicitly a deterministic mock format, not Brush
  compatibility proof.
- Missing real GPU/data versions remain `UNVERIFIED/TBD` by authority.
- Recovery is file-level because no migration, external write or destructive
  operation is performed.

## Progress

- [x] Bootstrap repository, authority and current scaffold.
- [x] Synchronize authority docs and task catalog.
- [x] Implement typed contracts and artifact services.
- [x] Build resolvable fixtures and negative fixtures.
- [x] Add contract/integration/invalidation/isolation tests.
- [x] Add readiness checker, CI and CODEOWNERS changes.
- [x] Run Foundation validation and consistency audit.
- [ ] Verify repository-wide Python 3.11 CI run, then move plan to completed.

## Decisions

- 2026-09-23: Apply user-provided Foundation decisions verbatim; do not infer
  missing benchmark/runtime values.
- 2026-09-23: `SceneIR` content excludes workflow review state; workflow state is
  modeled separately and edit invalidation clears downstream lineage.
- 2026-09-23: Direct browser Gaussian rendering is stretch/non-blocking; synthetic
  fixture declares a deterministic mock visual format only.
- 2026-09-23: Viewer priority above is superseded by `docs/PRD.md` v1.12:
  real Brush 3DGS browser rendering is P0. Foundation's synthetic fixture remains
  a contract/integration fixture, not browser compatibility evidence.
- 2026-09-23: Artifact byte verification is performed through external
  `ArtifactRef`; manifest-internal identity fields are not treated as
  self-referential byte checksums.

## Validation

- `ruff check src/ tests/ scripts/check_foundation.py` → PASS.
- `ruff format --check src/ tests/ scripts/check_foundation.py` → PASS, 75 files already formatted.
- `python -m pytest tests/test_config.py -v` with test API-key environment → 3 passed.
- `python -m pytest tests/test_contracts tests/test_orchestration tests/integration -v` → 32 passed.
- `python -m scripts.check_foundation` → READY; all four readiness groups PASS.
- `git diff --check` → PASS.
- Consistency audit confirms `REC-02A`, `REC-07`, SceneIR review-state isolation,
  evaluation-only expected labels, artifact URI semantics and conditional
  evaluation-report release invariant are projected in active authority docs.
- `REQUIRED_ROUTE_BLOCKED` drift fixed: it is no longer a `PreflightRuleId`; a
  regression test rejects that misuse and `SIM-06` now documents the correct
  Isaac/Product-config boundary.
- Repository-wide `pytest tests/ -v` is NOT verified green on this checkout.
  Local Python is 3.14.0 while CI targets 3.11; the run collected 46 tests and
  timed out after the first LangGraph test reported PASS. Isolated LangGraph
  tests also reported PASS but process teardown was intermittently slow/hung.
  Python 3.11 is not installed locally, so CI-equivalent execution remains
  external/unverified until the GitHub Actions run executes on a PR/push.

## Result

Integration Foundation implementation is locally ready at the synthetic
fixture/integration level. Typed contracts, canonical coordinate/transform
semantics, mixed-modality reconstruction, SceneIR, validation/evaluation
isolation, immutable artifact storage, fixtures, negative proofs, handoff tests,
revision invalidation, readiness checker and CI definition are in place.

This result is explicitly NOT real TorWIC reconstruction proof, Brush
compatibility proof, Isaac/GPU acceptance or final benchmark acceptance.

The only completion gate not currently observable from this local checkout is
the repository-wide Python 3.11 CI result. Keep this plan active until that CI
run is observed green; do not mark implementation-track tasks DONE because of
Foundation fixture evidence.

## M0 freeze follow-up — 23/09/2026

- User locked `Aisle_CW` as P0 traversal, `Aisle_CCW` as backup and supplied
  REC-01B sensor-verification results. `REC-01A` report/checksums are not present
  in repository; do not infer its output. The REC-01B `verify.py` exists on the
  external dataset volume, but its full run was not repeated in this task.
- Dataset Playbook records observed 1092/1092 sync, `T_world_from_sensor`,
  `T_os_from_cam` direction, uint16 depth scale 0.001 and residual 0.147 m with
  provenance/uncertainty. `os_sensor` remains unconfirmed by SLAM backend.
- Contract now supports optional RGB+Depth metadata without changing P0 product
  input scope. LiDAR GT-assistance dependency must propagate from source ref into
  mixed bundle provenance. Added resolvable depth, rack, pallet and
  floor/collider fixtures plus typed EX-PRODUCT workflow snapshots.
- `python -m pytest tests/test_contracts tests/integration tests/test_orchestration tests/test_config.py -q`
  → 43 passed. `ruff check src/ tests/ scripts/check_foundation.py` and
  `ruff format --check src/ tests/ scripts/check_foundation.py` → PASS.
- `python -m scripts.check_foundation` → synthetic fixture readiness PASS.
  `python -m pytest tests/test_config.py -q` → 3 passed.
- `timeout 45s python -m pytest tests/ -q` → timeout (exit 124) after initial
  dots on local Python 3.14. Python 3.11 executable was not found locally.
- M0 freeze remains **NOT READY** for four-track branching until intended
  Foundation changes are committed into one shared commit/SHA and Python 3.11
  repository CI is observed green. No commit/branch/push was authorized in this
  task. Current `Quan` HEAD predates the dirty Foundation work.
