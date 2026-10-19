# Kiểm tra telemetry của pipeline hiện tại — 2026-10-19

## Kết luận

Telemetry hiện tại chưa đo đủ sáu thành phần được yêu cầu. Đã có journal theo job/attempt/stage, số đo elapsed của tool và đồng hồ thao tác trên trang scene. Chưa có mô hình thời gian thống nhất tới lúc scene dùng được, chưa đo các pha con của bước tạo mesh và chưa gắn thời gian người dùng với từng tác vụ.

Đây là báo cáo kiểm tra. Không sửa implementation telemetry, không chạy lại pipeline, không sửa DB hay artifact gốc, không restart dịch vụ.

## Phạm vi và bằng chứng

- Dò code hiện tại bằng CodeGraph và graphify trước khi đọc nguồn chi tiết.
- Đọc SQLite bằng kết nối `mode=ro`, dùng SQLite backup để tính bằng production functions trên bản sao trong `/tmp/p087-telemetry-audit-20261019/`.
- Snapshot có 4 job, 52 job events, 105 resource usage records và 891 value events. Chưa có registration operation, validation operation hoặc validation run trong DB này.
- Tính lại bằng `build_benchmark`, `processing_seconds`, `hands_on` và `_interval_union_seconds`; không suy kết quả từ pitch hay tài liệu cũ.
- [runtime-evidence.json](runtime-evidence.json) chứa số tính lại; [aggregation-probes.json](aggregation-probes.json) chứa hai phép tái hiện aggregation.

## Sáu thành phần cần đo

| Thành phần | Hiện có | Phần thiếu |
| --- | --- | --- |
| Thời gian hệ thống của mỗi bước nhỏ | `ResourceUsage` có start/end, monotonic duration, tool, attempt và outcome. | Tool đang khá lớn: prepare, preview, finalize, scene_extract, scene.geometry. Chưa có span bền vững cho shell, ObjectGS, từng collider/vật, vá nền, đóng gói, publication. Diagnostic timestamps không thay thế được cặp start/end và coverage chuẩn. |
| Thời gian hệ thống của mỗi bước lớn | `StageTiming` tính stage trong attempt; thời gian các lượt scene.* được ghi riêng. | Chưa ánh xạ nhóm bước thống nhất. Hàng Duyệt vật & Tạo mesh không thuộc benchmark stages; UI luôn để thời lượng null. Có lỗi gộp hai artifact cùng StageId làm interval chồng nhau. |
| Tổng hệ thống / time to usable scene | Có job lifecycle, first-preview latency, tổng tool duration và union tool intervals. | Chưa có `time_to_usable_scene` tới mesh-ready. Job SUCCEEDED kết thúc trước duyệt vật/tạo mesh. Tổng processing hiện chỉ lấy latest completed của tool pipeline và mọi completed scene.*; bỏ các lượt thất bại/hủy, không giới hạn ở lần ready đầu. |
| Thời gian mỗi bước cần người dùng | Có metric-confirmation wait và event ghi nhận thao tác. | Chưa có task clock cho duyệt ẩn danh, chọn/duyệt/sửa vùng từng vật, quyết định retry/fallback, chọn căn LiDAR, review/approve/release. `user_wait` là khoảng chờ gồm cả người chưa có mặt; không phải active work. |
| Tổng thời gian người dùng xử lý | Có operator_time, lọc visibility và idle, cộng active_seconds. | Chỉ gắn ở ScenePage với 4 surface. Chưa theo step/task; thiếu StageInspectionPage và chuẩn bị input trước khi có job; chưa loại overlap của cùng người trên nhiều tab; gửi best effort có thể mất lô. |
| Tổng người + hệ thống | Có thành phần rời để đọc. | Chưa có chỉ số kết hợp, cùng workflow boundary và coverage. Cộng tool sum với người không tạo ra end-to-end wall time nếu có overlap, queue hoặc idle. |

## Các phát hiện trong code

### F1. Mốc job hoàn tất dừng trước bước mesh-ready

`ProjectRegistry.record_finalize` đặt `JobStatus.SUCCEEDED` và `completed_at` sau EX-REC + extraction. Duyệt vật và `build_object_geometry` chạy sau trên hàng đợi scene riêng.

`benchmark.py:403` tính `total_seconds = completed_at - started_at`; `_tool_timings` chỉ giữ resource record trong attempt, trước terminal và cùng config/runtime identity. Các record `scene.geometry` còn dùng operation config checksum riêng. Do đó benchmark job không bao phủ tác vụ tạo mesh sau terminal.

Nguồn: `src/services/orchestration/projects/registry.py:1358`, `src/services/orchestration/jobs/runner.py:1738`, `src/services/orchestration/benchmark.py:262`, `src/services/orchestration/benchmark.py:399`.

### F2. Hàng mới và pha con chưa có đồng hồ chuẩn

`UI-GEOMETRY-REVIEW` chỉ là hàng phía UI. `ProgressTab.tsx:62` truyền `seconds: null` cho hàng này. `objectify_queue.py:861` ghi đè mỗi trường `phase`, không lưu thời điểm bắt đầu/kết thúc từng pha. Bảng `r2s_scene_requests` giữ một hàng mới nhất trên mỗi job.

`_scene_sampler` đo toàn bộ một lượt `scene.<mode>`, có lưu outcome kể cả lỗi. Trong build, callback shell → objectgs → quality → collider → environment → publish chỉ báo trạng thái. Không có resource/span theo từng object hoặc từng pha.

Nguồn: `frontend/src/features/studio/stages.ts:74`, `frontend/src/features/studio/scene/ProgressTab.tsx:62`, `src/services/orchestration/scene/objectify_queue.py:741`, `src/services/orchestration/scene/object_geometry_build.py:786`.

### F3. Artifact bundle làm sai ranh giới bước xác nhận tỉ lệ

Job có cả `RGBMetricConfirmation` và `ReconstructionBundle` cùng `ST-METRIC-CANONICALIZE`. `job_progress` gom records bằng dict theo StageId, nên bundle ở cuối thay mốc kết thúc xác nhận bằng mốc xuất bundle.

Ở DrJohnson:

- Người xác nhận: `2026-10-17T10:34:44.207504Z`.
- RGB geometry đã bắt đầu: `2026-10-17T10:34:45.017624Z`.
- Bundle gắn cùng StageId kết thúc: `2026-10-17T10:43:35.646618Z`.
- `user_wait_seconds`: 125.989 s; `stages[metric].waiting_seconds`: 657.428 s.

Metric interval vì thế chồng lên RGB geometry. `critical_path_seconds` trả null với `overlapping_serial_stage_intervals` ở 3/4 job. Chưa có bằng chứng cho phép diễn giải các duration đó là tổng thời gian hệ thống theo bước lớn.

Nguồn: `src/services/orchestration/jobs/progress.py:202`, `src/services/orchestration/benchmark.py:139`, `src/services/orchestration/benchmark.py:202`.

### F4. Thời gian máy có policy chọn lượt, chưa phải tổng mọi công hệ thống

`billed_usages` chỉ chọn outcome completed. Tool pipeline lấy lần completed mới nhất theo `(job, tool)`; scene.* cộng mọi completed. Failed/cancelled/interrupted bị bỏ. Việc cộng duration có thể đếm overlap nhiều lần và có thể gộp tool pipeline từ các attempt khác nhau.

`machine_minutes` gọi chính policy này và trả provenance measured khi có ít nhất một số đo, chưa chứng minh đủ toàn bộ bước bắt buộc. Với playroom, không có finalize completed trong resource journal; attempt mới nhất chỉ còn một tool record scene_extract, nhưng timing coverage vẫn 2/2 và timing_issues rỗng. Coverage hiện chỉ xét timestamp của các stage thuộc attempt, không kiểm đầy đủ tool nhỏ hoặc hàng mới.

Nguồn: `src/services/orchestration/processing/observed.py:86`, `src/services/orchestration/value/scorecard.py:156`, `src/services/orchestration/benchmark.py:359`.

### F5. Người dùng chưa được đo theo tác vụ và thiếu màn hình mới

`useOperatorTime` chỉ được gọi trong `ScenePage.tsx:294`. Surface có progress/studio/evaluation/other; payload không có workflow_run_id, stage_id, task_id, operation_id, object_id hoặc scene_revision.

Trang xem giai đoạn dùng `StageInspectionPage` và có công cụ chỉnh scene, nhưng không gọi hook này. Khâu chọn/chuẩn bị input trước khi có job cũng không nằm trong phép đo.

Clock nhận pointerdown, keydown, wheel và kéo chuột; mỗi tick tối đa 2 s, idle cutoff 60 s, batch 30 s. Đây là proxy hoạt động trình duyệt: có thể tính thêm khoảng sau click và không tính việc đọc/suy nghĩ quá idle cutoff. Không phải phép đo độc lập toàn bộ công người.

Nguồn: `frontend/src/features/studio/ScenePage.tsx:47`, `frontend/src/features/studio/value/useOperatorTime.ts:22`, `frontend/src/features/studio/value/operator-clock.ts:8`, `frontend/src/features/studio/inspection/StageInspectionPage.tsx:42`, `src/api/studio/value.py:47`.

### F6. Chờ người dùng mới chỉ có metric confirmation

`_user_wait_seconds` chỉ xét ST-METRIC-CANONICALIZE. Frame anonymization có trạng thái waiting trong progress nhưng chưa có human-task interval riêng. Duyệt vật/tạo mesh và các bước review sau job không được cộng vào trường này.

Thời gian từ lúc cần xử lý đến lúc hoàn thành phải tách: chờ người nhận việc, hoạt động của người, hệ thống đang xử lý trong tác vụ, và phần idle chưa xác định. Một số wait timestamps không thể biến thành active work bằng phép trừ đơn giản.

Nguồn: `src/services/orchestration/benchmark.py:297`, `src/services/orchestration/jobs/progress.py:278`.

### F7. Chưa xử lý đầy đủ overlap và giao điểm ready của công người

API chỉ chống chồng lô theo session_key. `hands_on` cộng mọi lô, không hợp interval theo actor. Probe cùng một actor, hai session, mỗi session 30 s cho tổng 60 s dù elapsed chỉ 30 s. Cần phân biệt person-time với wall time và loại đếm trùng cùng người.

Việc chia trước/sau ready gán toàn bộ batch theo ended_at; batch vắt qua ready không được cắt tại mốc đó. Batch chỉ có active_seconds, không có vị trí các active interval bên trong để chia chính xác.

Nguồn: `src/api/studio/value.py:91`, `src/services/orchestration/value/scorecard.py:193`.

### F8. Telemetry hiện là best effort

Frontend retry một lần rồi bỏ lô, chưa có durable outbox. `record_event` và resource recording log warning khi không ghi được rồi cho thao tác chính tiếp tục. Thiết kế này giữ được tương tác nhưng không bảo đảm dữ liệu đủ để coi tổng là hoàn chỉnh. Chưa có cờ coverage chung cho toàn workflow người + máy.

Nguồn: `frontend/src/lib/api/value.ts:66`, `src/services/orchestration/value/events.py:71`, `src/services/orchestration/jobs/runner.py:352`.

### F9. Các nhánh mở rộng chưa ghép vào tổng chung

LiDAR ingestion/QA/odometry có sampler ở runner. Registration và Isaac có operational records/lease; validation có requested_at, started_at, completed_at để suy một phần latency. Tuy nhiên chúng chưa được ghép vào benchmark stages/total của workflow hiện tại. Chưa có registration/Isaac run thật trong DB snapshot để kiểm chứng duration của các nhánh này.

Các field active_compute_seconds, io_seconds, publication_seconds hiện được build_benchmark đặt None. Resource duration là process elapsed có I/O, không phải GPU busy time.

Nguồn: `src/services/orchestration/jobs/runner.py:1075`, `src/models/contracts/validation_run.py:108`, `src/services/orchestration/jobs/registration_operations.py:48`, `src/services/orchestration/benchmark.py:453`.

### F10. Phiên demo riêng sẽ xóa cả telemetry riêng khi đóng

Demo dùng DB và worker directory riêng; purge xóa toàn bộ session root. Chưa có bước xuất duration/counters của demo vào một kho analytics bền vững trước cleanup. Nếu cần đo các phiên demo qua nhiều người và nhiều lượt, hiện chưa đủ cơ chế lưu giữ.

Nguồn: `src/services/orchestration/samples/sessions.py:67`, `src/services/orchestration/samples/sessions.py:300`.

## Bằng chứng từ job thật

| Job | Job lifecycle | First mesh-ready từ scene event | Resource records sau terminal |
| --- | --- | --- | --- |
| DrJohnson `job-f9f14e7fbfb1` | 15,479.491 s ≈ 4 h 18 min | 64,362.417 s từ job start ≈ 17 h 53 min | 12 scene.geometry: 11 failed, 1 completed |
| Room `job-bfc7d73f0dbf` | 11,896.428 s | Chưa có; head hiện awaiting_review | 0 |
| Playroom `job-7c9820b4834f` | 92,528.632 s | Chưa có; head hiện awaiting_review | 0 |
| Room cũ `job-a14981f78f85` | 7,627.615 s | Không có marker object_geometry của luồng mới | 0 |

Các khoảng elapsed trên gồm queue, chờ người, idle và retry theo lịch sử. Không gọi 17 h 53 min của DrJohnson là thời gian GPU hoặc công người. First-ready suy từ event + SceneIR đã lưu, chưa phải một field time_to_usable_scene được hệ thống phát hành.

DrJohnson có 9,376.283 s operator active trong toàn lịch sử được ghi, gồm cả sửa scene sau lần ready đầu. Không dùng nguyên tổng đó làm công người của lần tạo scene đầu tiên.

## Cách tính cần có

Nên công bố ba milestone riêng: preview_ready, geometry_ready có thể Walk/xuất theo gate hiện tại, và simulation_validated/released nếu quy trình yêu cầu. Không đồng nhất JobStatus.SUCCEEDED với cả ba.

- System effort: tổng duration của các leaf span thực sự chạy; chỉ cộng leaf, không cộng cả span cha và con. Báo cả mọi lượt chạy và lượt thành công được chọn.
- System wall: union interval hệ thống trong cùng workflow, tính overlap một lần.
- Human effort: tổng active duration theo người và task; hợp overlap của cùng actor trước khi cộng các actor.
- Human-task elapsed: task_required_at → task_completed_at, cùng các trạng thái opened/claimed/submitted và active work riêng.
- Time to usable: milestone_at − workflow_started_at, có ghi rõ mốc bắt đầu; tách queue/idle/unknown.
- Effort người + máy: system effort + human effort, ghi rõ đây là effort sum.
- Elapsed có người hoặc máy hoạt động: union các interval của hai loại. Không đồng nhất với effort sum hay end-to-end elapsed.

Ví dụ máy chạy [0,10], người làm [5,12]: effort sum 17 s, union 12 s. Nếu có một khoảng không ai làm gì trước đó, end-to-end còn lớn hơn union.

## Thứ tự bổ sung đề xuất

1. Chuẩn hóa workflow_run_id, parent/child step identity và các milestone readiness. Giữ job attempt và operation ID riêng để không trộn rerun với lần tạo ban đầu.
2. Sửa phép chiếu metric-confirmation/bundle; bổ sung timer bền vững cho bước lớn Duyệt vật & Tạo mesh và từng pha con, trạng thái queued/started/completed/failed/cancelled, object ID khi đo từng vật.
3. Gắn human task intervals và active tracking vào mọi màn hình thực sự thao tác, gồm StageInspectionPage; phân biệt time awaiting user với active work.
4. Ghép system/human/queue theo interval và cùng workflow boundary. Mọi tổng cần coverage, missing step IDs và policy rõ cho retries, cancelled work và người đồng thời.
5. Bổ sung durable delivery/dedup và, nếu cần đo demo, xuất telemetry tổng hợp độc lập trước xóa session. Dữ liệu cũ thiếu mốc giữ unknown/partial, không điền số giả.

## Kiểm chứng

- Backend: `pytest tests/test_orchestration/test_pipeline_timing.py tests/test_orchestration/test_benchmark_provenance.py tests/test_orchestration/test_value_scorecard.py tests/test_api/test_value_routes.py -q --tb=short` — 79 passed.
- Frontend: `vitest run tests/operator-time.test.ts tests/operator-time-scene.test.tsx tests/value-api.test.ts tests/value-card.test.tsx` — 25 passed, 4 files.
- Tính lại bằng production functions trên DB copy và chạy pure aggregation probes; không có GPU/Isaac workload, không dùng DevTools.
- Những suite này kiểm chứng chức năng hiện có; kết quả pass không chứng minh pipeline mới đã đủ coverage.

## Kiểm tra trước commit tổng hợp

Theo yêu cầu commit/push toàn bộ trạng thái hiện tại, đã chạy thêm suite liên quan tới các thay đổi viewer, demo và telemetry: **333 frontend tests passed, 27 files**. TypeScript, ESLint trên các file frontend thay đổi, Ruff check/format trên 19 file Python thay đổi và `git diff --cached --check` đạt. Không sửa các thiếu sót telemetry nêu trong báo cáo này.
