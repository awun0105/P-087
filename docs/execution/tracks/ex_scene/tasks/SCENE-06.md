# SCENE-06 — Scene Decomposition

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M2` |

## 2. Goal

Decompose global reconstruction into Environment and independent object bindings.

## 3. Why This Task Exists

Global reconstruction is not an editable scene; confirmed objects must be independently transformable/removable.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-05 confirmed candidates.
- Canonical geometry and representation refs.

## 5. Input Contract

- Confirmed candidates, global visual/geometry and canonical coordinate metadata.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Environment representation and object-level visual/geometry bindings.
- Decomposition provenance.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/decomposition/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` with R2G/gs-real2sim/DISCOVERSE as `REFERENCE`; do not make full research systems runtime dependencies.

**Code Donor Reference (Audit #1, #2 & #6):**
- [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim) (chi tiết: [`docs/execution/audits/01_openreal2sim.md`](../../../audits/01_openreal2sim.md)):
  - `reconstruction/modules/scenario_construction.py` (**`ADAPT-MEDIUM`**): Tiện ích hình học Open3D + Trimesh (mesh ↔ point cloud registration, centroid alignment, ICP, ground alignment).
  - `background_pixel_inpainting.py` + `background_mesh_generation.py` (**`ADAPT P1`**): Tham chiếu `BackgroundCompletionBackend` P1.
- [`BigCiLeng/R2G`](https://github.com/BigCiLeng/R2G) (chi tiết: [`docs/execution/audits/02_r2g.md`](../../../audits/02_r2g.md)):
  - Per-object point cloud export (`models/point_cloud/obj_*.ply`) (**`ADAPT-HIGH`**).
  - Trích xuất OBB định hướng qua `get_aabb.py` (Open3D minimal OBB: center, dimensions, rotation) (**`ADAPT-HIGH`** cho candidate bounding box).
  - Assist-GS: Phân rã Gaussian background và object models (`object_*.ply`) (**`ADAPT P1 / Fallback`** nếu việc trích xuất subset từ Brush Gaussian gặp khó khăn).
- [`lkeab/gaussian-grouping`](https://github.com/lkeab/gaussian-grouping) (chi tiết: [`docs/execution/audits/06_gaussian_grouping.md`](../../../audits/06_gaussian_grouping.md)):
  - Khái niệm `GaussianObjectMembership`: Ánh xạ tập hợp Gaussian splats thuộc về từng object mà không mutate hay ghi đè lên file PLY gốc của Brush.
  - Non-destructive Object Removal / Hide Preview: Khi người dùng ẩn/loại bỏ đối tượng, thao tác là `visibility = false` trên `SceneRevision` / Viewer thay vì xóa vĩnh viễn hàng Gaussian trong file PLY.
  - P1 Background Visual Completion: Kỹ thuật inpaint 2D-guided (LaMa) cho các khoảng trống sau khi di dời/xóa vật thể.
- **Guardrails:**
  - ❌ **Không thay Canonical Coordinate Contract**: Mọi transform phải tuân thủ nghiêm ngặt `parent_from_local` và quy ước hệ trục của Real2Sim Studio.
  - ❌ **Không đổi Brush sang Assist-GS trong P0**: P0 giữ Brush làm primary Visual backend; Assist-GS là fallback ở P1.
  - ❌ **Không dùng R2G directory layout làm canonical**: Output từ R2G phải qua `SceneObjectAdapter` chuẩn hóa thành `SceneIR`.
  - ❌ **Không dùng GPT-4 methods của R2G**: Tuyệt đối không upload ảnh lên `sm.ms` và không để LLM gán mass/collider làm physics truth.
  - ❌ **Không kéo submodules nặng**: Không đưa Hunyuan3D-2 hay Mega-SAM vào P0 runtime dependencies.
  - ❌ **Cấm dùng Convex-Hull Expansion làm Collider**: Thuật toán mở rộng convex hull từ Gaussian points (Gaussian Grouping) chỉ là heuristic loại bỏ visual thô, dễ gây over-removal (bao trùm cả khoảng trống ở kệ hàng chữ U) và suy thoái hình học (`Qhull` failure). Tuyệt đối không dùng làm ground-truth geometry hay collider.
  - ❌ **Visual Inpainting ≠ Physics Truth**: Kết quả vá lỗ hổng 3DGS (inpainted visual) chỉ phục vụ tính thẩm mỹ của viewport thị giác (P1), không có bằng chứng cảm biến và cấm dùng làm collision surface hay vật lý.

## 9. Implementation Plan

1. Thiết lập cấu trúc phân rã SceneIR: tách Environment và Object bindings độc lập.
2. Tận dụng các utility alignment từ `scenario_construction.py` để chuẩn hóa bounding box và vị trí đối tượng.
3. Liên kết visual và geometry artifact refs cho từng object đã confirm.
4. Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Environment/object partition and ref-binding unit tests.
- Overlap/missing geometry/duplicate ownership negative tests.
- Candidate-to-decomposition fixture smoke.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Environment and independent object bindings exist.
- [ ] Confirmed reconstructed object can be removed from active geometry/physics path.
- [ ] Bindings preserve source provenance and feed SCENE-07/09.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Decomposition sample/visualization.
- Object-to-source mapping.
- Ambiguous binding failure.

