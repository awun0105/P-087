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
