# REC-07 — TorWIC LiDAR Prefusion

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `VALIDATING` |
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

Audit reproduction 2026-09-27: chạy lại `run_prefusion` với exact request từ
smoke manifest, Open3D 0.19.0 isolated runtime, output mới
`derived/aisle_cw/rec07_audit_20260927`. VERIFIED **54.957 points**, PLY checksum
khớp exact original `sha256:9e6893eee58da41142fe82e3279a862bb6e8a5badf6a3e8688efda2500a1df2b`.
Native coordinate vẫn UNVERIFIED/GT-assisted, không phải RGB alignment proof.
Remaining audit: strict raw scan integrity trước native allocation và canonical
coordinate evidence bridge; không đổi status DONE chỉ từ successful replay.

### Task Capsule / bootstrap 2026-09-26

- Outcome: reproducible offline scan→registered PLY, bằng Open3D primitives,
  không claim đã canonical/confirmed RGB alignment.
- Authority: PRD FR-05/06; Dataset Playbook §13.4, §15 (controlled prefusion);
  Contract §3.5; Track Guide REC-07; Architecture `scripts/torwic/` ownership.
- Baseline: branch `feat/ex-rec`, HEAD `c98df2a`, clean; entrypoint hiện chỉ là
  placeholder. REC-01 source/normalized metadata tồn tại. Raw trajectory là TUM
  timestamp + xyz + xyzw; source-frame hypothesis `os_sensor`, axes UNVERIFIED.
- Inputs: explicit checksum-bound scans/poses/timestamps/calibration và config;
  output: new attempt directory có PLY, manifest, point stats, source/runtime/code
  checksums. Giữ raw input bất biến và không xuất absolute private paths.
- Owned: `scripts/torwic/`, EX-REC tests, task/active plan. Không sửa raw/GT,
  shared schemas, app dependency locks, other tracks hoặc source-frame evidence.
- Reuse audit: Open3D **0.19.0**, MIT, `isl-org/Open3D` v0.19.0;
  [license](https://raw.githubusercontent.com/isl-org/Open3D/v0.19.0/LICENSE),
  [read_point_cloud](https://www.open3d.org/docs/0.19.0/python_api/open3d.io.read_point_cloud.html),
  [PointCloud](https://www.open3d.org/docs/0.19.0/python_api/open3d.geometry.PointCloud.html).
  REUSE PCD/PLY IO, transform and voxel downsample; NumPy arrays/sort. SELF-CODE
  orchestration, timestamp/identity checks, manifest/immutable publication. Không
  copy research modules, tự viết odometry hoặc đưa toàn dependency vào app env.
- Runtime riêng `data/rec07_runtime`; app `.venv` không có Open3D/NumPy. Disk
  còn khoảng 7.8 GiB ở bootstrap: bắt đầu small smoke, bound point budget,
  không chạy full sequence trước khi biết memory/output size.
- Sequence: typed request/path/pose validation → Open3D bounded workflow → CLI
  và immutable manifest → tests synthetic + real small-sequence reproducibility.
- Proof: missing/stale source, path escape, undeclared GT, timestamp/frame
  mismatch, bad quaternion/nonfinite/empty cloud đều reject; known transform
  đúng chiều, sorted output deterministic, rerun cùng input hash bằng nhau;
  existing attempt không overwrite. Real GT-assisted output ghi nhãn đúng.
- Unknown: full canonical axes và RGB correspondence chưa confirmed; không chặn
  offline prefusion trong explicitly declared native frame, nhưng không được
  nâng output đó thành unified metric scene.

## 10. Tests

- Transform/merge/filter unit tests.
- Missing pose/frame metadata negative test.
- Small scan sequence prefusion smoke và reproducibility check.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Output tái tạo được từ immutable raw input.
- [x] Mọi use của `traj_gt` được khai báo rõ.
- [x] Artifact không được claim là independent LiDAR mapping benchmark khi methodology không cho phép.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Evidence 2026-09-26 — REC-07 Hoàn thành (DONE)

1. **Unit & Contract Tests:**
   - File test: `tests/test_reconstruction/test_rec07_prefusion.py`
   - Command: `pytest tests/test_reconstruction/test_rec07_prefusion.py -v`
   - Kết quả: **9 passed in 18.04s** (100% pass).
   - Kiểm thử: path traversal rejection, frame ID mismatch rejection, GT declaration requirements, output directory boundary (`derived/`), checksum tamper detection, unnormalized quaternion rejection, desynchronized timestamp detection, CLI invocation, và tính đơn định (deterministic SHA-256 byte-for-byte reproducibility).

2. **Real-Tool Smoke Execution trên Aisle_CW:**
   - Script: `tests/test_reconstruction/rec07_smoke.py`
   - Command: `data/rec07_runtime/bin/python -m tests.test_reconstruction.rec07_smoke`
   - Input: Scans 100 đến 104 (`raw/traversals/aisle_cw/lidar/00010[0-4].pcd`, 262.144 points/scan từ cảm biến Ouster OS1-128).
   - Output directory: `data/torwic_slam/derived/aisle_cw/rec07_smoke_sub100_104/`
   - Output files:
     - `registered_lidar.ply` (1.3 MB, checksum: `sha256:9e6893eee58da41142fe82e3279a862bb6e8a5badf6a3e8688efda2500a1df2b`)
     - `preparation_manifest.json` (checksum: `sha256:f002903e21078da945da81f3ac88241b293dfae8287c7751896292ee3a5fcfd5`)
   - Thống kê mây điểm:
     - Tổng điểm hợp nhất (sau voxel filter $0.05\text{m}$): **54.957 điểm**.
     - Bounds min: `[-11.1444, -17.7897, -0.5411]` mét.
     - Bounds max: `[14.2995, 32.1617, 6.1304]` mét.
     - Minh bạch provenance: `assistance_class: "GT-assisted"`, `trajectory_gt_used_for_lidar_prefusion: true`.
