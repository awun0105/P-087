# Execution Plan: EX-SCENE Rush Path

Date: 2026-09-29

## Status

Active

## Outcome

Produce the fastest contract-shaped EX-SCENE implementation path that can run from
a fixture `ReconstructionBundle` to a valid `SceneIR`, with deterministic domain
operations and explicit runtime blockers for SAM2/real reconstruction acceptance.

## Context

- `AGENTS.md`
- `ARCHITECTURE.md`
- `docs/PRD.md`
- `docs/execution/TEAM_EXECUTION_CONTRACT.md`
- `docs/execution/INTEGRATION_PLAYBOOK.md`
- `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md`
- `docs/execution/TEAM_EXECUTION_PLAN.md`
- `docs/execution/tracks/ex_scene/TRACK.md`
- `docs/execution/tracks/ex_scene/tasks/SCENE-01.md` through `SCENE-10.md`
- `src/models/contracts/reconstruction.py`
- `src/models/contracts/scene.py`
- `fixtures/reconstruction_bundle/`
- `fixtures/scene_ir/`

## Scope

In scope:

- Preserve and validate the current SCENE-01 bundle consumer.
- Add deterministic, fixture-first SCENE domain modules for extraction metadata,
  association, candidate state/confirmation, decomposition, SceneIR publication,
  edit/add operations, and a worker boundary.
- Add focused tests under `tests/test_scene/`.
- Record blockers where real SAM2, real REC output, or EX-SIM runtime proof is
  required.

Out of scope:

- Installing or vendoring SAM2/Open3D/research repositories.
- Changing shared contracts without producer/consumer review.
- Claiming real GPU/SAM2/Brush/Isaac/E2E acceptance from fixture tests.
- Editing EX-REC, EX-SIM, EX-PRODUCT internals.

## Approach

1. Audit existing SCENE code, contracts, fixtures, and tests.
2. Keep implementation additive inside `src/services/scene/`.
3. Implement a deterministic adapter path that emits the same kind of metadata
   later SAM2/association implementations must emit.
4. Build candidate and edit operations as pure functions over typed dataclasses
   and existing shared `SceneIR` contracts.
5. Publish/verify `SceneIR` with canonical content checksum and resolvable refs.
6. Add a worker-style orchestration function around the fixture path.

## Risks And Recovery

- SAM2 runtime is absent. Mitigation: make the deterministic extractor explicit
  and do not label it real SAM2 proof.
- Real reconstruction output is absent. Mitigation: keep SCENE-01 fixture proof
  and leave real handoff as blocked evidence.
- Shared schema may be insufficient for later behavior. Mitigation: avoid schema
  changes unless a concrete blocker appears.

## Progress

- [x] Bootstrap repository state and authority docs.
- [x] Inspect EX-SCENE task files, current contracts, and fixtures.
- [x] Implement focused fixture-first EX-SCENE modules.
- [x] Add focused tests.
- [x] Run validation and update plan evidence.

## Decisions

- 2026-09-29: Use a deterministic fixture extractor instead of SAM2 for local
  rush path because SAM2 runtime/checkpoint is not present in repo dependencies.
  This is fixture proof only, not model acceptance.
- 2026-09-29: Avoid shared contract edits unless implementation hits a true
  contract gap; existing `SceneIR` contract already covers P0 object fields.

## Validation

- Focused proof: `pytest --noconftest tests/test_scene/ -q` → 11 passed.
- Contract + focused proof:
  `pytest --noconftest tests/test_contracts/test_scene.py tests/test_scene/ -q`
  → 21 passed.
- Static proof: `ruff check src/services/scene tests/test_scene` could not run
  because `ruff` is not installed or on PATH in the current environment;
  `python -m ruff ...` also failed with `No module named ruff`.

## Result

Implemented a fixture-first EX-SCENE rush path:

- deterministic mask metadata extractor;
- baseline mask association;
- candidate object state model and confirmation operations;
- decomposition bindings;
- SceneIR builder/checksum refresh;
- edit/add primitive operations;
- fixture worker boundary from `ReconstructionBundle` ref to `SceneIR`.

This is fixture/deterministic proof only. Real SAM2 smoke, real
`ReconstructionBundle`, real object quality evidence and EX-SIM handoff remain
blocked on external runtime/artifacts.
