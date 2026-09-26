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

Audit 2026-09-27: tách strict streaming payload inspector (PLY scalar vertices,
PCD ASCII/binary) khỏi typed request; kiểm toàn bộ records, đúng field order,
finite bounds và exact payload count/size, budget trước decode. Compressed/list
encoding chưa qualify phải reject rõ, không trả bounds giả. Open3D v0.19.0 native
reader preallocates trước decode và Python wrapper không expose bool success,
nên không coi nonempty native cloud là structural integrity proof. Dùng Open3D
roundtrip làm independent runtime proof. REC-07 manifest phải verify canonical
checksum, giữ native frame/GT provenance; UNVERIFIED không tự thành canonical.
Publication content-addressed, bind metadata qua ref, không đổi shared schema.

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

### Audit correction 2026-09-27 — không kế thừa historical DONE

- VERIFIED: 6 red regressions tái hiện binary fake bounds/truncation và ASCII
  ngoài 1.000 points/EOF; sửa thành full streaming validation. Hỗ trợ scalar
  vertex-only PLY ASCII/little-/big-endian; PCD ASCII/binary đúng declared fields,
  sizes, counts. Compressed PCD/list-element PLY reject rõ, chưa qualify.
- Ingest yêu cầu explicit coordinate/source-frame declarations, check format
  khớp bytes, finite transform/frame binding và rehash bytes trước publish.
  Content-addressed publication giữ metadata riêng, `ingest_with_metadata`
  trả đủ refs. Create-only store tiếp tục reject duplicate, không overwrite.
- REC-07 preparation reader verify canonical manifest checksum/output hash/count,
  giữ `role=pose` và đúng estimated/external/GT origin, toàn inventory dependencies,
  output target frame. Legacy auto-ingest reject UNVERIFIED thay vì đổi nhãn world.
- REAL RUNTIME: Open3D **0.19.0** trong `data/rec07_runtime` đọc REC-07 smoke:
  **54.957 points**, min/max bounds khớp chính xác strict inspector. SHA-256 PLY
  `9e6893eee58da41142fe82e3279a862bb6e8a5badf6a3e8688efda2500a1df2b`.
  Đây là GT-assisted native output, chưa canonical/world acceptance.
- LIMIT: coordinate evidence/conversion bridge cho real prefusion vẫn cần làm;
  không dựng CONFIRMED producer giả. Point-cloud cleaning tiếp tục reuse Open3D
  REC-07; REC-08 hiện validate/publish, không tự crop/filter không có config.
- Validation: `pytest tests/test_reconstruction/ -q` **314 passed, 11 skipped**
  (57.92s); `ruff check src/ tests/ scripts/torwic` và `ruff format --check`
  **181 files pass**; AST <=30 lines/<=3 parameters cho lidar source pass;
  `git diff --check` pass. No full-product/Isaac acceptance claim.

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
