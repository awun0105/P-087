# Giao thức benchmark `pipeline_runtime`

`pipeline_runtime` đo thời gian thực thi của một job Studio và phân biệt thời gian worker,
xếp hàng, chờ xác nhận của người dùng và publication. Benchmark không đánh giá chất lượng
hình học; phải đối chiếu với các protocol chất lượng tương ứng trước khi kết luận tối ưu hóa.

## Snapshot và tương thích

Schema 1.1 lưu snapshot riêng theo job, attempt và phase:

- `partial`: job còn chạy hoặc chờ người dùng; `total_seconds` và `attempt_wall_seconds`
  vẫn `null`, vì chưa có thời điểm kết thúc.
- `terminal`: attempt đã kết thúc. `total_seconds` là toàn bộ vòng đời từ
  `JobManifest.started_at` đến `JobManifest.completed_at`; `attempt_wall_seconds` là từ lần
  claim RUNNING của attempt đến terminal journal event.
- Artifact mới dùng `attempt-<n>-partial.json` và `attempt-<n>-terminal.json`. Bản ghi schema
  1.0 vẫn đọc được; trường không có trong dữ liệu cũ giữ `null`/`unknown`.
- Mọi số đo thiếu giữ `null`; `0` chỉ có nghĩa là đã đo được thời lượng bằng 0. Không cộng
  các stage đang overlap để suy ra wall time.

## Trường và cách diễn giải

| Field | Đơn vị | Nguồn / ý nghĩa |
|---|---:|---|
| `snapshot_phase` | — | `partial` hoặc `terminal`, cho phép giữ cả snapshot tiến trình và kết quả cuối. |
| `stages[].seconds` | giây | Khoảng `started_at` → `completed_at` của stage thuộc attempt hiện tại; null khi thiếu một trong hai mốc. |
| `stages[].scope` | — | `attempt`, `reused` hoặc `unknown`; stage tái sử dụng từ attempt trước không bị tính lại. |
| `stages[].waiting_seconds` | giây | Thời gian chờ metric confirmation; không được tính vào worker critical path. |
| `total_seconds` | giây | Vòng đời job đầy đủ, gồm queue và người dùng chờ; chỉ có ở snapshot terminal. |
| `attempt_wall_seconds` | giây | Wall time của attempt; chỉ có khi attempt có terminal event. |
| `queue_seconds` | giây | Từ QUEUED đến lần RUNNING đầu của attempt. |
| `user_wait_seconds` | giây | Từ lúc job chờ metric confirmation đến lúc có xác nhận; nếu còn chờ, đo đến `recorded_at` của snapshot. |
| `critical_path_seconds` | giây | Từ stage worker đầu tiên đến stage cuối cùng, trừ phần overlap với metric-confirmation wait; chỉ có khi mọi interval đã kết thúc và không overlap. Gaps giữa các stage được giữ lại như latency thực. |
| `worker_process_seconds` | giây | Tổng `ResourceUsage.duration_seconds` của các tool thuộc attempt và cùng config/runtime identity; là elapsed process time, không phải GPU busy time. |
| `worker_wall_seconds` | giây | Hợp các interval `ResourceUsage`, tính vùng overlap một lần. |
| `tool_timings[]` | giây | Tool, mốc bắt đầu/kết thúc, duration và outcome lấy từ resource journal. |
| `timing_coverage` | — | Số worker stage có đủ hai mốc và danh sách stage chưa đủ; không xem missing là zero. |
| `first_preview_ready_at` | UTC | Thời điểm consumer verifier xác nhận SOG dùng được; thời gian preview không được suy từ metric stage kết thúc. |
| `time_to_first_preview_seconds` | giây | `JobManifest.started_at` đến lần preview verified đầu tiên. |
| `actual_frame_count` | frame | Số frame thực tế trong frame-set artifact, không phải `sampling.max_frames` (giới hạn cấu hình). |
| `input_manifest_checksum`, `config_checksum`, `runtime_manifest_checksum` | — | Identity cần khớp khi so sánh benchmark. |
| `gpu_power_limit_watts` | watt | Chỉ có khi đo/ghi được giới hạn công suất; hiện thường null. Không điền từ cấu hình mặc định giả định. |
| `gpu_allocated_seconds` | giây | Thời lượng GPU allocation của provider; null nếu không có allocation ledger. |
| `active_compute_seconds`, `io_seconds`, `publication_seconds` | giây | Null đến khi có phép đo riêng đáng tin cậy cho từng loại công việc. |
| `estimated_gpu_cost_usd` | USD | Null khi chưa có GPU allocation duration đã đo; không nhân rate với lifecycle wall hay user wait. |

`machine` ghi capability hiện có. Capability snapshot không chứng minh power mode, GPU
utilization hay allocation; các số đó chỉ được đưa vào khi có nguồn telemetry trực tiếp.

## Quy trình thu thập và so sánh

```bash
python -m scripts.benchmark.collect --all --label aisle-cw-demo --gpu-hourly-usd 0.34
# → eval/results/pipeline_runtime/aisle-cw-demo.jsonl
```

Collector ghi tối đa một bản ghi cho mỗi `(job, attempt, phase)`, nên partial và terminal
có thể cùng tồn tại. Các bản ghi schema 1.0 không có phase được phân loại theo trạng thái.

Chỉ so benchmark có cùng `input_manifest_checksum`, `config_checksum`,
`runtime_manifest_checksum`, số frame thực, GPU model và tool/runtime identity. Ghi riêng
power/thermal condition; nếu thiếu thì báo là chưa kiểm soát, không gọi là paired evidence.
Giữ nguyên config và quality gates. Báo median và từng cặp, phân biệt job wall, worker process
sum, worker interval union, queue và user wait. Thành công latency không bù cho suy giảm
visual, pose, metric, collision hoặc scene quality.

## Mốc audit hiện có và target cho AUD-15

`job-6bc02e5de4ed` là một mốc đơn có `input_manifest_checksum` bắt đầu bằng
`sha256:bfa8ad…`, `config_checksum` bắt đầu bằng `sha256:55d779…`,
`runtime_manifest_checksum` bắt đầu bằng `sha256:861c5b…`, Quadro T2000 và 50 frame thực tế
(cấu hình đặt `sampling.max_frames=300`). Cộng các `ResourceUsage` đã lưu cho prepare,
preview, metric proposal, finalize và scene extraction được **5.046,05 giây** process time.
Đây là một run đơn; power/thermal state không được ghi nên chưa phải paired performance
acceptance. Hai benchmark cũ của job được chụp khi trạng thái còn RUNNING và không đại diện
cho toàn bộ vòng đời job.

AUD-15.S2/S3 dùng target đã đóng băng: với cùng input/config/runtime, 50-frame inventory,
30.000 Brush iterations, 1280 px, 1.000.000 max splats và cùng GPU/tool identity, đạt median
optimized `worker_process_seconds ≤ 4.541,45 giây`, giảm tối thiểu 10% so với run baseline
5.046,05 giây. Chạy tối thiểu ba cặp baseline/optimized; ghi power/thermal condition hoặc đánh dấu chưa kiểm soát. Giữ nguyên
selected config và yêu cầu mọi quality gate của cùng bộ dữ liệu/holdout không suy giảm ngoài
tolerance đã định nghĩa trong protocol tương ứng. Baseline một mẫu hiện tại chỉ dùng làm mốc
định hướng; chưa chứng minh target đạt.
