# REC-08 — Registered LiDAR Ingest

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
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

- [x] Artifact immutable sau checksum và resolver đọc được.
- [x] Declared transform chỉ là metadata, không bị coi là confirmed alignment.
- [x] Downstream REC-09/composer consume qua published ref.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Evidence 2026-09-26 — REC-08 Hoàn thành (DONE)

1. **Service & Models:**
   - Files: `src/services/reconstruction/lidar/models.py`, `src/services/reconstruction/lidar/ingest.py`
   - Header inspector siêu tốc: `inspect_point_cloud_header` đọc số lượng điểm trong <1ms từ header ASCII của PLY/PCD.
   - Thẩm định toàn vẹn: Kiểm tra SHA-256 byte checksum, định dạng PLY/PCD, đơn vị bắt buộc `meter` (PRD FR-05/06), giới hạn điểm `[min_points, max_points]`.
   - Xuất bản bất biến: `LiDARIngestService` xuất bản payload sang `artifact://jobs/{job_id}/rec08/lidar.{ext}` và manifest `lidar_geometry.json` mang kiểu chuẩn `LiDARGeometryArtifact` theo hợp đồng shared contract `src/models/contracts/reconstruction.py`.
   - Kết nối tự động với REC-07: Hàm `build_request_from_rec07_manifest` đọc trực tiếp `preparation_manifest.json` và ánh xạ đầy đủ `PreprocessingProvenance` (`ground_truth_assisted`, `dependencies`).

2. **Test Suite:**
   - File: `tests/test_reconstruction/test_rec08_lidar_ingest.py`
   - Command: `pytest tests/test_reconstruction/test_rec08_lidar_ingest.py -v`
   - Kết quả: **4 passed in 0.19s** (100% pass).
   - Kiểm thử: Header inspector (PLY/PCD/bad header), request validation (checksum mismatch, file missing, non-meter unit, out-of-budget points), service publication e2e, và integration đọc trực tiếp output thật của REC-07 (`data/torwic_slam/derived/aisle_cw/rec07_smoke_sub100_104/`).
