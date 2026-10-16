# Bàn giao đo metric giá trị — Sprint 6 / T-035

Phạm vi: hệ thống ghi và xuất metric theo `.ai/architecture.md` §15, T-027–T-034.
Có triển khai và test tự động không đồng nghĩa đã nghiệm thu scene thật, PostgreSQL thật hoặc Isaac.
Chủ dự án kiểm UI bằng mắt và chạy quy trình thực địa.

## Nguồn của 5 metric

| Metric | Nguồn và cách hiểu |
| --- | --- |
| Chính: phút công người, phút máy, phần cứng, chi phí | `operator_time` từ trình duyệt; `ResourceUsage` của pipeline và hàng đợi `scene.*`; snapshot `MachineCapability` của job. Phút máy dùng `processing_seconds`, pipeline lấy lượt tính phí mới nhất theo tool, `scene.*` cộng dồn. Chi phí là giờ GPU nhân đơn giá `benchmark_gpu_hourly_usd` do người vận hành khai báo; đây không phải hoá đơn nhà cung cấp. Thiếu đơn giá hoặc dữ liệu thì unavailable. |
| Can thiệp | `scene_edit` có `origin=human` và `scene_request` có `origin=human`. Worker publish `system` không cộng thêm một can thiệp. Số lần không phải số cú nhấp chuột. |
| P2: khe hẹp, bỏ sót/giả, sai số kích thước, vật cản chính có collider | Ground truth trong `r2s_benchmark_truth`; `value/measure.py` đo trên collision tổng hợp theo revision của layout. So bề rộng với robot và hai khoảng an toàn. Sai số kích thước đối chiếu đoạn chọn với số thước khai báo; không phải ground truth độc lập nếu số nhập do ước lượng. Chưa đo khe thì không diễn giải thành 0 lỗi. |
| P3: phút đổi bố trí đến thử lại, nhất quán sau dời | Layout A/B, `scene_edit` human sau mốc A, `walk_session` hoàn tất trên B; kiểm collision môi trường ở vị trí cũ và collider vật ở vị trí mới. Thiếu layout, revision hoặc Walk thì chưa có số. |
| P4: bậc L1–L4 | L1: xác nhận mét và hình học ready. L2: L1, vật cản chính có collider, Walk hoàn tất trên revision hiện tại, khe A không bỏ sót. L3: L2, gói mô phỏng của revision hiện tại và validation Isaac được chọn COMPLETED với overall_result PASS. L4: L3 và ba khai báo thử robot đều đúng, có bằng chứng. |

Code gom số: `src/services/orchestration/value/scorecard.py`. Mỗi Figure ghi `measured`, `declared` hoặc
`unavailable`; giữ nguyên nguồn khi trích bảng. Ô thiếu để trống hoặc hiện “—/chưa có”, không đổi thành số 0.
Phần cứng lấy snapshot job mới nhất có máy; đỉnh RAM/VRAM lấy các usage completed, không suy cấu hình máy từ đỉnh sử dụng.

## Nhập ground truth và chạy một scene

1. Mở trang scene, tab Studio, bấm **Benchmark** ở góc viewer. Người có quyền sửa job mới lưu được; người xem chỉ đọc.
2. Nhập robot: bề rộng, khoảng an toàn mỗi bên, độ cao thấp nhất/cao nhất. Mặc định 0,6 m; 0,05 m; 0,05–1,2 m.
3. Thêm đoạn đo: chọn hai điểm trên Gaussian rồi nhập chiều dài thật bằng mét từ thước. Đặt tên dễ nhận diện.
   Chọn đủ hai điểm sẽ dừng chọn. Huỷ nếu chọn sai; lớp phủ collision/vỏ/box tạm ẩn trong lúc chọn điểm rồi khôi phục.
4. Thêm khe: chọn hai đầu ngang trong hệ canonical mét, Z-up, sàn z=0; khai báo layout A/B, bề rộng thật nếu có,
   và thực tế robot qua được hay không. Khoảng cách hai điểm phải trong [0,1; 10] m. Máy đo tia theo dải cao robot bước 0,05 m.
5. Chọn các vật cản chính. Nếu vật đã xoá thì bỏ chọn mục “vật đã xoá (id)” trước khi lưu.
6. Gắn revision hiện tại là layout A, lưu. Dời vật, gắn revision mới là B và lưu; A/B phải khác revision.
   Hoàn tất Walk trên revision cần đánh giá. Mốc P3 lấy lần chỉnh sửa human sau mốc gắn A tới Walk hoàn tất của B.
7. Nhập mốc làm tay bằng phút không âm, dùng dấu chấm thập phân; chọn nguồn dữ liệu và cờ đưa scene vào benchmark.
8. L4: chỉ khai báo sau khi thử robot ở cả A và B, kết quả khớp thực tế; ghi bằng chứng. Khai báo không tự tạo validation Isaac.
9. Bấm **Lưu**. Ghi CAS theo version: nếu 409, đọc lại bản máy chủ rồi nhập lại thay đổi cần giữ; không ghi đè mù.
   Khi rời panel có nháp chưa lưu, xử lý cảnh báo trước khi đóng.

Phút công người chỉ cộng khi trang scene đang mở, tab hiển thị và có pointer/keyboard/wheel trong 60 s gần nhất.
Dữ liệu gửi theo lô tối đa 300 s, phân surface studio/progress/evaluation/other và trước/sau ready.
Không cần bấm đồng hồ ngoài, nhưng công việc thực địa và công việc ở ứng dụng khác không được tính.

## Xem và xuất bảng

- Một scene: mở tab đánh giá, thẻ **Giá trị**; tải CSV hoặc Markdown. “Mở Benchmark” đưa về tab Studio.
- Nhiều scene: trang `/benchmark`, chỉ lấy job mới nhất mỗi project có cờ `include_in_benchmark`.
  Có bảng tổng hợp, trung vị và cỡ mẫu; không so trung vị khi thiếu dữ liệu mà không nêu cỡ mẫu.
- CSV UTF-8 có BOM; ô chưa có dữ liệu để trống. Markdown giữ nhãn nguồn đo/khai báo.
- API đã đăng nhập: `GET /api/v1/jobs/{job_id}/value-metrics` (JSON), thêm `.csv` hoặc `.md` để tải một scene.
  Bộ benchmark: `GET /api/v1/value-metrics/benchmark`, thêm `.csv` hoặc `.md` để tải bảng tổng.
- Sau sửa ground truth, Walk hoặc revision, tải lại thẻ/trang để lấy số mới trước khi xuất.

## Giới hạn đã biết

- Nhánh PostgreSQL của ground truth (T-030) mới có test SQLite, chưa chạy trên PostgreSQL thật.
- Đồng hồ máy khách lệch quá 60 s so với máy chủ thì mọi lô thời gian thao tác bị 422 và bỏ im lặng → phút công “chưa đo được”.
- Link tải CSV/Markdown dùng `<a download>`: phiên hết hạn thì file tải về là JSON lỗi; đăng nhập lại rồi tải lại.
- “Mở Benchmark” ở thẻ Giá trị chỉ mở tab Studio; người dùng bấm nút “Benchmark” ở góc viewer.
- L4 là khai báo của người nhập, không phải kết quả máy tự xác thực thử robot ngoài đời.
- Phút công người chỉ đo trong trang scene; không bao gồm quay phim, đo thước, ứng dụng khác hoặc tab ẩn/quá 60 s không hoạt động.
- Chi phí dùng đơn giá khai báo, không bao gồm mọi khoản hạ tầng. Thiếu snapshot máy thì phần cứng có thể không đủ trường.
- Chưa đo hiệu năng tổng hợp trên DB lớn; bảng nhiều scene có thể đọc usage lặp lại.
- Test hình học/fixture và jsdom không chứng minh độ đúng của collision trên scene thật hoặc UI WebGL. Chủ dự án kiểm UI bằng mắt.

## “Sản phẩm cần thêm gì” — danh sách đã có để Architect cập nhật Playbook

Danh sách ánh xạ theo architecture §15 và các task accepted; Architect cập nhật trang Playbook bên ngoài.
“Đã có” ở đây là triển khai trong repo, không phải kết quả benchmark thực địa.

| Đã có | Task / vị trí |
| --- | --- |
| Nhật ký chỉnh sửa, yêu cầu scene, phiên Walk và thời gian thao tác | T-027, T-029; `value/events.py`, `useOperatorTime`, `useWalkSession` |
| Đo tài nguyên mọi mode hàng đợi tách vật để phút máy đủ | T-028; `objectify_queue.py`, ResourceUsage |
| Ground truth phiên bản/CAS: robot, đoạn, khe, vật cản, layout, mốc làm tay, L4 | T-030; `value/ground_truth.py`, API benchmark-truth |
| Đo khe trên collision tổng hợp, sai số đoạn, kiểm nhất quán sau dời | T-031; `value/measure.py` |
| Bảng 5 metric, nguồn từng số, L1–L4, phần cứng và đơn giá | T-032; `value/scorecard.py` |
| Panel nhập ground truth/chọn điểm trong Studio | T-033; `BenchmarkPanel.tsx` |
| Thẻ Giá trị, bảng nhiều scene, xuất CSV/Markdown/JSON | T-034; `ValueCard.tsx`, trang `/benchmark`, API value-metrics |
| Ẩn lớp phủ khi chọn điểm; nhãn vật đã xoá; tổng khe chưa đo hiện “—” | T-035 |
