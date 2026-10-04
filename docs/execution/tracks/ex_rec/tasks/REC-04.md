# REC-04 — Visual Reconstruction With Brush

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
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
4. Bootstrap 2026-09-25: `feat/ex-rec` tại `b1bd026`, worktree sạch; đọc harness,
   task/track và các source anchors. REC-03 có published smoke 65 train frames;
   full 954-frame run chưa thành công. Không dùng held-out/evaluation-only inputs.
5. Owned paths: `adapters/brush*.py`, `adapters/splat*.py`/Node bridge,
   `rgb/visual*.py`, focused tests và manual smoke runner trong `tests/test_reconstruction/`.
   Không sửa shared schema, EX-PRODUCT/SCENE/SIM, runtime drivers hoặc upstream repos.
6. Resolve CameraPoseArtifact và từng frame; materialize model được REC-03 chọn.
   Undistort qua COLMAP khi cần để Brush nhận PINHOLE đúng ảnh; không relabel
   SIMPLE_RADIAL thành PINHOLE. Chỉ đưa registered training frames vào workspace.
7. Reuse Brush CLI, kiểm tra version/help, pin config/runtime; subprocess timeout,
   exit, logs và output validation. Fresh attempt workspace, không implicit resume.
8. Reuse splat-transform 3.6.6 qua process boundary: readFileInfo, streaming stats,
   Gaussian/finite validation, SOG packaging. Giữ master PLY immutable; ghi rõ
   conversion convention của delivery derivative, không claim metric alignment.
9. Publish manifest cuối, verify toàn bộ refs/lineage ở consumer. REC-04 raw
   visual manifest là nội bộ EX-REC với `sfm_world`/arbitrary scale; shared
   `VisualArtifact.coordinate_system` chỉ nhận meter/Z-up/world, nên REC-06 mới
   tạo shared canonical descriptor sau confirmation (Integration §3.3, Contract §4).
10. Proof trước code: command/config/lineage, altered/missing input, process error/
    timeout, malformed/non-Gaussian/nonfinite PLY, derivative checksum, publication
    failure và consumer re-read. Real-tool smoke dùng upstream COLMAP artifact;
    fixture proof không thay GPU/browser/Primary Demo acceptance.

## 10. Tests

- Config/command/provenance unit tests.
- Missing COLMAP artifact negative test.
- Small COLMAP scene to Brush GPU smoke.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Adapter tạo visual artifact bằng reproducible config.
- [x] Output publish qua artifact ref/checksum, không private temp path.
- [x] Downstream có thể resolve visual artifact; collider path không consume nó.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Verified 2026-09-26 — task-level completion

- Implementation: `adapters/brush.py`, `brush_input.py`, `brush_runtime.py`,
  `splat.py`, `splat_bridge.mjs`; internal manifest/resolver tại `rgb/splat/visual.py`
  và `visual_publication.py`. Reuse Brush trainer, COLMAP undistorter,
  FFmpeg image probe và splat-transform parser/stats/filter/SOG codec. Không thêm
  Python dependency, không copy upstream algorithms hoặc sửa shared contracts.
- Native Brush **v0.3.0** archive SHA-256
  `4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20`;
  runtime probe xác nhận `brush-cli 0.3.0`, `--total-steps`. COLMAP bridge dùng
  pinned image `b8498ebecab11c3f9b9a25370e3fcfb6de9b6bcd4f3c85d5dc39a40229f40954`;
  SIMPLE_RADIAL được undistort thật, camera world poses giữ nguyên.
- Published upstream REC-03 smoke: **65/65 registered training frames**, 6,202
  sparse points. REC-02A subset manifest trước ở `/tmp` đã mất; khôi phục exact
  bytes từ records của full producer inventory, chỉ ghi sau khi SHA-256 khớp ref
  gốc `b20bb5c61c37d2079b767afccae3423a2a999e9def2cbb595ecdf8a9f3d0603e`.
  Không đổi refs/checksums, không chọn lại split, không dùng held-out frames.
- Real GPU smoke `10c`: **Intel UHD Graphics 630 (CFL GT2), IntegratedGpu,
  Vulkan, Mesa 25.2.8-0ubuntu0.24.04.2** được xác nhận trong `brush-train.log`.
  10 steps, max resolution 128, SH=0, seed=0, splat budget=10,000,
  refine every=200, SOG iterations=1; elapsed **23.151s** end-to-end.
  Output **6,202 Gaussian**, splat-transform **3.6.6 / afbc281**; master immutable,
  finite stats, SOG roundtrip, source lineage và consumer re-read đều thành công.
- Artifact root (ignored local evidence):
  `data/torwic_slam/derived/aisle_cw/rec04_smoke_artifacts_10c/`.
  `receipt.json` chứa full logical ref; manifest byte SHA-256
  `023a044b139b116a6a3a7f1534635b6a27457474dfb18a0cdd6db35252d34612`.
  Namespace `artifact://jobs/torwic-aisle-cw-rec04-smoke-10c/rec04/` chứa
  `visual.json`, `visual.ply`, `scene.sog`, sanitized logs và `preview.webp`.
- Render sample: upstream splat-transform GPU rasterizer đọc published SOG,
  registered training view 100, 640×480; observed nonempty rendered scene.
  Preview SHA-256 `2411ff5a6e6a41e88ee5f559d55f90498e73bb6ecc8ee5967bf9ca6e2ae0f75a`.
  `preview_receipt.json` bind source visual và camera convention. Sample còn mờ
  vì chỉ 10 steps; không claim visual quality, held-out evaluation hoặc browser QA.
- Validation (exit 0): `.venv/bin/ruff check src/ tests/`,
  `.venv/bin/ruff format --check src/ tests/` (111 files), `node --check` bridge;
  `.venv/bin/pytest tests/test_reconstruction/test_rec04_brush.py -q` **27 passed**;
  `.venv/bin/pytest tests/test_reconstruction tests/test_contracts tests/integration -q`
  **226 passed**. Cả hai pytest commands truyền `REC04_TEST_SPLAT_MODULE` tới
  installed pinned module để 5 real codec cases chạy, không skip.
- Reproduction entrypoints: `python -m tests.test_reconstruction.smoke.rec04_smoke`
  và `python -m tests.test_reconstruction.smoke.rec04_preview`; config qua Settings/
  environment. Provisioned runtime + command script ở ignored `data/rec04_runtime/`.
  NVIDIA unavailable; không thay driver. Attempt `10` thất bại do sandbox Docker
  permission được giữ riêng; `10b` thành công nhưng `10c` thêm explicit GPU log.
- Limits: shared canonical `VisualArtifact` và metric-ready geometry chờ REC-06;
  EX-PRODUCT vẫn cần browser renderer acceptance. SOG là delivery derivative;
  REC-05 chỉ được tạo geometry riêng sau confirmed metric prerequisite.

Checkpoint 2026-09-25 — bootstrap/audit, implementation đang diễn ra:

- Brush checkout `5f6e45cca42e8570cf859bdd939b7d2d21c0d198`, Apache-2.0,
  workspace version 1.0.0; inspected headless CLI, train/process/load config,
  COLMAP loader. Upstream release v0.3.0 ở commit
  `3edecbb2fe79d3e2c87eeab85b15e0b1dd10d486` khác checkout; runtime phải
  qualification riêng, không suy flags/distortion support từ HEAD.
- splat-transform target 3.6.6, MIT, Node >=22; inspected published package
  exports/readFileInfo/readFile/computeStats/writeSource types. Reuse algorithms
  bằng runtime dependency, không vendor trainer, parser hay SOG codec.
- Runtime: NVIDIA driver hiện unavailable; Intel UHD 630 Vulkan/Mesa có mặt.
  Brush release và splat-transform đang provision riêng để thử smoke; chưa
  claim GPU training hoặc visual quality pass.
- Chưa sửa source implementation hoặc shared contracts tại checkpoint này.

Expected evidence:

- Visual screenshots/render sample.
- Brush/runtime/GPU versions và duration.
- Artifact manifest/checksum.

## Cập nhật 02/10/2026 (không đổi Goal/I/O/DoD đã khoá)

Brush giữ lại mỗi ảnh thứ 8 không train (`brush.eval_split_every = 8`) và ghi PSNR/SSIM/LPIPS vào `BrushVisualArtifact.holdout_quality`; `training_frame_ids` chỉ còn ảnh thật sự train, thêm `held_out_frame_ids`. Câu "Chỉ đưa registered training frames vào workspace" vẫn đúng (Brush tự tách trong số ảnh đã đăng ký). Chi tiết: [plan đánh giá](../../../../plans/active/2026-10-02-evaluation-system.md).

## Cập nhật 03/10/2026 — Fatal Log Interception & Hang Watchdog

- Nâng cấp `VisualProcess._invoke` trong `src/services/reconstruction/adapters/brush_runtime.py`:
  - Thêm `FATAL_LOG_PATTERNS` (`wgpu: requested wait timed out`, `CUDA out of memory`, `VK_ERROR_DEVICE_LOST`, `torch.cuda.OutOfMemoryError`) và đọc stream log realtime (chu kỳ 0.5s). Khi phát hiện lỗi driver deadlock hoặc tràn VRAM, gửi `SIGKILL` ngay lập tức giải phóng GPU (dưới 0.2s thay vì bị treo deadlock vô hạn hàng giờ).
  - Thêm `hang_timeout_seconds` (mặc định 180s) cho `brush-train`: nếu tiến trình huấn luyện đứng im không ghi thêm log hoặc tiến độ, tự động hủy và raise `VISUAL_HANG_TIMEOUT`.
  - Nâng cấp `src/services/reconstruction/preview_worker.py`: giữ nguyên `VisualError` code và human message chi tiết trong `ExecutionError` để giao diện Web hiển thị lý do chính xác cho người dùng.
  - Bổ sung unit tests `test_real_process_fatal_log_interception` trong `tests/test_reconstruction/test_rec04_brush.py` (2/2 passed).
