# REC-08 — Registered LiDAR Ingest

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
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

### Evidence 2026-09-26 — REC-08 Refactor Hoàn thành (DONE)

1. **Service & Models:**
   - Files: `src/services/reconstruction/lidar/models.py`, `src/services/reconstruction/lidar/ingest.py`
   - Header & Geometry Inspection: `inspect_point_cloud_header` đọc số lượng điểm trong <1ms từ header ASCII của PLY/PCD; `inspect_point_cloud` thẩm định tính hữu hạn của tọa độ (chặn NaN/Inf) và tính toán bounding box không gian 3D.
   - Thẩm định toàn vẹn: Kiểm tra SHA-256 byte checksum (không strip gây lệch sha256), định dạng PLY/PCD, đơn vị bắt buộc `meter` (PRD FR-05/06), giới hạn điểm `[min_points, max_points]`.
   - Xuất bản bất biến qua FilesystemArtifactStore thật: `LiDARIngestService` xuất bản payload sang `artifact://jobs/{job_id}/rec08/lidar.{ext}` và manifest `lidar_geometry.json` mang kiểu chuẩn `LiDARGeometryArtifact` theo hợp đồng shared contract `src/models/contracts/reconstruction.py`. `geometry_ref` trỏ trực tiếp tới PLY payload với `source_provenance` chứa `PreprocessingProvenance` (`ground_truth_assisted`, `dependencies`).
   - Kết nối tự động với REC-07: Hàm `build_request_from_rec07_manifest` đọc trực tiếp `preparation_manifest.json` và ánh xạ đầy đủ `PreprocessingProvenance` (`ground_truth_assisted`, `dependencies`).
   - Tương thích 100% với EX-SCENE: Đã kiểm chứng trực tiếp với `load_reconstruction_bundle` của EX-SCENE qua `tests/test_reconstruction/test_rec10_bundle.py`.

2. **Test Suite:**
   - Files: `tests/test_reconstruction/test_rec08_lidar_ingest.py`, `tests/test_reconstruction/test_rec10_bundle.py`
   - Commands:
     - `pytest tests/test_reconstruction/test_rec08_lidar_ingest.py -v` (4 passed in 0.14s)
     - `pytest tests/test_reconstruction/test_rec10_bundle.py -v` (3 passed in 1.05s)
   - Kiểm thử: Header & cloud inspection (PLY/PCD/NaN/Inf), request validation (checksum mismatch, file missing, non-meter unit, out-of-budget points), service publication e2e qua `FilesystemArtifactStore` thật và `ArtifactResolver`, và integration đọc trực tiếp output thật của REC-07 (`data/torwic_slam/derived/aisle_cw/rec07_smoke_sub100_104/`). Phối hợp trực tiếp vào ReconstructionBundle cho consumer EX-SCENE.
