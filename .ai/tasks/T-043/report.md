# T-043 — Báo cáo triển khai

## Kết quả

Đã làm đủ 7 bước của `plan.md` trên branch `mvp-pipeline-v2`, từ `9eab46e0` đến `5d974325`. Không push, merge, tạo branch hay thêm Co-Authored-By. Không sửa `scripts/gpu/studio.env` của laptop.

- **Canh tiến độ dùng chung:** `ProgressWatchdog` và `ProcessStalledError` (`PROCESS_STALLED`) trong `src/services/process_control.py`. Brush, COLMAP, voxel, MoGe, LiDAR odometry và ObjectGS đều dừng khi log/kết quả không đổi quá ngưỡng, thay vì chờ hết giờ cố định.
- **Hạn tự tính theo số đo:** `expected_seconds()` trong `src/services/orchestration/processing/expected_duration.py`. Hạn = `max(10 phút, 3 × ước)`, không vượt giới hạn cố định. Thiếu số đo thì giữ giới hạn cũ. Lỗi khi hết hạn có mã `EXPECTED_DURATION_EXCEEDED`.
- **Trần giờ GPU mỗi scene:** `PRODUCT_JOB_GPU_HOURS_MAX`, mặc định tắt. Vượt trước khi chạy hoặc trong khi chạy thì dừng với mã `GPU_BUDGET_EXCEEDED`, không retry.
- **Lưới cứng:** COLMAP 14400 s, Brush 21600 s trong code, image entrypoint và `scripts/gpu/studio.env.example`.
- **Thông báo tiếng Việt:** `frontend/src/features/studio/errorGuidance.ts` có hướng dẫn cho `PROCESS_STALLED`, `GPU_BUDGET_EXCEEDED`, `EXPECTED_DURATION_EXCEEDED`.

## Quyết định triển khai

1. **Ngưỡng treo COLMAP = 600 s**, không phải 15 phút như plan đề xuất. Bằng chứng: đo 10 log `process.log` COLMAP thật trong `data/studio_local/artifacts` (log preview rec04 và log COLMAP trực tiếp). Tổng 7 688 khoảng im lặng giữa các dòng log, p50 0,000 s, p99 1,89 s, lớn nhất 16,5 s (pha *Retriangulation and Global bundle adjustment*, hai job dài nhất: 3 603 và 3 097 dòng log). 600 s cách số đo lớn nhất gần 36 lần. Vẫn cấu hình được qua `R2S_COLMAP_STALL_SECONDS`.
2. **Brush giữ ngưỡng 180 s** như trước, chỉ chuyển sang lớp chung. Hành vi không đổi.
3. **Voxel 120 s, MoGe 300 s (có dòng tiến độ mỗi ảnh), LiDAR odometry 300 s (có dòng tiến độ mỗi scan), ObjectGS 1800 s** (`PRODUCT_OBJECTGS_STALL_SECONDS`). Mỗi ngưỡng đặt qua biến `R2S_<CÔNG CỤ>_STALL_SECONDS` theo quy ước T-036.
4. **Ước lượng chỉ dùng lượt `completed` cùng công cụ và cùng GPU.** Ưu tiên lượt cùng runtime khi có ≥ 3 mẫu; không thì dùng toàn bộ mẫu cùng GPU. Dưới 3 mẫu thì không ước. Khối lượng lấy từ tham số preset (`brush.total_train_iters`, `scene.objectgs_iterations`, `sampling.max_frames`).
5. **Phần kiểm trần GPU dùng `getattr`** trong `runner.py` (`_gpu_budget_at_start`), cùng mẫu với `api/studio/deps.py`. Lý do: 7 test tích hợp dựng settings giả thiếu trường mới; lỗi này được bắt ở lượt full backend đầu tiên (commit `5d974325`).
6. **`deploy/studio/*.env.example` không đổi:** các file này không chứa khóa COLMAP/Brush/GPU budget nên không có gì để cập nhật. Chỉ `deploy/studio/OVERVIEW.md` được thêm mục giới hạn thời gian.

## File đã thay đổi

- Canh tiến độ: `src/services/process_control.py`, `src/services/reconstruction/adapters/brush_runtime.py`, `colmap_runtime.py`, `voxel_runtime.py`, `moge_runner.py`, `metric_proposal.py`, `lidar/odometry.py`, `scripts/gpu/lidar_odometry_runner.py`, `src/services/scene/objectgs.py`, `src/services/orchestration/scene/objectify.py`, `src/config.py`.
- Hạn và trần GPU: `src/services/orchestration/processing/expected_duration.py`, `gpu_budget.py`, `src/services/orchestration/jobs/runner.py`, `src/models/contracts/retryability.py`.
- Giới hạn cứng và tài liệu: `scripts/gpu/docker_entrypoint.sh`, `scripts/gpu/studio.env.example`, `scripts/gpu/README.md`, `deploy/studio/OVERVIEW.md`, `docs/RUNPOD_GUIDE.md`.
- Giao diện: `frontend/src/features/studio/errorGuidance.ts`.
- Test mới: `tests/test_process_stall.py`, `tests/test_reconstruction/test_colmap_stall.py`, `test_voxel_stall.py`, `test_moge_stall.py`, `test_lidar_odometry_stall.py`, `tests/test_scene/test_objectgs_stall.py`, `tests/test_reconstruction/test_tool_time_limits.py`, `tests/test_orchestration/test_expected_duration.py`, `test_runner_expected_deadline.py`, `test_gpu_budget.py`, `frontend/tests/error-guidance-time-limits.test.ts`.
- Test cũ đã sửa: `tests/test_reconstruction/test_rec03_colmap.py` (theo hành vi `Popen` mới).
- Handoff: `.ai/status.md`, `.ai/tasks/T-043/report.md`.

## Kiểm thử

Ruff trên toàn bộ file Python đã sửa:

```bash
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

**All checks passed; 22 files already formatted.**

Frontend:

```bash
cd frontend
./node_modules/.bin/vitest run tests/error-guidance-time-limits.test.ts
npm run typecheck
```

**5 / 5 tests passed; typecheck exit 0.**

Full backend một lần (task chạm mọi runner), không có GPU thật:

```bash
.venv/bin/python -m pytest tests -q -p no:cacheprovider
```

**3935 passed, 28 skipped, 15 warnings in 597.25s (0:09:57), exit 0.** Lượt này chạy sau commit `5d974325`, sửa lỗi 7 test tích hợp thiếu trường settings.

## Ghi chú

- Chưa chạy trên GPU thật: ngưỡng treo và ước lượng đã kiểm bằng log thật và tiến trình giả trong test; kiểm thử thật cần một lượt chạy scene thật trên máy GPU.
- Khuyến nghị cho chủ dự án: nếu muốn dừng sớm hơn trên máy thuê, đặt `PRODUCT_JOB_GPU_HOURS_MAX` theo ngân sách mỗi scene. Mặc định tắt nên không ảnh hưởng hành vi hiện tại.
- `graphify update .` đã chạy trước bước sửa `getattr`; cần chạy lại sau khi có thay đổi cuối.
