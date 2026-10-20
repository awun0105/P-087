# Vấn đề còn tồn đọng — 2026-10-20

Ghi lại sau đợt đưa Sprint 8 lên production và chạy thử bằng video/bộ ảnh thật (IMG_4476, cup, chinsu, flower,
apartment). Mỗi mục gồm: hiện trạng, vì sao quan trọng, hướng xử lý đề xuất, cần build lại image GPU hay không.

Ký hiệu: **[GPU]** = sửa phải build và chứng nhận lại image GPU (khoảng 30–40 phút); **[API]** = chỉ máy chủ API;
**[Web]** = chỉ web Studio; **[Hạ tầng]** = cấu hình/máy, không đổi mã.

## A. Đang chờ anh quyết định

| # | Việc | Ghi chú |
|---|---|---|
| A1 | Gộp một lần build image: (1) bỏ dừng-vì-quá-lâu, chỉ cảnh báo (mục C1); (2) tăng tốc kiểm tra video (C5); (3) báo rõ khi tách vật thất bại (C3) | Khoảng 2–3 giờ tổng cộng. Đang chờ duyệt. |
| A2 | Có giới hạn Khách chỉ xem scene của mình không (B6) | Khoảng nửa ngày. |
| A3 | Job apartment `job-390939c7a6d9`: để chạy tiếp hay huỷ và tạo lại với 1 khung/giây, mức "Cân bằng" | Đang chạy lượt 2. |

## B. Hạ tầng và vận hành

| # | Vấn đề | Hướng xử lý | Loại |
|---|---|---|---|
| B1 | Máy chủ API 4 GB bị hết bộ nhớ (đã sập 1 lần lúc 10:00 UTC) khi có người mở "Chỉnh vùng" trên cảnh lớn: `fit_region` nạp file 3D 472 MB của drjohnson, mỗi lần khoảng 1,5 GB. | **Anh đã duyệt** nâng `real2sim-api-seoul` từ e2-medium (4 GB) lên e2-standard-2 (8 GB). Chưa làm, chờ lúc tiện (máy chủ ngừng khoảng 2 phút). Lâu dài: chỉ nạp toạ độ thay vì cả file, và giới hạn số lần nạp chạy cùng lúc. | Hạ tầng (+API) |
| B2 | Mã đăng nhập Vercel (`VERCEL_TOKEN` trên awun0105/P-087) hết hạn, web không tự triển khai được. | Anh tạo mã mới ở vercel.com/account/tokens rồi `gh secret set VERCEL_TOKEN -R awun0105/P-087`. Trong lúc chờ: chạy tay `vercel deploy --prod --yes` trong `frontend/`. | Hạ tầng |
| B3 | RunPod hay hết máy A5000 trong mức giá ≤ 0,55 USD/giờ. Sau 3 lần không thuê được, bộ điều khiển tự dừng thuê (`drain`) và **không tự mở lại**; phải chạy `runpod_controller resume`. | Cho bộ điều khiển tự thử lại sau một khoảng chờ; cân nhắc thêm loại GPU dự phòng (phải chứng nhận riêng). | API |
| B4 | Khi RunPod trả lời không rõ ràng lúc tạo máy, bộ điều khiển kẹt ở trạng thái `unknown` mãi; phải chạy tay `runpod_controller forget-unknown`. | Tự gỡ sau vài phút nếu RunPod không có máy nào mang đúng tên của lần thuê đó (lệnh `forget-unknown` đã kiểm đúng điều kiện này). | API |
| B5 | Danh mục image GPU chỉ được đọc khi máy chủ API khởi động; cài danh mục mới mà không khởi động lại thì vẫn thuê image cũ. | Đọc lại danh mục khi file thay đổi, hoặc ghi rõ vào quy trình triển khai. | API |
| B6 | Khách xem được **mọi** scene (của nhóm và khách khác), chỉ không sửa được. Rủi ro riêng tư nếu scene là nhà riêng. | Lọc theo người tạo ở danh sách scene và ở mọi đường xem chi tiết (bản 3D, khung hình, video); giữ scene mẫu công khai. | API (+Web) |
| B7 | Đã mở đăng ký Khách và nút "Dùng thử ngay". Một người có thể tạo nhiều tài khoản (đổi trình duyệt hoặc dùng cửa sổ ẩn danh) để lấy thêm lượt GPU. Chặn cuối hiện chỉ là ngân sách GPU tổng 5 USD. | Giới hạn số tài khoản Khách mới mỗi ngày theo địa chỉ IP. | API |
| B8 | Tài khoản Khách thử `guest-ae44d13fd49d@try.real2sim.dev` tạo lúc kiểm tra nút "Dùng thử ngay". | Khoá hoặc giữ làm mẫu (trang Nhóm). | — |

## C. Pipeline và máy GPU

| # | Vấn đề | Bằng chứng | Hướng xử lý | Loại |
|---|---|---|---|---|
| C1 | **Bộ canh "chạy quá lâu" dừng nhầm job đang chạy tốt.** Thời gian dự kiến của bước xem trước (COLMAP + Brush) chỉ ước theo số vòng học của Brush, không tính số khung và kiểu ghép ảnh (ghép mọi cặp tăng theo bình phương số khung). Quá 3 lần ước lượng là dừng. | apartment: COLMAP 66 phút, Brush đang chạy 28 phút thì bị dừng "quá 94 phút" (15:49 UTC). | Không dừng vì quá lâu nữa, chỉ ghi cảnh báo để người dùng tự quyết. Chỉ dừng khi thật sự đứng yên (bộ canh treo 10 phút đã có). Giữ giới hạn cứng cuối cùng. Về sau: ước riêng COLMAP (theo số cặp ảnh) và Brush. | GPU + Web |
| C2 | **Chạy lại mất tiến độ Brush.** COLMAP được dùng lại (10 giây) nhưng Brush học lại từ đầu. | apartment lượt 2. | Brush lưu điểm dừng định kỳ lên kho lưu trữ, lượt sau học tiếp. | GPU |
| C3 | **Tách vật thể thất bại mà không báo.** Job báo "thành công" nhưng bước Tách vật thể nằm ở trạng thái chờ mãi; lý do chỉ có trong nhật ký máy GPU. | cup và chinsu: "mặt sàn chưa đủ tin cậy: độ nhiễu 5,18 cm vượt ngưỡng 3 cm" (`runner._extract_scene_stage` bắt mọi lỗi rồi trả `[]`). | Ghi bước Tách vật thể là THẤT BẠI kèm lý do và gợi ý (chụp thêm ảnh, đo tỉ lệ tay, chọn lại sàn); job vẫn coi phần dựng 3D là xong. | GPU + Web |
| C4 | Kiểm tra sàn quá chặt với cảnh vật đặt trên bàn: dựng 3D ít ảnh thì mặt bàn nhiễu hơn 3 cm, nên không tách được vật. | cup, chinsu. | Xem lại ngưỡng theo tỉ lệ cảnh, hoặc cho người dùng chọn mặt phẳng. | GPU |
| C5 | **Kiểm tra video chậm.** Lượt đo độ nét (blurdetect, 1 luồng) chiếm phần lớn: video 4 phút 39 giây 720p mất khoảng 114 giây trên máy anh, ước 4–5 phút trên máy GPU (sau khi đã cho 4 lượt chạy song song; trước đó 21 phút). | Đo ngày 2026-10-20; CPU máy GPU thật khoảng 7,6 nhân, chạy song song tốt. | Cho bộ giải mã dùng nhiều luồng (kết quả độ nét giống hệt, đã kiểm). Chia lượt đo độ nét thành nhiều đoạn chạy song song (mỗi khung đo độc lập). Đích: 1–2 phút. | GPU |
| C6 | **Xếp lịch GPU mức 1:** cấu hình chưa từng đo phải chạy một mình trên GPU, nên 3 worker phần lớn đứng chờ. | cup chờ dù GPU trống 18,8 GB và cup chỉ cần 4,2 GB. | Bản sửa (cho chạy chung khi ước lượng ≤ 50% VRAM trống, trừ job từng hết bộ nhớ) đã viết và kiểm thử, **chưa đưa lên**: `.e2e-upload/unmeasured-share.patch`. Anh dặn gộp vào task mức 2. | GPU |
| C7 | **Xếp lịch GPU mức 2:** một job giữ chỗ GPU suốt cả lượt, kể cả lúc chỉ dùng CPU (kiểm tra video, tách khung). | — | Xếp lịch theo từng bước, mỗi bước khai CPU/GPU, chỉ giữ GPU lúc bước GPU chạy. **Anh sẽ soạn task** (phiên kia đã có ghi chép T-072/T-073). | GPU |
| C8 | Web không cảnh báo khi bộ thông số sẽ rất chậm (ví dụ ghép mọi cặp với hàng trăm khung); ước thời gian không tính kiểu ghép ảnh. | apartment: 528 khung × ghép mọi cặp (khoảng 139 nghìn cặp). | Cảnh báo ở trang tạo scene trước khi bấm tạo. | Web (+API) |
| C9 | COLMAP ghép kém video đi bộ khó (góc rộng, tường trắng, rẽ gấp); chưa có cách tự thử lại với thông số khác. | IMG_4476: 119/598 khung (20%). | Thang thử lại (khép vòng, đổi kiểu ống kính, tăng ảnh lân cận); phiên kia đã có ghi chép T-071. | GPU |
| C10 | Bước LOD mới (Sprint 8) chưa kiểm hết danh sách của phiên kia: có bước ST-VIEW-LOD, file `lod-meta.json` trên kho cho cảnh lớn hơn 600 nghìn điểm, đường dẫn LOD trả 200/307, bảng `r2s_step_marks` có mốc. | cup: "Bước LOD đã tạo 0 bộ" (cảnh nhỏ, đúng dự kiến). drjohnson chờ bộ dựng LOD chạy ngầm. | Kiểm trên một job cảnh lớn. | — |
| C11 | Rủi ro phiên kia nêu: bước xem trước/hoàn tất chạy trên máy GPU khác sau khi máy đổi (dữ liệu dự án có thể chưa được kéo về). | Chưa gặp. | Theo dõi khi đổi máy giữa chừng. | — |

## D. Đầu vào và hướng dẫn người dùng

| # | Vấn đề | Hướng xử lý | Loại |
|---|---|---|---|
| D1 | Chưa nhận ảnh rời (JPG/PNG/HEIC); hiện phải ghép ảnh thành video. **Anh cho tạm gác.** | Khoảng nửa ngày đến 1 ngày, gồm đổi HEIC sang JPG ở máy chủ. | GPU + API + Web |
| D2 | Trình duyệt nén lại video theo dung lượng mỗi giây, nên video ít khung/giây bị bóp chất lượng mỗi khung (ảnh ghép thành video 2 khung/giây chỉ còn khoảng 33 KB/khung). | Tính dung lượng theo số khung thay vì theo giây khi video có ít khung/giây. | Web |
| D3 | Nút "Hướng dẫn quay/chụp" thiếu các điều quan trọng: dùng camera 1x (không 0,5x), tắt video HDR, khoá phơi sáng (AE/AF Lock), quay ngang 16:9, đi chậm, khép vòng; với một vật: nền có hoa văn, 100–150 ảnh, 2–3 vòng độ cao. | Cập nhật nội dung hướng dẫn. | Web |

## E. Kiểm thử và mã

| # | Vấn đề | Ghi chú |
|---|---|---|
| E1 | 15 bài kiểm thử phía máy chủ lỗi từ trước: role_matrix (demo-sessions), 7 sample_routes, 2 test_install_scripts, 2 objectgs, runtime_migrations v11/v12, deploy_env example. | Không do đợt này gây ra; nên dọn để kết quả kiểm thử có ý nghĩa. |
| E2 | 1 bài kiểm thử web lúc qua lúc hỏng (1 lần trong 3 lần chạy toàn bộ). | Chưa xác định bài nào. |
| E3 | Image GPU có Isaac Sim 5.1. | **Đã hoãn** theo quyết định của anh. |

## F. Đã xử lý trong ngày (để đối chiếu)

- Bộ điều khiển ghi cứng 1 worker mỗi máy GPU → dùng số trong `worker.env` (A5000: 3 worker).
- Mức xử lý luôn rơi về tối thiểu 300 khung khi chưa có máy GPU chạy → dùng số đo của máy thuê gần nhất.
- Lỗi COLMAP bị nuốt thành câu chung → giữ mã lỗi, lời nhắn, trích nhật ký.
- 4 lượt đọc video ở bước kiểm tra chạy song song.
- Web build lỗi do Turbopack không đọc được `in` trong giá trị mặc định của tham số.
- Nút "Dùng thử ngay" (mỗi trình duyệt một tài khoản Khách); trang Nhóm ghi đúng hạn mức Khách 3 lượt/ngày.
- Bật che mặt/biển số (EgoBlur) trên production.
