# REC-08 — Registered LiDAR Ingest

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Validate format/unit/frame và publish immutable LiDARGeometryArtifact.

## 3. Why This Task Exists

Chứng minh LiDAR là geometry source thực sự, không chỉ upload rồi bỏ qua.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Registered/fused LiDAR product input hoặc REC-07 output.
- LiDARGeometryArtifact normative contract.

## 5. Input Contract

- Registered/fused LiDAR và declared metadata.
- InputManifest/source checksum; `lidar_metadata` bắt buộc khi
  `registered_lidar_present` là true.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Checksummed LiDARGeometryArtifact.
- Format/unit/frame và generic preprocessing dependencies: direct registered
  input, estimated/external poses hoặc GT-assisted source có checksum.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/lidar/`
- `tests/test_reconstruction/`
- shared reconstruction contract với review

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` + Open3D IO/filter utilities; alignment không nằm trong LiDAR ingest.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Format/unit/frame validator unit tests.
- Empty cloud/unknown unit negative tests.
- Small registered cloud smoke và artifact contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Artifact immutable sau checksum và resolver đọc được.
- [ ] Declared transform chỉ là metadata, không bị coi là confirmed alignment.
- [ ] Downstream REC-09/composer consume qua published ref.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- LiDAR stats/preview.
- Artifact manifest/checksum.
- Invalid unit/frame failure.
