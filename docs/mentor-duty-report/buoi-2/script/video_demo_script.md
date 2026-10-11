# Kịch bản Video Demo Real2Sim Studio (End-to-End User Flow)

### Thông tin chung
- **Thời lượng mục tiêu:** ~3 phút
- **Định dạng:** Quay màn hình UI phần mềm + Lồng tiếng (Voiceover)
- **Tốc độ thao tác:** Vừa phải, có điểm dừng (pause) ngắn ở những màn hình hoặc tính năng quan trọng để người xem kịp quan sát.

---

## Kịch bản chi tiết

### Cảnh 1: Đăng nhập & Tổng quan Workspace (0:00 - 0:30)
- **Thao tác trên màn hình (Hành động quay):**
  1. Mở trang đăng nhập, nhập Email và Password, sau đó click nút **"Sign In"**.
  2. Màn hình chuyển vào giao diện Dashboard chính.
  3. Rê chuột lướt qua menu điều hướng (Sidebar).
  4. Click vào tab **"Scenes"** để hiển thị danh sách các Scene dạng Grid/List, cuộn nhẹ để xem các dự án gần đây.
  5. Click vào tab **"Jobs"** để lướt qua danh sách các tác vụ đang chạy hoặc đã hoàn thành.
- **Voiceover (Lời thuyết minh):**
  > "Chào mừng bạn đến với Real2Sim Studio. Để bắt đầu, chúng ta tiến hành đăng nhập vào hệ thống an toàn. Ngay khi đăng nhập, màn hình Dashboard sẽ hiển thị tổng quan không gian làm việc của bạn. Tại đây, bạn có thể dễ dàng quản lý toàn bộ các dự án trong mục 'Scenes', cũng như theo dõi tiến độ của các tác vụ ngầm ở mục 'Jobs'."

### Cảnh 2: Khởi tạo Scene mới & Upload Dữ liệu (0:30 - 1:00)
- **Thao tác trên màn hình (Hành động quay):**
  1. Click vào nút nổi bật **"New Scene"** ở góc trên bên phải.
  2. Chọn luồng (flow): **"Video to 3D"** (hoặc Import Video).
  3. Màn hình Upload hiện ra, kéo thả một file video vào vùng Dropzone (hoặc click để chọn file).
  4. Chờ thanh trạng thái upload chạy xong (có thể tua nhanh nếu cần).
  5. Điền tên cho Scene (ví dụ: "Robot Arm Workspace") và nhấn **"Continue"**.
- **Voiceover (Lời thuyết minh):**
  > "Để số hóa một môi trường thực tế, chúng ta sẽ tạo một Scene mới. Bạn chỉ cần chọn tùy chọn biến Video thành 3D, kéo thả đoạn video quay môi trường của bạn vào hệ thống. Sau khi video tải lên hoàn tất, chúng ta đặt tên cho dự án và chuyển sang bước tiếp theo."

### Cảnh 3: Cài đặt thông số & Theo dõi tiến trình (1:00 - 1:30)
- **Thao tác trên màn hình (Hành động quay):**
  1. Giao diện **Processing Settings** hiện ra. Bật/tắt một số tùy chọn như *High Quality Gaussian* hoặc *Auto-segmentation*.
  2. Nhấn nút **"Start Processing"**.
  3. Màn hình chuyển sang tab **Pipeline Timeline** hiển thị quá trình xử lý: Trích xuất khung hình -> Colmap -> Training 3DGS.
  4. (Dùng hiệu ứng tua nhanh thời gian ở khúc này) đến khi các thanh trạng thái chuyển sang màu xanh (Done/PASS).
- **Voiceover (Lời thuyết minh):**
  > "Trước khi bắt đầu huấn luyện, bạn có thể tùy chỉnh các thông số xử lý và độ chi tiết của mô hình. Ngay sau khi bấm chạy, hệ thống Pipeline sẽ tự động thực hiện các bước từ trích xuất khung hình, định vị Camera đến huấn luyện Gaussian Splatting. Mọi tiến trình đều được cập nhật theo thời gian thực."

### Cảnh 4: Trình chỉnh sửa 3D (Object-centric Editor) (1:30 - 2:20)
- **Thao tác trên màn hình (Hành động quay):**
  1. Khi quá trình hoàn tất, click mở **Scene Editor** (tab Canvas/Viewer).
  2. Tương tác với cảnh 3D: Dùng chuột xoay vòng (Orbit), cuộn chuột thu phóng (Zoom), và di chuyển (Pan) để xem toàn cảnh 3DGS đã render.
  3. Click vào một vật thể cụ thể trong không gian (ví dụ: một cái bàn hoặc cánh tay robot). Công cụ **Gizmo** (các trục XYZ) xuất hiện.
  4. Dùng Gizmo để kéo thả (Translate), xoay (Rotate) vật thể đi một chút.
  5. Mở panel Layers/Objects bên phải, thử tắt (ẩn) một đối tượng như "Mặt sàn" hoặc "Nền", sau đó bật lại.
- **Voiceover (Lời thuyết minh):**
  > "Kết quả trả về là một môi trường 3D vô cùng chân thực ngay trên trình duyệt. Bạn có thể dễ dàng xoay, thu phóng để quan sát không gian. Điểm đặc biệt của Real2Sim Studio là khả năng chỉnh sửa dựa trên vật thể (Object-centric). Khi chọn một vật, bạn có thể dùng trục Gizmo để di chuyển, xoay hướng, hay thậm chí bật/tắt các lớp vật thể để làm sạch môi trường trước khi đưa vào mô phỏng."

### Cảnh 5: Validation & Xuất file (Export) (2:20 - 3:00)
- **Thao tác trên màn hình (Hành động quay):**
  1. Chuyển sang tab **Results/Release**.
  2. Click nút **"Run Preflight Check"**. Màn hình hiện check-list chạy qua 6 bước (Ví dụ: Scale, Bounding Box, Physics...). Tất cả báo trạng thái xanh (PASS 6/6).
  3. Thông báo "Ready to Export" hiện ra.
  4. Click nút **"Export to USD"** (hoặc Download ZIP).
  5. Hiện Toast thông báo thành công (Success toast) trên góc màn hình và file bắt đầu tải xuống trình duyệt.
- **Voiceover (Lời thuyết minh):**
  > "Sau khi đã ưng ý với cảnh 3D, bước cuối cùng là chuẩn bị dữ liệu xuất ra. Hệ thống cung cấp bộ công cụ Preflight Check để đảm bảo mô hình đáp ứng đủ 100% tiêu chuẩn vật lý và tỷ lệ chuẩn. Khi tất cả các bài kiểm tra đều vượt qua, chỉ với một cú click chuột, môi trường của bạn đã được đóng gói dưới định dạng USD sẵn sàng tích hợp thẳng vào Isaac Sim hoặc các nền tảng mô phỏng khác."

---

### Mẹo nhỏ khi quay màn hình:
- Bạn nên **ẩn các thanh dấu trang (bookmark)** và dọn dẹp các tab không liên quan trên trình duyệt để video trông chuyên nghiệp.
- Nếu thời gian chờ training/processing quá lâu (ở Cảnh 3), bạn hãy quay nguyên bản, sau đó lúc dựng video dùng hiệu ứng "Tua nhanh" (Speed up x10, x20) và thêm text dạng *"Processing... (Speed up)"* trên màn hình.
- Chú ý quay rõ các thông báo **Toast Notification** (VD: "Saved successfully", "Export started") vì nó nằm trong thiết kế UX trọng tâm của hệ thống.
