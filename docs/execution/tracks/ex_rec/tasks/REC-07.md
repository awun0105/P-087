# REC-07 — TorWIC LiDAR Prefusion

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Offline transform/merge/filter/downsample TorWIC raw LiDAR thành registered_lidar.ply có dependency provenance.

## 3. Why This Task Exists

Product MVP không nhận raw LiDAR scan sequence; prefusion là controlled dataset preparation.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-01 raw traversal/calibration metadata.
- Declared pose source; `traj_gt` use phải theo Dataset Playbook.

## 5. Input Contract

- `lidar/*.pcd`, calibration và declared poses.
- Optional `traj_gt.txt` chỉ trong declared offline preprocessing.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- `registered_lidar.ply`.
- Preparation manifest nêu pose/GT dependencies, transforms, filters và checksums.
- Nếu dùng `traj_gt`, field bắt buộc là
  `trajectory_gt_used_for_lidar_prefusion: true` và `assistance_class: GT-assisted`; output không được claim độc lập
  với trajectory GT.
- Hai field trên chỉ thuộc TorWIC preparation manifest. Khi REC-08 publish shared
  artifact, map thành dependency generic `role: pose`, `origin: ground_truth`,
  `source_checksum` và `ground_truth_assisted: true`.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `scripts/torwic/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` workflow dùng Open3D primitives; không đưa raw prefusion vào product runtime.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Transform/merge/filter unit tests.
- Missing pose/frame metadata negative test.
- Small scan sequence prefusion smoke và reproducibility check.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Output tái tạo được từ immutable raw input.
- [ ] Mọi use của `traj_gt` được khai báo rõ.
- [ ] Artifact không được claim là independent LiDAR mapping benchmark khi methodology không cho phép.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Input/output checksums.
- Prefusion manifest và command/log.
- Point-cloud stats/preview.
