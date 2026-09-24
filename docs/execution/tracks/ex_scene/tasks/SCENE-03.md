# SCENE-03 — Multi-View Object Association

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M1/M2` |

## 2. Goal

Associate masks across views with camera poses and canonical geometry to create stable candidate identities.

## 3. Why This Task Exists

SAM2 masks per frame do not establish cross-view object identity.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-01 poses/canonical geometry.
- SCENE-02 mask artifacts.

## 5. Input Contract

- Masks with metadata, normalized camera poses and canonical geometry.
- Deterministic association config.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Candidate identity groups with source mask/geometry refs and provenance.
- Association confidence/diagnostics.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/association/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` deterministic baseline; Gaussian Grouping/ObjectGS/SegAnyGaussians are `REFERENCE`.

**Code Donor Reference (Audit #2):**
- Candidate algorithm donor: [`BigCiLeng/R2G`](https://github.com/BigCiLeng/R2G) / `sampro3d` submodule (xem chi tiết tại [`docs/execution/audits/02_r2g.md`](../../../audits/02_r2g.md)).
- Core code/logic đáng adapt (**`ADAPT-HIGH`**):
  - SAMPro3D: `perform_3dsegmentation()`, `compute_mapping()`, `prompt_filter()`, `prompt_consolidation()`.
  - Thuật toán: Chiếu 3D điểm sang camera views (fx/fy/cx/cy), visibility/occlusion test, tích lũy điểm membership từ 2D SAM2 masks, lọc nhiễu không gian bằng DBSCAN, và hợp nhất các candidate instances trùng lặp (`prompt_consolidation`) gợi ý cho HITL merge.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Không copy nguyên `compute_mapping()`**: R2G hardcode `depth_shift = 1000`, `R_edit = diag(1, -1, -1)` và `.tif` depth. Mọi transform và camera projection phải tuân theo canonical `CoordinateSystem` của Real2Sim Studio.
  - ❌ **Data Adapter cho Depth**: SAMPro3D cần depth. Khi primary path chỉ có OpenMVS mesh, phải render depth từ viewpoint; chỉ dùng trực tiếp khi có `DepthFrameSet` artifact hợp lệ.
  - ❌ **Không kéo Cutie vào P0**: Đã khóa SAM2 cho video mask propagation; Cutie chỉ là reference/fallback.

## 9. Implementation Plan

1. Xây dựng `MultiViewProjectionService` chuyển đổi điểm 3D/mesh vertices sang camera coordinate theo canonical contract.
2. Adapt logic voting và tích lũy score từ SAMPro3D kết hợp với SAM2 mask artifacts.
3. Tích hợp DBSCAN spatial cleanup và `prompt_consolidation` để tạo candidate groups và merge suggestions cho Human Confirmation.
4. Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Deterministic grouping and stable-ID unit tests.
- Conflicting/unprojectable mask negative tests.
- Fixture masks+poses+geometry smoke.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Repeated run on same fixture produces same grouping/IDs.
- [ ] Each group traces to masks, poses and geometry selections.
- [ ] Baseline produces input accepted by SCENE-04.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Grouping visualization/table.
- Config/seed/checksum.
- Failure/ambiguity sample.

