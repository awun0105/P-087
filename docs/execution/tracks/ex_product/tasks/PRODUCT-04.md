# PRODUCT-04 — Artifact Registry And Resolver

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Resolve/publish artifacts by identity/checksum instead of personal local paths.

## 3. Why This Task Exists

Every cross-track handoff and release lineage depends on stable artifact access.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-01 artifact API.
- Shared `artifact://jobs/<job_id>/<artifact-path>` URI and `ARTIFACT_ROOT` authority.

## 5. Input Contract

- Artifact refs, bytes/files and metadata from producers.
- Typed `data_class` ở product-facing refs/manifest; URI/path không quyết định
  quyền dùng GT/evaluation-only data.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Registry records, resolver responses and checksum verification.
- Artifact access API used by workers/Web/release.
- MP4 artifact fixture được serve qua FastAPI với `video/mp4` cho browser
  playback; URI/checksum vẫn là identity, không dùng worker-local path.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/artifacts/`
- `src/api/` artifact routes
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

Foundation P0 uses `ArtifactResolver` + `FilesystemArtifactStore` with SHA-256,
atomic immutable publication, existence/schema validation and traversal-safe
resolution. Future configurable backend must preserve this contract.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Publish/resolve/checksum unit tests.
- Checksum mismatch, traversal and missing artifact negative tests.
- Raw GT/evaluation-only dù đổi URI vẫn bị product boundary reject; derived
  GT-assisted giữ provenance và không bị nhầm với raw GT.
- Producer publish→consumer resolve integration test.
- Media smoke sớm: `artifact://.../simulation.mp4` → resolver → FastAPI
  `video/mp4` → browser playback bằng trang/harness tối thiểu, không đợi
  PRODUCT-10; missing/corrupt checksum negative cases.
  HTTP Range chỉ bổ sung nếu playback thực tế cần, không là điều kiện smoke đầu.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Filename/local path is not artifact identity.
- [ ] Resolver verifies checksum and access boundary.
- [ ] Publication is atomic and cannot overwrite an existing URI.
- [ ] All track fixtures/real artifacts can be handed off without manual copy/rename.
- [ ] Browser phát được MP4 fixture qua artifact API; access/missing/checksum
  errors được báo đúng mà không leak local filesystem path.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Registry entries/URIs.
- Checksum negative proof.
- Cross-track resolution test.
- Media response/playback smoke và negative checksum/access evidence.
