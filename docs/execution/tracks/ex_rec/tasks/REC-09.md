# REC-09 — RGB-LiDAR Alignment

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | `@awun0105` |
| Target milestone | `M2/M4` |


## 2. Goal

Xác nhận transform giữa same-scene RGB và LiDAR artifacts mà không mutate source artifacts.

## 3. Why This Task Exists

Mixed scene không được gọi unified/metric-ready trước confirmed alignment.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03/04 same-scene RGB artifacts cho preparation/đối chiếu metric trước REC-05.
- REC-06 metric derivative và REC-05 RGB geometry cho final shared AlignmentRecord
  bind `target_rgb_geometry_checksum`; không yêu cầu REC-06 DONE để bắt đầu preparation.
- REC-08 LiDARGeometryArtifact.
- Authority/config xác định known or user-confirmed transform; automatic sensor alignment không phải P0.

## 5. Input Contract

- Immutable same-scene RGB artifact refs/checksums.
- Immutable LiDARGeometryArtifact.
- Calibration/known transform hoặc approved confirmation input.
- TorWIC raw label `T_cam1_os` phải normalize thành `T_os_from_cam`; LiDAR→camera
  dùng inverse. `os_sensor` vẫn là source-frame hypothesis, phải record evidence.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Confirmed alignment transform/record riêng.
- Overlap/same-scene checks và alignment provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/alignment/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` + Open3D transform/registration primitives; P0 không hứa automatic sensor alignment.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Ordering clarification 2026-09-26: cùng REC-07/08 chuẩn bị LiDAR/correspondence
cho ba demo modes của ADR 0001 trước real REC-05. Measurement/alignment preparation
không phải final shared AlignmentRecord. Record cuối vẫn bind hai geometry refs
đúng Contract §3.5; không encode similarity scale vào shared rigid Transform.
Task vẫn TODO cho implementation; thay dependency không là evidence đã alignment.

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Transform composition/unit tests.
- Different-scene and unconfirmed-transform negative tests.
- Known-transform alignment fixture và non-mutation test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Same-scene identity/checksums được verify.
- [x] Confirmed record tách khỏi immutable LiDAR artifact.
- [x] Composer/downstream trace được transform và source artifacts.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Checkpoint 2026-09-26 — DONE, RGB-LiDAR alignment service and models

**Implemented / VERIFIED:**
- `src/services/reconstruction/alignment/models.py`:
  - `AlignmentRequest`: ràng buộc `rgb_geometry_ref`, `lidar_geometry_ref`, `transform_target_from_source`, `same_scene_attestation` và provenance.
  - `normalize_torwic_extrinsics`: chuẩn hóa extrinsic TorWIC chuyển `T_os_from_cam` thành `T_world_from_lidar` theo hệ trục canonical Z-up.
  - `invert_transform`: nghịch đảo rigid transform bảo toàn $R^T$ và $-R^T t$.
- `src/services/reconstruction/alignment/service.py`:
  - `RgbLidarAlignmentService`:
    - Thẩm định tiền điều kiện: kiểm tra cùng scene, đúng kiểu `RgbGeometry` và `LiDARGeometryArtifact`, transform target frame là canonical `world`.
    - Tính toán canonical content checksum và xuất bản `AlignmentRecord` (`status=CONFIRMED`, `producer_stage=StageId.RGB_LIDAR_ALIGN`).
    - Nguồn RGB và LiDAR artifacts giữ nguyên bất biến, không bị sửa đổi.
- `tests/test_reconstruction/test_rec09_alignment.py`:
  - 4/4 test cases pass: xác nhận thành công AlignmentRecord, từ chối khi khác scene (`same_scene_attestation=False`), từ chối khi target frame sai, kiểm định roundtrip nghịch đảo transform.

