# SCENE-04 — Candidate Object Model

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M1/M2` |

## 2. Goal

Define project-owned candidate identities, states and provenance for UNREVIEWED, CONFIRMED, IGNORED and NEEDS_CORRECTION.

## 3. Why This Task Exists

Human correction and preflight need deterministic domain state, not raw mask groups.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-03 candidate identities.
- PRD candidate lifecycle.

## 5. Input Contract

- Associated candidate groups and source refs.
- Scene revision identity.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Candidate object records with stable IDs, states and provenance.
- Validated state-transition operations used by SCENE-05.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/candidates/`
- `src/models/contracts/` only with shared review
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` from PRD; no semantic classifier or business state imported from research repos.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- State/ID/provenance unit tests.
- Invalid transition and duplicate-ID negative tests.
- Serialization/roundtrip contract test.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] All four states represented with explicit transition rules.
- [ ] IDs stable within scene revision and unique.
- [ ] Unresolved candidates can be detected without confusing CandidatePackage review.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Candidate sample artifact.
- Transition test output.
- Duplicate/invalid transition failure.

