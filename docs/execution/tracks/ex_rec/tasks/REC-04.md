# REC-04 — Visual Reconstruction With Brush

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Tạo 3DGS visual artifact từ COLMAP output qua Brush adapter.

## 3. Why This Task Exists

Cung cấp Visual Representation cho Primary RGB Product Path và Web preview.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03 camera poses và COLMAP model.
- Locked Brush/runtime environment cho heavy smoke.

## 5. Input Contract

- REC-03 COLMAP model/camera poses.
- Versioned training/config parameters.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Checksummed visual artifact ref.
- Training/runtime/config provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/adapters/`
- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`REUSE` Brush CLI/API qua process boundary; không copy trainer hoặc dùng visual artifact làm collider.

**Core Utility Candidate (Audit #4a):**
- Utility đóng gói & kiểm thử: [`playcanvas/splat-transform`](https://github.com/playcanvas/splat-transform) (xem chi tiết tại [`docs/execution/audits/04a_splat_transform.md`](../../../audits/04a_splat_transform.md)).
- Core features đáng sử dụng (**`REUSE-HIGH`**):
  - Hỗ trợ trực tiếp metadata của Brush (`SplatRenderMode: default/mip/2dgs`).
  - `readFileInfo()`: Kiểm tra cấu trúc ngữ nghĩa (Gaussian validity, splat count, LOD counts, SH bands) trước khi công bố artifact.
  - Streaming statistics: min, max, NaN/Inf check và chỉ số `fillRatio` (phát hiện overdraw pathological scenes).
  - Tối ưu hóa phân phối Web: Morton spatial sorting, nén SOG / Streamed SOG LOD cho `@playcanvas/supersplat-viewer`.
  - Optional cleanup: `--filter-nan`, GPU-based `filterFloaters()` loại bỏ hạt trôi nổi/nhiễu.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Coordinate Convention**: `splat-transform` sử dụng quy ước chuyển đổi riêng (`Transform.PLY` xoay 180° quanh trục Z). Bắt buộc chuyển đổi tại adapter boundary, không để convention này làm thay đổi canonical `CoordinateSystem` của Real2Sim Studio.
  - ❌ **Master PLY là Canonical Artifact**: Master `visual.ply` sinh ra từ Brush là bất biến (immutable); file `scene.sog` là delivery derivative phục vụ Web preview trong PlayCanvas Viewport.
  - ❌ **Ranh giới Collider**: Voxel collision mesh từ 3DGS do `REC-05` và `EX-SIM` phụ trách; `REC-04` chỉ tập trung vào Visual representation (`master.ply` và `scene.sog`).

## 9. Implementation Plan

1. Xây dựng Brush adapter kích hoạt huấn luyện 3DGS qua CLI/process boundary.
2. Tích hợp `SplatArtifactProcessor` (dựa trên `splat-transform`) chạy validate `readFileInfo()`, tính stats và xuất `scene.sog` delivery derivative cho `@playcanvas/supersplat-viewer`.
3. Xuất bản `VisualArtifact` kèm checksum và provenance liên kết với COLMAP camera poses.
4. Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Config/command/provenance unit tests.
- Missing COLMAP artifact negative test.
- Small COLMAP scene to Brush GPU smoke.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Adapter tạo visual artifact bằng reproducible config.
- [ ] Output publish qua artifact ref/checksum, không private temp path.
- [ ] Downstream có thể resolve visual artifact; collider path không consume nó.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Visual screenshots/render sample.
- Brush/runtime/GPU versions và duration.
- Artifact manifest/checksum.

