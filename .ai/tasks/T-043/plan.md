# T-043: Dừng công cụ theo tiến độ và theo khối lượng scene, không theo một con số cố định

## Goal
Công cụ đang chạy bình thường (dù chậm) không bị cắt oan; công cụ treo thật bị dừng sớm; mỗi scene có trần chi phí GPU khi chạy
máy thuê. Giới hạn thời gian cố định chỉ còn là lưới an toàn cuối cùng.

## Context (đã kiểm trong code)
- Giới hạn thời gian hiện là con số cố định theo từng công cụ:
  - `ColmapRuntimeSettings.timeout_seconds` (mặc định 1800, `colmap_runtime.py:25`), chạy bằng `subprocess.run(timeout=...)`
    (dòng 84–92): **không theo dõi tiến độ**, chỉ chờ hết giờ.
  - `BrushRuntimeSettings.timeout_seconds` (1800) và **đã có phát hiện treo**: `hang_timeout_seconds` (180) — quá 180 s không có
    dòng log tiến triển của `brush-train` thì dừng (`brush_runtime.py:113–158`). Đây là mẫu cần nhân rộng.
  - `VoxelRuntimeSettings.timeout_seconds` (300), `MogeSettings.timeout_seconds` (1800), `LidarOdometryRuntimeSettings`
    (3600), `ObjectGSRuntime.timeout_seconds` (14400, đặt qua `product_objectgs_timeout_seconds`).
  - Ở tầng job: `product_prepare_timeout_seconds` (3600), `product_preview_timeout_seconds` (21600),
    `product_finalize_timeout_seconds` (7200), `product_scene_timeout_seconds` (1800) — dùng trong `runner._run_tool`
    (`runner.py:205–260`, vòng lặp đã kiểm hủy, mất lease, hết giờ mỗi giây).
  - Laptop đang đặt COLMAP/Brush 3600 s trong `scripts/gpu/studio.env`; image đặt 7200/14400 trong `docker_entrypoint.sh`.
- Số đo thời gian thật đã có: mỗi lượt công cụ ghi `ResourceUsage` (`processing/telemetry.py`): `tool`, `params`, `gpu_name`,
  `runtime_manifest_checksum`, `duration_seconds`, `outcome`. `observed.py` đã lọc usage theo GPU và runtime cho ngân sách
  VRAM/RAM; `queue.py:275–300` đã ước thời gian chờ bằng trung vị thời lượng từng pha.
- Chi phí GPU của một job: `value/scorecard.py` (`billed_usages`, giờ GPU × `benchmark_gpu_hourly_usd`).
- T-042 (RunPod Serverless) sẽ cần ước thời gian của job để worker không nhận job không kịp chạy trước hạn của RunPod.

## Thiết kế

### 1. Bộ canh tiến độ dùng chung
Thêm vào `src/services/process_control.py` (đã có `ProcessTimeoutError`) một lớp canh tiến độ, ví dụ
`ProgressWatchdog(stall_seconds, probes)`:
- `probes`: các dấu hiệu tiến triển rẻ, kiểm mỗi vài giây: kích thước file log tăng, hoặc dòng log khớp mẫu tiến độ của công cụ,
  hoặc thời điểm sửa của file/thư mục kết quả tăng.
- Không có tiến triển quá `stall_seconds` → dừng nhóm tiến trình (dùng cách dừng sẵn có, `start_new_session` + kill group) và
  ném lỗi riêng `PROCESS_STALLED` (khác `*_TIMEOUT`), thông báo tiếng Việt: "{công cụ} không tiến triển trong {N} phút, đã dừng."
- Brush chuyển sang dùng lớp chung, giữ hành vi hiện tại (180 s theo log `brush-train`).
- COLMAP chuyển từ `subprocess.run` sang `Popen` + vòng lặp có canh tiến độ. Dấu hiệu: log tăng, `database.db` và thư mục
  `sparse/` đổi. **Ngưỡng riêng cho từng lệnh COLMAP** vì có pha im lặng lâu (bundle adjustment toàn cục): đọc mã nguồn và log
  thật trong `data/studio_local/artifacts` của job đã chạy để chọn ngưỡng (đề xuất mặc định 15 phút, cấu hình được qua
  `R2S_COLMAP_STALL_SECONDS`). Ghi bằng chứng chọn ngưỡng vào report (khoảng im lặng dài nhất thấy được trong log thật).
- Áp dụng tương tự cho voxel/splat (Node), MoGe, LiDAR odometry, ObjectGS (log huấn luyện). Mỗi công cụ một ngưỡng mặc định có
  lý do, đặt qua biến `R2S_<CÔNG CỤ>_STALL_SECONDS` / `PRODUCT_OBJECTGS_STALL_SECONDS` (tên theo quy ước T-036).

### 2. Hạn tổng tự tính theo khối lượng scene
Hàm thuần `expected_seconds(tool, params, gpu_name, runtime, usages) -> Estimate | None` (module mới cạnh `observed.py`):
- Lấy các lượt `completed` cùng `tool`, cùng `gpu_name` (và cùng runtime nếu đủ mẫu, không thì chỉ cùng GPU).
- Quy theo khối lượng: COLMAP theo số ảnh, Brush/ObjectGS theo số vòng huấn luyện, các công cụ khác theo tham số chính có trong
  `params` (đọc preset ở `configs/product/processing_presets_v1.json` để chọn đúng khoá). Ước = trung vị (giây/đơn vị) × khối
  lượng của job này.
- Hạn dùng = `max(sàn, hệ số × ước)`, chặn trên bởi giới hạn cố định hiện có. Đề xuất hệ số 3, sàn 10 phút. Không đủ mẫu (dưới 3
  lượt) → dùng giới hạn cố định như hiện nay. Ghi `Estimate` (giây ước, số mẫu, nguồn: "đo" / "mặc định") vào log của lượt chạy và
  vào `details` của lỗi khi hết hạn.
- Lỗi khi hết hạn tự tính: "{công cụ} chạy quá {X} phút, gấp {k} lần thời gian thường thấy trên {GPU} cho scene cỡ này; đã dừng."
- Xuất hàm này cho T-042 dùng (worker không nhận job mà thời gian ước vượt thời gian còn lại).

### 3. Trần chi phí GPU mỗi scene (tuỳ chọn, mặc định tắt)
- Biến `PRODUCT_JOB_GPU_HOURS_MAX` (không đặt = không giới hạn; laptop không đặt).
- Trước khi chạy một công cụ dùng GPU: tổng giờ GPU đã tính của job (`billed_usages`) + ước của công cụ sắp chạy > trần → không
  chạy, job FAILED với mã `GPU_BUDGET_EXCEEDED`, `retryable=False`, thông báo: "Scene này đã dùng {a} giờ GPU, vượt mức tối đa {b}
  giờ đã đặt." Trong lúc chạy: vòng canh dừng công cụ khi tổng vượt trần.
- Người có quyền vẫn tạo lượt chạy mới sau khi người vận hành nâng trần (không cần cơ chế đặc biệt).

### 4. Giới hạn cố định thành lưới an toàn
Giữ các biến hiện có (không đổi tên, không bỏ). Nâng mặc định trong code lên mức rộng (ví dụ COLMAP 14400, Brush 21600) vì hai cơ
chế trên mới là cơ chế chính; cập nhật `scripts/gpu/studio.env.example`, `docker_entrypoint.sh`, `deploy/studio/*.env.example`
(sinh lại bằng `scripts.studio.deploy_env render --examples`). **Không sửa `scripts/gpu/studio.env` của laptop** (file riêng của
máy); ghi vào report khuyến nghị cho chủ dự án.

## Steps
1. Lớp canh tiến độ + test bằng tiến trình giả (script `sleep`/in log): có tiến triển → không dừng; im quá ngưỡng → dừng đúng
   nhóm tiến trình, mã `PROCESS_STALLED`; hủy và mất lease vẫn hoạt động như cũ. Chuyển Brush sang lớp chung, test Brush cũ xanh.
   Commit.
2. COLMAP qua `Popen` + canh tiến độ. Đọc log thật của job đã chạy để chọn ngưỡng, ghi bằng chứng. Test lỗi OOM, exit code, hết
   giờ hiện có vẫn đúng (`tests/test_reconstruction/test_rec03_colmap.py`). Commit.
3. Áp canh tiến độ cho voxel/splat, MoGe, LiDAR odometry, ObjectGS. Commit theo từng công cụ.
4. `expected_seconds` + test (đủ mẫu, thiếu mẫu, khác GPU, khác runtime, khối lượng gấp đôi → ước gấp đôi). Nối vào chỗ khởi
   chạy từng công cụ; log `Estimate`. Commit.
5. Trần chi phí GPU + test (không đặt → không chặn; vượt trước khi chạy → không chạy; vượt khi đang chạy → dừng). Commit.
6. Nâng mặc định giới hạn cố định, cập nhật file mẫu và tài liệu (`scripts/gpu/README.md`, `deploy/studio/OVERVIEW.md` mục
   giới hạn thời gian). Commit.
7. Thông báo lỗi mới hiện đúng trên giao diện: kiểm `frontend/src/features/studio/errorGuidance.ts` có hướng dẫn cho
   `PROCESS_STALLED`, `GPU_BUDGET_EXCEEDED` và lỗi hết hạn tự tính (câu tiếng Việt rõ: nguyên nhân và nên làm gì). Test. Commit.

## Acceptance criteria
1. Mọi công cụ chạy lâu có canh tiến độ; dừng vì treo có mã và câu thông báo riêng.
2. Hạn tổng tự tính khi có đủ số đo trên đúng GPU; thiếu số đo thì giữ hành vi cũ.
3. Trần chi phí GPU hoạt động khi đặt, không ảnh hưởng khi không đặt.
4. Không lượt chạy bình thường nào trong test hiện có bị dừng oan; test hiện có của COLMAP, Brush, runner xanh.
5. Không sửa `scripts/gpu/studio.env`; không cần GPU thật để kiểm.

## Tests required
```
.venv/bin/python -m pytest tests/test_reconstruction/test_rec03_colmap.py tests/test_reconstruction/test_rec04_brush.py \
  tests/test_reconstruction/test_preview_cancellation.py tests/test_orchestration -q
.venv/bin/python -m pytest <test mới> -q
cd frontend && ./node_modules/.bin/vitest run <test errorGuidance> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```
Sau bước 6 chạy full backend một lần (task chạm mọi runner), ghi số thật.

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`. Không khởi động lại stack.
