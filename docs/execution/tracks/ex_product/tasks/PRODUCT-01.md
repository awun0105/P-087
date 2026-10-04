# PRODUCT-01 — Mock-First Project Job And Artifact API

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
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

**Files**

| File | Vai trò |
|---|---|
| [`src/services/orchestration/projects/errors.py`](../../../../../src/services/orchestration/projects/errors.py) | Lỗi domain, kế thừa `RuntimeError` theo khuôn `artifacts/errors.py` |
| [`src/services/orchestration/projects/privacy.py`](../../../../../src/services/orchestration/projects/privacy.py) | Luật privacy gate thuần, không I/O |
| [`src/services/orchestration/projects/models.py`](../../../../../src/services/orchestration/projects/models.py) | Input model + `ProjectRecord` (product-level, không phải shared contract) |
| [`src/services/orchestration/projects/registry.py`](../../../../../src/services/orchestration/projects/registry.py) | `ProjectRegistry` nạp fixture, giữ project/job, lọc artifact theo `data_class` |
| [`src/api/schemas.py`](../../../../../src/api/schemas.py) | DTO response |
| [`src/api/routes_product.py`](../../../../../src/api/routes_product.py) | 7 endpoint product |
| [`src/api/routes.py`](../../../../../src/api/routes.py) | `router.include_router(product_router)` — không sửa `main.py` |

**API flow (sau `/api/v1`)**

| Method | Path | State ownership |
|---|---|---|
| `POST` | `/projects` | Tạo `ProjectRecord`, privacy khởi tạo `PRELIMINARY_SCREENED` |
| `GET` | `/projects` | Đọc registry |
| `GET` | `/projects/{project_id}` | Đọc registry |
| `GET` | `/projects/{project_id}/privacy` | Cho PRODUCT-02/05 |
| `GET` | `/projects/{project_id}/jobs` | Đọc registry |
| `POST` | `/projects/{project_id}/jobs` | **Qua privacy gate**, tạo `JobManifest` QUEUED |
| `GET` | `/jobs/{job_id}` | Đọc registry |
| `GET` | `/jobs/{job_id}/artifacts` | Lọc theo `data_class` có type |

State nằm ở backend registry, không ở UI. `record_privacy_report()` là seam duy nhất
để nâng privacy state — PRODUCT-03/08 cắm `ST-PRIVACY-GATE` thật vào đó.

**Failure handling**

| Tình huống | Kết quả |
|---|---|
| Attestation thiếu field / `rights_to_use_confirmed` mà không `anonymization_confirmed` | `422` (validator của `SourceRightsAttestation`) |
| Project/job không tồn tại | `404` với `{"detail": ...}` |
| Privacy chưa cho dispatch | `409` với lý do tiếng Việt |

## 10. Tests

- `tests/test_orchestration/test_privacy_gate.py` — luật gate thuần, 8 test.
- `tests/test_orchestration/test_project_registry.py` — seed, tạo project, gate, lọc artifact, not-found, 16 test.
- `tests/test_api/test_product_routes.py` — HTTP thật qua `ASGITransport`, 18 test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [x] Endpoints validate typed contracts and never expose hidden local paths.
- [x] Privacy/source-rights state is enforced and visible.
- [ ] Mock API can later swap to real workers without response-shape rewrite.
- [x] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

Ô thứ ba **cố ý để trống**: response shape tái dùng thẳng shared contract
(`JobManifest`, `ProductArtifactRef`) và registry có seam `record_privacy_report()`,
nhưng việc "swap được" chỉ chứng minh được khi có worker thật cắm vào.

## 12. Result / Evidence

**Ngày:** 2026-09-24 · **Nhánh:** `feat/product`

**Test — `pytest tests/` (CI set `OPENAI_API_KEY`, không có key thật):**

```
160 passed in 0.67s     ← lúc đóng PRODUCT-01
288 passed in 3.07s     ← cuối ngày 24/09, sau khi PRODUCT-02/06 thêm test của chúng
```

**Test — `python -m scripts.check_foundation`:**

```
[PASS] typed contract fixtures
[PASS] artifact existence and SHA-256
[PASS] synthetic handoff lineage
[PASS] negative fixtures rejected
[PASS] stage/task documentation projection
Foundation fixture readiness: READY (M0 freeze also requires CI and common commit SHA)
```

**Smoke — request/response mẫu (chưa có `frontend/`, nên là API-level, không phải browser proof):**

```jsonc
// GET /api/v1/projects/project-fixture-001/privacy
{
  "result": "VERIFIED_ANONYMIZED",
  "input_manifest_checksum": "sha256:afe1bbad09183a1e732c4deb9b4f22b37753852c9275acbfb683f78c5ad65622",
  "inspection_scope": "approved_copy",
  "unresolved_finding_count": 0,
  "dispatch_allowed": true,
  "block_reason": null
}

// GET /api/v1/jobs/job-fixture-001/artifacts
{
  "job_id": "job-fixture-001",
  "artifacts": [{
    "artifact_type": "InputManifest",
    "schema_version": "1.0",
    "artifact_uri": "artifact://jobs/job-fixture-001/manifests/input_manifest.json",
    "artifact_checksum": "sha256:61c9b7ebf77ed5d2fafdda6a19c2c412f7afe5742d320b759b56060dc089b7a5",
    "data_class": "derived",
    "producer_stage": "ST-INPUT-VALIDATE",
    "job_id": "job-fixture-001",
    "source_provenance": null
  }],
  "excluded_artifact_count": 0
}

// POST /api/v1/projects  →  201, project mới luôn ở mức sàng lọc sơ bộ
{ "privacy": { "result": "PRELIMINARY_SCREENED", "dispatch_allowed": false,
               "block_reason": "input mới ở mức sàng lọc sơ bộ, chưa được QA xác nhận ẩn danh" } }

// POST /api/v1/projects/{project_id}/jobs  →  409
{ "detail": "không thể tạo job: input mới ở mức sàng lọc sơ bộ, chưa được QA xác nhận ẩn danh" }
```

**Limitations**

- `PrivacyValidationReport` của project mẫu là **suy luận từ fixture** (job có
  `status: SUCCEEDED` ⇒ `ST-PRIVACY-GATE` đã cho qua trong lần chạy mẫu), không phải
  QA ký. Chưa có `ST-PRIVACY-GATE` thật.
- `source_rights_attestation` của project mẫu giữ nguyên văn `{"attested": true,
  "fixture": true}` của fixture — **không** được nâng thành attestation người dùng khai.
- Registry là in-memory, mất state khi restart.
- Trạng thái `QUARANTINED` chưa có project mẫu nào chạm tới; luật đã được test ở tầng
  unit nhưng chưa có đường end-to-end.
- Blocker môi trường Windows: `core.autocrlf=true` làm sai mọi checksum fixture, đã
  sửa cục bộ (`git config --local core.autocrlf false`); repo vẫn **chưa có**
  `.gitattributes` nên máy Windows khác sẽ gặp lại.

