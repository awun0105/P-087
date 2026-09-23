# SCENE-01 — Fixture-First ReconstructionBundle Consumer

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M0/M1` |

## 2. Goal

Load, validate and expose a stable internal view of fixture/real ReconstructionBundle without reading producer temp folders.

## 3. Why This Task Exists

Cho EX-SCENE phát triển song song và tạo proof cho handoff REC→SCENE.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Normative ReconstructionBundle contract and shared fixture.
- No upstream real artifact required for initial implementation.

## 5. Input Contract

- Published ReconstructionBundle artifact/ref.
- Artifact resolver and schema version.
- Depth metadata và LiDAR preprocessing dependency được đọc theo shared
  contract; consumer không yêu cầu TorWIC depth scale hay trajectory GT key.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Validated bundle view for masks/poses/geometry consumers.
- Actionable contract error on invalid/unresolved input.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/`
- `tests/test_scene/`
- `fixtures/reconstruction_bundle/` and contract tests with EX-REC review

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` loader/validator against shared contract; no producer-internal imports.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Valid fixture deserialize/resolve test.
- Schema-version, checksum and unresolved-ref negative tests.
- Real REC bundle consumer integration test when available.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Fixture bundle is consumed directly.
- [ ] Invalid/unresolved bundle fails before scene processing.
- [ ] Same consumer accepts real bundle without manual conversion.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Fixture and real bundle checksums.
- Consumer test output.
- Representative contract failure.
