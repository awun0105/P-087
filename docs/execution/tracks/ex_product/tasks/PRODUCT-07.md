# PRODUCT-07 — Object And Human Confirmation Actions

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M2/M3` |

## 2. Goal

Expose P0 candidate/object actions through UI/application commands without duplicating Scene Core logic.

## 3. Why This Task Exists

Users must confirm/correct candidates and edit SceneObjects in the product workflow.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-06 viewer selection.
- SCENE-05 Human Confirmation and SCENE-08 edit command contracts.

## 5. Input Contract

- Selected candidate/object, current scene revision and allowed command schema.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Rename/confirm/ignore/merge/create/reassign and move/rotate/hide/delete requests.
- Updated revision/audit feedback.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/features/scene/`
- shared object controls trong `frontend/src/components/`
- `src/api/` command endpoints
- `tests/test_orchestration/` and browser tests

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` UI/application layer consuming Scene Core operations; no local-only mutation.

**UX / Interaction Donor (Audit #4 & #8):**
- Candidate interaction machinery: [`playcanvas/engine`](https://github.com/playcanvas/engine) kết hợp [`playcanvas/supersplat`](https://github.com/playcanvas/supersplat).
- Core machinery đáng adapt (**`REUSE-CORE` & `ADAPT-HIGH`**):
  - `TranslateGizmo` và `RotateGizmo` từ PlayCanvas Engine, gắn trực tiếp vào `pc.Entity` của vật thể.
  - `EntityTransformHandler` và `EditHistory` (Undo/Redo) trích xuất từ SuperSplat.
  - Bộ công cụ selection phong phú (brush, lasso, polygon, volume) phục vụ Human Object Correction.
  - **Human-in-the-Loop Action (Safeguard 2)**: Nút bấm **"Replace Collider with Box"** trên panel thuộc tính của vật thể, cho phép kỹ sư thay thế mesh va chạm phức tạp bằng Box/OBB Collider chuẩn xác.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Kiểm soát Scale**: Không cho phép scale tự do tùy tiện khi chưa đồng bộ được cả Visual, Geometry và Collider. Bắt buộc disable/restrict công cụ Scale theo contract.
  - ❌ **Xóa Gaussian ≠ Xóa SceneObject**: Thao tác xóa cụm điểm trên editor không được tự tiện map thành xóa SceneObject. Xóa SceneObject phải xóa toàn diện cả visual, geometry, collider trong backend revision.
  - ❌ **Backend là Source of Truth**: `EditHistory` chỉ là cache trải nghiệm cục bộ; mọi hành động confirm/commit phải lưu thành `SceneIR` revision trên FastAPI backend.

## 9. Implementation Plan

1. Thiết lập các command handler trên frontend nhận event từ Gizmo PlayCanvas (`transform-committed`, `selection-changed`).
2. Gửi request tương ứng về `src/api/` scene endpoints (Move, Rotate, Hide, Show, Confirm, Ignore, **Replace Collider with Box**).
3. Cập nhật SceneIR revision và reload trạng thái đồng bộ giữa backend và 3D viewport.
4. Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Command authorization/payload unit/API tests.
- Stale revision, invalid operation and hidden local mutation negative tests.
- Candidate correction and object edit browser integration.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] All P0 actions invoke backend domain operations.
- [ ] Stale/conflicting edits return actionable errors.
- [ ] UI reload shows canonical revision/audit result.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Before/after UI and SceneIR.
- Correction/edit API logs.
- Conflict/error case.
