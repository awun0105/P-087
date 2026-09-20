Dưới đây là **toàn bộ thông tin RAV-01 được trích từ file đề tài**, không bổ sung kiến thức bên ngoài.

## RAV-01

**Khối:** Robot & xe tự hành (Vinfast)
**Mã đề:** `RAV-01`
**STT trong file:** 337
**Max team / đề tài:** 2 team

### Tên đề tài

**Real2Sim Studio - Công cụ dựng lại cảnh đường/kho từ video & LiDAR thành scene mô phỏng chỉnh sửa được**

### Thực trạng

Kỹ sư AV/robotics cần rất nhiều cảnh mô phỏng đa dạng để huấn luyện và kiểm thử policy, nhưng dựng scene 3D thủ công trong CARLA/Isaac rất tốn công.

Trong khi đó, dữ liệu thật đã quay được lại không dễ chỉnh sửa, ví dụ:

* không thêm được người đi bộ;
* không thêm được xe cắt ngang;
* không dễ thay đổi thời tiết;
* không thể trực tiếp biến cảnh thật thành các biến thể phục vụ simulation.

### Vấn đề cần giải quyết

Xây dựng một công cụ **Real2Sim** có khả năng:

* nhận **video RGB** và/hoặc **point cloud LiDAR**;
* tái tạo một đoạn đường hoặc một góc kho thành **scene mô phỏng 3D**;
* sử dụng **3D Gaussian Splatting hoặc NeRF** để reconstruction;
* cho phép kỹ sư:

  * chèn vật thể;
  * xóa vật thể;
  * di chuyển vật thể;
  * thêm agent/chướng ngại;
  * thay đổi ánh sáng;
  * thay đổi thời tiết;
* sau đó export scene sang định dạng có thể tái sử dụng trong môi trường mô phỏng.



---

## Ràng buộc

Đề yêu cầu các boundary sau:

**Human-in-the-loop**

* Kỹ sư phải review và duyệt scene được tái tạo trước khi scene được đưa vào tập huấn luyện.

**An toàn**

* Mọi thử nghiệm policy chỉ được thực hiện trong mô phỏng.
* Không được điều khiển trực tiếp xe/robot thật.

**Đánh giá chất lượng reconstruction**
Phải đo được:

* **PSNR**
* **SSIM**
* **LPIPS**
* **Chamfer Distance** để đánh giá độ khớp hình học so với ground truth.

**Hiệu năng**

* Cần tối ưu thời gian huấn luyện Gaussian Splatting.
* Cần tối ưu độ trễ rendering.
* Mục tiêu là scene có thể được render tương tác trên **1 GPU**.

**Dữ liệu và privacy**

* Dữ liệu thu thập phải được ẩn danh:

  * biển số xe;
  * khuôn mặt.



---

# Tech stack được đề xuất trong file

### AI / 3D reconstruction

* **Python**
* **PyTorch**
* **3D Gaussian Splatting**

  * `nerfstudio`
  * `gsplat`
* **NeRF**

### Point cloud

* **Open3D**
* **PCL**

### Dataset

File đề xuất:

* **nuScenes**
* **KITTI**
* **Waymo Open**

### Simulation

* **CARLA**
* **Isaac Sim**

Dùng để:

* export scene;
* chạy simulation.

### Computer Vision

* **SAM2**

Mục đích được đề nêu:

* tách vật thể.

### Backend

* **FastAPI**

### Frontend / 3D visualization

* **React / Next.js**
* **three.js / WebGL**

Dùng để:

* trực quan scene 3D;
* chỉnh sửa scene.

### Data / experiment versioning

* **DVC**
* **MLflow**

Dùng để:

* quản lý phiên bản scene.

### Deployment / compute

* **Docker**
* **GPU**



---

# Yêu cầu đầu ra cơ bản

Phiên bản **Cơ bản** phải có:

1. **Web app**.
2. Dựng lại được **1 scene mẫu từ dữ liệu công khai**.
3. Có **3D viewer trên trình duyệt**.
4. Cho phép:

   * xoay scene;
   * zoom;
   * bật/tắt vật thể.
5. Có ít nhất **2 vai trò**:

   * người dựng scene;
   * kỹ sư duyệt.
6. Báo cáo các metric:

   * **PSNR**
   * **SSIM**
   * **Chamfer Distance**
7. Có **Human-in-the-loop**:

   * kỹ sư phải duyệt scene;
   * scene chỉ được lưu sau khi được duyệt.



---

# Yêu cầu đầu ra nâng cao

Phiên bản **Nâng cao** cần hướng tới pipeline khép kín:

```text
Video / LiDAR
      ↓
3D scene reconstruction
      ↓
Editable scene
      ↓
Dynamic agent insertion
      ↓
Weather modification
      ↓
Export CARLA / Isaac
      ↓
Closed-loop simulation
```

Cụ thể:

* pipeline tự động từ video/LiDAR đến scene chỉnh sửa được;
* chèn **agent động**;
* thay đổi **thời tiết**;
* tự động export sang **CARLA hoặc Isaac**;
* chạy **closed-loop simulation**;
* benchmark chất lượng reconstruction trên **nhiều scene**;
* tối ưu:

  * tốc độ render;
  * thời gian training.



---

## Tóm tắt nguyên bản của RAV-01

Có thể cô đọng toàn bộ đề thành:

> **Input:** video RGB và/hoặc LiDAR của môi trường thật.
> **Core:** dùng NeRF/3D Gaussian Splatting dựng lại scene 3D.
> **Product:** web app cho kỹ sư xem, chỉnh sửa và duyệt scene.
> **Output nâng cao:** scene có thể export sang CARLA/Isaac để chạy simulation.
> **Evaluation:** PSNR, SSIM, LPIPS, Chamfer Distance, render/train performance.
> **Human role:** kỹ sư luôn review và approve trước khi dùng scene cho training/testing.

Đó là toàn bộ nội dung RAV-01 mà file đề tài cung cấp; file không nêu thêm kiến trúc agent cụ thể, cách triển khai từng tuần, acceptance threshold cụ thể cho các metric, hay dataset subset nào bắt buộc phải dùng.
