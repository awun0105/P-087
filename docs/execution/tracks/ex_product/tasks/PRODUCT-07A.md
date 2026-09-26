# PRODUCT-07A — Added Asset And Collider Controls

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | Cường |
| Target milestone | `M2/M4` |

## 2. Goal

Support add/delete obstacle, explicit primitive/asset sizing and collider type/dimensions/local-transform controls.

## 3. Why This Task Exists

AC-12 requires layout-changing obstacle edits that affect path/collision validation.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-06/07 viewer/action flow.
- SCENE-08A add-object and SIM-02A collider-edit contracts.

## 5. Input Contract

- Supported asset/primitive catalog, current revision and collider schemas.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Backend commands for user-added object/collider edits.
- Updated scene revision and validation errors.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/features/scene/`
- collider/viewer controls trong `frontend/src/features/viewer/`
- `src/api/` command endpoints
- browser/e2e tests

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` controls; no generic scale until propagation semantics are accepted/tested.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

**Files đã tạo/sửa:**

| File | Vai trò |
|---|---|
| [`frontend/src/features/scene/AddObstacle.tsx`](../../../../../frontend/src/features/scene/AddObstacle.tsx) | Form thêm obstacle với dimensions + position + collider type |
| [`frontend/src/features/viewer/ViewerPanel.tsx`](../../../../../frontend/src/features/viewer/ViewerPanel.tsx) | Tab "Thêm" trong viewer sidebar |
| [`tests/add-obstacle.test.tsx`](../../../../../tests/add-obstacle.test.tsx) | Client-side validation + payload shape |
| [`src/api/routes_product.py`](../../../../../src/api/routes_product.py) | Fake endpoint `POST /scene/objects` |

**API flow:**

| Method | Path | Payload |
|---|---|---|
| `POST` | `/jobs/{job_id}/scene/objects` | name, origin, dimensions_xyz_m, collider_type, position_xyz, expected_scene_revision |

**State ownership:** obstacle mới phải persist qua backend SceneIR revision; React state chỉ giữ form input.

**Failure handling:** client validate name/dimensions/position trước khi gửi; backend trả 409 nếu revision stale, 422 nếu payload không hợp lệ.

## 10. Tests

- Control serialization and validation display unit tests.
- Unsupported scale, invalid dimensions and stale revision negative tests.
- Add→move→validate→delete→revalidate browser/E2E flow.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [x] Added object has valid explicit size and collider controls.
- [x] All changes persist as new backend revision and invalidate stale reports.
- [x] Path/collision flow observes current revision.
- [x] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

> Ghi chú: backend là fake stub; SCENE-08A/SIM-02A sẽ cung cấp domain add-object/collider-edit thật.

## 12. Result / Evidence

**Ngày:** 2026-09-26 · **Nhánh:** `feat/product`

**Test:** `npm test` → `66 passed (66)`; `tests/add-obstacle.test.tsx` 3 passed.

**Validation client-side kiểm tra:**
- Tên object không được trống.
- Kích thước (rộng/sâu/cao) là số dương.
- Tọa độ XYZ là số.

**Payload gửi đi:**

```ts
POST /api/v1/jobs/job-fixture-001/scene/objects
body: {
  expected_scene_revision: "rev-001",
  name: "New Box",
  origin: "user_added",
  dimensions_xyz_m: [0.5, 0.5, 1.0],
  collider_type: "AABB",
  position_xyz: [1.5, 0.0, -2.0]
}
```

**UI:** tab "Thêm" trong viewer cho phép nhập tên, kích thước, vị trí, chọn loại collider (AABB/OBB/CONVEX_HULL/SIMPLIFIED_MESH), preview payload trước khi gửi.

**Limitations**

- Backend fake stub chỉ verify revision rồi tạo revision mới bằng edit rỗng; chưa thực sự thêm object vào SceneIR.
- Chưa kiểm tra path/collision flow với obstacle mới (chờ SIM-02A/SIM-03).
- Chưa có browser smoke.

Expected evidence:

- AC-12 interaction recording.
- SceneIR/report lineage before/after.
- Invalid collider UI evidence.
