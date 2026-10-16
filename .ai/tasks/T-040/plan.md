# T-040: Bỏ bước chép runtime manifest bằng tay giữa GPU worker và API

## Goal
Đổi pod, thuê GPU khác loại hay bật thêm worker **không cần đụng vào API**. Worker tự công bố runtime manifest của mình;
API gắn job vào runtime của worker đang sống. Job đang dở không bị kẹt vĩnh viễn khi pod cũ đã trả.

## Context (cơ chế hiện tại, đã đọc code)
- Runtime manifest (`scripts/gpu/make_runtime_manifest.py`) ghi phiên bản thật của công cụ, model GPU, driver; checksum
  canonical của nó là identity runtime.
- **API** đọc `PRODUCT_RUNTIME_MANIFEST` + `PRODUCT_PROCESSING_CONFIG` thành `ExecutionProfile`
  (`src/services/orchestration/jobs/profile.py`; dựng ở `get_project_registry`, `registry.py:1920`). Mỗi job mới mang
  `runtime_manifest_checksum` của profile đó (`_build_queued_job`, `registry.py:1696–1719`). Thiếu profile thì API từ
  chối tạo scene (`registry.py:1702`, `api/studio/scenes.py:185`, `api/studio/assemblies.py:440`). Settings bắt hai biến
  phải cùng có hoặc cùng thiếu (`src/config.py:186`).
- **Worker** chỉ nhận job có checksum trùng profile của nó (`require_profile`, `jobs/dispatch.py:73–83`;
  `worker_cli.py:270`). Đường chạy tiếp (finalize sau khi xác nhận tỉ lệ, preview sau khi duyệt bản che) kiểm ở
  `runner.py:1563`.
- Worker đã có nhịp ghi cấu hình máy vào DB mỗi 300 s (`_start_capability_heartbeat`, `worker_cli.py:299–331`,
  `record_capability`).
- Hệ quả hiện tại: đổi pod sang GPU/driver khác → checksum khác → mọi job mới và job đang chờ chạy tiếp bị worker từ
  chối im lặng, cho tới khi người vận hành chép manifest mới lên API và khởi động lại API (`deploy/studio/OVERVIEW.md`
  bước 4 và mục "Những chỗ dễ vấp").

## Phần A: khảo sát và thiết kế (làm trước, **dừng chờ Architect duyệt**)
Viết `.ai/tasks/T-040/design.md` trả lời bằng code đã đọc (file:dòng), không đoán:
1. Ngoài `JobManifest.runtime_manifest_checksum`, runtime identity còn được ghi ở đâu (artifact từng stage, attempt,
   evidence, benchmark snapshot `pipeline_runtime`, release seal, validation)? Cái nào được kiểm lại về sau và sẽ vỡ nếu
   một job có các stage chạy trên hai runtime khác nhau?
2. Một job đang ở từng trạng thái sau thì hiện nay đi đường nào khi worker có checksum khác: QUEUED chưa có stage nào;
   QUEUED do retry sau lỗi preview; RUNNING chờ xác nhận tỉ lệ rồi finalize; chờ duyệt bản che; yêu cầu tách vật/Tạo mesh
   (`objectify_queue`, có kiểm runtime không?); import scene; validation Isaac.
3. Đề xuất bảng DB (migration 22) và luồng như phác thảo dưới, sửa lại cho khớp với câu trả lời 1–2.

Phác thảo của Architect (engineer kiểm và đề xuất chỉnh):
- Bảng `r2s_worker_runtimes(runtime_manifest_checksum PK, manifest JSON, config_checksum, seed, gpu_name, first_seen_at,
  last_seen_at)`. Worker upsert lúc khởi động và trong mỗi nhịp heartbeat. Manifest phải qua kiểm canonical checksum như
  `ExecutionProfile.load`.
- API: nếu có `PRODUCT_RUNTIME_MANIFEST` thì giữ hành vi cũ (ghim tay, cho máy dev và cho ai muốn khoá). Nếu không có
  và bật `PRODUCT_RUNTIME_FROM_WORKERS=true`: job mới gắn vào runtime có `last_seen_at` mới nhất trong TTL (15 phút) và
  `config_checksum` trùng file config của API. Không có worker sống: vẫn tạo job, gắn runtime thấy gần nhất, UI báo
  "đang chờ GPU" (không từ chối).
- **Gắn lại runtime** (rebind) chỉ cho job **chưa có stage artifact nào** (QUEUED lần đầu): khi runtime của job không có
  worker sống quá TTL mà có runtime khác đang sống, API hoặc worker gắn lại, ghi job event `runtime_rebound {from, to,
  reason}`. Job đã có stage chạy trên runtime cũ thì **không tự gắn lại**; cách xử lý do design.md đề xuất dựa trên câu 1
  (ví dụ: nút "Chạy tiếp trên GPU hiện có" cho Reviewer, ghi rõ provenance hai runtime; hoặc chạy lại từ đầu).
- `scripts/autoscaler` và UI tiến trình: hiện "đang chờ GPU (runtime …)" thay vì im lặng.

## Phần B: làm theo design.md đã duyệt
Plan bổ sung sẽ được Architect ghi vào cuối file này sau khi duyệt Phần A. Không viết code Phần B trước đó.

## Acceptance criteria (cho cả task)
1. Deploy production không còn bước chép manifest tay; `OVERVIEW.md` bỏ bước 4.
2. Đổi pod sang GPU khác loại: job mới chạy được ngay, không khởi động lại API.
3. Job đang dở khi đổi pod có đường xử lý rõ ràng, có ghi provenance thật, không kẹt im lặng.
4. Máy dev ghim `PRODUCT_RUNTIME_MANIFEST` chạy như cũ.
5. Test cho: upsert manifest, chọn runtime cho job mới, rebind job chưa chạy, từ chối rebind job đã có stage, TTL.

## Tests required
Phần A: không có. Phần B: ghi trong phần bổ sung.

## Commit
Phần A: một commit `design.md`, đặt status `changes-requested` kèm ghi chú "cần Architect duyệt design". Không
Co-Authored-By.
Cần T-038 accepted (đường dẫn và tên biến ổn định). Không cần T-039.
