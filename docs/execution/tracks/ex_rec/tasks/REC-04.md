# REC-04 — Visual Reconstruction With Brush

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Tạo 3DGS visual artifact từ COLMAP output qua Brush adapter.

## 3. Why This Task Exists

Cung cấp Visual Representation cho Primary RGB Product Path và Web preview.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03 camera poses và COLMAP model.
- Locked Brush/runtime environment cho heavy smoke.

## 5. Input Contract

- REC-03 COLMAP model/camera poses.
- Versioned training/config parameters.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Checksummed visual artifact ref.
- Training/runtime/config provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/adapters/`
- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`REUSE` Brush CLI/API qua process boundary; không copy trainer hoặc dùng visual artifact làm collider.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Config/command/provenance unit tests.
- Missing COLMAP artifact negative test.
- Small COLMAP scene to Brush GPU smoke.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Adapter tạo visual artifact bằng reproducible config.
- [ ] Output publish qua artifact ref/checksum, không private temp path.
- [ ] Downstream có thể resolve visual artifact; collider path không consume nó.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Visual screenshots/render sample.
- Brush/runtime/GPU versions và duration.
- Artifact manifest/checksum.

