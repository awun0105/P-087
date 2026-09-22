# Product Brief: RAV-01 — Real2Sim Studio

**Ngày tạo:** 19/09/2026
**Team:** P-087 — VinUni AI20K Build Phase (Cohort 4)
**Thời gian MVP:** 4 tuần
**Trạng thái:** Draft
**Document Role:** Product rationale / high-level communication.
**Upstream Constraint:** Không định nghĩa lại P0/P1 hoặc acceptance nếu PRD đã quy định.

------

## 1. Project này là gì?

**Real2Sim Studio** là một nền tảng hỗ trợ kỹ sư chuyển dữ liệu quan sát từ môi trường thật thành scene 3D có thể xem, chỉnh sửa, kiểm định và đưa vào môi trường mô phỏng.

Trong MVP P0, moving-camera RGB là input của full product/release vertical slice. Registered/fused LiDAR được hỗ trợ như một optional geometry input cho RGB + Registered LiDAR Contribution Evidence. Full standalone LiDAR-only product configuration thuộc P1.

Sản phẩm được thiết kế theo hướng **Universal Real2Sim Core**, tức phần xử lý cốt lõi không bị khóa vào riêng một loại môi trường hay simulator. Trong MVP 4 tuần, nhóm triển khai một lát cắt hoàn chỉnh từ **Warehouse/Indoor AMR đến NVIDIA Isaac Sim**. Các ranh giới chính được tổ chức bằng `DomainAdapter` và `SimulatorAdapter` để kiến trúc không bị khóa vào riêng lát cắt này.

Sau MVP, lõi xử lý này có thể được mở rộng sang các domain và simulator khác. Road/CARLA là một hướng mở rộng, không thuộc phạm vi triển khai hiện tại.

------

## 2. Vấn đề thực tế nào đang được giải quyết?

Kỹ sư robotics và autonomous systems cần môi trường mô phỏng để kiểm thử robot, policy và các tình huống vận hành trước khi triển khai ngoài đời thực.

Tuy nhiên, dữ liệu thu thập ngoài thực tế như video hoặc LiDAR chưa thể sử dụng trực tiếp như một simulation scene.

Một video có thể cho thấy môi trường rất rõ nhưng không trực tiếp cung cấp metric scale, cách nhóm các điểm thành object, collider và metadata tối thiểu để simulator hiểu đâu là sàn, tường hoặc vật cản.

LiDAR cung cấp geometry đo trực tiếp tốt hơn nhưng vẫn chỉ là point cloud, chưa phải scene hoàn chỉnh có object, collider và cấu trúc cần thiết cho simulator.

Trong MVP, “sẵn sàng cho kiểm thử vật lý” chủ yếu có nghĩa là scene có tỷ lệ theo đơn vị mét, collider và chỉ định static/rigid tối thiểu để kiểm tra va chạm và đường đi. Hệ thống không đặt mục tiêu tự động suy ra đầy đủ khối lượng, ma sát, độ nảy, mật độ, vật liệu hoặc đặc tính động lực học từ RGB/LiDAR.

Ngược lại, nếu dựng scene thủ công trong các công cụ 3D hoặc simulator, kỹ sư phải mất nhiều thời gian tái tạo lại môi trường, căn chỉnh kích thước, tạo collider, phân loại vật thể và kiểm tra lỗi.

Bottleneck chính mà dự án muốn giải quyết là:

```text
Real-world data
      ↓
[ nhiều bước xử lý và dựng scene thủ công ]
      ↓
Simulation-ready scene
```

Real2Sim Studio hướng tới rút ngắn đoạn workflow ở giữa này.

------

## 3. Persona nào đang đau và pain point của họ là gì?

### Simulation / Real2Sim Engineer — Persona chính

Đây là người nhận dữ liệu khảo sát hiện trường và chịu trách nhiệm biến nó thành scene có thể sử dụng trong simulator.

Workflow hiện tại thường bao gồm:

```text
Nhận video / LiDAR
      ↓
Xử lý dữ liệu
      ↓
Dựng lại môi trường
      ↓
Căn chỉnh scale / coordinate
      ↓
Tách và định danh vật thể
      ↓
Tạo geometry / collision
      ↓
Import sang simulator
      ↓
Chạy thử
      ↓
Phát hiện lỗi
      ↓
Quay lại sửa
```

Pain point chính là **phần lớn thời gian bị tiêu tốn cho scene preparation và validation thay vì công việc mô phỏng thực sự**.

Các vấn đề thường gặp gồm:

- phải dựng hoặc chỉnh geometry thủ công;
- phải tạo collision proxy;
- phải căn chỉnh coordinate và metric scale;
- khó tách một reconstruction thành các object độc lập để chỉnh sửa;
- phải chuyển dữ liệu qua nhiều công cụ;
- scene nhìn đúng nhưng physics sai;
- mỗi lần layout thay đổi phải sửa và kiểm tra lại nhiều bước.

### AMR Integration Engineer — Persona cộng tác trong MVP

Người này cần scene warehouse để kiểm thử robot, route, collision và khả năng di chuyển khi layout thay đổi.

Pain point chính là scene có thể nhìn đúng nhưng robot vẫn bị kẹt, xuyên vật thể hoặc gặp collider sai.

### Simulation Reviewer / Tech Lead

Người chịu trách nhiệm kiểm tra scene trước khi được sử dụng.

Pain point chính là thiếu một nơi tập trung để đối chiếu reconstruction quality, geometry, simulation test và lịch sử chỉnh sửa trước khi approve.

------

## 4. Giải pháp tổng quát là gì?

Real2Sim Studio tự động hóa và gom các bước rời rạc thành một workflow thống nhất. Hệ thống không triển khai ba pipeline độc lập theo từng tổ hợp input; thay vào đó, các modality branch tạo artifact để được composition theo configuration:

```text
REUSABLE MODALITY BRANCHES

RGB Branch
├── Camera Pose
├── 3DGS Visual
└── RGB-derived Geometry

Registered LiDAR Branch
└── Registered/Fused LiDAR
    → LiDARGeometryArtifact

                 ↓

          Scene Composition

PRODUCT / EVIDENCE CONFIGURATIONS

Primary RGB Product Path — P0 full release vertical slice
RGB Branch
    → Metric Scale
    → Candidate Objects
    → Human Confirmation
    → Scene Decomposition
    → Collider + Editing
    → Candidate OpenUSD
    → Isaac Validation
    → Human Review
    → Release

RGB + Registered LiDAR Integration Configuration — P0 LiDAR Contribution Evidence
RGB artifacts của cùng scene
    +
LiDARGeometryArtifact
    → Alignment / Unified Metric Scene
    → actual downstream consumption + provenance evidence

Full LiDAR-only Product Configuration — P1
LiDARGeometryArtifact
    → geometry-first product workflow
```

Primary RGB Product Path là P0 end-to-end release path duy nhất. P0 còn yêu cầu một RGB + Registered LiDAR integration run có giới hạn để chứng minh LiDAR-derived geometry thực sự được alignment/composition và sử dụng downstream; run này không phải một full P0 vertical slice thứ hai. Full LiDAR-only product configuration thuộc P1.

Hệ thống sử dụng **3D Gaussian Splatting (3DGS)** để tái tạo lớp hình ảnh của môi trường.

Trong configuration chỉ có RGB, geometry phục vụ collider được tạo từ quá trình tái tạo đa góc nhìn, sau đó được hiệu chỉnh tỷ lệ theo đơn vị mét bằng một khoảng cách tham chiếu đã biết. Khi có point cloud LiDAR đã đăng ký, Registered LiDAR Branch tạo `LiDARGeometryArtifact` dùng làm nguồn geometry đo trực tiếp và tham chiếu tỷ lệ mét. Với đầu vào kết hợp, RGB artifacts và LiDAR phải thuộc cùng scene/traversal, được kiểm tra bằng checksum và căn chỉnh về cùng một hệ tọa độ.

SAM2 hỗ trợ trích xuất và lan truyền mask để tạo các đối tượng ứng viên. Máy chỉ tạo các định danh trung tính như `Object_001`, `Object_002`; con người xác định, đổi tên hoặc xác nhận object trước khi đưa vào scene chính thức. Tự động nhận diện và gán tên ngữ nghĩa không phải yêu cầu bắt buộc của MVP.

Scene được quản lý theo ba lớp liên kết: **Visual Representation** để hiển thị, **Geometry Representation** để biểu diễn bề mặt và kích thước, và **Physics Representation** để cung cấp collider cùng metadata vật lý tối thiểu. Khi một object được chỉnh sửa, các lớp liên quan phải giữ cùng transform.

Kỹ sư có thể xem và chỉnh sửa scene trên Web App, sau đó hệ thống kiểm tra chất lượng reconstruction và simulation trước khi Reviewer approve.

Kiến trúc được thiết kế theo hướng:

```text
Universal Real2Sim Core
        ↓
Domain Adapter
        ↓
Simulator Adapter
```

MVP triển khai:

```text
Warehouse
   ↓
Isaac Sim
```

Road/CARLA là hướng mở rộng sau MVP.

------

## 5. Ai sẽ sử dụng hệ thống?

Hệ thống có ba nhóm người dùng chính.

**Simulation / Real2Sim Engineer** là người upload dữ liệu, chạy reconstruction, kiểm tra scene, chỉnh sửa object và chuẩn bị scene cho simulation.

**AMR Integration Engineer** sử dụng scene đã dựng để chạy robot, route và các bài kiểm tra collision trong Warehouse MVP.

**Simulation Reviewer / Tech Lead** kiểm tra reconstruction metrics, geometry, simulation result và quyết định approve hoặc reject scene.

Hệ thống không thay thế các kỹ sư này mà giảm phần công việc lặp lại trong pipeline chuẩn bị scene.

------

## 6. MVP 4 tuần làm đến đâu?

MVP chỉ implement sâu **một reference domain: Warehouse/Indoor AMR**.

### Input

**P0 Primary Input**

- **Video RGB quay bằng camera di chuyển** là input của full product/release vertical slice. Hệ thống có thể nhận chuỗi ảnh tương đương ở mức pipeline/backend khi cần.

**P0 Optional Geometry Input**

- **Point cloud LiDAR đã được đăng ký hoặc hợp nhất** ở định dạng `.ply` hoặc `.pcd`, nằm trong một hệ tọa độ bản đồ thống nhất, có thể được dùng cùng RGB trong RGB + Registered LiDAR Integration Configuration để tạo LiDAR Contribution Evidence.

**P1 Product Configuration**

- standalone registered/fused LiDAR không có RGB Visual Representation thuộc Full LiDAR-only Product Configuration.

Trong MVP P0, registered/fused LiDAR được hỗ trợ như một geometry input branch. Ít nhất một RGB + Registered LiDAR integration run phải tạo `LiDARGeometryArtifact`, đưa artifact đó vào canonical/unified scene và chứng minh geometry có nguồn LiDAR thực sự được dùng trong scene geometry, collider hoặc simulator validation.

RGB artifacts được reuse cho evidence run phải thuộc cùng scene/traversal, đã immutable/checksummed và truy vết được. Evidence run không yêu cầu chạy lại toàn bộ RGB reconstruction hoặc đạt full object correction, editing, review và release parity với Primary RGB Product Path.

MVP P0 không yêu cầu một LiDAR-only product execution riêng. Full LiDAR-only product configuration thuộc P1. Raw LiDAR scan sequence registration/SLAM vẫn nằm ngoài phạm vi này.

Chuỗi scan LiDAR thô liên tiếp không thuộc hợp đồng đầu vào của MVP. Hệ thống không thực hiện LiDAR odometry, SLAM, đăng ký scan, loop closure hoặc tối ưu bản đồ. RGB-D và depth map cũng không phải một nhánh đầu vào của MVP. Với nhánh chỉ có RGB, dữ liệu phải đủ điều kiện cho tái tạo đa góc nhìn và có khoảng cách tham chiếu đã biết để hiệu chỉnh tỷ lệ theo đơn vị mét.

### Reconstruction

- 3D Gaussian Splatting để tái tạo lớp hình ảnh từ RGB;
- geometry từ quá trình tái tạo RGB đa góc nhìn cho Primary RGB Product Path;
- khi có registered/fused LiDAR, Registered LiDAR Branch tạo LiDAR-derived metric geometry qua một artifact contract dùng chung;
- với RGB + LiDAR, hai modality cùng scene/traversal được căn chỉnh về canonical coordinate system trước khi composition;
- full LiDAR-only geometry-first product configuration thuộc P1;
- đánh giá chất lượng tái tạo trên các góc nhìn được giữ lại để kiểm thử.

### Scene Editing

Web App cho phép:

- xem scene 3D;
- orbit / zoom / pan;
- bật/tắt layer hoặc object;
- chọn object;
- xem và kiểm tra các đối tượng ứng viên được tạo tự động;
- xác nhận, đổi tên, bỏ qua hoặc gộp các đối tượng ứng viên;
- khi khả thi, sửa cách nhóm hoặc chạy lại bước phân tách; chức năng tách hoặc phân đoạn lại không phải điều kiện bắt buộc để phát hành MVP. P0 correction không phụ thuộc vào advanced split/re-segmentation. Correction tối thiểu được thực hiện bằng Merge, Create Missing Object và Reassign selected evidence/geometry;
- thêm một vật cản hoặc asset cơ bản;
- translate / rotate object;
- xóa object khỏi scene hiện tại;
- đồng bộ thay đổi giữa Visual, Geometry và Physics/Collider.

Đối với reconstructed object, thao tác Delete có nghĩa object được loại khỏi cấu trúc scene và không còn tham gia geometry/collision của revision hiện tại. MVP không cam kết tự động phục hồi photorealistic hoàn hảo phần background chưa từng được quan sát phía sau object. Với video đa góc nhìn, nếu vùng phía sau object đã xuất hiện trong những frame khác, hệ thống có thể tận dụng evidence đã quan sát đó trước khi cần tới inpainting. Background completion nâng cao là enhancement, không phải điều kiện để thao tác Delete thành công.

### Human-in-the-loop

Scene có workflow:

```text
DRAFT
  ↓
PROCESSING
  ↓
CANDIDATE_READY
  ↓
VALIDATING
  ↓
READY_FOR_REVIEW
  ├── APPROVED
  │      ↓
  │   RELEASED
  │
  └── REJECTED
         ↓
      New DRAFT revision
```

Scene chỉ trở thành approved release sau khi Reviewer kiểm tra.

### Simulator

MVP implement:

```text
WarehouseDomainAdapter
        +
IsaacSimAdapter
```

để tạo scene tương thích với NVIDIA Isaac Sim và chạy các bài simulation validation cơ bản.

------

## 7. Giá trị cốt lõi

Real2Sim Studio giảm phần công việc lặp lại trong quá trình biến dữ liệu môi trường thật thành scene mô phỏng có cấu trúc, có thể chỉnh sửa và kiểm chứng được.

Giá trị của sản phẩm không chỉ nằm ở việc dựng một mô hình 3D đẹp, mà ở khả năng tạo ra một scene:

- có metric scale;
- có object structure;
- có Visual, Geometry và Physics nhất quán;
- có thể chỉnh sửa layout (Scene có cấu trúc giúp kỹ sư thay đổi layout bằng thao tác trên object thay vì phải tái dựng toàn bộ scene khi một pallet, box hoặc obstacle thay đổi);
- có thể validation trong simulator trước khi phát hành;
- vẫn giữ kỹ sư trong vòng quyết định cuối cùng.

Trong Warehouse/Indoor AMR MVP, giá trị này được thể hiện trực tiếp bằng việc kỹ sư có thể tái dựng môi trường, thêm hoặc di chuyển vật cản, kiểm tra collision/path feasibility và đánh giá tác động của layout mới trước khi thay đổi môi trường thật.

## 8. Không làm gì trong phase này?

MVP 4 tuần không đặt mục tiêu:

- điều khiển robot hoặc xe thật;
- implement đầy đủ Road/CARLA;
- hỗ trợ nhiều simulator ngang nhau;
- nhận chuỗi scan LiDAR thô liên tiếp và tự thực hiện LiDAR SLAM hoặc đăng ký scan;
- hỗ trợ RGB-D hoặc depth maps như một input branch riêng;
- reconstruct hoàn hảo các scene có nhiều object động;
- không cam kết photorealistic background inpainting hoặc general 3D scene completion hoàn hảo cho mọi reconstructed object sau khi xóa;
- thay đổi weather hoặc lighting một cách photorealistic;
- tự động nhận diện và gán tên ngữ nghĩa mà không có người xác nhận;
- tự động ước lượng đầy đủ các thuộc tính vật lý như khối lượng, ma sát, độ nảy, mật độ hoặc đặc tính động lực học;
- giải quyết mọi loại domain ngay trong MVP.

“Universal” trong giai đoạn này có nghĩa là **kiến trúc được thiết kế để mở rộng**, không có nghĩa MVP đã implement tất cả domain.

------

## 9. Thành công được đo bằng gì?

### Chất lượng tái tạo hình ảnh

Hệ thống phải đo được:

- **PSNR:** đo mức độ giống nhau giữa ảnh thật và ảnh render lại từ scene; càng cao càng tốt;
- **SSIM:** đo mức độ giống nhau về cấu trúc hình ảnh; càng gần `1` càng tốt;
- **LPIPS:** đo mức độ khác biệt về cảm nhận thị giác giữa ảnh thật và ảnh render; càng thấp càng tốt.

### Chất lượng hình học, tỷ lệ mét và đối tượng

Hệ thống theo dõi:

- **Chamfer Distance:** đo sai lệch hình học với **independent reference geometry** (Hình học tham chiếu độc lập). Nghiêm cấm lấy chính LiDAR đã tạo ra Scene để làm Ground Truth chấm điểm Chamfer (Self-validation leakage).
- **Geometry Precision / Recall / F1 tại một ngưỡng khoảng cách:** đo cả phần geometry đúng, phần geometry bị thiếu và phần geometry được tạo sai;
- **Scale Error (%):** đo sai lệch tỷ lệ so với kích thước thực;
- **Distance RMSE:** đo sai số của các khoảng cách kiểm tra trong scene;
- **Object Recall:** đo tỷ lệ object cần thiết được tạo thành candidate object;
- **AP50:** chỉ sử dụng khi benchmark có ground-truth object annotation phù hợp.

### Chất lượng collider và mô phỏng

Hệ thống theo dõi:

- **Collision Precision / Recall / F1:** đo chất lượng của collision proxy so với vật cản mà nó cần đại diện;
- **Path Feasibility F1:** đo mức khớp giữa kết quả đường đi trên scene mô phỏng và ground truth của bài thử;
- **Unsafe Path Rate:** đo tỷ lệ đường được hệ thống xem là đi được nhưng thực tế đi xuyên hoặc va vào vật cản;
- **Isaac Load Success:** đo tỷ lệ scene package được nạp thành công vào NVIDIA Isaac Sim.

Các threshold cụ thể được khóa theo cơ chế metric-status tại PRD §2.2 và Locked Evaluation Set tại PRD §10.

Protocol kỹ thuật cho TorWIC-SLAM, leakage control, held-out split và từng nhóm benchmark được mô tả trong DATASET_PLAYBOOK §§14–20.

Nếu sau này project tách riêng một EVALUATION_PLAN.md, tài liệu đó phải cụ thể hóa các quyết định evaluation đã được phê duyệt và không được tự thay đổi product scope hoặc metric semantics của PRD.

### Hiệu năng

Theo dõi:

- **End-to-end runtime:** tổng thời gian từ input hợp lệ đến scene sẵn sàng để review;
- **Per-stage runtime:** thời gian của từng bước tái tạo scene, xử lý geometry, trích xuất đối tượng ứng viên và kiểm định mô phỏng;
- **GPU-hours và peak VRAM:** được đo trên một cấu hình phần cứng cố định để kết quả có thể so sánh;
- **Render latency / FPS:** được đo trên một cấu hình thiết bị demo cố định. Viewer phải đủ responsive cho thao tác review và chỉnh sửa, còn target cụ thể chỉ được đặt sau baseline.

### Mức độ thành công của toàn hệ thống

- **End-to-end Success Rate:** tỷ lệ input hợp lệ đi hết pipeline và tạo được scene package có báo cáo đánh giá;
- **Human-in-the-loop Completion Rate:** tỷ lệ scene hoàn tất luồng review và có quyết định approve hoặc reject rõ ràng.

### Mức độ hoàn thành chức năng

MVP phải chạy end-to-end được:

Functional end-to-end success dưới đây áp dụng cho Primary RGB Product Path.
Registered LiDAR có thể tham gia như geometry source trong RGB + Registered LiDAR Integration Configuration. P0 LiDAR Contribution Evidence được nghiệm thu theo artifact provenance và downstream consumption; mixed configuration không bắt buộc đi qua toàn bộ Object/Edit/Release workflow dưới đây.

```text
Moving-camera RGB [+ optional Registered/Fused LiDAR geometry]
      ↓
Tái tạo scene 3D
      ↓
Hình ảnh + Geometry
      ↓
Hiệu chỉnh tỷ lệ mét / Căn chỉnh hệ tọa độ
      ↓
Candidate Object Identities
      ↓
Human Object Confirmation
      ↓
Scene Decomposition
(Environment + Independent SceneObjects)
      ↓
Visual + Geometry + Physics/Collider
      ↓
Editable Scene
      ↓
Build Candidate OpenUSD
Isaac Sim Validation
      ↓
Validation Report
      ↓
Human Review
      ↓
Approve / Reject
      ↓
Seal Approved Release
```

Scene chỉ được xem là thành công về mặt chức năng khi có thể đi xuyên suốt pipeline trên mà không cần kỹ sư phải tự dựng lại scene từ đầu bằng công cụ bên ngoài.

### Năng suất của người dùng

So sánh với workflow thủ công thông qua các chỉ số:

- thời gian từ raw data đến editable scene;
- manual hands-on time;
- số bước thủ công;
- thời gian chỉnh sửa một object;
- thời gian chuẩn bị scene để chạy lại simulation.

Mục tiêu của dự án là chứng minh hệ thống có thể **giảm công sức và thời gian chuẩn bị scene cho kỹ sư**, thay vì thay thế vai trò của họ.

Tỷ lệ cải thiện cụ thể sẽ được xác định bằng cách đo baseline workflow thủ công và so sánh với workflow sử dụng Real2Sim Studio.
