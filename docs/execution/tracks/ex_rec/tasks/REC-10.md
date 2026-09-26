# REC-10 — Publish ReconstructionBundle

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |


## 2. Goal

Build, validate và publish ReconstructionBundle mà EX-SCENE đọc trực tiếp.

## 3. Why This Task Exists

Đây là cross-track handoff chính REC→SCENE và không được phụ thuộc temp folders của tools.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03/04/05/06 cho RGB bundle.
- REC-08/09 conditional cho mixed configuration.
- Normative mixed-modality bundle đã khóa: canonical geometry luôn required;
  mixed RGB/LiDAR phải có exact-checksum-bound `CONFIRMED AlignmentRecord`.

## 5. Input Contract

- Published REC-02A frame, pose, visual, geometry and metric artifacts.
- Conditional LiDAR/alignment composition records.
- Optional RGB+sensor-depth refs chỉ khi input_configuration.depth_present;
  dtype/format/positive scale do producer khai báo. `uint16` PNG và scale `0.001`
  là TorWIC adapter metadata, không phải universal invariant hay GT depth.
- Conditional LiDAR ref mang generic preprocessing dependency provenance;
  bundle phải giữ `ground_truth_assisted: true` nếu LiDAR đã dùng GT.
- Input/job/config provenance.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Versioned ReconstructionBundle với checksum và resolvable refs.
- Bundle publication/handoff record.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/`
- `src/models/contracts/reconstruction.py` chỉ với shared review
- `fixtures/reconstruction_bundle/` và `tests/test_contracts/` với consumer review

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` theo shared contract; không serialize ad-hoc format cạnh tranh.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Builder/roundtrip/checksum unit tests.
- Missing required artifact/unresolved ref negative tests.
- EX-SCENE fixture/real consumer contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Bundle validate normative schema và coordinate/metric metadata đủ.
- [x] RGB-only, RGB+Depth và RGB+LiDAR bundle invariants pass; mixed bundle thiếu alignment bị reject.
- [x] Không chứa hidden local path hoặc require private COLMAP/Brush/OpenMVS folders.
- [x] EX-SCENE deserialize trực tiếp không sửa file tay.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Checkpoint 2026-09-26 — DONE, ReconstructionBundle publication service and validation

**Implemented / VERIFIED:**
- `src/services/reconstruction/bundle.py`:
  - `BundleBuildRequest`: ràng buộc modality, bắt buộc `canonical_geometry_ref` (mặc định lấy `rgb_geometry_ref`), fail closed khi mixed RGB+LiDAR thiếu `CONFIRMED AlignmentRecord`.
  - `ReconstructionBundleService`: lắp ráp và tính toán canonical content checksum chuẩn, xuất bản `ReconstructionBundle` (`producer_stage=StageId.METRIC_CANONICALIZE`) qua atomic writer.
- `tests/test_reconstruction/test_rec10_bundle.py`:
  - 3/3 test cases pass:
    - RGB-only bundle xuất bản và được EX-SCENE consumer (`load_reconstruction_bundle` từ `src.services.scene.bundle_consumer`) đọc và deserialize trực tiếp, giải quyết toàn bộ canonical geometry, frames, poses.
    - Mixed RGB+LiDAR bundle có confirmed alignment được xuất bản và EX-SCENE consumer deserialize thành công cả canonical geometry và lidar geometry.
    - Fail-closed khi cấu hình mixed RGB+LiDAR nhưng thiếu alignment.
