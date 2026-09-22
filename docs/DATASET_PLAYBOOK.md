# Ghi chú Dataset — TorWIC-SLAM cho Real2Sim Studio

> **Mục đích tài liệu:** Ghi chú kỹ thuật để cả team hiểu TorWIC-SLAM là gì, dataset gồm những gì, và quan trọng nhất là **nó phù hợp tới đâu với sản phẩm Real2Sim Studio mà team thực sự sẽ xây**, cần tải bao nhiêu, cần tổ chức lại dữ liệu như thế nào, preprocessing những gì, và từng file/modality sẽ được sử dụng ở stage nào của pipeline cho development, demo, validation và benchmarking.
>
> **Document Role:** Dataset preparation, leakage control và evaluation methodology.
>
> **Scope:** TorWIC-SLAM preparation, dataset-specific preprocessing, data organization, leakage boundary và evaluation protocol cho RAV-01.
>
> **Upstream Constraint:** Không thay đổi Product Input Contract hoặc P0/P1/P2 của PRD.
>
> **Status:** Draft for Review.
>
> **Related Documents:** [PRD](./PRD.md), [BRIEF](./BRIEF.md), [WIREFRAME](./WIREFRAME_AND_UI_FLOW.md), [Execution Contract](./execution/TEAM_EXECUTION_CONTRACT.md), [Integration Playbook](./execution/INTEGRATION_PLAYBOOK.md).
>
> **Project context:** RAV-01 — Real2Sim Studio  
> **MVP domain:** Warehouse / Indoor AMR  
> **Simulator:** NVIDIA Isaac Sim  
> **Dataset chính đã chọn:** **TorWIC-SLAM — Toronto Warehouse Incremental Change SLAM Dataset**

---

## Bảng thuật ngữ (Glossary)

- **Traversal (Chuyến đi):** Là sự kiện thực tế. Nó bao hàm tất cả mọi thứ thu được trong chuyến đi đó (file video, file điểm LiDAR, file thông số). Bạn mở máy tính lên, bạn sẽ thấy một thư mục tên là Traversal 1.
- **Trajectory (Quỹ đạo):** Là đường nét hình học ghi lại chuyển động. Nó chỉ là một tập hợp các con số tọa độ (x, y, z) cho biết trong cái Traversal đó, cái camera đã vẽ ra đường đi như thế nào trong không gian. Nó thường chỉ là một file văn bản (như traj_gt.txt) nằm bên trong thư mục Traversal.
- **Pipeline:** Chuỗi các bước xử lý liên tiếp nhau trong hệ thống phần mềm, đầu ra của bước trước là đầu vào của bước sau.
- **Preprocessing (Tiền xử lý):** Quá trình làm sạch, chuẩn hóa, hoặc gộp dữ liệu trước khi đưa vào luồng xử lý chính.
- **Methodology (Phương pháp luận):** Cách thức và quy tắc tiến hành đánh giá để đảm bảo tính khoa học, khách quan và không bị rò rỉ dữ liệu (data leakage).
- **Benchmark:** Đánh giá hiệu năng và chất lượng của hệ thống bằng các thước đo định lượng so với một tiêu chuẩn chuẩn xác.
- **Ground truth:** Dữ liệu gốc chuẩn xác (thường do con người gán nhãn hoặc thiết bị chuyên dụng đo lường) dùng làm "đáp án" để so sánh với kết quả dự đoán.
- **Reconstruction (Tái tạo):** Quá trình tính toán, dựng lại không gian 3D từ các dữ liệu cảm biến (như ảnh 2D, LiDAR).
- **Modality (Dạng dữ liệu):** Các loại dữ liệu đầu vào khác nhau thu từ các cảm biến (ví dụ: ảnh RGB, điểm LiDAR, thông số IMU).
- **Calibration (Hiệu chuẩn):** Đóng gói các thông số nội hàm (intrinsics) của cảm biến hoặc vị trí tương đối giữa các cảm biến với nhau (extrinsics).
- **Collider / Occupancy / Free-space:** Các thuật ngữ biểu diễn không gian vật lý trong giả lập: mô tả vùng không gian có vật cản (có thể xảy ra va chạm) và vùng trống (robot có thể di chuyển).
- **Metric scale:** Tỷ lệ kích thước thật (tính bằng mét, centimet thay vì đơn vị vô hướng không xác định).

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

# 2. Nguồn chính thức

## 2.1 Repository chính thức

**GitHub:**  
https://github.com/Viky397/TorWICDataset

Repository này chứa cả TorWIC-Mapping và TorWIC-SLAM, mô tả cấu trúc dataset, sensor, scenario, FAQ, paper và terms of use.

## 2.2 Dataset download

**Google Drive chính thức được link từ repository:**  
https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ?usp=sharing

Không nên tải toàn bộ root ngay. Xem mục **TorWIC-SLAM** và chỉ tải traversal/modality cần thiết.

## 2.3 Paper liên quan

**POV-SLAM: Probabilistic Object-Aware Variational SLAM in Semi-Static Environments**  
Robotics: Science and Systems (RSS), 2023  
DOI: https://doi.org/10.15607/RSS.2023.XIX.069

Proceedings:  
https://roboticsproceedings.org/rss19/p069.html

arXiv:  
https://arxiv.org/abs/2307.00488

## 2.4 License / Terms of Use

License directory:  
https://github.com/Viky397/TorWICDataset/tree/main/License

Theo Dataset Terms của repository, nếu không có nhãn khác thì dataset được cung cấp theo:

> **Creative Commons Attribution-NonCommercial 4.0 International — CC BY-NC 4.0**

kèm các Dataset Terms bổ sung.

Điều này phù hợp với project học thuật / competition hiện tại, nhưng **không nên mặc định rằng dataset có thể được dùng cho sản phẩm thương mại sau này**.

Terms cũng cấm sử dụng dataset để nhận dạng hoặc xâm phạm privacy của người vô tình xuất hiện trong dữ liệu.

---

# 3. Cẩn thận: TorWIC có hai dataset khác nhau

Repository TorWIC public hai bộ chính.

| Dataset | Năm | Sensor chính | Mục tiêu gốc | Phù hợp Real2Sim MVP? |
|---|---:|---|---|---|
| **TorWIC-Mapping** | 2022 | Intel RealSense D435i RGB-D + Hokuyo UAM501 **2D LiDAR** | Map maintenance / change detection | Không phải lựa chọn chính |
| **TorWIC-SLAM** | 2023 | 2× Azure Kinect RGB-D + Ouster OS1-128 **3D LiDAR** | SLAM trong warehouse thay đổi theo thời gian | **Có — lựa chọn chính** |

Khi nói trong PRD, Evaluation Plan hoặc source code, team nên dùng tên đầy đủ:

> **TorWIC-SLAM — Toronto Warehouse Incremental Change SLAM Dataset**

Không nên chỉ ghi `TorWIC` vì dễ nhầm với TorWIC-Mapping.

---

# 4. TorWIC-SLAM là gì?

TorWIC-SLAM là dataset thực tế thu trong một facility/warehouse của Clearpath Robotics.

Dataset được thu trên **OTTO 100 Autonomous Mobile Robot**, robot được người vận hành điều khiển từ xa ở tốc độ đi bộ.

Sensor chính gắn trên platform gồm:

- **2× Azure Kinect RGB-D cameras**;
- **Ouster OS1-128 3D LiDAR**;
- IMU đi kèm camera;
- dữ liệu base/robot bổ sung trong raw ROS bag.

Dataset có:

- **20 trajectories**;
- **3 scenarios**;
- thu trong **3 ngày khác nhau**;
- trải dài khoảng **4 tháng**;
- các traversal đi qua warehouse theo đường định trước, clockwise/counter-clockwise;
- robot bắt đầu gần cùng origin của map frame.

Ý tưởng nghiên cứu ban đầu là quan sát một warehouse có các thay đổi semi-static theo thời gian, ví dụ vật thể bị di chuyển, xuất hiện hoặc biến mất giữa các lần traversal.

Điều này rất phù hợp với hướng Real2Sim vì project của chúng ta cũng quan tâm tới:

```text
real warehouse
→ reconstruct
→ object-aware scene
→ thay đổi layout
→ kiểm tra ảnh hưởng trong simulation
```

---

# 5. Sensor và ground truth quan trọng

## 5.1 RGB

Dataset có hai stream RGB:

```text
image_left/
image_right/
```

được lấy từ hai Azure Kinect cameras.

Với MVP hiện tại, primary RGB path của Real2Sim không cần stereo, vì vậy **chỉ cần dùng `image_left/` trước**.

## 5.2 Depth

Có:

```text
depth_left/
depth_right/
```

là RGB-aligned depth images từ Azure Kinect.

Project của chúng ta hiện **không chọn RGB-D làm MVP input contract**, nên depth không cần tải trong bring-up đầu tiên.

Có thể tải sau để:

- debug geometry;
- auxiliary evaluation;
- nghiên cứu thêm nếu RGB-only geometry quá yếu.

## 5.3 3D LiDAR

Có folder:

```text
lidar/
├── 0000.pcd
├── 0001.pcd
├── ...
```

mỗi file là một 3D scan từ **Ouster OS1-128**.

Đây là **raw per-frame / per-timestamp scans**, chưa phải đúng input contract cuối cùng của Real2Sim Studio.

Real2Sim MVP của chúng ta nhận:

```text
registered / fused LiDAR point cloud
```

chứ không claim hỗ trợ:

```text
raw LiDAR sequence
→ LiDAR odometry
→ SLAM
→ loop closure
→ global map optimization
```

Vì vậy cần có một bước **dataset preprocessing bên ngoài product boundary** để tạo point cloud đã hợp nhất.

## 5.4 Ground-truth map

Dataset cung cấp:

```text
groundtruth_map.ply
```

Đây là một điểm rất giá trị.

Ground-truth 3D warehouse map được tạo bằng **Leica MS60 Total Station**. Các sub-scans được xử lý và ghép bằng Leica Cyclone Register 360.

Tác giả mô tả ground-truth scan ở mức **centimetre-level accuracy**.

Đối với project chúng ta, đây là reference để benchmark geometry như:

- Chamfer Distance;
- Geometry Precision;
- Geometry Recall;
- Geometry F1 ở distance threshold;
- metric/distance errors.

## 5.5 Ground-truth trajectory

Mỗi traversal có:

```text
traj_gt.txt
```

chứa ground-truth pose của Ouster OS1-128 LiDAR.

Tác giả tạo các poses này bằng cách **align LiDAR scans với ground-truth 3D map**.

Điểm này rất hữu ích để benchmark pose/SfM, nhưng đồng thời tạo ra một **data leakage risk** nếu dùng không cẩn thận. Xem mục Benchmark Methodology bên dưới.

## 5.6 Calibration

Dataset có:

```text
calibrations.txt
```

chứa intrinsic/extrinsic calibration của camera và quan hệ với LiDAR.

Theo FAQ chính thức:

- Azure Kinect RGB cameras được calibrate bằng Matlab camera calibration toolbox;
- extrinsic giữa camera và Ouster được xác định bằng alignment giữa depth và LiDAR trong calibration session.

Đây là dữ liệu rất hữu ích cho project vì MVP **không muốn tự xây full automatic RGB–LiDAR calibration**.

## 5.7 Timestamp / synchronization

Mỗi traversal có:

```text
frame_times.txt
```

để liên kết timestamp giữa RGB, depth, segmentation và LiDAR.

Hai Azure Kinect dùng master/subordinate setup và camera + Ouster được synchronize bằng **PTP (Precision Time Protocol)**.

---

# 6. Cấu trúc TorWIC-SLAM chính thức

Cấu trúc được mô tả trong repository gần như sau:

```text
TorWIC-SLAM/
│
├── groundtruth_map.ply
├── calibrations.txt
│
└── WarehouseSequences/
    │
    ├── Scenario 1 Traversal 1/
    │   ├── image_left/
    │   ├── image_right/
    │   ├── depth_left/
    │   ├── depth_right/
    │   ├── segmentation_color_left/
    │   ├── segmentation_color_right/
    │   ├── segmentation_greyscale_left/
    │   ├── segmentation_greyscale_right/
    │   ├── lidar/
    │   ├── imu_left.txt
    │   ├── imu_right.txt
    │   ├── frame_times.txt
    │   └── traj_gt.txt
    │
    ├── Scenario 1 Traversal 2/
    │   └── ...
    │
    └── Scenario X Traversal Y/
        └── ...
```

---

# 7. Segmentation data có gì?

Dataset còn có semantic segmentation masks:

```text
segmentation_color_left/
segmentation_color_right/
segmentation_greyscale_left/
segmentation_greyscale_right/
```

Nhưng repository nói rõ các masks này **không hoàn hảo**. Chúng được tạo bằng một semantic segmentation model đã train trên warehouse images có human labels.

Do đó:

> Không được mặc định coi segmentation masks này là perfect ground truth cho object segmentation benchmark.

Repository cũng public một subset riêng cho fine-tuning, gồm **79 folders**, với các class warehouse như:

- driveable ground;
- wall/fence/pillar;
- rack/shelf;
- goods materials;
- fixed machinery;
- cart/pallet jack;
- pylons;
- person;
- forklift/truck;
- miscellaneous dynamic/static features.

MVP hiện tại **không cần tải subset này ngay**, vì chúng ta chưa quyết định fine-tune segmentation model.

---

# 8. TorWIC-SLAM phù hợp với **sản phẩm Real2Sim Studio của team** ở mức nào?

Phần này không đánh giá TorWIC-SLAM theo nghĩa chung chung là "có phù hợp với Real2Sim hay không". Mục tiêu là đối chiếu dataset với **product contract đã chốt của team**:

```text
Moving-camera RGB Video
        + optional Registered/Fused LiDAR
        ↓
Reconstruction
        ↓
Visual + Geometry
        ↓
Metric / Coordinate Alignment
        ↓
Candidate Object Identities
↓
Human Object Confirmation
↓
Scene Decomposition
↓
Environment + Independent SceneObjects
↓
Collider
↓
Scene Editing
↓
Candidate OpenUSD
        ↓
Isaac Sim Validation
        ↓
Approved Release
```

## 8.1 Đối chiếu trực tiếp với input/output contract của sản phẩm

| Product requirement | TorWIC-SLAM có gì? | Cách dùng trong project |
|---|---|---|
| Moving-camera RGB | `image_left/`, `image_right/` | Dùng `image_left/` làm RGB source chính; có thể đóng gói thành video để demo Web App |
| Registered/fused LiDAR | Dataset cung cấp `lidar/*.pcd` dạng scan sequence | **Phải preprocessing trước** thành một point cloud chung như `registered_lidar.ply`; raw scan sequence không được coi là direct product input |
| Metric scale | LiDAR và Leica map đều ở metric coordinates | Dùng để kiểm tra/neo metric scale; không dùng GT map như hidden input cho RGB-only prediction |
| RGB↔LiDAR calibration | Có `calibrations.txt` | Dùng cho transform/alignment experiments và dataset preprocessing |
| Geometry reference | Có `groundtruth_map.ply` từ Leica MS60 | Dùng **evaluation-only** để chấm geometry; không đưa vào prediction pipeline |
| Pose reference | Có `traj_gt.txt` | Dùng cho pose evaluation/debug; hoặc controlled LiDAR pre-fusion với dependency phải khai báo |
| Warehouse/mobile robot domain | Thu tại Clearpath warehouse trên OTTO 100 | Khớp trực tiếp với Warehouse/Indoor AMR MVP |
| Object-aware editing | Có RGB + semantic masks, nhưng không có perfect 3D instance GT | Có thể hỗ trợ development; benchmark object cần một manually annotated subset nhỏ |
| Collider/path validation | Không có sẵn collider GT hay path labels hoàn chỉnh | Cần derive occupancy/reference từ map hoặc annotate một tập start-goal nhỏ; không claim dataset cung cấp sẵn metric này |

## 8.2 Kết luận về độ phù hợp với **sản phẩm**

TorWIC-SLAM phù hợp rất tốt với phần **input → reconstruction → metric geometry → RGB/LiDAR integration → evaluation** của Real2Sim Studio. Nó đặc biệt mạnh ở việc cung cấp real warehouse data và reference geometry mà team không thể tự đo bằng thiết bị chuyên dụng.

Tuy nhiên nó **không phải một dataset hoàn chỉnh cho mọi feature của sản phẩm**. Dataset không cho sẵn:

- editable SceneObject graph của chúng ta;
- collider proxy ground truth;
- OpenUSD/Isaac scene;
- approval/review state;
- path-feasibility labels hoàn chỉnh;
- perfect 3D instance-object ground truth.

Các phần đó vẫn phải do Real2Sim Studio tạo ra hoặc team bổ sung annotation nhỏ phục vụ evaluation.

Vì vậy cách dùng đúng là:

```text
TorWIC-SLAM
    ↓
Real-world sensor input + reference data
    ↓
OUR Real2Sim Studio
    ↓
Structured / Editable / Physics-ready scene
```

chứ không phải coi TorWIC-SLAM là một scene simulator-ready đã hoàn chỉnh.

# 9. Dataset được dùng để làm gì trong project?

TorWIC-SLAM không chỉ có một vai trò.

## 9.1 Public sample data cho app

App có thể có:

```text
Try Sample Scene
→ TorWIC Warehouse Sample
```

User không cần upload dữ liệu riêng mà vẫn có thể thử:

- mở reconstructed scene;
- xem Visual/Geometry/Collider;
- chọn object;
- chỉnh transform;
- chạy validation.

Không nhất thiết public toàn bộ raw dataset trong app; có thể chỉ dùng một derived/demo subset theo đúng license.

## 9.2 Demo input

Một traversal/subset cố định có thể dùng để chứng minh:

```text
real public dataset
→ Real2Sim pipeline
→ reconstructed scene
→ editable SceneObjects
→ OpenUSD
→ Isaac validation
```

## 9.3 Development / smoke testing

Tạo một subset nhỏ cố định để developer/agent chạy nhanh sau mỗi thay đổi pipeline.

Ví dụ:

```text
torwic_dev_small/
├── image_left/      # chỉ sampling một số frame
├── lidar/
└── metadata/
```

Dùng để test:

- loaders;
- frame preprocessing;
- COLMAP;
- 3DGS;
- mesh generation;
- LiDAR processing;
- Scene IR;
- OpenUSD exporter.

## 9.4 Benchmarking

TorWIC-SLAM là **real-world quantitative benchmark chính** của MVP.

Các nhóm metric có thể đo:

### Visual

- PSNR;
- SSIM;
- LPIPS.

### Pose

- ATE;
- RPE.

### Geometry

- Chamfer Distance;
- Geometry Precision;
- Geometry Recall;
- Geometry F1 @ chosen distance thresholds.

### Metric fidelity

- Scale Error;
- independent Distance MAE/RMSE.

Lưu ý: collision/path/object metrics cần additional annotation hoặc derived evaluation references; không nên mặc định TorWIC có sẵn perfect GT cho mọi metric đó.

## 9.5 Regression testing

Giữ một tập traversal cố định giữa các version:

```text
v0.1
v0.2
v0.3
```

rồi chạy cùng benchmark để phát hiện regression.

Ví dụ:

```text
v0.2 Geometry F1@5cm = 0.82
v0.3 Geometry F1@5cm = 0.73
```

Code có thể vẫn chạy nhưng chất lượng đã giảm.

## 9.6 Baseline / threshold setting

Không nên tự đặt threshold như:

```text
PSNR >= 25
Geometry F1 >= 0.8
runtime <= 30 min
```

trước khi có baseline.

Dùng dataset để:

```text
run baseline
→ collect distribution
→ understand difficulty
→ propose target
→ lock acceptance threshold later
```

---

# 10. Chính xác cần tải gì cho MVP?

## Phase 0 — Bring-up: chỉ tải 1 traversal

### BẮT BUỘC tải

#### 1. `image_left/`

Dùng làm RGB input chính.

```text
image_left/
├── 0000.png
├── 0001.png
├── ...
```

Dùng cho:

```text
frame selection
→ COLMAP/SfM
→ camera poses
→ 3DGS
→ RGB-derived geometry
```

Không cần `image_right/` trong baseline đầu tiên.

---

#### 2. `lidar/`

Dùng làm nguồn 3D LiDAR.

```text
lidar/
├── 0000.pcd
├── 0001.pcd
├── ...
```

Nhưng lưu ý:

> Đây là sequence scans; Real2Sim Studio MVP không nhận raw LiDAR sequence làm input trực tiếp.

Ta sẽ dùng dataset preprocessing để tạo:

```text
registered_lidar.ply
```

trước khi đưa vào product LiDAR path.

---

#### 3. `frame_times.txt`

Dùng để match timestamp giữa RGB và LiDAR khi cần.

---

#### 4. `traj_gt.txt`

Dùng cho:

- pose evaluation;
- controlled LiDAR preprocessing;
- debugging.

**Không được coi nó là ordinary product input cho RGB-only benchmark.**

---

#### 5. `calibrations.txt`

Global file, cần tải ngay.

Dùng cho:

- camera intrinsics;
- camera extrinsics;
- RGB ↔ LiDAR transforms;
- evaluation/alignment experiments.

---

#### 6. `groundtruth_map.ply`

Global file, cần tải để benchmark geometry.

Nên đặt riêng:

```text
evaluation_only/groundtruth_map.ply
```

và pipeline production không được tự động đọc file này.

---

# 11. Chưa cần tải gì trong lần đầu?

## `image_right/`

Chưa làm stereo reconstruction nên không cần.

## `depth_left/`, `depth_right/`

RGB-D không nằm trong MVP input contract hiện tại.

Chỉ tải nếu sau này cần auxiliary geometry/debug.

## `segmentation_color_*`

Không cần cho automatic-object baseline.

## `segmentation_greyscale_*`

Không dùng làm perfect GT vì mask do model tạo và không hoàn hảo.

Có thể tải sau cho debug/auxiliary experiment.

## `imu_left.txt`, `imu_right.txt`

Project không làm visual-inertial SLAM trong MVP.

## Raw ROS bags / wheel odometry

Không cần vì project không xây full SLAM stack từ raw robot sensors.

## Fine-tuning segmentation subset

Không tải trừ khi team quyết định thực sự fine-tune segmentation model.

---

# 12. Có cần sắp xếp lại folder không? — Có, nhưng **không sửa source gốc**

Không nên để code Real2Sim đọc trực tiếp một cấu trúc Google Drive lộn xộn hoặc chỉnh sửa file tải về tại chỗ. Team nên giữ nguyên source download và tạo một lớp dữ liệu normalized/derived bên cạnh.

Cấu trúc đề xuất:

```text
data/
└── torwic_slam/
    │
    ├── README_DATASET.md
    ├── dataset_manifest.yaml
    │
    ├── raw/                         # immutable: giữ nguyên file tải về
    │   ├── global/
    │   │   ├── calibrations.txt
    │   │   └── groundtruth_map.ply
    │   │
    │   └── scenario_x_traversal_y/
    │       ├── image_left/
    │       ├── lidar/
    │       ├── frame_times.txt
    │       └── traj_gt.txt
    │
    ├── normalized/                  # format đã chuẩn hóa cho pipeline
    │   └── scenario_x_traversal_y/
    │       ├── rgb_frames/
    │       ├── timestamps.csv
    │       ├── calibration.json
    │       └── coordinate_metadata.json
    │
    ├── derived/                     # artifact do team tạo, có thể regenerate
    │   └── scenario_x_traversal_y/
    │       ├── demo_video/
    │       │   └── traversal.mp4
    │       ├── lidar/
    │       │   └── registered_lidar.ply
    │       ├── dev_subset/
    │       └── benchmark_split.json
    │
    └── evaluation_only/             # tuyệt đối không auto-feed vào product pipeline
        ├── groundtruth_map.ply
        ├── traj_gt_reference/
        └── manual_annotations/
```

## 12.1 Vì sao phải tách `raw / normalized / derived / evaluation_only`?

- **`raw/`**: giữ bằng chứng dataset gốc, dễ audit và regenerate.
- **`normalized/`**: giúp code của team không phụ thuộc chặt vào naming/layout của TorWIC.
- **`derived/`**: chứa video demo, fused LiDAR, subsets; có thể xóa và tạo lại.
- **`evaluation_only/`**: tạo boundary chống leakage giữa dữ liệu input và ground truth.

## 12.2 Có cần copy `groundtruth_map.ply` hai nơi không?

Không bắt buộc. Có thể chỉ giữ file thật trong `raw/global/` và tạo symlink/reference logic vào `evaluation_only/`. Điểm quan trọng là **code reconstruction không được quét toàn bộ `raw/global/` một cách tự động**.

## 12.3 Có cần đưa dataset vào Git repo không?

Không. Git repo chỉ nên chứa:

```text
configs/
manifest/templates/
download-notes/
preprocessing scripts/
small metadata
```

Không commit RGB, PCD, PLY dung lượng lớn vào source repository.

# 13. Preprocessing cần làm gì trước khi dataset đi vào product?

Có. TorWIC-SLAM **không nên được feed nguyên trạng vào tất cả stage của Real2Sim Studio**. Preprocessing phải phân biệt rõ giữa:

1. **dataset normalization** — chỉ đổi format/tổ chức dữ liệu;
2. **derived product input creation** — ví dụ tạo video hoặc registered LiDAR;
3. **evaluation preparation** — tạo held-out split, GT reference, annotations;
4. **prediction/reconstruction** — đây mới là phần của Real2Sim product pipeline.

## 13.1 RGB preprocessing

Source:

```text
raw/.../image_left/*.png
```

Các bước nên làm:

```text
validate image sequence
→ đọc timestamps
→ kiểm tra missing/corrupt frame
→ optional temporal subsampling
→ tạo benchmark train/held-out split
→ copy/symlink selected frames vào normalized/rgb_frames
```

### Dùng cho benchmark

Giữ original images để chạy COLMAP/3DGS và visual metrics, tránh thêm compression artifact.

### Dùng cho Web App / demo input

Có thể tạo thêm:

```text
image_left/*.png
→ FFmpeg
→ traversal.mp4
```

`traversal.mp4` là **derived demo asset**, không thay thế original frames trong benchmark.

## 13.2 Calibration preprocessing

Source:

```text
calibrations.txt
```

Nên parse một lần thành format nội bộ rõ ràng:

```text
normalized/calibration.json
```

bao gồm tối thiểu:

- camera intrinsics;
- camera extrinsics;
- transform camera ↔ LiDAR;
- coordinate-frame names;
- unit convention.

Lợi ích là các backend khác nhau không phải tự parse file text của TorWIC theo cách riêng.

## 13.3 Timestamp normalization

Source:

```text
frame_times.txt
```

Nên chuyển thành một bảng chuẩn như:

```text
timestamps.csv
```

để hỗ trợ mapping:

```text
RGB frame ↔ LiDAR scan
```

khi team chạy RGB+LiDAR integration.

## 13.4 LiDAR preprocessing — phần quan trọng nhất

Source của TorWIC:

```text
lidar/*.pcd
```

Nhưng product MVP của chúng ta nhận:

```text
registered/fused point cloud
```

Do đó cần một **offline dataset-preparation step**:

```text
lidar/*.pcd
+
known/declared poses for dataset preparation
        ↓
transform scans into a common frame
        ↓
merge
        ↓
remove invalid points / optional outlier filtering
        ↓
optional voxel downsample
        ↓
registered_lidar.ply
```

`registered_lidar.ply` mới là input phù hợp cho Real2Sim LiDAR path.

### Cần ghi rõ dependency

Nếu `traj_gt.txt` được dùng để transform/fuse LiDAR scans thì manifest phải ghi:

```yaml
trajectory_gt_used_for_lidar_prefusion: true
```

và output đó chỉ nên dùng cho:

- LiDAR ingestion/integration test;
- RGB+LiDAR unified-scene test;
- product functionality demonstration.

Không dùng output đó để claim một **independent Leica geometry benchmark** mà không giải thích dependency.

## 13.5 Coordinate normalization

Trước khi đưa derived data vào Scene IR cần ghi rõ:

- metric unit;
- up-axis;
- handedness;
- map/world frame;
- transform source;
- whether scale is native metric or calibrated.

Nên tạo:

```text
coordinate_metadata.json
```

để tránh lỗi về sau khi export OpenUSD/Isaac.

## 13.6 Evaluation preprocessing

Tạo các artifact riêng:

```text
benchmark_split.json
heldout_frame_ids.txt
manual_annotations/*.json
start_goal_pairs.json   # nếu team benchmark path
```

Những file này thuộc evaluation harness, không phải raw product input.

## 13.7 Những preprocessing **không cần** làm trong MVP

Không cần tự triển khai:

- LiDAR SLAM;
- loop closure;
- raw visual-inertial SLAM;
- RGB-D fusion pipeline;
- automatic sensor calibration;
- regenerate semantic masks cho toàn dataset.

Nếu một preprocessing step bắt đầu biến thành một research project riêng, cần kiểm tra lại xem nó có thực sự thuộc product scope hay không.

# 14. Benchmark methodology — tránh data leakage

Đây là phần quan trọng nhất khi dùng TorWIC.

## 14.1 Vì sao có nguy cơ leakage?

`traj_gt.txt` không phải hoàn toàn độc lập với `groundtruth_map.ply`.

Theo tác giả, LiDAR ground-truth poses được tạo bằng cách align Ouster scans với ground-truth map.

Nếu ta làm:

```text
LiDAR scans
+
traj_gt.txt
        ↓
fused LiDAR prediction
        ↓
compare với groundtruth_map.ply
```

rồi gọi đó là một **independent geometry benchmark**, methodology sẽ yếu vì prediction preprocessing đã dùng pose được tạo dựa trên cùng ground-truth map.

Không phải lỗi của dataset; chỉ là cần ghi đúng protocol.

---

## 14.2 Quy tắc sử dụng `traj_gt.txt` và `groundtruth_map.ply` cho đúng methodology

Đây là contract mà team nên tuân thủ để tránh data leakage và tránh claim sai mức độ độc lập của benchmark.

### Nguyên tắc 1 — RGB-only benchmark phải giấu toàn bộ ground truth khỏi prediction pipeline

Trong Track A, prediction pipeline chỉ được dùng RGB input (và camera intrinsics nếu protocol đã công bố trước). Không cho reconstruction đọc:

```text
traj_gt.txt
groundtruth_map.ply
lidar/
depth_*
segmentation_*
```

Sau khi reconstruction hoàn tất và artifacts đã được đóng băng, evaluator mới được đọc `traj_gt.txt` và `groundtruth_map.ply` để tính metrics.

### Nguyên tắc 2 — Có thể dùng `traj_gt.txt` để tạo `registered_lidar.ply`, nhưng phải coi đó là dataset preparation có sử dụng GT

Vì product MVP không nhận raw LiDAR scan sequence, team có thể dùng:

```text
lidar/*.pcd
+
traj_gt.txt
        ↓
transform về common frame
        ↓
merge / filter / downsample
        ↓
registered_lidar.ply
```

Cách này **được phép** cho các mục đích:

- kiểm thử LiDAR ingestion;
- kiểm thử RGB+LiDAR unified scene;
- kiểm thử Scene IR / collider / OpenUSD / Isaac;
- demo product flow với input registered/fused LiDAR đúng contract của MVP.

Nhưng manifest/report phải ghi rõ:

```yaml
trajectory_gt_used_for_lidar_prefusion: true
```

### Nguyên tắc 3 — Không được dùng LiDAR đã pre-fuse bằng `traj_gt.txt` rồi gọi việc so với Leica map là benchmark hình học hoàn toàn độc lập

Không nên viết:

> “LiDAR geometry được benchmark độc lập với Leica ground truth.”

nếu chính `traj_gt.txt` đã được dùng để tạo fused cloud và các pose GT này được suy ra bằng alignment vào Leica map.

Trong trường hợp đó, cách mô tả đúng là:

> “RGB+LiDAR integration/functionality evaluation using TorWIC-provided ground-truth poses for offline LiDAR pre-fusion.”

Nếu vẫn tính Chamfer/F1 so với Leica map thì kết quả chỉ nên dùng như **diagnostic/reference consistency metric**, không phải bằng chứng độc lập về khả năng tự đăng ký LiDAR của sản phẩm.

### Nguyên tắc 4 — `groundtruth_map.ply` chỉ nằm ở evaluation side

`groundtruth_map.ply` không được:

- đưa vào reconstruction backend;
- dùng để sửa mesh prediction bằng tay trước khi chấm;
- dùng để chọn hyperparameter dựa trực tiếp trên final benchmark scene rồi lại báo đó là test result;
- dùng để tạo product input rồi sau đó coi là unseen GT.

Nó được phép dùng để:

- tính geometry metrics sau prediction;
- tạo evaluation-only occupancy/free-space reference;
- chọn các khoảng cách kiểm tra độc lập;
- hỗ trợ error analysis sau benchmark.

### Nguyên tắc 5 — Calibration data không đồng nghĩa với ground-truth geometry leakage

`calibrations.txt` có thể được dùng trong RGB+LiDAR path vì calibration giữa sensor là metadata hợp lệ của dataset. Tuy nhiên protocol phải ghi rõ team sử dụng:

- camera intrinsics nào;
- camera↔LiDAR extrinsics nào;
- coordinate convention nào.

Đây khác với việc đưa `groundtruth_map.ply` vào prediction pipeline.

### Nguyên tắc 6 — Tách code path bằng filesystem và config

Nên enforce:

```text
product_input/
    rgb/
    registered_lidar.ply
    calibration.json

evaluation_only/
    groundtruth_map.ply
    traj_gt.txt
    manual_annotations/
```

Evaluation runner được quyền đọc cả hai phía; product/reconstruction runner chỉ đọc `product_input/`.

### Bảng quyết định nhanh

| Tình huống | Dùng `traj_gt`? | Dùng Leica map trong prediction? | Có thể claim gì? |
|---|---:|---:|---|
| RGB-only reconstruction benchmark | Không | Không | Benchmark pose/visual/geometry độc lập sau prediction |
| Pose evaluation sau RGB reconstruction | Chỉ evaluator dùng | Không | ATE/RPE so với reference trajectory |
| Offline LiDAR pre-fusion cho product input | Có | Không trực tiếp | LiDAR/RGB+LiDAR integration test |
| Fused LiDAR bằng `traj_gt` rồi so Leica | Có | Không trực tiếp | Diagnostic/reference consistency; **không claim independent LiDAR mapping benchmark** |
| Geometry evaluation của RGB-only mesh | Không trong prediction | Chỉ evaluator dùng | Chamfer/P-R/F1 với independent reference geometry |
| Derive occupancy/path labels | Không bắt buộc | Chỉ evaluation preprocessing | Path benchmark nếu reference protocol được khóa và công bố |

### Quy tắc báo cáo tối thiểu

Mỗi benchmark run nên log ít nhất:

```yaml
input_modalities:
  rgb: true
  lidar: false

references_used_during_prediction:
  trajectory_gt: false
  groundtruth_map: false

references_used_during_preprocessing:
  trajectory_gt_for_lidar_prefusion: false

references_used_during_evaluation:
  trajectory_gt: true
  groundtruth_map: true
```

Nếu một cờ thay đổi, tên track và claim trong report cũng phải thay đổi tương ứng.

---

# 15. Track A — RGB-only quantitative benchmark

Phần này phân biệt rạch ròi 2 giao thức test cho luồng RGB:

1. **Product E2E Acceptance (Test Toàn trình Sản phẩm):** Bắt buộc test toàn bộ luồng. Đầu vào phải là Video `MP4` → upload Web/API → giải mã bằng FFmpeg → Reconstruction pipeline. 
2. **Reconstruction Backend Benchmark (Test Lõi Thuật toán AI):** Được quyền dùng trực tiếp tập ảnh `PNG` (từ `image_left/`) đưa thẳng vào COLMAP để tránh nhiễu do nén video.

Vì luồng RGB không có thông tin không gian thực tế, Track A được chia thành 2 nhánh con:

## Track A1: Scale-free benchmark (Không có tỷ lệ thực)

Chỉ đánh giá chất lượng hình ảnh, hình học tỷ đối, hình dáng và pose.
- **Input:** Tập ảnh `image_left/` hoặc video `traversal.mp4`.
- **Pipeline:** RGB → Pose estimation → Visual Reconstruction → Prediction.
- **Evaluation:** Dùng công thức gióng hàng Sim(3) để so sánh với Ground Truth. *Không claim* (tuyên bố) khả năng đo đạc metric scale.

## Track A2: Product metric-scale benchmark (Có tỷ lệ thực)

Đánh giá khả năng của hệ thống khi chạy thực tế (cần đo chính xác mét).
- **Input:** Tập ảnh RGB **cộng thêm MỘT khoảng cách chuẩn được khai báo trước (Locked Anchor)** (ví dụ: khoảng cách giữa điểm A và B là 2 mét).
- **Pipeline:** RGB → Pose estimation → Reconstruction → Áp dụng scale từ Locked Anchor → Metric-ready Prediction.
- **Evaluation:** Kiểm tra khoảng cách ở các vùng hình học khác. **TUYỆT ĐỐI KHÔNG** dùng lại khoảng cách của Locked Anchor làm bài test (để tránh tự chấm điểm).

## Không cho reconstruction pipeline đọc
```text
lidar/
depth_left/
depth_right/
traj_gt.txt
groundtruth_map.ply
segmentation masks
```

## Evaluation-only (Dùng sau khi Prediction xong)
```text
traj_gt.txt
groundtruth_map.ply
```

### Metrics phù hợp
```text
Pose: ATE / RPE
Visual: PSNR / SSIM / LPIPS
Geometry: Chamfer, Precision / Recall / F1

Metric:
Scale Error
Distance MAE/RMSE
```

Nếu metric scale calibration dùng một khoảng cách lấy từ reference map, khoảng cách đó phải được ghi rõ là **calibration anchor** và không được tái sử dụng làm evaluation distance.

---

# 16. Track B — RGB + LiDAR integration test

Mục đích chính:

> Chứng minh Real2Sim có thể sử dụng RGB + registered LiDAR để tạo unified metric scene.

Track B đồng thời cung cấp **P0 LiDAR Contribution Evidence** cho PRD AC-04. Track này không biến RGB + Registered LiDAR thành một full P0 release path thứ hai và không yêu cầu một Track LiDAR-only riêng trong P0.

Input product:

```text
immutable/checksummed RGB artifacts
của cùng scene/traversal
+
registered_lidar.ply
```

RGB Visual, pose hoặc RGB-derived Geometry có thể được reuse từ Primary RGB Product Path mà không cần chạy lại toàn bộ RGB reconstruction. Các artifact được reuse và LiDAR bắt buộc phải thuộc cùng scene/traversal, có checksum và manifest truy vết được.

## Minimum P0 LiDAR Contribution Evidence

- LiDAR ingestion;
- tạo `LiDARGeometryArtifact` theo shared artifact contract;
- coordinate/alignment integration với same-scene RGB artifacts;
- đưa artifact vào canonical/unified Scene IR;
- ghi provenance của input, artifact, transform và downstream consumer;
- chứng minh actual downstream use trong ít nhất một scene geometry, collider hoặc simulator validation.

Minimum evidence không yêu cầu mixed configuration hoàn thành full object correction, editing, review hoặc release parity với Primary RGB Product Path.

## Extended integration coverage

Các kiểm tra sau có giá trị nhưng không tự động là P0 gate của AC-04, trừ khi PRD sau này cố ý nâng chúng thành acceptance requirement:

- Visual ↔ Geometry inspection;
- collider generation ngoài minimum consumer đã chọn;
- OpenUSD export/load;
- Isaac checks;
- collision/path pipeline.

Nếu `registered_lidar.ply` được tạo bằng `traj_gt.txt`, **không nên claim đây là independent LiDAR geometry benchmark với Leica map**.

Nên gọi:

> **RGB+LiDAR integration / functionality evaluation**

hoặc ghi đầy đủ preprocessing dependency trong report.

---

# 17. Track C — Evaluation cho object / collider / path mà **không cần tự tạo synthetic dataset**

Team hiện không có scanner, LiDAR hardware, motion-capture system hoặc nguồn lực để xây một synthetic-data generation pipeline riêng. Vì vậy **Synthetic Warehouse không phải requirement của MVP**.

Các metric mà TorWIC không cung cấp sẵn perfect ground truth có thể xử lý bằng một evaluation subset nhỏ.

## 17.1 Object evaluation

Chọn một phần nhỏ của traversal đã khóa và tự annotate các object quan trọng cho use case warehouse, ví dụ:

- rack / shelf;
- pallet / cart;
- box / goods;
- fixed machine;
- obstacle.

Không cần annotate toàn dataset.

## 17.2 Collider / free-space evaluation

Có thể derive một reference occupancy/free-space representation từ `groundtruth_map.ply` theo một protocol cố định, sau đó so với occupancy/collider representation được sinh từ scene reconstruction.

Cần ghi rõ đây là **derived evaluation reference**, không phải native label có sẵn trong dataset.

## 17.3 Path-feasibility evaluation

Team có thể tạo một tập nhỏ các cặp:

```text
Start → Goal
```

trên reference occupancy và gán:

```text
CLEAR / BLOCKED
```

sau đó chạy cùng start-goal pairs trên scene do Real2Sim tạo ra để đo agreement / false-clear rate.

## 17.4 Synthetic data chỉ là optional future work

Nếu sau này có đủ compute/thời gian, synthetic scenes có thể hữu ích cho perfect-GT tests. Nhưng chúng **không phải dataset strategy bắt buộc của MVP hiện tại** và không nên làm chậm việc xây sản phẩm chính.

# 18. Object extraction benchmark

TorWIC có segmentation masks, nhưng masks chính trong sequence là model-generated và không hoàn hảo.

Do đó nếu cần đánh giá:

```text
Object Recall
AP50
instance IoU
```

cách tốt hơn cho MVP là:

1. chọn một số frame/scene nhỏ;
2. team tự annotate một subset object quan trọng;
3. chỉ annotate các class liên quan warehouse use case, ví dụ:
   - rack/shelf;
   - pallet/cart;
   - box/goods;
   - fixed machinery;
   - obstacle;
4. giữ annotation đó trong `evaluation_only/`.

Không cần annotate toàn dataset.

---

# 19. Held-out view protocol cho visual reconstruction

Không nên đánh giá PSNR/SSIM/LPIPS bằng chính toàn bộ frame đã dùng train reconstruction.

Nên chia:

```text
input RGB sequence
├── reconstruction/train views
└── held-out evaluation views
```

Held-out views nên có khác biệt viewpoint đủ ý nghĩa, không chỉ chọn frame liền kề gần như giống nhau.

Metrics:

```text
PSNR ↑
SSIM ↑
LPIPS ↓
```

---

# 20. Cần tải bao nhiêu traversal?

## Phase 0 — Bring-up

**1 traversal**.

Mục đích:

- inspect data;
- test directory parser;
- first COLMAP run;
- first 3DGS run;
- first geometry output;
- LiDAR preprocessing;
- OpenUSD/Isaac smoke test.

## Phase 1 — Development

**2–3 traversals**.

Mục đích:

- development;
- regression testing;
- tránh overfit pipeline vào đúng một sequence.

## Phase 2 — Final MVP benchmark

Khoảng **3–5 locked traversals** nếu compute/storage cho phép.

Mỗi traversal phải được chọn trước và không đổi tùy kết quả để tránh cherry-picking.

---

# 21. Chọn traversal đầu tiên theo tiêu chí nào?

Hiện chưa chốt một `Scenario X Traversal Y` cụ thể.

Không nên tự chọn ngẫu nhiên rồi commit luôn.

Traversal đầu nên đáp ứng:

- warehouse layout rõ ràng;
- nhiều rack/pallet/obstacle dễ nhận diện;
- phần lớn static;
- camera coverage tốt;
- không quá dài;
- ít người hoặc vật thể động;
- có đủ parallax/viewpoint variation;
- LiDAR coverage tốt;
- phù hợp demo CLEAR/BLOCKED path scenario.

Quy trình chọn:

```text
inspect 3–5 candidate traversals
        ↓
compare length / visual quality / object richness
        ↓
lock one bring-up traversal
        ↓
record choice in dataset_manifest.yaml
```

Không đổi traversal chỉ vì metric của một traversal khác đẹp hơn.

---

# 22. Dung lượng — lưu ý quan trọng

Repository chính thức không công bố rõ total size/per-traversal size trong README.

Một số nguồn thứ cấp có đưa ra ước lượng toàn TorWIC-SLAM rất lớn (hàng trăm GB), nhưng **không nên ghi con số đó như official dataset size nếu chưa đo trực tiếp từ Drive**.

Vì vậy storage planning của team nên dựa trên download thực tế:

```text
Step 1: tải selective modalities của 1 traversal
Step 2: đo dung lượng thực tế
Step 3: tính storage cho 3–5 traversals
Step 4: chỉ tải thêm khi thực sự cần
```

Không cần mirror toàn bộ dataset cho MVP 4 tuần.

---

# 23. Checklist download lần đầu

## Tải ngay

- [ ] `calibrations.txt`
- [ ] `groundtruth_map.ply`
- [ ] chọn **1 traversal**
- [ ] `<traversal>/image_left/`
- [ ] `<traversal>/lidar/`
- [ ] `<traversal>/frame_times.txt`
- [ ] `<traversal>/traj_gt.txt`

## Chưa tải

- [ ] `image_right/`
- [ ] `depth_left/`
- [ ] `depth_right/`
- [ ] `segmentation_color_left/`
- [ ] `segmentation_color_right/`
- [ ] `segmentation_greyscale_left/`
- [ ] `segmentation_greyscale_right/`
- [ ] `imu_left.txt`
- [ ] `imu_right.txt`
- [ ] raw ROS bags
- [ ] 79-folder fine-tuning segmentation subset

---

# 24. Dataset manifest team nên lưu

Ví dụ:

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

---

# 25. Dataset strategy thực tế cho project của team

Không nên cố bắt một dataset làm tất cả mọi nhiệm vụ, nhưng cũng không cần tự tạo thêm một synthetic dataset nặng nề.

Chiến lược thực tế cho MVP:

```text
TorWIC-SLAM locked subsets
    ↓
main real-world development + benchmark dataset

TorWIC small manual-annotation subset
    ↓
object / collider / path evaluation where native GT is insufficient

Team smartphone capture (optional but useful)
    ↓
product demo trên dữ liệu tự quay + workflow/usability timing
```

## 25.1 TorWIC-SLAM là dataset chính

Dùng cho:

- development;
- smoke/regression testing;
- RGB-only reconstruction benchmark;
- RGB+LiDAR integration;
- metric/geometry evaluation;
- sample scene/demo input nếu license/redistribution policy được tuân thủ.

## 25.2 Manual annotation chỉ làm ở mức nhỏ

Chỉ tạo annotation cho đúng phần cần đo; không xây lại một annotation dataset quy mô lớn.

## 25.3 Team capture không thay benchmark

Dữ liệu điện thoại của team dùng để chứng minh product chạy ngoài dataset nghiên cứu và để đo workflow/human effort. Vì không có Leica-like GT, nó không thay TorWIC cho geometry benchmark.

# 26. Mapping dataset → từng Pipeline ID cụ thể của Real2Sim Studio

Đây là phần quan trọng nhất để cả team biết **đã tải file nào thì file đó được dùng ở đâu, dùng như thế nào, và output của stage là gì**.

| Pipeline ID | Loại | Dữ liệu TorWIC sử dụng | Preprocessing | Cách sử dụng | Output |
|---|---|---|---|---|---|
| **DP-DATASET-INTAKE** | Offline Dataset Preparation | `image_left/`, `lidar/`, `frame_times.txt`, `calibrations.txt` | integrity check, count files, parse metadata | Xác nhận subset hợp lệ trước khi chạy heavy pipeline | dataset manifest + validation report |
| **DP-PRIVACY-SCREEN** | Offline Dataset Preparation | sampled frames | detect faces/license plates | Preliminary screening: sampled frames. Before persistent/public/demo use: inspect all selected frames OR use an already-anonymized approved copy. If unresolved: quarantine / reject. | privacy validation report |
| **ST-INPUT-VALIDATE** | Product Runtime | `image_left/` hoặc derived `traversal.mp4` | optional sampling / video encode | Web/CLI nhận RGB input | normalized RGB job input |
| **ST-FRAME-EXTRACT** | Product Runtime | original `image_left/` hoặc `traversal.mp4` | nếu dùng image sequence thì không cần decode video; nếu dùng video thì extract frames | Chuẩn bị frame cho SfM/3DGS | selected RGB frames |
| **ST-CAMERA-POSE** | Product Runtime | selected `image_left/`; optional camera intrinsics từ `calibrations.txt` | held-out split phải được khóa trước | COLMAP/SfM estimate camera poses | camera poses + sparse reconstruction |
| **ST-VISUAL-RECON** | Product Runtime | RGB training frames + estimated poses | image normalization nếu backend yêu cầu | train/build 3DGS visual representation | Gaussian visual artifact |
| **ST-RGB-GEOMETRY** | Product Runtime | RGB frames + poses | backend-specific conversion | OpenMVS/mesh backend tạo geometry từ RGB | RGB-derived mesh |
| **DP-LIDAR-PREFUSION** | Offline Dataset Preparation | `lidar/*.pcd`, `traj_gt.txt` nếu dùng controlled prefusion | transform, merge, filter, voxel downsample | **Nằm ngoài product runtime**; tạo registered point cloud đúng contract | `registered_lidar.ply` |
| **ST-LIDAR-INGEST** | Product Runtime | `registered_lidar.ply` | coordinate/unit validation, filter/crop, optional downsample | Reusable Registered LiDAR Branch; không phụ thuộc RGB và không tự alignment với RGB | `LiDARGeometryArtifact` |
| **ST-RGB-LIDAR-ALIGN** | Product Runtime, conditional | immutable/checksummed same-scene RGB artifacts, `LiDARGeometryArtifact`, `calibrations.txt` | parse known transform. P1 only: optional manual/semi-auto refinement | Chỉ chạy khi cả RGB và LiDAR có mặt; xác nhận transform trước unified composition | aligned RGB/LiDAR artifacts + transform provenance |
| **ST-METRIC-CANONICALIZE** | Product Runtime | aligned RGB/LiDAR artifacts cho mixed configuration; RGB reconstruction + locked anchor cho RGB-only | không dùng Leica GT như hidden production input | Chạy sau `ST-RGB-LIDAR-ALIGN` trong mixed configuration; xác nhận scene ở đúng đơn vị thực | metric-ready Scene IR |
| **ST-OBJECT-EXTRACT** | Product Runtime | RGB frames/visual reconstruction; optional TorWIC segmentation chỉ để debug | không feed model-generated masks vào benchmark baseline nếu muốn đánh giá fair | SAM2/proposal + multi-view grouping | candidate SceneObjects |
| **ST-OBJECT-CONFIRM** | Product Runtime | candidate objects; optional manual GT subset chỉ cho evaluator | manual annotations tách khỏi UI input | rename / confirm / ignore / merge / create missing object / reassign selected mask or geometry region | confirmed editable SceneObjects |
| **ST-SCENE-DECOMPOSE** | Product Runtime | candidate/confirmed objects + canonical geometry | object-to-geometry binding | Tách scene thành Environment + Independent SceneObjects | Environment + Independent SceneObjects |
| **ST-COLLIDER** | Product Runtime | geometry per object / scene geometry | simplify / OBB / convex proxy | tạo Physics Representation | colliders |
| **ST-EDIT** | Product Runtime | Visual + Geometry + Collider | none ngoài runtime asset conversion | user move/rotate/hide/show object | updated Scene IR/version |
| **ST-PREFLIGHT** | Product Runtime | Scene IR + colliders | deterministic audit / warehouse rules | chạy preflight trước khi build/validate candidate | `preflight_report.json` |
| **ST-CANDIDATE-BUILD** | Product Runtime | Scene IR + geometry + colliders | coordinate conversion to USD conventions | IsaacSimAdapter build candidate package | candidate USD |
| **ST-ISAAC-VALIDATE** | Product Runtime | candidate USD | none ngoài simulator setup | load/collision/spawn/path checks | validation report |
| **EV-GEOMETRY** | Evaluation / Benchmark | `groundtruth_map.ply` **evaluation-only** | align evaluation frames only theo protocol công bố | compare prediction vs Leica reference | Chamfer / P-R-F1 / distance errors |
| **EV-POSE** | Evaluation / Benchmark | `traj_gt.txt` **evaluation-only** | convert LiDAR pose GT to camera frame nếu cần bằng calibration | compare SfM trajectory vs reference | ATE / RPE |
| **EV-VISUAL** | Evaluation / Benchmark | held-out `image_left/` | split before training | render held-out camera views | PSNR / SSIM / LPIPS |
| **EV-OBJECT** | Evaluation / Benchmark | manually annotated small subset | team annotation | compare candidate objects with held-out labels | Object Recall / AP/IoU if protocol supports |
| **EV-PATH** | Evaluation / Benchmark | derived reference occupancy + locked start-goal pairs | derive once and freeze | compare predicted CLEAR/BLOCKED | path F1 / unsafe false-clear rate |

## 26.1 Hai luồng phải tách biệt trong code

### Product/runtime path

```text
raw/normalized input
→ Real2Sim pipeline
→ Scene IR
→ candidate USD
→ Isaac validation
```

### Evaluation path

```text
prediction artifacts
+
evaluation_only references
→ metrics
```

Không để `groundtruth_map.ply` hoặc manual annotations xuất hiện trong product input resolver.

## 26.2 Ví dụ cụ thể cho một traversal

Giả sử team khóa `Scenario 1 Traversal 2`:

```text
raw/scenario_1_traversal_2/image_left/
    ↓ ST-FRAME-EXTRACT
    ↓ ST-CAMERA-POSE
    ↓ ST-VISUAL-RECON / ST-RGB-GEOMETRY
immutable/checksummed RGB visual + poses + RGB mesh

raw/scenario_1_traversal_2/lidar/
+ raw/scenario_1_traversal_2/traj_gt.txt
    ↓ offline preprocessing
registered_lidar.ply
    ↓ ST-LIDAR-INGEST
LiDARGeometryArtifact
    ↓ ST-RGB-LIDAR-ALIGN
aligned same-scene RGB/LiDAR artifacts
    ↓ ST-METRIC-CANONICALIZE / SceneComposer
unified metric scene + downstream-consumption provenance

raw/global/groundtruth_map.ply
    ↓ evaluation only → EV-GEOMETRY
geometry metrics
```

Cách viết này giúp team nhìn rõ một file không phải "tải cho có" mà có một consumer/stage cụ thể.

# 27. Những claim team có thể và không nên đưa ra

## Có thể nói

> TorWIC-SLAM được chọn làm real-world warehouse benchmark chính vì cung cấp synchronized RGB-D cameras, 3D LiDAR, calibration, trajectory ground truth và centimetre-level Leica ground-truth map.

> Real2Sim RGB-only reconstruction được benchmark trên held-out RGB views và independent reference geometry sau khi reconstruction hoàn tất.

> RGB+LiDAR flow được dùng để kiểm chứng khả năng xây dựng unified metric scene.

## Không nên nói nếu chưa chứng minh

> TorWIC LiDAR sequence là input trực tiếp được Real2Sim hỗ trợ.

Sai với MVP hiện tại vì product chỉ nhận registered/fused LiDAR.

> `traj_gt` + fused LiDAR so với Leica map là hoàn toàn independent benchmark.

Không sạch methodology vì `traj_gt` được tạo bằng alignment vào Leica map.

> TorWIC segmentation masks là perfect object ground truth.

Không đúng; repository nói masks không hoàn hảo.

> Dataset chính thức có chính xác X GB.

Chỉ nói sau khi có số liệu xác minh từ Drive hoặc nguồn chính thức.

---

# 28. Action items tiếp theo

1. Mở Google Drive chính thức.
2. Inspect danh sách TorWIC-SLAM traversals.
3. Chọn 3–5 candidate traversal theo tiêu chí ở mục 21.
4. Tải selective modalities của **1 traversal**.
5. Ghi exact size sau download.
6. Tạo `dataset_manifest.yaml`.
7. Chuẩn hóa folder thành `raw/`, `normalized/`, `derived/`, `evaluation_only/`.
8. Parse `calibrations.txt` và `frame_times.txt` thành format nội bộ.
9. Tạo `traversal.mp4` từ `image_left/` chỉ cho Web/demo nếu cần.
10. Tạo offline `registered_lidar.ply` cho LiDAR ingestion/integration test.
11. Khóa held-out split + Track A RGB-only benchmark trước khi chạy metrics.
12. Chọn một subset rất nhỏ để manual-annotate object/path nếu cần. Thêm `instance_id` xuyên nhiều frame (VD: Pallet_01 = frame_20 mask_03, frame_47 mask_07, frame_91 mask_02) để test MultiViewObjectAssociator.
13. Không cho product reconstruction code truy cập `evaluation_only/`.

---

# 29. Citation gợi ý cho report/paper

Paper liên quan:

```bibtex
@INPROCEEDINGS{QianRSS23,
  author    = {Jingxing Qian and Veronica Chatrath and James Servos and
               Aaron Mavrinac and Wolfram Burgard and Steven L. Waslander and
               Angela P. Schoellig},
  title     = {POV-SLAM: Probabilistic Object-Aware Variational SLAM in
               Semi-Static Environments},
  booktitle = {Proceedings of Robotics: Science and Systems},
  year      = {2023},
  address   = {Daegu, Republic of Korea},
  month     = {July},
  doi       = {10.15607/RSS.2023.XIX.069}
}
```

Khi dùng dataset trong deliverable/public report, kiểm tra lại citation wording mới nhất trong official repository trước khi submit.

---

# 30. Kết luận

TorWIC-SLAM là lựa chọn rất phù hợp cho Warehouse Real2Sim MVP vì nó đồng thời có **real RGB, 3D LiDAR, calibration, pose ground truth và centimetre-level 3D reference map** trong đúng môi trường warehouse/mobile robotics.

Điểm mạnh nhất của nó không phải chỉ là “có nhiều sensor”, mà là cho phép team biến câu hỏi:

> “Scene nhìn có đẹp không?”

thành câu hỏi đo được:

> “Scene reconstruction lệch bao nhiêu so với môi trường thực?”

Chiến lược của team không phải tải toàn bộ dataset, mà là:

```text
selective download
→ locked small subset
→ E2E bring-up
→ real quantitative benchmark
→ expand only when needed
```

Và nguyên tắc methodology quan trọng nhất là:

> **Ground truth chỉ được dùng để đánh giá hoặc cho preprocessing đã được khai báo rõ; không được vô tình đưa ground truth vào prediction pipeline rồi dùng lại chính ground truth đó để claim independent benchmark.**

---

## Official links — quick access

- TorWIC Dataset GitHub: https://github.com/Viky397/TorWICDataset
- Official Google Drive: https://drive.google.com/drive/folders/12-h2OPmlmxLk0Y9C3Hr5glkalUp66oEJ?usp=sharing
- License / Dataset Terms: https://github.com/Viky397/TorWICDataset/tree/main/License
- POV-SLAM RSS 2023: https://roboticsproceedings.org/rss19/p069.html
- POV-SLAM arXiv: https://arxiv.org/abs/2307.00488
- DOI: https://doi.org/10.15607/RSS.2023.XIX.069
