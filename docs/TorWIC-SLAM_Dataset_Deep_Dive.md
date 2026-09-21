# Dataset Deep Dive: TorWIC-SLAM cho Real2Sim Studio

**🔗 Liên kết nhanh:**
- **Repository chính thức (GitHub):** [https://github.com/Viky397/TorWICDataset](https://github.com/Viky397/TorWICDataset)
- **Link tải Dataset (Google Drive):** [https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ](https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ)

> **Mục đích tài liệu:** Ghi chú kỹ thuật để cả team hiểu TorWIC-SLAM là gì, dataset gồm những gì, và quan trọng nhất là **nó phù hợp tới đâu với sản phẩm Real2Sim Studio mà team thực sự sẽ xây**, cần tải bao nhiêu, cần tổ chức lại dữ liệu như thế nào, preprocessing những gì, và từng file/modality sẽ được sử dụng ở stage nào của pipeline cho development, demo, validation và benchmarking.
>
> **Project context:** RAV-01 — Real2Sim Studio  
> **MVP domain:** Warehouse / Indoor AMR  
> **Simulator:** NVIDIA Isaac Sim  
> **Dataset chính được đề xuất:** **TorWIC-SLAM — Toronto Warehouse Incremental Change SLAM Dataset**

---

## Bảng thuật ngữ (Glossary)

- **Traversal (Lượt chạy / Chuyến đi):** Là một "lượt" robot chạy quanh nhà kho để thu thập dữ liệu. Toàn bộ dữ liệu của một lượt chạy (gồm ảnh RGB, điểm LiDAR, file tọa độ...) được nhóm chung vào một thư mục con nằm trong thư mục gốc của dataset (ví dụ: thư mục `Scenario 1 Traversal 1`).
- **Trajectory (Quỹ đạo):** Là đường nét hình học ghi lại toàn bộ lộ trình di chuyển của robot. Cụ thể, nó là một tập hợp các tọa độ không gian (x, y, z) cho biết trong lượt chạy đó, cụm cảm biến đã di chuyển như thế nào. Dữ liệu quỹ đạo này được lưu trữ trong file văn bản `traj_gt.txt` nằm bên trong thư mục của mỗi Traversal.
- **Pipeline:** Chuỗi các bước xử lý liên tiếp nhau trong hệ thống phần mềm, đầu ra của bước trước là đầu vào của bước sau.
- **Preprocessing (Tiền xử lý):** Quá trình "nấu sơ" dữ liệu trước khi đưa vào luồng chính. Ví dụ: Trong TorWIC, các file điểm LiDAR thô (pcd) được gộp lại thành một cụm mây điểm duy nhất (registered_lidar.ply) trước khi đưa vào Real2Sim.
- **Methodology (Phương pháp luận):** Cách thức và quy tắc tiến hành đánh giá để đảm bảo tính khoa học, khách quan. Ví dụ: Phải giấu kín bản đồ Ground truth, không cho phần mềm nhìn thấy trước khi dự đoán, để chống gian lận (data leakage).
- **Benchmark:** Trận đấu chấm điểm hiệu năng. Đánh giá chất lượng của hệ thống phần mềm bằng các thước đo định lượng (con số cụ thể) thay vì nói chung chung "nhìn đẹp" hay "xấu".
- **Ground truth:** Dữ liệu "đáp án" gốc chuẩn xác tuyệt đối dùng để chấm điểm. Ví dụ: Trong TorWIC, bản đồ 3D quét bằng máy trắc địa Leica MS60 chính là "Ground truth hình học", dùng để đối chiếu xem hệ thống của chúng ta dựng lại 3D bị sai số bao nhiêu cm.
- **Reconstruction (Tái tạo):** Quá trình tính toán, dựng lại một môi trường 3D hoàn chỉnh trên máy tính từ các bức ảnh 2D hoặc điểm LiDAR.
- **Modality (Dạng cảm biến/Dữ liệu):** Các loại nguồn cấp dữ liệu khác nhau. Ví dụ trong TorWIC, các Modality bao gồm: Ảnh màu (RGB), Ảnh chiều sâu (Depth), Đám mây điểm (LiDAR 3D), và Dữ liệu gia tốc (IMU).
- **Calibration (Hiệu chuẩn):** Là các thông số toán học giúp máy tính hiểu rõ cấu tạo và vị trí của các "con mắt" trên robot. Gồm 2 loại chính:
  - *Intrinsics (Nội hàm):* Hiểu nôm na là cấu tạo của chính camera đó (tiêu cự bao nhiêu, ống kính bị méo/cong ở rìa như thế nào). Trong dataset này, Azure Kinect được đo intrinsics bằng phần mềm Matlab.
  - *Extrinsics (Ngoại hàm):* Là vị trí tương đối giữa các cảm biến với nhau. Ví dụ: Nó là ma trận con số cho phần mềm biết "Camera RGB nằm cách máy quét LiDAR bao nhiêu cm và bị nghiêng một góc bao nhiêu độ". Nhờ có Extrinsics, máy tính mới có thể chồng chính xác màu của ảnh RGB lên các điểm LiDAR.
- **Collider / Occupancy / Free-space:** Các thuật ngữ về vật lý trong giả lập không gian. Ví dụ: Vùng mặt sàn robot chạy được gọi là vùng trống (Free-space); chỗ nào có bức tường hay kệ hàng cản lại thì gọi là vật cản (Collider / Occupancy).
- **Metric scale:** Tỷ lệ kích thước chuẩn thật. Có nghĩa là 1 đơn vị trong mô hình 3D trên máy tính tương đương đúng 1 mét ở ngoài đời thực, chứ không phải bị co giãn vô lý.

## Điều khoản sử dụng

Dưới đây là tóm tắt các điểm quan trọng nhất trong Điều khoản sử dụng bộ dữ liệu của Clearpath Robotics và Đại học Toronto:

**Giấy phép & Mục đích sử dụng:** Dữ liệu được cấp miễn phí theo giấy phép CC BY-NC 4.0. Điều này có nghĩa là bạn chỉ được phép sử dụng cho mục đích phi thương mại (không dùng để bán hay kiếm tiền) và bắt buộc phải ghi rõ nguồn tác giả.

**Quyền riêng tư (Rất quan trọng):** Tuyệt đối cấm sử dụng dữ liệu để cố tình nhận diện khuôn mặt, danh tính hoặc xâm phạm quyền riêng tư của những người vô tình lọt vào khung hình, kể cả khi việc đó không vi phạm pháp luật sở tại.

**Không mượn danh thương hiệu:** Bạn không được phép sử dụng tên, logo hay nhãn hiệu của Đại học Toronto và Clearpath Robotics để quảng bá cho dự án của mình hoặc ám chỉ rằng họ đang hợp tác/tài trợ cho bạn.

**Miễn trừ trách nhiệm & Bồi thường:** Tác giả cung cấp dữ liệu "như hiện trạng" và có quyền cắt quyền truy cập của bạn bất cứ lúc nào. Nếu việc bạn sử dụng (hoặc lạm dụng) dữ liệu gây ra kiện cáo hay thiệt hại, bạn phải tự chịu trách nhiệm và bồi thường toàn bộ chi phí pháp lý cho tác giả.

**Giải quyết tranh chấp:** Mọi vấn đề pháp lý phát sinh sẽ được giải quyết tại tòa án và tuân theo luật pháp của bang Ontario, Canada.

**Tuân thủ pháp luật:** Bạn phải tự chịu trách nhiệm đảm bảo việc dùng dữ liệu không vi phạm các đạo luật về an ninh, bảo mật hay xuất khẩu của quốc gia bạn.

---

## 1. Tóm tắt nhanh

TorWIC-SLAM là một dataset thực tế được thu trong warehouse/facility của Clearpath Robotics để nghiên cứu SLAM và thay đổi môi trường theo thời gian. Dataset đặc biệt phù hợp với Real2Sim Studio vì có đồng thời:

- RGB từ camera di chuyển;
- 3D LiDAR;
- calibration giữa các sensor;
- trajectory ground truth;
- một 3D ground-truth map độ chính xác centimet;
- nhiều traversal trong cùng warehouse theo thời gian.

Điểm quan trọng nhất đối với project của chúng ta là **có ground truth hình học đủ tốt để benchmark reconstruction thay vì chỉ nhìn bằng mắt xem scene có đẹp hay không**.

Tuy nhiên, team **không cần tải toàn bộ dataset ngay từ đầu**. Chiến lược MVP là:

```text
1 traversal nhỏ / đại diện
        ↓
chạy E2E pipeline
        ↓
ổn định development
        ↓
2–3 traversals cho development/regression
        ↓
3–5 traversals cố định cho final benchmark
```

Lần tải đầu tiên chỉ nên lấy:

```text
image_left/
lidar/
frame_times.txt
traj_gt.txt
calibrations.txt
groundtruth_map.ply
```

Trong đó `traj_gt.txt` và `groundtruth_map.ply` phải được coi là **evaluation-only / controlled-preprocessing assets**, không được vô tình đưa vào RGB-only reconstruction pipeline.

---

# Chương 1: Tổng quan TorWIC-SLAM, Nguồn gốc và Lý do lựa chọn

Chương này mô tả trọn vẹn bối cảnh xuất xứ của dataset, phân biệt các phiên bản, lý do lựa chọn nó thay vì các dataset phổ biến khác, cùng các thông tin về giấy phép, nơi tải về và cách trích dẫn. Các thông tin dưới đây được tổng hợp trực tiếp từ tài liệu gốc của tác giả.

## 1.1 TorWIC-SLAM là gì? Bối cảnh và Xuất xứ

TorWIC-SLAM (Toronto Warehouse Incremental Change SLAM Dataset) là một bộ dữ liệu thực tế (real-world dataset) được thu thập trực tiếp trong nhà kho/cơ sở vật chất của công ty **Clearpath Robotics**. Dự án này được tài trợ bởi **Viện Trí tuệ Nhân tạo Vector (Vector Institute for Artificial Intelligence)** tại Toronto và **Mạng lưới Robot Canada (NSERC NCRN)**.

Dataset được thu thập bằng cách gắn các hệ thống cảm biến lên **OTTO 100 Autonomous Mobile Robot**, một nền tảng robot di động, và được người vận hành điều khiển từ xa đi quanh nhà kho với tốc độ đi bộ.

**Thông tin tổng quan về dữ liệu thu được:**
- **Thời gian:** Thu thập trong 3 ngày khác nhau, trải dài khoảng 4 tháng.
- **Quy mô:** Bao gồm 3 kịch bản (scenarios) với tổng cộng 20 chuyến đi (trajectories/traversals).
- **Hành trình:** Các chuyến đi di chuyển quanh nhà kho theo các tuyến đường định trước (cùng chiều kim đồng hồ hoặc ngược chiều kim đồng hồ), tất cả đều bắt đầu gần cùng một gốc tọa độ (origin) của bản đồ tham chiếu.
- **Ý tưởng nghiên cứu cốt lõi:** Quan sát một nhà kho có các yếu tố "semi-static" (bán tĩnh) thay đổi theo thời gian. Ví dụ: Các vật thể (pallet, xe đẩy, thùng hàng) bị di chuyển, xuất hiện hoặc biến mất giữa các lần chạy (traversals) cách nhau đến cả 4 tháng.

Điều này cực kỳ phù hợp với hướng Real2Sim vì dự án của chúng ta cũng mô phỏng lại chu trình:
`Nhà kho thực tế → Tái tạo 3D (Reconstruct) → Nhận diện vật thể (Object-aware scene) → Chỉnh sửa Layout → Kiểm tra tầm ảnh hưởng trong giả lập (Simulation)`.

## 1.2 Tại sao chọn TorWIC-SLAM làm lựa chọn số 1 cho Real2Sim Studio?

Dự án RAV-01 (Real2Sim Studio) nhắm đến domain MVP là **Warehouse / Indoor AMR** (Robot tự hành trong nhà kho). Để phát triển và đánh giá hệ thống tái tạo không gian 3D, chúng ta cần một dataset thực tế thỏa mãn rất nhiều tiêu chí khắt khe.

### Đánh bại các dataset ngoài trời (Autonomous Driving Datasets)
Các dataset cực kỳ nổi tiếng như **KITTI**, **Waymo Open Dataset**, hay **nuScenes** tuy có chất lượng rất cao nhưng lại được thu thập trên đường phố (outdoor/autonomous driving). Khung cảnh chủ yếu là đường nhựa, xe cộ, tòa nhà và bầu trời. Chúng hoàn toàn không khớp với không gian nhà kho trong nhà (indoor warehouse) của dự án chúng ta. TorWIC-SLAM khắc phục triệt để vấn đề này vì nó được thu thập trực tiếp trên một AMR di chuyển trong nhà kho thực tế.

### Sự đồng bộ hoàn hảo của hệ thống phần cứng (Hardware Sync)
Thay vì sử dụng các cảm biến chắp vá rời rạc, TorWIC-SLAM có một hệ thống phần cứng cực kỳ đồng bộ:
- Sử dụng 2 camera **Azure Kinect RGB-D** được cấu hình theo chế độ Master (Trái) - Subordinate (Phải).
- Camera và LiDAR 3D (**Ouster OS1-128**) được đồng bộ hóa thời gian tuyệt đối bằng **Precision Time Protocol (PTP)**.
- **Đã được hiệu chuẩn (Calibrated) hoàn chỉnh:** Camera và LiDAR được gắn ở các vị trí *khác nhau* trên robot, nên chúng nhìn sự vật từ các góc độ khác nhau. Tác giả đã đo đạc và cung cấp sẵn file thông số hình học (Extrinsics) cho biết chính xác camera nằm cách LiDAR bao nhiêu cm và nghiêng bao nhiêu độ. Nhờ vậy, hệ thống của chúng ta có thể chập (fuse) chính xác hình ảnh từ camera lên các đám mây điểm của LiDAR mà không bị xô lệch. Các thông số về độ cong của ống kính bên trong camera (Intrinsics) cũng đã được đo sẵn. 

### Có Bản đồ tham chiếu chuyên dụng (Ground-truth 3D map)
Đây là yếu tố quyết định. Tác giả không dùng chính robot để vẽ bản đồ làm đáp án, mà dùng thiết bị quét chuyên nghiệp **Leica MS60 Total Station** quét từng phần nhà kho, sau đó ghép lại bằng phần mềm **Leica Cyclone Register 360** để tạo ra bản đồ với độ chính xác cấp độ centimet. 
Các tọa độ (poses) của robot được tính ngược lại bằng cách căn chỉnh quét LiDAR vào chính bản đồ Leica này. Điều này cung cấp cho chúng ta một thước đo định lượng (metric benchmark) hoàn hảo để chấm điểm độ sai số hình học sau khi tái tạo 3D, thay vì chỉ đánh giá cảm quan.

## 1.3 Phân biệt hai phiên bản TorWIC (Cần hết sức lưu ý)

Repository chính thức của TorWIC chia sẻ công khai hai bộ dữ liệu chính. Cần phân biệt rõ để tải đúng và không bị nhầm lẫn khi giao tiếp trong team:

| Tính chất | **TorWIC-Mapping** | **TorWIC-SLAM (Lựa chọn chính của dự án)** |
|---|---:|---|
| **Năm công bố** | 2022 | 2023 |
| **Tên bài báo** | POCD: Probabilistic Object-Level Change Detection | POV-SLAM: Probabilistic Object-Level Variational SLAM |
| **Cảm biến chính** | Intel RealSense D435i RGB-D + Hokuyo UAM501 **(LiDAR 2D)** | 2× Azure Kinect RGB-D + Ouster OS1-128 **(LiDAR 3D)** |
| **Mục tiêu gốc** | Bảo trì bản đồ / Phát hiện thay đổi | SLAM trong nhà kho thay đổi theo thời gian |
| **Sự phù hợp với MVP** | ❌ Không phải lựa chọn chính | ✅ **Có — Đây là lựa chọn chính** |

**Lưu ý:** Khi viết trong các tài liệu PRD, Evaluation Plan hay code, hãy luôn dùng tên đầy đủ là **TorWIC-SLAM** hoặc **Toronto Warehouse Incremental Change SLAM Dataset**, tuyệt đối không viết tắt là `TorWIC` để tránh tải nhầm sang bản Mapping 2D.

## 1.4 Nguồn tài liệu chính thức, Tải về và Trích dẫn

**1. Repository chính thức (GitHub):**
[https://github.com/Viky397/TorWICDataset](https://github.com/Viky397/TorWICDataset)
Nơi chứa toàn bộ tài liệu mô tả cấu trúc, thông số cảm biến, kịch bản, các câu hỏi thường gặp (FAQ), bài báo khoa học và điều khoản sử dụng.

**2. Link tải Dataset (Google Drive):**
[https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ?usp=sharing](https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ?usp=sharing)
*(Lưu ý: Không tải toàn bộ thư mục root ngay lập tức. Hãy xem kỹ hướng dẫn tải ở các chương sau để chỉ tải phần cần thiết).*

**3. Paper gốc (Tài liệu học thuật):**
- Tên: *POV-SLAM: Probabilistic Object-Level Variational SLAM* (RSS 2023) - Tác giả: Jingxing Qian và cộng sự.
- Link Proceedings: [https://roboticsproceedings.org/rss19/p069.html](https://roboticsproceedings.org/rss19/p069.html)
- PDF nằm trong thư mục gốc của repository: `Qian_POV_SLAM.pdf`

**4. Citation (Trích dẫn dùng cho Report/Paper của dự án):**
Khi công bố báo cáo công khai có sử dụng dataset này, hãy sử dụng định dạng trích dẫn BibTeX dưới đây:

```bibtex
@INPROCEEDINGS{QianChatrathPOVSLAM,
  author={Qian, Jingxing and Chatrath, Veronica and Servos, James and Mavrinac, Aaron and Burgard, Wolfram and Waslander, Steven L. and Schoellig, Angela},
  booktitle={2023 Robotics: Science and Systems (RSS)}, 
  title={{POV-SLAM: Probabilistic Object-Level Variational SLAM}}, 
  year={2023},
  volume={},
  number={},
  pages={},
  doi={10.15607/RSS.2023.XIX.069}
}
```

---

# Chương 2: Phân tích Cảm biến (Sensors), Thành phần Dữ liệu và Chiến lược Tải về

Chương này đi sâu vào phân tích cấu trúc của TorWIC-SLAM và từng loại dữ liệu bên trong. Với mỗi loại dữ liệu, chúng ta sẽ làm rõ bản chất kỹ thuật, vị trí lưu trữ trong thư mục gốc, và chốt lại **Chiến lược Tải về (có cần tải ngay cho MVP hay không, và tải để làm gì)**. Cuối chương là hướng dẫn chọn Traversal và quản lý dung lượng.

## 2.1 Cấu trúc thư mục gốc của TorWIC-SLAM
Bộ dữ liệu TorWIC-SLAM được tổ chức rất quy củ. Khi truy cập vào Google Drive gốc, bạn sẽ thấy cấu trúc chính như sau:
```text
TorWIC-SLAM/
│
├── groundtruth_map.ply         # Bản đồ 3D chuẩn xác quét bằng máy Leica MS60
├── calibrations.txt            # File thông số hiệu chuẩn (Intrinsics & Extrinsics)
│
└── WarehouseSequences/
    │
    ├── Scenario 1 Traversal 1/ # Chuyến đi số 1
    │   ├── image_left/         # Ảnh RGB từ camera trái
    │   ├── image_right/        # Ảnh RGB từ camera phải
    │   ├── depth_left/         # Ảnh chiều sâu (Depth) tương ứng
    │   ├── depth_right/
    │   ├── segmentation_color_left/       # Mask màu (Segmentation)
    │   ├── segmentation_greyscale_left/   # Mask xám (chứa Class ID 1-16)
    │   ├── lidar/              # Điểm quét 3D (file .pcd) từ Ouster OS1-128
    │   ├── imu_left.txt        # Dữ liệu gia tốc/góc
    │   ├── frame_times.txt     # File đồng bộ thời gian các cảm biến
    │   └── traj_gt.txt         # Tọa độ quỹ đạo (Ground-truth pose) của robot
    │
    ├── Scenario 1 Traversal 2/
    └── ... (tổng cộng 20 thư mục Traversal)
```

## 2.2 Phân tích từng loại dữ liệu và Quyết định tải về

### 2.2.1 Hình ảnh RGB (RGB Images)
- **Bản chất:** Ảnh màu thu từ 2 camera Azure Kinect, được đặt tên theo thứ tự thời gian (ví dụ `0000.png`).
- **Vị trí:** Trong thư mục `image_left/` và `image_right/` của từng Traversal.
- **Quyết định tải:** ✅ **BẮT BUỘC TẢI `image_left/`**. 
  - **Lý do:** Đây là nguồn dữ liệu hình ảnh (visual) chính để chạy các thuật toán tái tạo 3D (COLMAP/SfM, 3D Gaussian Splatting) và trích xuất vật thể. 
  - **Lưu ý:** Với MVP hiện tại, chúng ta không chạy tái tạo bằng hệ thống Stereo (camera kép), nên **chưa cần tải `image_right/`**.

### 2.2.2 Đám mây điểm 3D (3D LiDAR)
- **Bản chất:** Các file quét không gian `.pcd` thô thu được từ cảm biến Ouster OS1-128. Mỗi file là một "lát cắt" quét tại một thời điểm (per-timestamp scans).
- **Vị trí:** Trong thư mục `lidar/` của từng Traversal.
- **Quyết định tải:** ✅ **BẮT BUỘC TẢI**.
  - **Lý do:** Dùng làm nguồn dữ liệu hình học thực tế. Tuy nhiên, lưu ý cực kỳ quan trọng là MVP của chúng ta KHÔNG nhận chuỗi file `.pcd` rời rạc này làm đầu vào trực tiếp (dự án không làm LiDAR SLAM từ đầu). Chúng ta tải về để phục vụ bước **Tiền xử lý offline**, gộp chúng lại thành một cụm mây điểm duy nhất (`registered_lidar.ply`) trước khi đưa vào pipeline chính.

### 2.2.3 Bản đồ hình học chuẩn (Ground-truth Map)
- **Bản chất:** Bản đồ nhà kho tĩnh được quét bằng máy trắc địa Leica MS60 (độ chính xác centimet).
- **Vị trí:** Nằm ở thư mục gốc `groundtruth_map.ply`.
- **Quyết định tải:** ✅ **BẮT BUỘC TẢI NGAY**.
  - **Lý do:** Đây là "đáp án" để chấm điểm Benchmark hình học (tính toán khoảng cách Chamfer, sai số kích thước Metric). 
  - **Lưu ý tối quan trọng:** File này là tài sản **Evaluation-only (Chỉ dùng để chấm điểm)**. Tuyệt đối không được cài cắm file này vào pipeline tái tạo 3D tự động để tránh rò rỉ dữ liệu (data leakage).

### 2.2.4 Tọa độ quỹ đạo (Ground-truth Trajectory)
- **Bản chất:** Tọa độ chính xác của cụm cảm biến theo từng thời điểm, được tính bằng cách căn chỉnh ảnh quét LiDAR vào bản đồ Leica.
- **Vị trí:** File văn bản `traj_gt.txt` trong thư mục mỗi Traversal.
- **Quyết định tải:** ✅ **BẮT BUỘC TẢI**.
  - **Lý do:** Dùng để chấm điểm độ chính xác của quỹ đạo (Pose Evaluation / ATE / RPE) và hỗ trợ tiền xử lý gộp file LiDAR. Giống như Ground-truth Map, file này cũng không được đưa vào luồng tái tạo RGB-only.

### 2.2.5 Thông số hiệu chuẩn và Đồng bộ thời gian (Calibration & Timestamps)
- **Bản chất:** File `calibrations.txt` chứa thông số Nội hàm và Ngoại hàm của các camera/LiDAR. File `frame_times.txt` dùng để đối chiếu mốc thời gian giữa ảnh RGB và điểm LiDAR.
- **Vị trí:** `calibrations.txt` ở thư mục gốc, `frame_times.txt` nằm trong từng Traversal.
- **Quyết định tải:** ✅ **BẮT BUỘC TẢI NGAY**.
  - **Lý do:** Đây là siêu dữ liệu (metadata) bắt buộc để hệ thống biết cấu tạo thiết bị và đồng bộ 2 luồng ảnh - điểm quét 3D vào chung một hệ trục tọa độ.

### 2.2.6 Dữ liệu chiều sâu (Depth Images)
- **Bản chất:** Ảnh chiều sâu (Depth) đã được căn chỉnh vừa khít với ảnh RGB, thu từ Azure Kinect.
- **Vị trí:** `depth_left/` và `depth_right/` trong từng Traversal.
- **Quyết định tải:** ❌ **CHƯA CẦN TẢI**.
  - **Lý do:** Pipeline MVP hiện tại chỉ sử dụng "RGB-only" hoặc "RGB + LiDAR". Chúng ta chưa đưa hệ thống RGB-D vào hợp đồng đầu vào (input contract). Chỉ tải sau này nếu cần debug mảng hình học hoặc chạy thử nghiệm phụ (auxiliary).

### 2.2.7 Dữ liệu phân mảnh ngữ nghĩa (Segmentation Data)
- **Bản chất:** Các ảnh mask (mặt nạ) gán nhãn vật thể (có 16 lớp như: mặt sàn, tường, kệ hàng, người, xe nâng...). Gồm bản màu và bản xám chứa Class ID. Đã có sẵn một tập phụ (79 thư mục) để fine-tune.
- **Vị trí:** Các thư mục `segmentation_*` trong từng Traversal.
- **Quyết định tải:** ❌ **CHƯA CẦN TẢI CHO MVP BAN ĐẦU**.
  - **Lý do:** Tác giả nhấn mạnh rằng các mask này **không hoàn hảo** vì chúng được sinh ra tự động từ một mô hình AI. Do đó, chúng ta không thể dùng nó làm "Ground truth" chuẩn 100% để chấm điểm bài toán nhận diện vật thể của chúng ta.

### 2.2.8 Dữ liệu quán tính & thô khác (IMU, ROS Bags)
- **Bản chất:** Thông số gia tốc/góc quay (`imu_left.txt`, `imu_right.txt`) và dữ liệu ROS Bag nguyên thủy (chứa cả số vòng quay bánh xe của base robot).
- **Quyết định tải:** ❌ **KHÔNG CẦN TẢI**.
  - **Lý do:** Dự án của chúng ta không xây dựng hệ thống Visual-Inertial SLAM (SLAM dùng IMU) từ đầu, nên những file này hoàn toàn dư thừa với MVP.

## 2.3 Chiến lược Chọn Traversal và Quản lý Dung lượng

Bộ dữ liệu chứa 20 chuyến đi với tổng dung lượng vô cùng lớn. Việc tải toàn bộ ngay từ đầu là **không cần thiết** và sẽ gây lãng phí dung lượng ổ cứng cũng như cản trở quá trình phát triển (Dev) nhanh.

**Chiến lược tải khuyên dùng (Phase 0 - Bring-up):**
1. **Chỉ tải duy nhất 1 Traversal đại diện (Ví dụ: Scenario 1 Traversal 1 hoặc 2):**
   - Ưu tiên chọn Traversal có đường chạy ngắn, độ sáng tốt, không bị rung lắc nhiều.
   - Dung lượng dự kiến cho 1 Traversal (chỉ lấy RGB trái và LiDAR thô) rơi vào khoảng vài chục GB.
2. **Chạy luồng E2E (End-to-End):** Đưa Traversal này chạy thông suốt từ đầu đến cuối pipeline để gỡ lỗi (debug) và ổn định hệ thống.
3. **Mở rộng dần dần:**
   - Sau khi pipeline đã chạy ngon, tải thêm 2-3 Traversals để làm tập dữ liệu Dev / Regression Test.
   - Cuối cùng, tải 3-5 Traversals cố định (khác kịch bản hoặc mốc thời gian) để khóa lại làm bộ Benchmark chính thức cuối cùng.

**Checklist các mục phải có trong máy tính sau lần tải đầu tiên:**
- [x] Thư mục chứa `image_left/*.png` (của 1 chuyến đi)
- [x] Thư mục chứa `lidar/*.pcd` (của 1 chuyến đi)
- [x] File `traj_gt.txt` (của chuyến đi đó)
- [x] File `frame_times.txt` (của chuyến đi đó)
- [x] File `calibrations.txt` (nằm ở gốc)
- [x] File `groundtruth_map.ply` (nằm ở gốc)

*(Lưu ý: Bạn KHÔNG được sửa hay xóa các file gốc này, mà sẽ thực hiện tổ chức lại thư mục theo hướng dẫn ở Chương 3).*

---
# Chương 3: Tổ chức Thư mục, Tiền xử lý (Preprocessing) và Tích hợp vào Pipeline

Chương này đóng vai trò như một bản thiết kế kiến trúc (Architecture Design) cho luồng dữ liệu. Chúng ta sẽ trình bày dòng chảy xuyên suốt: Từ việc copy nguyên trạng vào ổ cứng, quy hoạch lại cấu trúc nội bộ, cách tiền xử lý các file đặc thù (đặc biệt là gộp LiDAR), và cuối cùng là bảng đối chiếu chi tiết 20 bước tích hợp vào sản phẩm thật.

## 3.1 Quy tắc tổ chức lại thư mục nội bộ

Dù Google Drive gốc tổ chức khá gọn gàng, nhưng chúng ta **tuyệt đối không được sửa đổi hay xóa file trực tiếp trên source gốc**. Code của Real2Sim Studio không nên đọc trực tiếp thư mục gốc lộn xộn này. Thay vào đó, cần tạo một lớp dữ liệu chuẩn hóa (Normalized) ở bên cạnh.

Cấu trúc thư mục dự án nội bộ khuyên dùng:

```text
data/
└── torwic_slam/
    │
    ├── dataset_manifest.yaml        # Khai báo tình trạng dataset (tải gì, dùng gì)
    │
    ├── raw/                         # CHỈ ĐỌC (Immutable): Giữ nguyên trạng file tải về
    │   ├── global/
    │   │   ├── calibrations.txt
    │   │   └── groundtruth_map.ply
    │   └── scenario_1_traversal_1/
    │       ├── image_left/
    │       ├── lidar/
    │       ├── frame_times.txt
    │       └── traj_gt.txt
    │
    ├── normalized/                  # Dữ liệu đã chuẩn hóa format cho phần mềm dễ đọc
    │   └── scenario_1_traversal_1/
    │       ├── rgb_frames/          # Khung ảnh đã lọc
    │       ├── timestamps.csv       # File đồng bộ thời gian chuẩn CSV
    │       └── calibration.json     # File hiệu chuẩn chuyển sang JSON
    │
    ├── derived/                     # Dữ liệu phái sinh (Có thể xóa và tạo lại bằng code)
    │   └── scenario_1_traversal_1/
    │       ├── traversal.mp4        # Video nối từ ảnh để làm file demo
    │       └── registered_lidar.ply # Cụm mây điểm LiDAR đã được gộp lại
    │
    └── evaluation_only/             # VÙNG CẤM: Chỉ dành riêng cho tool chấm điểm
        ├── groundtruth_map.ply
        ├── traj_gt_reference/
        └── benchmark_split.json
```

**Lý do phân tách:**
- `raw/`: Giữ bằng chứng gốc, tránh vô tình làm hỏng dữ liệu khi code bị lỗi. Git repo của dự án KHÔNG được lưu thư mục này, chỉ lưu file cấu hình.
- `normalized/`: Đổi các file text thô thành file JSON/CSV chuẩn để pipeline dễ đọc, không bị chết code (crash) nếu dataset TorWIC đổi tên file.
- `derived/`: Chứa các file phái sinh sinh ra trong quá trình chạy.
- `evaluation_only/`: Tạo bức tường lửa (boundary) chống rò rỉ dữ liệu (data leakage) giữa dữ liệu đầu vào và "đáp án" Ground truth. `groundtruth_map.ply` ở gốc có thể được symlink (tạo shortcut) qua đây để chấm điểm chứ code tái tạo 3D không được phép quét vào.

**Ví dụ nội dung file theo dõi `dataset_manifest.yaml` team nên lưu cùng code:**

```yaml
dataset_name: TorWIC-SLAM
source_repo: https://github.com/Viky397/TorWICDataset
source_drive: https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ?usp=sharing
license: CC-BY-NC-4.0-plus-dataset-terms

subset:
  scenario: TBD
  traversal: TBD

modalities_downloaded:
  image_left: true
  lidar: true
  frame_times: true
  trajectory_gt: true
  calibration: true
  groundtruth_map: true
  depth: false
  image_right: false
  segmentation: false
  imu: false

usage:
  rgb_primary_input: true
  lidar_preprocessing_source: true
  geometry_ground_truth: true
  pose_ground_truth: true

leakage_controls:
  groundtruth_map_visible_to_product_pipeline: false
  trajectory_gt_visible_to_rgb_reconstruction: false
  trajectory_gt_used_for_lidar_prefusion: TBD

notes:
  - groundtruth_map and traj_gt must remain evaluation-only for RGB benchmark
  - document any use of traj_gt during LiDAR preprocessing
```

## 3.2 Tiền xử lý (Preprocessing) trước khi đưa vào Pipeline

TorWIC-SLAM **không thể bê nguyên xi ném vào mọi module của sản phẩm**. Chúng ta phải tiền xử lý để nhào nặn thành định dạng phù hợp, nhưng hãy nhớ nguyên tắc: Không biến bước tiền xử lý này thành một dự án nghiên cứu khoa học mới (Ví dụ: Không tự code lại hệ thống LiDAR SLAM, Loop Closure phức tạp làm gì).

**1. Tiền xử lý RGB:** 
- **Nguồn:** Các file ảnh rời rạc `raw/.../image_left/*.png`
- **Hành động:** Lọc file hỏng, đọc timestamp, chia tập Test/Train. Cuối cùng, dùng FFmpeg nối tất cả ảnh thành một video `traversal.mp4` đẩy vào mục `derived/` để đăng lên Web App Demo cho nhẹ (chạy Benchmark thì vẫn lấy ảnh rời).

**2. Tiền xử lý File Hiệu chuẩn (Calibration):** 
- **Nguồn:** File text thô `calibrations.txt`
- **Hành động:** Dùng Python parse (đọc) file này thành `calibration.json` chứa các ma trận Nội hàm, Ngoại hàm rõ ràng. Làm vậy các module sau cứ lôi JSON ra đọc, không phải tự viết code tách chuỗi văn bản lằng nhằng nữa. Cần chốt luôn quy chuẩn hệ tọa độ (Up-axis là Z hay Y).

**3. Tiền xử lý LiDAR (Quan trọng nhất):** 
- **Nguồn:** Hàng nghìn file `.pcd` rời rạc thu theo từng milli-giây.
- **Hành động:** Sản phẩm MVP của chúng ta không có khả năng đọc LiDAR thời gian thực. Do đó, cần có đoạn code offline chạy ghép nối (fuse) toàn bộ các `.pcd` này thành một cục mây điểm duy nhất (`registered_lidar.ply`). Khúc ghép nối này CÓ THỂ mượn "đáp án" tọa độ `traj_gt.txt` để ghép cho chuẩn xác, nhưng phải ghi rõ điều này vào log để minh bạch (Như ví dụ trong file yaml ở trên: `trajectory_gt_used_for_lidar_prefusion: true`).

## 3.3 Bảng Mapping Dataset vào 20 Stage của Real2Sim Studio

Đây là phần lõi: Giúp team biết **đã tải file nào thì file đó được đưa vào đoạn code nào, và sinh ra kết quả (output) gì**. Code của chúng ta phải tách bạch 2 luồng: **Luồng Sản phẩm (Product)** (chạy từ dữ liệu thô ra 3D) và **Luồng Đánh giá (Evaluation)** (lấy "đáp án" ra chấm điểm). Tuyệt đối không để "đáp án" lọt vào "Luồng Sản phẩm".

| Stage của product | Dữ liệu TorWIC sử dụng | Preprocessing trước stage | Cách sử dụng | Output mong đợi |
|---|---|---|---|---|
| **0. Dataset intake / validation** | `image_left/`, `lidar/`, `frame_times.txt`, `calibrations.txt` | integrity check, count files, parse metadata | Xác nhận subset hợp lệ trước khi chạy heavy pipeline | dataset manifest + validation report |
| **1. RGB ingestion** | `image_left/` hoặc derived `traversal.mp4` | optional sampling / video encode | Web/CLI nhận RGB input | normalized RGB job input |
| **2. Frame extraction / selection** | original `image_left/` hoặc `traversal.mp4` | nếu dùng image sequence thì không cần decode video; nếu dùng video thì extract frames | Chuẩn bị frame cho SfM/3DGS | selected RGB frames |
| **3. Camera pose estimation / SfM** | selected `image_left/`; optional camera intrinsics từ `calibrations.txt` | held-out split phải được khóa trước | COLMAP/SfM estimate camera poses | camera poses + sparse reconstruction |
| **4. Visual reconstruction** | RGB training frames + estimated poses | image normalization nếu backend yêu cầu | train/build 3DGS visual representation | Gaussian visual artifact |
| **5. RGB-derived geometry** | RGB frames + poses | backend-specific conversion | OpenMVS/mesh backend tạo geometry từ RGB | RGB-derived mesh |
| **6. LiDAR product input preparation** | `lidar/*.pcd`, `traj_gt.txt` nếu dùng controlled prefusion | transform, merge, filter, voxel downsample | **Nằm ngoài product runtime**; tạo registered point cloud đúng contract | `registered_lidar.ply` |
| **7. LiDAR geometry ingestion** | `registered_lidar.ply` | coordinate/unit validation | Real2Sim đọc LiDAR geometry | canonical geometry / mesh |
| **8. RGB↔LiDAR alignment** | visual reconstruction, registered LiDAR, `calibrations.txt` | parse transforms / optional manual refinement | Đưa hai modality vào cùng scene coordinate frame | unified metric scene |
| **9. Metric scale validation** | LiDAR metric geometry; RGB reconstruction; optional independent reference | không dùng Leica GT như hidden production input | Xác nhận scene ở đúng đơn vị thực | metric-ready Scene IR |
| **10. Candidate object extraction** | RGB frames/visual reconstruction; optional TorWIC segmentation chỉ để debug | không feed model-generated masks vào benchmark baseline nếu muốn đánh giá fair | SAM2/proposal + multi-view grouping | candidate SceneObjects |
| **11. Human review / object correction** | candidate objects; optional manual GT subset chỉ cho evaluator | manual annotations tách khỏi UI input | rename/confirm/merge/ignore | confirmed editable SceneObjects |
| **12. Collider generation** | geometry per object / scene geometry | simplify / OBB / convex proxy | tạo Physics Representation | colliders |
| **13. Web 3D editing** | Visual + Geometry + Collider | none ngoài runtime asset conversion | user move/rotate/hide/show object | updated Scene IR/version |
| **14. Candidate OpenUSD build** | Scene IR + geometry + colliders | coordinate conversion to USD conventions | IsaacSimAdapter build candidate package | candidate USD |
| **15. Isaac validation** | candidate USD | none ngoài simulator setup | load/collision/spawn/path checks | validation report |
| **16. Geometry benchmark** | `groundtruth_map.ply` **evaluation-only** | align evaluation frames only theo protocol công bố | compare prediction vs Leica reference | Chamfer / P-R-F1 / distance errors |
| **17. Pose benchmark** | `traj_gt.txt` **evaluation-only** | convert LiDAR pose GT to camera frame nếu cần bằng calibration | compare SfM trajectory vs reference | ATE / RPE |
| **18. Visual benchmark** | held-out `image_left/` | split before training | render held-out camera views | PSNR / SSIM / LPIPS |
| **19. Object benchmark** | manually annotated small subset | team annotation | compare candidate objects with held-out labels | Object Recall / AP/IoU if protocol supports |
| **20. Path benchmark** | derived reference occupancy + locked start-goal pairs | derive once and freeze | compare predicted CLEAR/BLOCKED | path F1 / unsafe false-clear rate |

**Dòng chảy thực tế của một Chuyến đi (Traversal) qua các Stage:**

```text
[Hình ảnh RGB] 
   → (Stage 1-5) Chạy thuật toán Reconstruct 3D (Gaussian Splatting / SfM) 
   → Output: Mô hình 3D tạo ra từ ảnh.

[Điểm LiDAR thô + Quỹ đạo GT] 
   → (Tiền xử lý offline) 
   → Output: Cụm mây điểm gộp (registered_lidar.ply)
   → (Stage 7-8) Căn chỉnh, đối chiếu không gian thật
   → Output: Mô hình đo lường vật lý chính xác (Metric scene).

[Bản đồ chuẩn Leica MS60 GT] 
   → NẰM IM CHỜ ĐỢI TẠI VÙNG CẤM (evaluation_only)
   → (Stage 16) Tool chấm điểm lôi Leica GT ra so sánh với Mô hình đo lường phía trên
   → Output: Điểm số khoảng cách sai lệch (Chamfer Distance).
```

# Chương 4: Chiến lược Đánh giá (Evaluation), Methodology và Chi tiết các Track Benchmark

Chương này tập trung hoàn toàn vào học thuật và phương pháp luận. Chúng ta sẽ làm rõ bộ dữ liệu TorWIC-SLAM đáp ứng được bao nhiêu phần trăm yêu cầu của sản phẩm, dùng nó để làm gì trong dự án, các quy tắc tối quan trọng để không "ăn gian" khi chấm điểm, và chi tiết từng bài thi (Track Benchmark). Cuối cùng là những lời tuyên bố (claim) mà team được phép và không được phép đưa ra.

## 4.1 Mức độ đáp ứng và Mục đích sử dụng của Dataset
TorWIC-SLAM phù hợp rất tốt với chu trình từ **Input → Reconstruction → Metric geometry → RGB/LiDAR integration → Evaluation**. Tuy nhiên, nó KHÔNG PHẢI là một bộ dữ liệu hoàn thiện 100% cho mọi tính năng của Real2Sim. Dataset này cung cấp dữ liệu cảm biến thực tế, chứ **không cho sẵn cấu trúc OpenUSD, Collider vật lý, hay nhãn dán đối tượng 3D hoàn hảo**. Những thứ đó phần mềm của chúng ta phải tự tạo ra.

**Chiến lược sử dụng Dataset:** TorWIC-SLAM đóng vai trò là "xương sống" của dự án, được sử dụng cho 6 mục đích chính:
1. **Public Sample Data:** Làm dữ liệu mẫu tích hợp sẵn vào Web App để khách hàng dùng thử hệ thống mà không cần tự upload.
2. **Demo Input:** Chạy luồng luân chuyển đầu cuối (E2E) để trình diễn tính năng.
3. **Development & Smoke Testing:** Trích ra một tập dữ liệu siêu nhỏ để lập trình viên test code hằng ngày.
4. **Regression Testing:** Chấm điểm định kỳ để đảm bảo code mới không làm giảm chất lượng (Ví dụ: v0.2 được 82 điểm, v0.3 tụt xuống 73 điểm là có lỗi - dù code vẫn chạy).
5. **Baseline Setting:** Chạy thử để lấy phân phối điểm, từ đó mới đặt ra các tiêu chuẩn (Threshold) hợp lý, thay vì tự ngồi nghĩ ra "PSNR phải trên 25".
6. **Quantitative Benchmarking (Quan trọng nhất):** Làm bộ bài thi chính thức để chấm điểm phần mềm (Trình bày chi tiết ở mục 4.3).

*(Lưu ý: Mặc dù team có thể tự quay thêm video bằng điện thoại (Team capture) để test vui, nhưng nó **không thể thay thế** TorWIC-SLAM làm Benchmark vì video điện thoại không có bản đồ 3D Leica làm Ground truth để chấm điểm).*

## 4.2 Phương pháp luận (Methodology) - Chống rò rỉ dữ liệu (Data Leakage)
Data Leakage (Rò rỉ dữ liệu) là lỗi tối kỵ trong học thuật: Cho AI/Thuật toán nhìn thấy "đáp án" trước khi làm bài.

- **Nguy cơ lớn nhất:** Việc lén dùng bản đồ Leica (`groundtruth_map.ply`) để chỉnh sửa lại mô hình 3D cho đẹp rồi mới đem đi chấm điểm là gian lận. Hoặc lén dùng tọa độ thật `traj_gt.txt` để hỗ trợ hệ thống SfM (COLMAP) trong Track RGB-only.
- **Quy tắc tuyệt đối:** 
  - `groundtruth_map.ply` VÀ `traj_gt.txt` chỉ được phép xuất hiện ở các bước Evaluation Stage (Đánh giá). 
  - Riêng với quá trình tiền xử lý gộp LiDAR (Pre-fusion), được phép dùng `traj_gt.txt` để ghép mây điểm cho chuẩn, nhưng phải **ghi chú minh bạch** điều này vào báo cáo, không được giấu diếm.

## 4.3 Chi tiết các Track Benchmark (Bài thi chấm điểm)

Dự án chia làm nhiều "bài thi" khác nhau để đánh giá toàn diện phần mềm:

### Track A — RGB-only quantitative benchmark
- **Input:** Chỉ dùng ảnh `image_left/*.png` (Không dùng LiDAR, không dùng tọa độ GT).
- **Mục tiêu:** Chấm điểm chất lượng hình ảnh của hệ thống 3D Gaussian Splatting hoặc NeRF.
- **Metrics (Thước đo):** Dùng PSNR, SSIM, LPIPS. Phải tuân thủ chuẩn "Held-out view protocol": Cất giấu 10% số khung ảnh không cho hệ thống train, sau đó bắt hệ thống render lại góc nhìn của 10% ảnh đó rồi so pixel với ảnh thật.

### Track B — RGB + LiDAR integration test
- **Input:** Ảnh RGB + Mây điểm đã gộp `registered_lidar.ply`.
- **Mục tiêu:** Chấm điểm khả năng kết hợp ảnh và LiDAR để dựng hình học không gian.
- **Metrics (Thước đo):** Chấm bằng khoảng cách hình học. Dùng Chamfer Distance, Geometry Precision, Recall, F1 so với bản đồ Leica. Kèm theo "Metric scale validation" (Kiểm tra sai số tỷ lệ: 1 mét trong mô hình có đúng là 1 mét ngoài đời hay không).

### Track C — Object, Collider và Path Evaluation
Dataset không có sẵn "đáp án hoàn hảo" cho vật thể 3D. Thay vì tốn tiền thuê người tạo Synthetic Dataset giả lập, chúng ta dùng luôn TorWIC-SLAM:
- **Object Extraction:** Team sẽ tự dán nhãn (annotate) thủ công một tập nhỏ ảnh/vật thể trong nhà kho để làm đáp án Benchmark. Dùng Object Recall, AP, IoU để chấm.
- **Collider / Free-space:** Đánh giá vùng trống. Trích xuất vùng không gian trống (Free-space) từ bản đồ Leica làm tham chiếu. Nếu robot đi qua vùng đó trong mô hình của ta mà không đụng vật cản là Passed.
- **Path-feasibility:** Đánh giá đường đi. Chọn sẵn các điểm A, B. Nếu mô hình sinh ra báo đường "Trống" nhưng thực tế có vật cản (Unsafe false-clear) thì bị điểm trừ rất nặng.

## 4.4 Những tuyên bố (Claims) được phép và không được phép đưa ra

Để tránh rủi ro "nói lố" (overselling) và bị bác bỏ tính khoa học:
- ❌ **Không được claim:** "Phần mềm tự động tạo ra bản đồ chính xác centimet". (Vì độ chính xác này là của máy quét chuyên nghiệp Leica 100 ngàn đô, không phải do phần mềm RGB-only tự nội suy ra).
- ❌ **Không được claim:** "Chúng tôi đã benchmark thuật toán nhận diện vật thể trên dữ liệu khổng lồ chuẩn Ground truth". (Vì bộ nhãn dán mask trong dataset này là do một mô hình AI khác sinh ra, không phải nhãn thủ công chuẩn 100%).
- ✅ **ĐƯỢC PHÉP claim:** "Chúng tôi đánh giá thuật toán tái tạo không gian bằng hệ đo lường định lượng trên một dataset nhà kho thực tế (TorWIC-SLAM) sử dụng bản đồ tham chiếu cấp độ centimet."


# Chương 5: Hạn chế, Rủi ro, Kế hoạch dự phòng và Action Items

Chương này tổng kết lại những điểm yếu chưa hoàn thiện của TorWIC-SLAM, các phương án dùng dữ liệu thay thế nếu cần, và chốt lại bằng danh sách công việc (Action Items) team cần bắt tay vào làm ngay.

## 5.1 Các hạn chế (Limitations) của TorWIC-SLAM
Dù rất tốt, bộ dữ liệu này vẫn có những khuyết điểm mà team cần nắm rõ để không kỳ vọng sai:
1. **Dữ liệu phân mảnh ngữ nghĩa (Segmentation) không chuẩn 100%:** Như tác giả đã thừa nhận, các mặt nạ màu (Semantic mask) được sinh ra tự động bằng một mô hình AI khác chứ không phải dán nhãn thủ công (Human-annotated). Chúng ta không thể dùng nó làm thước đo Ground-truth tuyệt đối cho thuật toán bóc tách vật thể của dự án.
2. **Không có Ground-truth cho Vật thể 3D:** Dataset chỉ cung cấp bản đồ tĩnh (Static map) của nhà kho. Nó không cung cấp tọa độ khối hộp (3D Bounding Box) hay trạng thái (State) cho từng chiếc xe nâng, thùng hàng hay con người.
3. **Chỉ dùng cho mục đích Phi thương mại (Non-commercial):** Giấy phép CC BY-NC 4.0 có nghĩa là bạn dùng để demo, nghiên cứu, viết báo thì được, nhưng **không được phép** sử dụng trực tiếp dataset này như một phần của sản phẩm thương mại sinh lời.

## 5.2 Kế hoạch dự phòng và Dữ liệu thay thế (Alternatives)
Nếu TorWIC-SLAM không đủ đáp ứng hoặc gặp rắc rối về bản quyền thương mại về sau, team có thể chuẩn bị sẵn 2 phương án:
1. **Team Capture (Tự thu thập):** Đem điện thoại/máy ảnh đi quay thực tế tại một nhà kho.
   - *Ưu điểm:* Toàn quyền thương mại, hình ảnh sát với môi trường Việt Nam (nếu có).
   - *Nhược điểm:* Không có bản đồ trắc địa Leica 3D để chấm điểm định lượng (Benchmark). Bắt buộc phải chấm bằng mắt.
2. **Dùng Synthetic Dataset (Dữ liệu giả lập 100%):** Chạy Isaac Sim sinh ra các nhà kho ảo, xuất ảnh và chiều sâu ra làm tập dữ liệu.
   - *Ưu điểm:* Sinh ra được hàng triệu Ground truth hoàn hảo không sai một pixel (3D Bounding Box, Segmentation, Depth).
   - *Nhược điểm:* Bị hiện tượng khoảng cách thực - ảo (Sim-to-Real gap). Ảnh giả lập nhìn không giống thực tế, ánh sáng không chân thực, làm giảm uy tín của thuật toán.

=> **Kết luận:** Tại phase MVP này, TorWIC-SLAM vẫn là "vũ khí" mạnh nhất. Nó cho phép team biến câu hỏi định tính *"Scene nhìn có đẹp không?"* thành câu hỏi định lượng *"Scene bị lệch bao nhiêu cm so với môi trường thực?"*.

## 5.3 Danh sách công việc cần làm ngay (Action Items)
1. **Tạo cấu trúc thư mục dự án:** Tạo sẵn các thư mục `raw/`, `normalized/`, `derived/`, `evaluation_only/` theo đúng hướng dẫn ở Chương 3.
2. **Tải dữ liệu thử nghiệm:** Mở link Google Drive (nằm ở đầu bài viết), KHÔNG tải toàn bộ, chỉ tải đúng ảnh RGB trái (`image_left/`) và file quét `lidar/` của **01 Traversal duy nhất** (Ví dụ: Traversal 1 của Scenario 1).
3. **Tiền xử lý:** Chạy script nội bộ để gộp LiDAR thô thành file `registered_lidar.ply` và parse thông số Calibration sang định dạng JSON cho dễ đọc.
4. **Bảo mật Ground-truth:** Tải file `groundtruth_map.ply` (Bản đồ chuẩn Leica) và giấu kỹ vào thư mục `evaluation_only/`. 
5. **Chạy luồng End-to-End (E2E):** Khớp nối dữ liệu vào pipeline Real2Sim để dựng mô hình 3D thử nghiệm đầu tiên. Khóa chặt thuật toán (không cho đụng chạm thay đổi thông số) trước khi chạy tool chấm điểm Benchmark.
