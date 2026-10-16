# T-042: GPU worker chạy trên RunPod Serverless (bật khi có việc, tắt khi rảnh)

## Goal
Production không giữ GPU chạy lúc rảnh. Khi hàng đợi có việc GPU, một worker RunPod Serverless được bật, chạy hết việc
rồi thoát; RunPod tự tìm máy trong danh sách nhiều loại GPU. Người dùng thấy "Đang chờ GPU, N phút" thay vì job im lặng.

## Context
- Worker hiện tự lấy việc từ DB (`src/services/orchestration/jobs/worker_cli.py`, `scripts/gpu/run_workers.py`), chạy mãi.
  Entrypoint image: `scripts/gpu/docker_entrypoint.sh` (chế độ `worker`, `stack`, `preflight`, `batch`).
- Autoscaler `scripts/cloud/gpu_autoscaler.py`: interface `GpuProvider` (`state/start/stop`), hàm thuần `decide()`, đếm
  việc qua `measure_workload` (job trong hàng đợi, job vừa xác nhận hệ mét, yêu cầu dựng lại tập vật; job chờ người dùng
  không tính). Provider hiện có: Vast.ai `instance`/`rent`. Vast.ai giữ làm dự phòng, không phát triển thêm.
- RunPod Serverless (tài liệu RunPod, chưa thử thật): endpoint chạy image của mình, số worker tối thiểu 0; gửi yêu cầu
  `/run` thì RunPod bật worker, gọi hàm xử lý; `executionTimeout` mặc định 10 phút, đặt tối đa tới 7 ngày (một trang cũ
  ghi 24 giờ); `ttl` tính cả thời gian xếp hàng. Ổ container mất sau mỗi lần chạy. Khai được nhiều loại GPU theo thứ tự
  ưu tiên.
- T-040 bắt buộc trước: mỗi lần chạy có thể rơi vào loại GPU khác nên runtime manifest khác; worker phải tự công bố
  runtime và job mới phải gắn theo worker sống.

## Thiết kế
1. **Chế độ `drain` của image** (`docker_entrypoint.sh drain`): khởi động như `worker`, chạy việc trong hàng đợi đến khi
   **không còn việc GPU nào nó nhận được** trong `R2S_DRAIN_IDLE_SECONDS` (mặc định 120) thì thoát mã 0. Dùng lại vòng
   dispatch hiện có; thêm điều kiện dừng, không viết worker mới. Job đang chạy dở khi gần chạm `executionTimeout`: không
   nhận job mới nếu thời gian còn lại < ước lượng của job (đọc từ `R2S_DRAIN_DEADLINE`).
2. **Hàm xử lý RunPod** `scripts/cloud/runpod_handler.py`: `runpod.serverless.start({"handler": handle})`; `handle(event)`
   chạy `docker_entrypoint.sh drain` như subprocess với deadline từ cấu hình endpoint, trả tóm tắt
   (`{"jobs_run": n, "exit": code}`). Gói `runpod` thêm vào image (lockfile riêng nhỏ, không vào `requirements.lock.txt`
   của app). Image GPU có `CMD` mới cho Serverless qua biến `R2S_MODE=serverless`; chế độ cũ giữ nguyên.
3. **Provider `RunPodServerless`** trong `gpu_autoscaler.py`:
   - `state()`: đọc trạng thái endpoint/yêu cầu đang mở qua API RunPod (`/health` của endpoint: số job đang chạy/xếp
     hàng, số worker).
   - `start()`: gửi **một** yêu cầu `/run` nếu chưa có yêu cầu nào đang xếp hàng hoặc chạy (không gửi chồng mỗi 30 giây).
     Có nhiều việc chờ và `RUNPOD_MAX_WORKERS > 1` thì gửi tối đa ngần ấy yêu cầu.
   - `stop()`: không làm gì (worker tự thoát); chỉ huỷ yêu cầu còn xếp hàng khi không còn việc.
   - Biến: `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `RUNPOD_MAX_WORKERS` (mặc định 1), `GPU_PROVIDER=runpod|vast`.
4. **Không có máy**: yêu cầu nằm trong hàng đợi RunPod (TTL đặt đủ dài, ví dụ 24 giờ). Autoscaler ghi vào DB thời điểm
   bắt đầu chờ GPU; API đọc để UI tiến trình hiện "Đang chờ GPU, đã chờ N phút". Quá `GPU_WAIT_ALERT_MINUTES`
   (mặc định 15) thì log mức cảnh báo một lần (để người vận hành biết); không tự đổi nhà cung cấp.
5. **Kích hoạt nhanh hơn polling**: khi API tạo job hoặc nhận yêu cầu tách vật, gọi `start()` ngay (nếu
   `GPU_PROVIDER=runpod`), autoscaler 30 giây vẫn là lưới an toàn.
6. **Cấu hình endpoint** (ghi thành tài liệu + script `scripts/cloud/runpod_endpoint.py` tạo/cập nhật endpoint qua API):
   image theo digest T-039, GPU ưu tiên `RTX 4090 → RTX 3090 → RTX A5000 → L40S` (24 GB trở lên), worker tối thiểu 0,
   tối đa `RUNPOD_MAX_WORKERS`, `executionTimeout` 6 giờ, `ttl` 24 giờ, ổ container 80 GB, biến môi trường từ
   `worker.env` (DB, R2, EgoBlur, không có khoá RunPod).

## Steps
1. **Thử nhỏ trước (bắt buộc, có chủ dự án duyệt chi phí).** Tạo endpoint bằng tay với image T-039 và một handler tối
   giản chỉ chạy `preflight`. Đo: thời gian từ `/run` tới lúc handler chạy (lần đầu trên máy mới và lần sau), loại GPU
   được cấp, `preflight` PASS. Ghi vào `report.md`. Khởi động lần đầu > 10 phút: dừng, báo Architect (cân nhắc tách
   ObjectGS ra endpoint riêng để image nhỏ hơn).
2. Chế độ `drain` + test (hàng đợi giả: hết việc thì thoát; còn việc thì chạy; deadline không nhận job mới). Commit.
3. `runpod_handler.py` + lockfile riêng + `R2S_MODE=serverless` trong image. Test handler gọi đúng lệnh và trả tóm tắt.
   Commit.
4. Provider `RunPodServerless` + trạng thái chờ GPU trong DB + kích hoạt từ API. Test với transport giả (mẫu test
   Vast.ai hiện có): không gửi chồng yêu cầu; gửi đúng số khi nhiều việc; huỷ yêu cầu xếp hàng khi hết việc; ghi và xoá
   mốc chờ. Commit.
5. UI tiến trình: dòng "Đang chờ GPU, đã chờ N phút" khi job QUEUED và có mốc chờ. Test component. Commit.
6. `runpod_endpoint.py` + tài liệu `deploy/studio/OVERVIEW.md` (GPU worker = RunPod Serverless, Vast.ai dự phòng).
   Commit.
7. **Chạy thật** (chủ dự án duyệt): stack local hoặc staging trỏ DB/R2 thử, autoscaler `GPU_PROVIDER=runpod`; tạo một job,
   xem worker được bật, chạy tới preview, tự thoát, endpoint về 0 worker. Ghi thời gian, chi phí.

## Acceptance criteria
1. Không có việc GPU thì RunPod có 0 worker chạy (không tốn tiền GPU).
2. Có việc thì worker được bật trong thời gian đo được ở bước 1, chạy hết việc, tự thoát.
3. Không bao giờ có hai yêu cầu chồng nhau khi `RUNPOD_MAX_WORKERS=1`.
4. Hết máy loại ưu tiên thì RunPod dùng loại kế; hết tất cả thì UI hiện thời gian chờ.
5. Vast.ai provider vẫn chạy (test cũ xanh).

## Tests required
```
.venv/bin/python -m pytest tests/test_gpu tests/test_packaging tests/test_orchestration/test_worker_cleanup.py -q
.venv/bin/python -m pytest <test mới của drain/handler/provider> -q
cd frontend && ./node_modules/.bin/vitest run <test UI chờ GPU> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. Không ghi khoá RunPod, ID endpoint thật vào repo.
Cần T-039 và T-040 accepted.
