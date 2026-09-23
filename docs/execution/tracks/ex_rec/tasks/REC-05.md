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

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

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

