**[1]** Hôm nay em xin báo cáo tiến độ của team theo ba phần chính: thứ nhất là scope và kiến trúc mà team đã chốt; thứ hai là những phần Foundation và dataset verification đã hoàn thành; cuối cùng là trạng thái hiện tại và kế hoạch triển khai bốn track tiếp theo.

**[2]** Bài toán của team là Real2Sim Studio. Mục tiêu là hỗ trợ kỹ sư chuyển dữ liệu quan sát từ môi trường thực, chủ yếu là moving-camera RGB (chuỗi ảnh màu RGB được ghi khi camera đang di chuyển) và registered LiDAR (dữ liệu point cloud LiDAR từ nhiều thời điểm đã được căn chỉnh về cùng một hệ tọa độ), thành một scene 3D có cấu trúc, chỉnh sửa được, có metric scale (tỷ lệ kích thước theo đơn vị thực như mét) và collider (hình học va chạm dùng bởi simulator), sau đó có thể validation (kiểm tra tính đúng đắn và khả năng hoạt động) trong simulator trước khi release.

**[3]** Pain point mà team nhắm tới không đơn thuần là reconstruction (tái dựng môi trường 3D từ dữ liệu quan sát) cho đẹp. Vấn đề chính là khoảng giữa từ dữ liệu thực đến một simulation-ready scene (scene đã đủ điều kiện đưa vào simulator sử dụng) hiện phải qua rất nhiều bước thủ công: reconstruction, căn scale và coordinate (tỷ lệ và hệ tọa độ), tách object, tạo collider, export simulator, chạy validation, phát hiện lỗi rồi quay lại chỉnh sửa.

**[4]** Vì thời gian MVP (Minimum Viable Product — phiên bản sản phẩm tối thiểu đủ để chứng minh pipeline hoạt động) chỉ khoảng bốn tuần, team đã thu hẹp scope triển khai thực tế xuống Warehouse/Indoor AMR (robot di động tự hành trong kho hoặc môi trường trong nhà) và NVIDIA Isaac Sim. Tuy nhiên phần Core được thiết kế theo hướng Universal Real2Sim để sau này có thể thay domain (miền ứng dụng như warehouse, road hoặc factory) hoặc simulator mà không phải viết lại toàn bộ pipeline.

---

**[5]** Kiến trúc hiện tại được chia thành bốn execution track (bốn luồng triển khai kỹ thuật có thể phát triển tương đối độc lập).

EX-REC nhận input và tạo ReconstructionBundle (gói artifact chuẩn chứa kết quả reconstruction).

EX-SCENE nhận ReconstructionBundle, thực hiện object understanding (nhận biết và hiểu các đối tượng trong scene) và scene decomposition (phân rã scene thành môi trường và các object riêng biệt) rồi tạo SceneIR (Intermediate Representation — biểu diễn trung gian chuẩn của scene).

EX-SIM nhận SceneIR, tạo collider, OpenUSD (định dạng scene chuẩn Universal Scene Description), chạy Isaac Sim validation và sinh CandidatePackage (gói scene ứng viên chuẩn bị được kiểm thử/release) cùng ValidationReport (báo cáo kết quả kiểm tra).

EX-PRODUCT chịu trách nhiệm orchestration (điều phối các stage của pipeline), API, Web Studio, editing, review và release.

Điểm quan trọng là bốn track không import implementation của nhau (không phụ thuộc trực tiếp vào code nội bộ của track khác). Chúng giao tiếp thông qua shared artifact contracts (các cấu trúc dữ liệu và quy ước giao tiếp chung đã được định nghĩa trước).

---

**[6]** Trong hai ngày Foundation vừa rồi, team chủ động chưa cho bốn track đi sâu vào implementation ngay. Lý do là nếu mỗi người tự xây data structure, coordinate convention (quy ước hệ tọa độ), checksum (mã kiểm tra để xác minh dữ liệu không bị thay đổi) và artifact format (định dạng dữ liệu đầu ra trung gian) riêng thì đến integration sẽ rất dễ vỡ hệ thống. Vì vậy team tập trung khóa Foundation trước.

Team đã chuẩn hóa shared schemas (các schema dữ liệu dùng chung) và handoff contracts (hợp đồng dữ liệu dùng để bàn giao kết quả giữa các track), gồm InputManifest, ReconstructionBundle, SceneIR, CandidatePackage và ValidationReport.

Coordinate convention, transform direction (chiều của phép biến đổi giữa hai hệ tọa độ) và metric scale được khóa ở shared contracts.

Mỗi artifact (kết quả trung gian được lưu trữ và truyền giữa các stage) có URI, schema version, provenance (thông tin nguồn gốc và quá trình tạo artifact) và SHA-256 để producer (thành phần tạo artifact) và consumer (thành phần sử dụng artifact) có thể xác minh chính xác dữ liệu đang sử dụng.

**[7]** Ground truth (dữ liệu chuẩn dùng làm mốc so sánh) và evaluation-only data (dữ liệu chỉ được sử dụng khi đánh giá) được tách khỏi product/runtime data để tránh data leakage (vô tình đưa thông tin đáp án vào prediction pipeline).

Team cũng đã xây fixtures (các bộ dữ liệu mẫu nhỏ có cấu trúc chuẩn dùng cho development và testing), nhờ đó từng track có thể phát triển ngay cả khi upstream chưa hoàn thành.

Các contract có negative tests (test cố tình đưa dữ liệu sai vào) để reject sớm những trường hợp như duplicate object ID, sai coordinate system, missing artifact, wrong checksum hoặc candidate lineage mismatch (candidate không có đúng chuỗi nguồn gốc artifact).

Runtime của Core cũng được chuẩn hóa về Python 3.12 và dependency được lock phiên bản để giảm nguy cơ cùng một code nhưng chạy khác nhau trên máy các thành viên.

Foundation sau đó được audit theo các blocker F-01 đến F-05 và hiện đã đạt trạng thái đủ để phân phối cho bốn track.

---

**[8]** Song song với Foundation, team đã bắt đầu verify dataset thật. Dataset chính hiện chọn là **TorWIC-SLAM**, là bộ dữ liệu thực tế được thu trong môi trường warehouse.

Dataset này phù hợp với Real2Sim vì có đồng thời RGB, depth (bản đồ khoảng cách từ camera tới bề mặt), LiDAR, calibration (tham số sensor và quan hệ hình học giữa các sensor), trajectory ground truth (quỹ đạo chuẩn) và ground-truth map (bản đồ 3D chuẩn). Nhờ đó team vừa có dữ liệu để reconstruction, vừa có reference để đánh giá kết quả.

Dữ liệu được chia theo từng **traversal**, có thể hiểu là một lần robot hoặc hệ sensor di chuyển qua warehouse và ghi lại toàn bộ dữ liệu.

Ở bước REC-01A team đã inspect ba traversal và chọn **Aisle_CW** làm traversal bring-up đầu tiên. Aisle_CW có 1092 frame và các modality (các loại dữ liệu cảm biến) RGB, depth, LiDAR cùng trajectory được đồng bộ one-to-one.

**[9]** Trong MVP, những thành phần dữ liệu chính được sử dụng gồm:

```text
image_left/
→ nguồn ảnh RGB chính
→ COLMAP lấy camera pose
→ Brush / 3DGS dựng visual
→ OpenMVS dựng geometry

calibrations.txt
→ camera intrinsics
→ quan hệ tọa độ giữa camera và LiDAR

frame_times.txt
→ timestamp
→ đồng bộ RGB frame, LiDAR scan và trajectory

lidar/*.pcd
+
traj_gt.txt
→ tiền xử lý offline
→ đưa các scan về cùng hệ tọa độ
→ merge thành registered_lidar.ply

groundtruth_map.ply
→ chỉ dùng cho evaluation
→ so sánh geometry, ví dụ bằng Chamfer Distance
```

Trong đó, camera pose là vị trí và hướng của camera trong không gian; 3DGS là 3D Gaussian Splatting (kỹ thuật biểu diễn và render scene 3D bằng các Gaussian); camera intrinsics là các tham số nội tại của camera như focal length và principal point; timestamp là mốc thời gian của từng frame; Chamfer Distance là metric đo khoảng cách hình học giữa hai tập point cloud.

---

**[10]** Với RGB, TorWIC đã cung cấp sẵn từng frame trong `image_left/`, nên team có thể dùng trực tiếp cho reconstruction. Nếu muốn mô phỏng đúng trải nghiệm người dùng upload video trên Web App thì có thể ghép các frame này thành một file `traversal.mp4`.

Với LiDAR, dataset cung cấp nhiều file `.pcd` (định dạng lưu point cloud) theo từng thời điểm. Tuy nhiên sản phẩm không nhận trực tiếp chuỗi raw LiDAR (các scan LiDAR thô chưa được căn chỉnh) này.

Team sử dụng `traj_gt.txt` trong bước chuẩn bị dataset để đưa các scan về cùng hệ tọa độ và merge thành một registered point cloud:

```text
registered_lidar.ply
```

File này mới là input phù hợp cho LiDAR branch của Real2Sim.

`traj_gt.txt` cũng được sử dụng làm trajectory reference trong evaluation. Tuy nhiên với RGB-only reconstruction, ground truth trajectory không được đưa vào prediction pipeline để tránh data leakage.

`groundtruth_map.ply` cũng tương tự: nó không phải input của sản phẩm mà chỉ được sử dụng ở bước evaluation để kiểm tra reconstructed scene lệch bao nhiêu so với reference.

---

**[11]** Ở REC-01B, team không chỉ tin vào documentation mà đã kiểm tra trực tiếp sensor geometry (quan hệ hình học và tọa độ giữa các sensor).

Team xác minh trajectory sử dụng transform từ sensor sang world (phép biến đổi đưa tọa độ từ hệ sensor sang hệ tọa độ toàn cục).

Camera–LiDAR extrinsics (ma trận mô tả vị trí và hướng tương đối giữa camera và LiDAR) cũng được kiểm tra bằng projection thực tế, tức chiếu các điểm LiDAR lên ảnh camera, và xác định đúng transform direction.

Depth uint16 (ảnh depth lưu bằng số nguyên không dấu 16-bit) được kiểm chứng có scale 0.001, tức chuyển từ millimeter sang meter.

Team cũng tạo accumulated LiDAR map (bản đồ point cloud được tích lũy từ nhiều LiDAR scan sau khi căn chỉnh) và RGB–LiDAR projection để kiểm tra trực quan rằng geometry hội tụ đúng.

Nhờ đó, các assumption quan trọng về coordinate, calibration và depth scale không còn chỉ là giả định trước khi EX-REC bắt đầu reconstruction thật.

---

**[12]** TorWIC còn có `image_right`, depth, segmentation masks (mặt nạ pixel xác định vùng thuộc từng đối tượng hoặc lớp) và IMU (Inertial Measurement Unit — cảm biến quán tính đo gia tốc và vận tốc góc).

Những dữ liệu này vẫn được giữ lại nhưng hiện không phải input bắt buộc của P0. Depth chủ yếu hỗ trợ sanity check và debugging; segmentation mask chỉ dùng tham khảo vì không được coi là perfect ground truth; còn IMU chưa cần vì MVP không tự xây Visual-Inertial SLAM (SLAM kết hợp camera và cảm biến quán tính).

Tóm lại, luồng sử dụng TorWIC trong project là:

```text
image_left
    ↓
RGB Reconstruction
    │
    ├───────────────┐
    │               │
lidar/*.pcd     calibrations / timestamps
+ traj_gt           │
    ↓               │
registered LiDAR    │
    │               │
    └───────┬───────┘
            ↓
     Real2Sim Pipeline
            ↓
      Reconstructed Scene
            │
            ├──────────────┐
            │              │
            ▼              ▼
        Product       Evaluation only
                       +
                 groundtruth_map.ply
                       ↓
                     Metrics
```

Điểm quan trọng là team tách rõ **dữ liệu dùng để tạo prediction** và **ground truth chỉ dùng để đánh giá**, để tránh leakage và giữ benchmark đáng tin cậy.

---

**[13]** Vì vậy trạng thái hiện tại của project là: Foundation phase đã kết thúc, dataset bring-up cơ bản đã được xác minh, và team đang ở điểm bắt đầu triển khai bốn track song song.

Milestone tiếp theo không phải là hoàn thiện toàn bộ sản phẩm ngay. Mục tiêu gần nhất là mỗi track chạy được một thin path (luồng xử lý tối thiểu nhưng chạy xuyên suốt từ input tới output) độc lập trên contract đã freeze.

EX-REC phải tạo được ReconstructionBundle thật.

EX-SCENE phải consume ReconstructionBundle và tạo SceneIR.

EX-SIM phải consume SceneIR và tạo CandidatePackage cùng ValidationReport.

EX-PRODUCT phải orchestrate được các stage và hiển thị được artifact trên product flow.

**[14]** Sau khi bốn thin path này chạy được, team sẽ thực hiện Integration #1 và sau đó chuyển sang real TorWIC end-to-end alpha (phiên bản thử nghiệm đầu tiên chạy xuyên suốt pipeline trên dữ liệu TorWIC thật).

Các rủi ro kỹ thuật lớn nhất team đang theo dõi là chất lượng reconstruction và metric alignment (khả năng căn reconstruction đúng tỷ lệ và tọa độ thực), độ ổn định của object decomposition và multi-view association (ghép cùng một object xuất hiện ở nhiều góc nhìn thành một object thống nhất), và dependency/runtime của Isaac Sim cũng như các heavy GPU providers.

**[15]** Ở thời điểm này team muốn xin mentor feedback chủ yếu ở ba điểm: scope Warehouse-to-Isaac hiện tại đã đủ tập trung cho MVP hay chưa; boundary (ranh giới trách nhiệm và phạm vi) của Universal Real2Sim Foundation có phần nào đang quá rộng hoặc còn thiếu; và trong các technical risk vừa nêu, phần nào nên được de-risk (giảm rủi ro bằng thử nghiệm hoặc kiểm chứng sớm) trước Integration #1.

---

**[16] Sơ đồ tổng quan pipeline**

```text
                         USER
                          │
                          ▼
             ┌─────────────────────────┐
             │       EX-PRODUCT        │
             │ Web / Project / Job API │
             └────────────┬────────────┘
                          │
                          │ InputManifest
                          ▼

════════════════════════ EX-REC ════════════════════════

                 INPUT RGB / LiDAR
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼

        RGB BRANCH                LiDAR BRANCH
             │                         │
       Video RGB                Registered LiDAR
             │                         │
             ▼                         ▼
      Frame Extraction             Validation
        (FFmpeg)                      │
             │                         ▼
             ▼                   LiDAR ingest
          Frames                   (Open3D)
             │                         │
             ▼                         ▼
          COLMAP              LiDARGeometryArtifact
      Camera Pose / SfM               │
             │                         │
       ┌─────┴──────┐                  │
       ▼            ▼                  │
     Brush       OpenMVS               │
     3DGS        Geometry              │
       │            │                  │
       └─────┬──────┘                  │
             │                         │
             └────────────┬────────────┘
                          │
                  RGB-LiDAR Alignment
                    nếu có cả hai
                          │
                          ▼
                Metric / Canonicalize
                          │
                          ▼
                   SceneComposer
                          │
                          ▼

                ReconstructionBundle
                          │
                          │ ARTIFACT HANDOFF
                          ▼

══════════════════════ EX-SCENE ═══════════════════════

                ReconstructionBundle
                          │
                          ▼
                 Object Segmentation
                       SAM2
                          │
                          ▼
                  Mask Propagation
                          │
                          ▼
               Multi-view Association
                          │
                          ▼
                2D masks → 3D regions
                          │
                          ▼
               Candidate SceneObjects
                          │
                          ▼
                  Human Confirmation
           confirm / rename / merge / ignore
                          │
                          ▼
                 Scene Decomposition
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
         Environment              SceneObjects
              └───────────┬───────────┘
                          ▼

                       SceneIR
                          │
                          │ ARTIFACT HANDOFF
                          ▼

═══════════════════════ EX-SIM ═════════════════════════

                       SceneIR
                          │
                          ▼
                 Collider Generation
              AABB / OBB / Convex / Mesh
                          │
                          ▼
                 Static Preflight
                          │
                          ▼
                   OpenUSD Export
                          │
                          ▼
                   CandidatePackage
                          │
                          ▼
                     Isaac Sim
                          │
              ┌───────────┼────────────┐
              ▼           ▼            ▼
          Spawn test   Collision     Floor test
                          │
                          ▼
                Start–Goal Path Test
                          │
                          ▼
                  ValidationReport
                          │
                EvaluationReport?
                  benchmark only
                          │
                          │ ARTIFACT HANDOFF
                          ▼

══════════════════════ EX-PRODUCT ══════════════════════

              Web Studio / 3D Viewer
                          │
                          ▼
                 Display Validation
                          │
                          ▼
                     Reviewer
                          │
                  ┌───────┴───────┐
                  ▼               ▼
               APPROVE          REJECT
                  │               │
                  ▼               ▼
           ApprovalRecord      Revision
                  │               │
                  ▼               └──→ sửa lại scene
           Seal exact tested
              Candidate
                  │
                  ▼
            APPROVED RELEASE
```

Trong sơ đồ:

* **SfM** là Structure from Motion (ước lượng camera pose và cấu trúc 3D từ nhiều ảnh).
* **RGB-LiDAR Alignment** là căn chỉnh reconstruction từ camera với point cloud LiDAR về cùng hệ tọa độ.
* **Canonicalize** là đưa scene về một hệ tọa độ, orientation và scale chuẩn chung của hệ thống.
* **SceneComposer** là thành phần tổng hợp các nguồn geometry thành ReconstructionBundle thống nhất.
* **Object Segmentation** là xác định vùng pixel thuộc từng object.
* **Mask Propagation** là theo dõi hoặc lan truyền mask của object qua nhiều frame.
* **Multi-view Association** là xác định những vùng quan sát ở nhiều camera view khác nhau thực chất thuộc cùng một object 3D.
* **AABB** là Axis-Aligned Bounding Box, hộp bao song song với các trục tọa độ.
* **OBB** là Oriented Bounding Box, hộp bao có thể xoay theo hướng của object.
* **Convex** là collider dạng khối lồi xấp xỉ object.
* **Mesh collider** là collider sử dụng trực tiếp hoặc gần trực tiếp hình học mesh của object.
* **Static Preflight** là bước kiểm tra scene trước khi khởi chạy simulator, ví dụ asset, transform, collider và cấu trúc USD có hợp lệ hay không.
* **Spawn test** kiểm tra scene hoặc object có thể được load và khởi tạo thành công trong simulator.
* **Floor test** kiểm tra mặt sàn và quan hệ giữa robot hoặc object với mặt sàn.
* **Start–Goal Path Test** kiểm tra robot có thể di chuyển từ vị trí bắt đầu tới vị trí mục tiêu trong scene hay không.
* **Artifact handoff** là việc một track bàn giao output đã chuẩn hóa cho track tiếp theo thông qua contract, thay vì gọi trực tiếp implementation của nhau.
* **Seal exact tested Candidate** nghĩa là khóa chính xác phiên bản candidate đã được validation và approve để bảo đảm bản release chính là bản đã được kiểm thử.
