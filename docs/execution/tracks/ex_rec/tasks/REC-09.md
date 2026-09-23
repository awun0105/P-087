# REC-09 — RGB-LiDAR Alignment

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M2/M4` |

## 2. Goal

Xác nhận transform giữa same-scene RGB và LiDAR artifacts mà không mutate source artifacts.

## 3. Why This Task Exists

Mixed scene không được gọi unified/metric-ready trước confirmed alignment.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-06 same-scene RGB artifacts.
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

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Transform composition/unit tests.
- Different-scene and unconfirmed-transform negative tests.
- Known-transform alignment fixture và non-mutation test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Same-scene identity/checksums được verify.
- [ ] Confirmed record tách khỏi immutable LiDAR artifact.
- [ ] Composer/downstream trace được transform và source artifacts.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Alignment transform/checksum.
- Overlay or distance sanity evidence.
- Different-scene rejection.
