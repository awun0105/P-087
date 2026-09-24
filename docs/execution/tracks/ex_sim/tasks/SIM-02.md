# SIM-02 — Collider Generation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M1/M2` |

## 2. Goal

Generate appropriate ColliderSpec for environment and SceneObjects using simple deterministic proxies.

## 3. Why This Task Exists

Raw reconstruction mesh is unsuitable as default physics collider and AC-08 requires floor/obstacle colliders.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SceneIR fixture or SCENE-09 output.
- Accepted collider baseline policy.

## 5. Input Contract

- SceneIR geometry refs and object/environment semantics.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- ColliderSpec records/artifacts for floor/wall, box-like and complex static objects.
- Generation provenance/config.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/colliders/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` policy using Trimesh/Open3D AABB/OBB/convex/simplification utilities.

**Code Donor Reference (Audit #1):**
- Candidate reference: [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim) (xem chi tiết tại [`docs/execution/audits/01_openreal2sim.md`](../../../audits/01_openreal2sim.md)).
- File tham khảo:
  - `reconstruction/modules/scenario_collision_optimization.py` (**`ADAPT-MEDIUM`**): SDF query, ground clearance, thuật toán phát hiện/đẩy vật thể chống penetration với sàn/nền.
  - `reconstruction/modules/scenario_construction.py` (**`ADAPT-MEDIUM`**): Trimesh/Open3D AABB extraction, mesh simplification trước khi tính toán collider.
- **Guardrails:**
  - ❌ **Không thay thế Preflight**: Logic remediation chỉ là tiện ích dọn dẹp trước Candidate Build; Preflight (`SIM-04`) và Isaac validation (`SIM-06`) mới là thẩm quyền quyết định PASS/FAIL cuối cùng.

## 9. Implementation Plan

1. Thiết lập các utility tạo AABB/OBB/convex hull từ mesh/geometry refs (dựa trên Trimesh/Open3D).
2. Tích hợp optional clearance/SDF remediation utility từ `scenario_collision_optimization.py` nếu cần xử lý penetration sàn/vật thể.
3. Sinh và xác thực `ColliderSpec` cho floor, wall và obstacles.
4. Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- AABB/OBB/convex/dimensions unit tests.
- Empty/non-finite/high-poly misuse negative tests.
- Fixture SceneIR collider generation smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Floor/wall and selected obstacles receive allowed collider types.
- [ ] Raw high-poly visual/mesh is not silently used as collider.
- [ ] Every collider binds geometry/object and generation provenance.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Collider overlay/images.
- ColliderSpec samples/checksums.
- Invalid geometry failure.

