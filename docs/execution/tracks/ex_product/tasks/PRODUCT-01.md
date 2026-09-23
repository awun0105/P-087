# PRODUCT-01 — Mock-First Project Job And Artifact API

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M0/M1` |

## 2. Goal

Provide fixture-backed project/job/artifact endpoints with source-rights and privacy gating.

## 3. Why This Task Exists

Product shell must develop in parallel before real REC/SCENE/SIM workers exist.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Shared InputManifest/PrivacyValidationReport/JobManifest fixtures.
- API route placement and existing organizer scaffold.

## 5. Input Contract

- User project/input metadata and source-rights attestation.
- Shared fixture manifests/artifact refs.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Typed project/job/artifact API responses.
- Input/attestation/privacy state visible to PRODUCT-02/05.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/api/`
- `src/services/orchestration/`
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` on FastAPI primitives; fixtures use the same contracts as real artifacts.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Request/response and attestation unit/API tests.
- QUARANTINED/missing-rights dispatch negative tests.
- Fixture-backed project→job→artifact smoke.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Endpoints validate typed contracts and never expose hidden local paths.
- [ ] Privacy/source-rights state is enforced and visible.
- [ ] Mock API can later swap to real workers without response-shape rewrite.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- API schema/examples.
- Positive/negative API tests.
- Mock workflow recording/log.

