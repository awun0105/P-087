# Roadmap: Duyệt tách vật + vỏ Gaussian + collider

Đọc `architecture.md` trước. Làm theo thứ tự; cột "Cần" là task phải `accepted` trước.

## Sprint 1: Nền tảng backend (hàm thuần + contract)

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-001 | Tách `occupancy_surface()` | Hàm dựng mesh từ ô voxel dùng chung, không đổi hành vi | – | S |
| T-002 | Dựng vỏ Gaussian kín | `build_gaussian_shell()` cho ra mesh qua QA | T-001 | M |
| T-003 | Contract vỏ + trạng thái hình học | `ObjectShellManifest`, `geometry_method=shell`, `geometry_review` (presets chuyển sang T-013) | – | M |
| T-004 | Box → membership | `ObjectRegionCommand` + `resolve_region()` + preview diff | T-003 | M |

## Sprint 2: Pipeline tách hai pha

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-005 | Tách vật dừng ở Draft | `objectify()` publish Draft SceneIR khi `geometry_review=required` | T-002, T-003 | M |
| T-006 | Tách helper khỏi `objectify()` | Hàm dùng chung: collider CoACD, vá nền + SOG, collision môi trường; không đổi hành vi | T-005 | M |
| T-007 | Build hình học từ vỏ | Draft → vỏ mịn → QA → CoACD → nền → SceneIR ready (hàm service) | T-006 | L |
| T-008 | Nâng cấp ObjectGS theo vật | Surface ObjectGS khi qua QA, ngược lại giữ vỏ + lý do | T-007 | M |
| T-009 | Hàng đợi + API build | Mode `geometry`, route build, cancel, role matrix, `auto` | T-007 | M |
| T-010 | API region preview/apply (Draft) | Preview vỏ thô; Apply đồng bộ ra revision mới | T-004, T-005 | M |
| T-011 | Sửa vùng sau khi ready | Apply trên scene ready → rebuild đúng vật bị ảnh hưởng | T-009, T-010 | M |
| T-012 | Khoá thao tác khi Draft | Walk/USD/Move/Rotate bị từ chối rõ ràng khi chưa có hình học | T-005 | S |

## Sprint 3: Studio

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-013 | API client + banner Draft + tiến độ build + presets | Nút "Tạo mesh", khoá Walk/USD/Move, phase build; đổi preset sang shell + required | T-009, T-012 | M |
| T-014 | Box model (TS thuần) | Kiểu dữ liệu, tự khớp OBB, kéo mặt, clamp sàn | – | M |
| T-015 | Box overlay + tay nắm + góc nhìn | Vẽ box, tay nắm mặt/xoay/dịch, Trên/Trước/Cạnh | T-014 | L |
| T-016 | Region Editor panel | Box cộng/trừ, preview debounce, bộ đếm, chồng lấn, Apply/Huỷ | T-010, T-015 | M |
| T-017 | Vỏ phát sáng + điểm thêm/bớt | Vỏ emissive, điểm xanh/đỏ, Draft không vẽ Gaussian vật chồng | T-016 | M |
| T-020 | Lựa chọn Duyệt trước / Tạo mesh ngay khi tạo job | Radio riêng cho `scene.geometry_review` | T-013 | S |
| T-021 | Tiến trình, chuông, đầu trang hiểu Draft | Hàng ảo "Duyệt vật & Tạo mesh", nhánh Draft của chuông, nhãn đầu trang, sửa mô tả bước | T-013, T-020 | M |

## Sprint 4: Bàn giao

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-018 | Tương thích scene cũ + Walk/USD với collider vỏ | Scene legacy/ObjectGS cũ vẫn chạy; Walk/USD dùng đúng collider vỏ | T-007..T-013 | M |
| T-019 | Full regression + handoff | Toàn bộ test/lint/typecheck, handoff, hướng dẫn chạy scene mới | tất cả | S |

## Sprint 5: Sửa sau regression (từ deep review T-019)

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-022 | Giữ số Gaussian vá nền khi Tạo mesh (GR-01, P1) | Preflight/package PASS khi inpaint > 0 | T-019 | S |
| T-023 | Box ban đầu khớp nhóm Gaussian hiện tại (GR-02, P1) | Route fit; mở lại Chỉnh vùng không loại hàng | T-019 | M |
| T-024 | Chỉ dẫn lỗi: banner, donor, preview 409 (GR-03/04/06) | Người dùng thấy lỗi trước khi bấm | T-019 | M |
| T-025 | Hiệu năng preview + khoá cache (GR-05) | Warm 2M hàng ≤ 1,5 s; không chặn khi đọc PLY | T-024 | M |

## Sprint 6: Hệ thống ghi và xuất metric giá trị (architecture §15)

Xong 2026-10-16: T-027 → T-035 accepted. Full backend 3.688 pass / 0 fail / 28 skip; frontend 936 pass. Handoff:
`docs/plans/active/2026-10-16-value-metrics/HANDOFF.md`. Việc tiếp theo: chạy một scene thật có đo thước (chủ dự án).

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-027 | Nhật ký sự kiện giá trị | Bảng `r2s_value_events`, ghi `scene_edit` từ `publish_next`, API nhận `operator_time` / `walk_session` | – | M |
| T-028 | Đo máy cho hàng đợi tách vật | `ResourceUsage` cho mọi mode của `objectify_queue`; phút máy đủ | – | S |
| T-029 | Bộ đếm phút công người + sự kiện Walk | Hook trình duyệt gửi lô thời gian thao tác; Walk gửi phiên | T-027 | M |
| T-030 | Ground truth của benchmark | Model + bảng + API CAS: robot, đoạn đo, khe, vật cản chính, layout A/B, mốc làm tay, L4 | – | M |
| T-031 | Máy đo khe, sai số, nhất quán | Tính trên collision tổng hợp của revision | T-030 | L |
| T-032 | Bảng metric + xuất JSON/CSV/MD | `ValueScorecard` cho job và cho bộ benchmark | T-027..T-031 | M |
| T-033 | Panel Benchmark trong Studio | Nhập ground truth: chọn điểm, khe, vật cản chính, gắn layout, mốc làm tay | T-030 | L |
| T-034 | Thẻ Giá trị + trang /benchmark | Hiển thị 5 metric, bảng nhiều scene, nút xuất | T-032 | M |
| T-035 | Regression + hướng dẫn đo | Full suite, cập nhật Playbook và handoff | tất cả | S |

## Sprint 7: Dọn hạ tầng

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-036 | Đổi tên thư mục runtime và biến `RECxx_*` | `data/*_runtime` và biến `R2S_*` theo chức năng; tên biến cũ vẫn nhận kèm cảnh báo | – | M |
| T-037 | Script dựng runtime ObjectGS | `setup_objectgs_runtime.sh` dựng lại được môi trường ObjectGS ở mọi máy; cache extension dùng chung | – | M |
| T-038 | Một công thức cài cho mọi máy GPU | `install.sh` + `doctor`; COLMAP 4.x không cần Docker; `Dockerfile.gpu` gọi `install.sh` | T-036, T-037 | L |
| T-039 | Build image GPU thật + chạy job trên pod RunPod | Image trên GHCR, `preflight` PASS, một job tới object geometry ready | T-038 | M |
| T-040 | Bỏ chép runtime manifest tay | Identity phần mềm tách phần cứng; worker công bố runtime; lease cho job mồ côi | T-036 | L |
| T-042 | GPU worker trên RunPod Serverless | Bật khi có việc, tắt khi rảnh; nhiều loại GPU; UI hiện thời gian chờ GPU | T-039, T-040 | L |
| T-041 | Deploy production thử trọn | Supabase, R2, Railway, Vercel, RunPod Serverless; 5 scene mẫu; đổi loại GPU không sửa API | T-039, T-040, T-042 | L |
| T-044 | Trang tiến trình đúng và đủ | Mô tả bước tiếng Việt rõ; khung xem đủ cho scene mẫu, có bước Duyệt vật; dòng kết quả thật dưới mỗi bước | – | M |
| T-043 | Dừng công cụ theo tiến độ và khối lượng | Canh treo theo tiến độ cho mọi công cụ; hạn tự tính theo số đo trên đúng GPU; trần giờ GPU mỗi scene | – | M |
| T-045 | 9 scene dataset chạy hết pipeline | Đầu vào là ảnh (1/2), COLMAP của pipeline, video ghép chỉ để xem; agent tự chạy và sửa lỗi | – | L |

## Sprint 8: Ổn định pipeline, một mô hình tiến trình, xem scene nhanh

Kế hoạch tổng (đọc trước mọi task): `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`. Có phiên khác cùng sửa cây
`develop`: tuân mục "Làm song song" trong kế hoạch tổng.

| ID | Tiêu đề | Mục tiêu | Cần | Cỡ |
| --- | --- | --- | --- | --- |
| T-046 | Vòng lặp worker không chết vì một lỗi | `QueueGuard` cho mọi hàng đợi, nghỉ tăng dần | – | S |
| T-047 | Tắt worker thì cho chạy lại, kể cả job cũ | SIGTERM → `INTERRUPTED_SHUTDOWN`; chiếu cờ chạy lại hai chiều | – | S |
| T-048 | Không còn job RUNNING không ai trông | Đóng khe trước khi tạo attempt; sweeper job không lease | T-047 | M |
| T-049 | Chịu lỗi DB thoáng qua | `HeartbeatTolerance` cho ba hàng đợi và `_run_tool` | T-046 | M |
| T-050 | Chờ tài nguyên có giới hạn | Lý do `gate_error`; hết hạn chờ không phải vì bận; hạn tự tính không lặp | T-049 | M |
| T-051 | File theo checksum giữ vĩnh viễn | immutable + 304, không băm lại, URL R2 ổn định | – | L |
| T-052 | Lưới va chạm Walk dựng một lần | Đệm bộ nhớ + đĩa theo revision, 304, gzip | T-051 | M |
| T-053 | Đệm SceneIR / JobManifest; gzip; CORS | Parse một lần mỗi checksum; nén JSON | – | M |
| T-054 | `/scenes` và stage-views nhẹ | Job mới nhất một truy vấn; usage bằng SQL; đệm stage-views | T-053 | M |
| T-055 | Một hàm trạng thái hình học | `object_geometry_view`; bỏ mã hoá trùng | – | S |
| T-056 | Bảng mốc bước | `r2s_step_marks` (migration v26), ghi trong `save_job` và từ runner | T-048 | L |
| T-057 | Pha có kiểu + mốc cho hàng đợi tách vật | `ObjectifyPhase`; xoá pha cũ khi lỗi; mốc theo lượt | T-050, T-056 | M |
| T-058 | Hàm thuần việc tiếp theo | `next_action()` 16 loại | T-055 | M |
| T-059 | Endpoint `/jobs/{id}/pipeline` | Bước thật tới khi scene dùng được, `next_action`, 304 | T-053, T-056, T-057, T-058 | L |
| T-060 | Một vòng poll mỗi trang | `usePipeline`, không re-render khi không đổi | T-059 | M |
| T-061 | Dòng tiến trình từ bước thật | Bỏ hàng giả; `stepActions` | T-060 | M |
| T-062 | Một nguồn việc cần làm | `nextActionView`; chuông không tải SceneIR | T-061 | L |
| T-063 | Một nguồn dữ liệu scene; dọn nhánh chết | `SceneRecordProvider` | T-062 | M |
| T-064 | Viewer không dựng lại, không vẽ thừa | Prop ổn định, mount sau camera, throttle, tab ẩn nghỉ | T-060 | M |
| T-065 | Tải lười | Ammo/va chạm khi Walk; bước 8 chỉ lưới; request song song; chia JS | T-064 | M |
| T-066 | Ảnh frame thu nhỏ | JPEG 160/320/640 có đệm | T-051 | S |
| T-067 | Vật nhẹ | SOG cho vật (job mới), tối đa 4 tải cùng lúc, vỏ không tải lại | T-064 | L |
| T-068 | SOG xem nhanh | Bản màu bậc 0 (+ LOD nếu công cụ hỗ trợ) cho job mới | T-051 | L |
| T-069 | Regression + đo + bàn giao | Full suite, bảng trước/sau, HANDOFF | tất cả | M |

### Backlog (chưa lập plan)
- Worker công bố registry năng lực input vào DB (bỏ chép tay `PRODUCT_INPUT_RUNTIME_REGISTRY`), cùng mẫu T-040.
- Nút "Chạy lại từ đầu" cho job đã có stage mà runtime không còn worker (T-040 Q1).
- Lệnh `reset-password` trong `auth.cli`.
- ObjectGS **chưa từng chạy đầu-cuối** qua worker trên một scene thật (HANDOFF PR-05 dòng 67, 79: "Full Studio worker job is unverified", "E2E NOT RUN"). Bằng chứng "mesh hở" hiện chỉ từ cube tổng hợp 96 px (1000/8000 vòng) và chạy lại trên dữ liệu Room đã tạo bằng `objectify_v1` — không đủ để kết luận chất lượng. Cần một lượt chạy đầu-cuối với `scene.geometry_method=objectgs` trên scene thật trước khi quyết mặc định.
- Scene Room `job-a14981f78f85` rev-100 (60 vật, tạo bằng `objectify_v1` SAM2+CoACD, **không** dùng ObjectGS) không mở được lưới va chạm/Walk từ khi có kiểm `require_closed_cuts` (commit `ee6b69f0`, 15/10): API trả 409 `UNREPAIRED_COLLISION_CUT: 954 new boundary edges remain` vì lỗ khoét vùng vật không nằm trên mặt phẳng nên không vá được. Cần quyết: xem trước/Walk hiện lưới kèm cảnh báo thay vì từ chối (giữ chặt cho xuất USD), và frontend không gọi lại khi 409.
### Kết quả Sprint 8 (2026-10-20)

T-046…T-069 đã cài (trạng thái `implemented`, chờ review). Bàn giao, số đo và lưu ý deploy:
`docs/plans/active/2026-10-20-pipeline-stability/HANDOFF.md`. Migration mới: v26. Lệch kế hoạch đáng chú ý (chi tiết trong
ledger và report): T-067 dùng PLY nén tạo lười trên API thay cho SOG trong pipeline; T-068 tạo bản xem nhanh nền trên API thay
cho artifact pipeline; T-065 hoãn Web Worker; T-063 gom request ở tầng API thay cho Provider.

