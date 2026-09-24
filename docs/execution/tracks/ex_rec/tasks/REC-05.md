# REC-05 — RGB Geometry With OpenMVS

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Tạo dense/mesh RGB geometry artifact đủ cho metric scaling, object association và collider downstream.

## 3. Why This Task Exists

Visual reconstruction không thay thế geometry/physics representation.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03 camera poses và COLMAP model.
- Locked OpenMVS/runtime environment.

## 5. Input Contract

- REC-03 COLMAP model và normalized camera metadata.
- Versioned OpenMVS config.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Normalized RGB geometry artifact ref.
- Geometry/runtime/config provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/adapters/`
- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`REUSE` OpenMVS import/densify/mesh; team viết adapter và output normalization, không viết lại MVS.

**Code Donor Reference (Audit #7):**
- [`InternRobotics/Re3Sim`](https://github.com/InternRobotics/Re3Sim) (chi tiết: [`docs/execution/audits/07_re3sim.md`](../../../audits/07_re3sim.md)):
  - Tham khảo `re3sim/scripts/reconstruct.py` chuỗi lệnh điều phối OpenMVS chuẩn:
    1. `InterfaceCOLMAP` (import SfM scene)
    2. `DensifyPointCloud` (tạo mây điểm dày đặc)
    3. `ReconstructMesh scene_dense.mvs -p scene_dense.ply` (dựng lưới đa giác)
    4. `RefineMesh scene_dense.mvs -m scene_dense_mesh.ply -o scene_dense_mesh_refine.mvs --scales 1 --max-face-area 16` (tối ưu hóa surface)
    5. `TextureMesh` (tùy chọn sinh textured mesh cho visualization/debug)
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Không nuốt lỗi subprocess**: Bắt buộc kiểm tra `check=True`, bắt return code và log chi tiết từng công đoạn OpenMVS.
  - ❌ **Timeout & Checksum**: Mọi artifact mesh trung gian và mesh cuối phải được bọc trong typed config, timeout và hash SHA-256.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Command/config builder unit tests.
- Missing/invalid geometry negative tests.
- Small COLMAP scene to OpenMVS smoke và downstream-readable artifact test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Geometry artifact được tạo bằng stable adapter.
- [ ] Format/coordinate metadata/checksum/provenance đầy đủ.
- [ ] Artifact đủ để REC-06 và EX-SCENE consume qua published ref.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Geometry screenshot/stats.
- OpenMVS version/log/runtime.
- Artifact manifest/checksum.

