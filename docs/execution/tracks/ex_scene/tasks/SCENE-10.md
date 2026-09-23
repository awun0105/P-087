# SCENE-10 — Scene Worker Entrypoint

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M2` |

## 2. Goal

Expose stable worker/CLI to transform ReconstructionBundle into SceneIR with explicit status/errors/artifacts.

## 3. Why This Task Exists

PRODUCT orchestration must call a track boundary, not scene internals.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-09 publication path.
- JobManifest/stage lifecycle and artifact resolver.

## 5. Input Contract

- ReconstructionBundle ref, JobManifest and versioned scene config.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Published SceneIR and stage record/error.
- Stable command/interface for PRODUCT-08.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` wrapper around extraction/association/confirmation/decomposition publication stages.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- CLI/config/error unit tests.
- Failed stage cannot publish success negative test.
- Fixture worker smoke and PRODUCT dispatch contract test.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Stable command runs without manual path edits.
- [ ] SUCCEEDED requires valid SceneIR checksum/refs.
- [ ] Failure reports exact stage/retryability and preserves prior attempt provenance.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Example command/log.
- Success and controlled failure JobManifest records.
- PRODUCT dispatch proof.

