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

**Code Donor Reference (Audit #1):**
- Candidate reference: [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim) (xem chi tiết tại [`docs/execution/audits/01_openreal2sim.md`](../../../audits/01_openreal2sim.md)).
- File tham khảo:
  - `reconstruction/modules/scenario_construction.py` (**`ADAPT-MEDIUM`**): Trích xuất các tiện ích hình học (Open3D + Trimesh) cho mesh ↔ point cloud registration, centroid alignment, ICP, ground alignment.
  - `background_pixel_inpainting.py` + `background_mesh_generation.py` (**`ADAPT P1`**): Ghi nhận reference cho `BackgroundCompletionBackend` ở giai đoạn P1 (không kéo vào P0 core).
- **Guardrails:**
  - ❌ **Không thay Canonical Coordinate Contract**: Mọi transform phải tuân thủ nghiêm ngặt `parent_from_local` và quy ước hệ trục của Real2Sim Studio.
  - ❌ **Không kéo submodules nặng**: Không đưa Hunyuan3D-2 hay Mega-SAM vào P0 runtime dependencies.

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

