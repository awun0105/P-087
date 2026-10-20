# Vấn đề lớn còn tồn đọng — 2026-10-20

**[GPU]** = cần build và chứng nhận lại image GPU · **[API]** = máy chủ API · **[Web]** = web Studio · **[Hạ tầng]** = cấu hình/máy.

## 1. Máy chủ API hết bộ nhớ khi mở cảnh lớn — [Hạ tầng] [API]
Máy 4 GB sập khi "Chỉnh vùng" trên drjohnson: mỗi lần nạp cả file 3D 472 MB, tốn khoảng 1,5 GB.
**Giải quyết:** nâng `real2sim-api-seoul` lên e2-standard-2 (8 GB), đã được duyệt. Chỉ nạp toạ độ thay vì cả file; giới hạn số lần nạp cảnh lớn chạy cùng lúc.

## 2. Job đang chạy tốt bị dừng vì "quá lâu" — [GPU] [Web]
Hạn thời gian của bước xem trước chỉ ước theo số vòng học Brush, bỏ qua số khung và kiểu ghép ảnh của COLMAP. Quá 3 lần ước lượng là dừng (apartment: dừng ở phút 94 khi Brush đang chạy bình thường).
**Giải quyết:** không dừng vì quá lâu, chỉ hiện cảnh báo kèm lý do để người dùng tự huỷ. Chỉ dừng khi thật sự đứng yên (bộ canh treo 10 phút đã có), giữ giới hạn cứng cuối cùng. Ước riêng COLMAP (theo số cặp ảnh) và Brush.

## 3. Chạy lại thì Brush học lại từ đầu — [GPU]
**Giải quyết:** Brush lưu điểm dừng định kỳ lên kho lưu trữ; lượt sau học tiếp từ điểm dừng gần nhất.

## 4. Tách vật thể thất bại mà không báo — [GPU] [Web]
Job báo thành công, bước Tách vật thể nằm ở trạng thái chờ mãi; lý do chỉ có trong nhật ký máy GPU (cup, chinsu: "mặt sàn nhiễu 5,18 cm vượt ngưỡng 3 cm").
**Giải quyết:** ghi bước là THẤT BẠI kèm lý do và cách sửa (chụp thêm, đo tỉ lệ tay, chọn mặt phẳng). Xem lại ngưỡng sàn cho cảnh vật đặt trên bàn.

## 5. 3 worker trên một máy GPU gần như không chạy song song — [GPU]
- Cấu hình chưa từng đo bị bắt chạy một mình trên GPU; chỉnh bất kỳ thông số nào cũng thành cấu hình mới.
- Job giữ chỗ GPU suốt cả lượt, kể cả các bước chỉ dùng CPU.

**Giải quyết:** xếp lịch theo từng bước (mỗi bước khai CPU hay GPU, chỉ giữ GPU lúc bước GPU chạy). Cho chạy chung GPU khi ước lượng không quá 50% bộ nhớ GPU trống; bản sửa phần này có sẵn ở `.e2e-upload/unmeasured-share.patch`. Gộp vào task mức 2.

## 6. Bước kiểm tra video chậm — [GPU]
Lượt đo độ nét chạy 1 luồng chiếm phần lớn: khoảng 4–5 phút trên máy GPU cho video 5 phút.
**Giải quyết:** giải mã video nhiều luồng (kết quả không đổi, đã kiểm). Chia lượt đo độ nét thành nhiều đoạn chạy song song. Đích: 1–2 phút.

## 7. Thông số chậm hoặc COLMAP ghép kém mà không có cảnh báo hay cách tự sửa — [Web] [GPU]
- Ghép mọi cặp với hàng trăm khung chạy hàng giờ mà không có cảnh báo.
- Video đi bộ khó chỉ ghép được 20% khung (IMG_4476).

**Giải quyết:** cảnh báo ở trang tạo scene khi bộ thông số sẽ rất chậm; ước thời gian tính cả kiểu ghép ảnh. Thêm thang tự thử lại cho COLMAP: khép vòng, đổi kiểu ống kính, tăng số ảnh lân cận.

## 8. Quyền và lạm dụng tài khoản Khách — [API] [Web]
- Khách xem được mọi scene của nhóm và của khách khác.
- Đổi trình duyệt là tạo được tài khoản mới để lấy thêm lượt GPU.

**Giải quyết:** lọc theo người tạo ở danh sách scene và mọi đường xem chi tiết (giữ scene mẫu công khai). Giới hạn số tài khoản Khách mới mỗi ngày theo địa chỉ IP.

## 9. Thuê GPU còn phải xử lý bằng tay — [API]
- RunPod hết máy A5000: sau 3 lần, bộ điều khiển ngừng thuê và không tự mở lại.
- RunPod trả lời không rõ ràng: bộ điều khiển kẹt ở trạng thái `unknown`.
- Danh mục image mới chỉ được đọc khi máy chủ API khởi động lại.

**Giải quyết:** tự thử lại sau một khoảng chờ tăng dần. Tự gỡ trạng thái kẹt khi RunPod không có máy nào mang tên của lần thuê đó. Đọc lại danh mục khi file thay đổi. Cân nhắc thêm loại GPU dự phòng đã chứng nhận.

## 10. Web không tự triển khai — [Hạ tầng]
Mã `VERCEL_TOKEN` trên awun0105/P-087 hết hạn.
**Giải quyết:** tạo mã mới ở vercel.com/account/tokens, rồi chạy `gh secret set VERCEL_TOKEN -R awun0105/P-087`.

## 11. Đầu vào ảnh và chất lượng quay chụp — [GPU] [API] [Web]
- Chưa nhận ảnh rời (JPG/PNG/HEIC).
- Trình duyệt nén mạnh video có ít khung/giây.
- Phần hướng dẫn quay chụp thiếu các điểm quyết định chất lượng.

**Giải quyết:** thêm luồng tập ảnh rời, đổi HEIC sang JPG ở máy chủ (đang tạm gác). Tính dung lượng nén theo số khung thay vì theo giây. Bổ sung hướng dẫn: camera 1x, tắt HDR, khoá phơi sáng, quay ngang 16:9, đi chậm, quay về điểm đầu; với một vật: nền có hoa văn, 100–150 ảnh, 2–3 vòng ở các độ cao.
