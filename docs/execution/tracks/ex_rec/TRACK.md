# EX-REC — Dataset & Reconstruction

## Mission

Biến moving-camera RGB và Registered LiDAR thành reconstruction artifacts chuẩn
để EX-SCENE consume trực tiếp.

```text
RGB → poses → visual → REC-06 confirmed metric transform
    → metric working derivative → REC-05 voxel/collision
    → REC-06 final cross-artifact verification → ReconstructionBundle
Registered LiDAR → LiDARGeometryArtifact → conditional alignment/composition
```

## Ownership

Track Owner: `@awun0105`.

- `src/services/reconstruction/`
- `scripts/torwic/` cho offline dataset preparation
- `tests/test_reconstruction/`
- reconstruction contract tests/fixtures với producer + consumer review

Không sở hữu object/SceneIR logic, simulation, Web/review/release hoặc evaluation
ground-truth comparison.

## Inputs And Outputs

Inputs:

- `InputManifest` và `PrivacyValidationReport`;
- moving-camera RGB hoặc normalized frames;
- registered/fused LiDAR;
- TorWIC raw LiDAR chỉ trong offline `DP-LIDAR-PREFUSION`.

Outputs:

- `ReconstructionBundle`;
- `LiDARGeometryArtifact`;
- confirmed alignment/metric provenance khi mixed;
- runtime, checksum và representative failure evidence.

## Technology And Strategy

- FFmpeg, COLMAP, Brush, splat-transform, Open3D, NumPy; OpenMVS là fallback P0.
- `playcanvas/splat-transform`: REC-04 validation/SOG packaging và REC-05 voxel geometry/collision theo [Audit #4a](../../audits/04a_splat_transform.md), có confirmed metric transform trước voxelization.
- `InternRobotics/Re3Sim`: Tier-0 System Architecture Reference & Code Donor cho PyCOLMAP orchestration (`REC-03`), OpenMVS command pipeline (`REC-05`) và FrameTools / similarity transform (`REC-06`) theo [Audit #7](../../audits/07_re3sim.md).
- Reuse core reconstruction tools qua adapter/process boundary.
- Team sở hữu validation, normalization, artifact publication, metric/alignment và provenance.
- Không tự viết lại SfM, 3DGS trainer, dense MVS hoặc generic point-cloud primitives.

## Authority Gates

- Canonical convention đã khóa: meter, Z-up, right-handed, world frame `world`, transform `parent_from_local`, quaternion `xyzw`, angle `radian`.
- `ReconstructionBundle` mixed-modality shape và optionality phải theo normative Contract; task không được suy ra từ fixture.
- `REC-02` chỉ input validation/privacy; `REC-02A` sở hữu `ST-FRAME-EXTRACT`.
- `traj_gt` chỉ được dùng trong declared offline prefusion và phải ghi dependency; không dùng để claim independent prediction.
- `Aisle_CW` là P0 traversal; `Aisle_CCW` bổ sung/backup. REC-01B sensor checks không chọn Primary Demo frame range.
- Calibration raw label `T_cam1_os` phải normalize thành `T_os_from_cam`; chiều đưa LiDAR sang camera là `T_cam_from_os = inverse(T_os_from_cam)`. `os_sensor` là source-frame hypothesis chưa backend-confirmed.

## Task Index

| Task | Name | Depends on | Primary output |
|---|---|---|---|
| [REC-01](./tasks/REC-01.md) | TorWIC preparation | — | normalized dataset + split metadata |
| [REC-02](./tasks/REC-02.md) | RGB validation and privacy | REC-01 for bring-up | validation/privacy evidence |
| [REC-02A](./tasks/REC-02A.md) | Frame extraction | REC-02 | normalized frame artifact |
| [REC-03](./tasks/REC-03.md) | Camera pose / COLMAP | REC-02A | normalized camera poses |
| [REC-04](./tasks/REC-04.md) | Visual reconstruction | REC-03 | visual artifact |
| [REC-05](./tasks/REC-05.md) | Voxel geometry / OpenMVS fallback | REC-04 + REC-06 anchor confirmation; REC-03 cho fallback | geometry artifact |
| [REC-06](./tasks/REC-06.md) | RGB metric scale | REC-03/04 cho anchor confirmation; REC-05 cho final verification | confirmed metric reconstruction |
| [REC-07](./tasks/REC-07.md) | TorWIC LiDAR prefusion | REC-01 | `registered_lidar.ply` + provenance |
| [REC-08](./tasks/REC-08.md) | Registered LiDAR ingest | registered LiDAR | `LiDARGeometryArtifact` |
| [REC-09](./tasks/REC-09.md) | RGB–LiDAR alignment | REC-03/04 + REC-08 cho preparation; REC-06/05 cho final record | confirmed alignment record |
| [REC-10](./tasks/REC-10.md) | Publish ReconstructionBundle | REC-02A/03/04/05/06; REC-08/09 conditional | `ReconstructionBundle` |
| [REC-11](./tasks/REC-11.md) | Worker entrypoint | REC-10 | stable worker/CLI |

## Track Definition Of Done

ADR 0001 phân biệt ba system paths (RGB + measured anchor, RGB + LiDAR,
RGB + future estimator) với adapter demo dùng LiDAR hỗ trợ hai RGB modes.
REC-07/08 và preparation REC-09 được làm trước real REC-05 để chuẩn bị nguồn
metric cho demo; final AlignmentRecord vẫn bind RGB geometry sau REC-05.
Demo-assisted proof không thay real RGB-only hoặc estimator acceptance.

REC-06 có pha xác nhận anchor/transform trước REC-05 metric-aware generation và
pha kiểm tra toàn bộ artifacts sau REC-05; REC-05 không phụ thuộc trạng thái DONE
của REC-06. Adapter/unit tests/synthetic GPU qualification của REC-05 vẫn làm
độc lập bằng fixture có kích thước biết trước. Chỉ real Aisle_CW metric-aware
spike chờ confirmation record, locked robot capsule và valid walkable seed;
không đánh dấu cả REC-05 BLOCKED chỉ vì prerequisite này chưa có. Đây là ordering
nội bộ EX-REC theo Integration §3.3, không thêm task/stage ID.

- Real RGB path tạo visual, geometry và metric artifacts.
- LiDAR ingest và mixed contribution evidence tồn tại.
- Bundle validate, checksum/provenance đầy đủ và refs resolve.
- EX-SCENE đọc real bundle trực tiếp, không manual conversion.
- Local/contract tests pass và required GPU/heavy smoke có evidence riêng.

## Required Sources

- [`PRD.md`](../../../PRD.md)
- [`DATASET_PLAYBOOK.md`](../../../DATASET_PLAYBOOK.md)
- [`TEAM_EXECUTION_CONTRACT.md`](../../TEAM_EXECUTION_CONTRACT.md)
- [`INTEGRATION_PLAYBOOK.md`](../../INTEGRATION_PLAYBOOK.md)
- [`TRACK_IMPLEMENTATION_GUIDE.md`](../../TRACK_IMPLEMENTATION_GUIDE.md)
- [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md)
- [`ARCHITECTURE.md`](../../../../ARCHITECTURE.md)
