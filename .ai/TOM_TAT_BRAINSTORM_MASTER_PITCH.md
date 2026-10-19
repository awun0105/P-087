# Tóm tắt chi tiết: BRAINSTORM.md và MASTER_PITCH.md

**Nguồn:**
- `/home/lqaq/PROJECT/AI20K/P-087/BRAINSTORM.md` (~30 KB, 323 dòng)
- `/home/lqaq/PROJECT/AI20K/P-087/MASTER_PITCH.md` (~93 KB, 1772 dòng)

**Dự án:** Real2Sim Studio (P-087)
**Mục đích tài liệu:** Thống nhất cách định vị, pitching và kể câu chuyện sản phẩm.

---

## 0. Tóm tắt điều hành (đọc 1 phút)

- **Vấn đề đã đổi:** Từ "chuyển video nhà kho thành 3D" sang **"chuẩn bị và chỉnh sửa môi trường mô phỏng robot từ dữ liệu quan sát thực"**.
- **Định vị chính:** *Editable Real-to-Sim Workspace for Robotics*.
- **Người dùng chính:** Kỹ sư mô phỏng / R&D / tích hợp robot di động **trong nhà**.
- **Use case MVP:** Robot giao hàng nội bộ (văn phòng, phòng lab). Một bài test navigation: chạy robot ở hai cách bố trí bàn/vật cản và so sánh kết quả.
- **Tầm nhìn dài hạn:** *Spatial Imagination for Robots* — tạo các "tương lai giả định" của không gian thực để robot được thử trước khi gặp thật.
- **Tagline thống nhất:** *"Let robots rehearse the real world before they enter it."*
- **Nguyên tắc xuyên suốt:** Không tuyên bố điều chưa đo được. Không tự nhận là "đầu tiên". Không dùng footage Isaac Sim để ngụ ý pipeline đã chạy E2E nếu chưa kiểm chứng.
- **Quan hệ giữa hai tài liệu:** BRAINSTORM là bản *suy nghĩ chiến lược ban đầu* (lập luận vì sao đổi định vị). MASTER_PITCH là bản *nội dung chuẩn* và được chỉ định là **nguồn gốc duy nhất** cho pitch deck, landing page, web app, video, PRD và tài liệu dự án.

---

## 1. BRAINSTORM.md — Định vị lại Real2Sim Studio

**Tiêu đề gốc:** "Định vị lại Real2Sim Studio: Từ một bài demo 3D thành sản phẩm giải quyết vấn đề thực tế"

### 1.1 Lý do đổi định vị

Hai cách pitch cũ đều yếu:

| Cách pitch cũ | Vấn đề |
|---|---|
| "Chuyển video nhà kho thành scene 3D" | Mô tả input/output, không nói khách hàng cần gì và thiệt hại gì nếu thiếu |
| "Lưu kỷ niệm / căn phòng dưới dạng 3D" | Dễ hiểu nhưng không chứng minh nhu cầu đủ lớn, thường xuyên hoặc đủ cấp thiết để trả tiền |

**Quyết định đề xuất:**
- Không biến Real2Sim thành app lưu kỷ niệm.
- Không giữ nhà kho làm domain duy nhất khi dữ liệu chưa hỗ trợ.
- Giữ **robot simulation** làm thị trường mục tiêu, mở rộng địa điểm từ "warehouse-only" sang "indoor environments".

**Câu định vị đề xuất:**
> Real2Sim Studio giúp các nhóm phát triển robot tạo nhanh một môi trường thử nghiệm mô phỏng từ video quay nơi robot dự kiến hoạt động. Họ có thể thay đổi cách bố trí đồ vật và kiểm tra những tình huống khác nhau trước khi thử nghiệm trên robot thật.

**Điểm mấu chốt:** Giá trị không nằm ở việc tạo mô hình 3D, mà ở việc **cho kỹ sư thử nghiệm thay đổi trong thế giới thực mà chưa cần thực hiện chúng ngoài đời**.

### 1.2 Bài toán có thật không? (Mục 1)

- **Có bằng chứng ngành:** NVIDIA mô tả việc chuẩn bị scene cho simulation là nhiều bước, dễ sai (gán nhãn, collision geometry, thuộc tính vật lý, kiểm tra xuất USD).
- **Phát hiện quan trọng:** NVIDIA **đã có** công cụ chuyển ảnh điện thoại thành scene trong Isaac Sim (từ 2025), dùng COLMAP + Gaussian reconstruction (Omniverse NuRec). Đã có Polycam, Scaniverse, Asset Harvester, World Labs Marble.
- **Hệ quả:** *Không thể* lấy "video/ảnh → 3D → Isaac Sim" làm lợi thế cạnh tranh duy nhất.
- **Pain point cụ thể hơn:** Từ "mô hình 3D nhìn được" đến "môi trường thử nghiệm dùng được". Phải làm thêm: căn chỉnh kích thước, tách vật thể, tạo va chạm, sửa lỗi, thiết lập scene trong simulator.
- **Lưu ý:** Tài liệu ngành xác nhận *có nhu cầu công việc này*, nhưng **chưa chứng minh** ai sẽ chọn và trả tiền. Cần phỏng vấn.

### 1.3 So sánh bốn hướng sản phẩm (Mục 2)

| Hướng | Đánh giá của BRAINSTORM |
|---|---|
| A. Dựng kho 3D cho kỹ sư robot | Giữ làm ứng dụng mở rộng (thiếu dữ liệu phù hợp) |
| **B. Tạo môi trường thử nghiệm cho robot trong nhà** | **Nên chọn làm trọng tâm** |
| C. Chuyển video thành 3D cho người không biết dựng hình | Không nên chọn (khác biệt chưa rõ) |
| D. Lưu giữ kỷ niệm / căn phòng 3D | Không phù hợp sản phẩm hiện tại |

**Persona đề xuất:** *Robotics Integration Engineer / Simulation Engineer* — đưa robot di động vào văn phòng, hành lang, bệnh viện, kho.
- **Người quyết định mua:** Trưởng nhóm R&D robot, quản lý tích hợp, doanh nghiệp cung cấp giải pháp robot.
- **Không chọn:** Người vận hành kho (biết robot làm gì nhưng không trực tiếp dựng scene trong Isaac Sim).
- **Không đưa TAM/doanh thu** khi chưa khảo sát.

### 1.4 Câu chuyện demo (Mục 3)

- **Tình huống:** Công ty sản xuất robot giao hàng đưa robot vào tòa nhà văn phòng; robot đi từ nơi nhận hàng đến các phòng làm việc.
- **Câu hỏi kỹ sư cần trả lời:** Robot có đi qua khoảng trống giữa bàn và tường không? Thêm tủ thì đường đi thay đổi thế nào? Hành lang bị chắn thì robot tìm đường khác không?
- **Kịch bản demo:**
  - **A — Lối đi thông thoáng:** Robot thử đi từ cửa đến vị trí nhận hàng.
  - **B — Thay đổi vị trí bàn:** Kéo bàn vào lối đi, chạy lại cùng bài thử.
- **Thông điệp cho giám khảo:** Cùng địa điểm, cùng robot, hai bố trí → kết quả khác nhau.
- **Lưu ý trung thực:** Đây là *kịch bản mục tiêu*, chưa phải bài test Isaac Sim đã hoàn tất. Cần chạy robot thật trong hai scene, tốt nhất cùng một bộ điều khiển.
- **Khả thi:** Isaac Sim đã có ví dụ Nova Carter + ROS 2 Nav2 điều hướng trong nhà kho.

### 1.5 Concept drift khi đổi sang Hugging Face? (Mục 4)

- **Có drift** nếu tuyên bố sản phẩm thiết kế cho nhà kho nhưng demo toàn phòng khách/bếp mà không giải thích.
- **Không drift** nếu định vị là "công cụ tạo môi trường thử nghiệm cho robot di động trong nhà", vì phòng, hành lang, văn phòng, kho cùng thuộc một nhóm bài toán.

**Phân vai dữ liệu:**

| Nguồn | Vai trò | Lưu ý |
|---|---|---|
| HF `room`, `kitchen`, `playroom` | Kiểm thử tách vật thể, chỉnh sửa, collision, xuất scene | Có thể dùng Gaussian dựng sẵn; **không gọi là bằng chứng video→3D end-to-end** |
| Video tự quay (phòng học, văn phòng, lab) | Demo đầu vào thực tế | Cần quay đủ góc, có quyền ghi hình, đo vài kích thước thật |
| TUM RGB-D `freiburg1_room` | Đối chiếu pose, scale, bước xử lý hình học | Có RGB-D và quỹ đạo tham chiếu; không tối ưu cho demo đẹp |
| Isaac Sim warehouse assets | Kiểm thử tổng quát sang kho, dữ liệu tổng hợp có ground truth | **Không** trình bày render simulator như footage kho thật |

**Kế hoạch dataset:**
- **Demo chính:** Room hoặc phòng tự quay → cho thấy chuyển từ quan sát sang scene chỉnh sửa được, rồi kiểm tra va chạm.
- **Benchmark mở rộng:** Warehouse → kiểm tra xử lý kệ hàng, kiện hàng, lối hẹp.
- **Nguyên tắc:** Tách dữ liệu *chứng minh năng lực kỹ thuật* và dữ liệu *chứng minh ứng dụng kinh doanh*.

### 1.6 Khác biệt so với công cụ hiện có (Mục 5)

- **Không nói** "chúng em là công cụ đầu tiên chuyển video thành 3D".
- **Định vị theo quy trình:** Quay hiện trường → tái tạo → kiểm tra và sửa từng vật → xây dựng tình huống mới → xuất và kiểm thử.

| Công cụ | Thế mạnh | Hướng giá trị team cần chứng minh |
|---|---|---|
| Polycam, Scaniverse | Ghi 3D, mesh / Gaussian | Quy trình chuẩn bị và kiểm tra scene cho bài toán robot cụ thể |
| NVIDIA NuRec + Isaac Sim | Tái tạo, xuất simulator | Trải nghiệm chỉnh sửa từng vật, quản lý collision, kiểm tra thay đổi trong một workflow dễ thao tác |
| Dựng thủ công | Linh hoạt | Giảm công việc thủ công khi đã có video khảo sát |
| **Real2Sim Studio** | Tách Gaussian, review object, Move/Rotate, collider, USD export | Chứng minh độ chính xác, thời gian tiết kiệm, hiệu quả workflow |

> Đây là **giả thuyết** về lợi thế sản phẩm, chưa phải lợi thế đã benchmark.

### 1.7 "Trí tưởng tượng cho robot" (Mục 6)

- **Định nghĩa chính xác:** Không phải robot tự tưởng tượng. Hệ thống tạo và kiểm tra các phiên bản giả định của môi trường thực.
- **Chuỗi ví dụ:** Thế giới hiện tại (bàn ở vị trí cũ) → Tương lai A (bàn chắn lối đi) → Tương lai B (thêm vật cản mới) → chạy cùng robot → so sánh trước khi thay đổi môi trường thật.
- **Thuật ngữ đề xuất:** *Counterfactual Simulation* — "Nếu thế giới khác đi thì chuyện gì xảy ra?"
- **Hai mức tầm nhìn:**
  - **Gần hạn:** Người dùng tự đổi môi trường trong Studio rồi chạy mô phỏng.
  - **Dài hạn:** Hệ thống tự đề xuất kịch bản kiểm thử từ nhiệm vụ robot (ví dụ: nhiều cách xếp vật cản trên hành lang vận chuyển, tìm cách làm robot thất bại).
- **Ranh giới:** Real2Sim hiện **chưa phải** world model dự đoán tự động. Nó là lớp môi trường 3D chỉnh sửa và mô phỏng — nền tảng cho hướng đó.
- **Thông điệp đề xuất:** *"Real2Sim Studio — Tái tạo thế giới thực, thử nghiệm những tình huống chưa xảy ra."*

### 1.8 Cần chứng minh điều gì để giám khảo tin? (Mục 7)

**Không nên** chỉ demo Gaussian đẹp, kéo được bàn, có collision. Đó là thành công kỹ thuật, không phải giá trị kinh doanh.

| Câu hỏi | Bằng chứng cần chuẩn bị |
|---|---|
| Có tiết kiệm thời gian không? | So sánh thời gian dựng thủ công và bằng Real2Sim, cùng tiêu chuẩn |
| Môi trường đủ chính xác để thử robot không? | Đối chiếu khoảng cách đo thật và kích thước scene; kiểm vật cản thật/giả |
| Chỉnh sửa có nhanh không? | Đo thời gian Move/Rotate + tạo collision đúng, so với thủ công |
| Dùng được ngoài Studio không? | Import package vào Isaac Sim và chạy bài thử với robot |
| Áp dụng ngoài một demo không? | Thử thêm scene khác, ghi rõ trường hợp thành công và thất bại |

- **Tách hai loại thời gian:** chờ máy xử lý vs. thời gian kỹ sư thao tác.
- **Giới hạn kỹ thuật cần giữ trong scope nghiệm thu:** PR-01 đến PR-04 đã cải thiện browser collision và scene lifecycle, nhưng còn: lỗi Gaussian membership, collision ownership tại vùng nối bàn–sàn, **chưa có bằng chứng E2E trực tiếp trong Isaac Sim**.
- **Lưu ý pain point:** Đừng giả định kỹ sư luôn dựng 3D từ đầu. Một số nhóm đã có CAD, bản đồ SLAM, thư viện asset, NuRec.
- **Hành động:** Phỏng vấn 5–8 người (dev robot, tích hợp robot, giảng viên/nghiên cứu viên). Hỏi về lần gần nhất họ tạo môi trường thử nghiệm, công cụ dùng, công đoạn tốn công nhất, tần suất, hệ quả khi scene sai. **Nếu không ai gặp vấn đề thường xuyên, điều chỉnh persona thay vì bảo vệ giả định.**

### 1.9 Pitch đề xuất (Mục 8)

Kể câu chuyện công ty đưa robot giao hàng vào tòa nhà mới → kỹ sư cần kiểm tra va chạm và đường đi khi bố trí thay đổi → Real2Sim rút ngắn bước từ dữ liệu khảo sát đến môi trường 3D chỉnh sửa được → ví dụ kéo bàn ra khỏi lối đi và chạy lại bài thử → tầm nhìn dài hạn.

Bản này **tránh ba vấn đề:** tuyên bố thị trường chưa ai làm; quá nhiều thuật ngữ 3D; hứa sản phẩm đã tự động giải quyết hoàn toàn.

### 1.10 Quyết định cần chốt (Mục 9)

| Hạng mục | Định hướng |
|---|---|
| Định vị | Công cụ tạo và chỉnh sửa môi trường mô phỏng cho robot từ dữ liệu quan sát thực |
| Primary persona | Kỹ sư phát triển/tích hợp robot di động trong nhà, khi chưa có scene phù hợp |
| Use case đầu tiên | Robot giao nhận nội bộ: kiểm tra đường đi và va chạm khi bàn ghế/vật cản thay đổi |
| Demo | Room thật → tạo scene → chỉnh sửa vật → kiểm tra collision → xuất Isaac Sim → thử cùng robot ở hai bố trí, khi các bước E2E sẵn sàng |
| Tầm nhìn dài hạn | Công cụ tạo tình huống giả định từ môi trường thực |

**Kết luận của BRAINSTORM:** Vấn đề không phải thiếu ứng dụng. Các thành phần (Gaussian reconstruction, tách vật thể, chỉnh sửa, collision, USD export) hợp lý, nhưng **sản phẩm không nên được định nghĩa bằng tập hợp công nghệ**. Nhà kho chỉ là một nơi áp dụng, không còn là điều kiện tồn tại.

**Thông điệp xuyên suốt:**
> "Chúng tôi không chỉ giúp người dùng nhìn lại một không gian dưới dạng 3D. Chúng tôi muốn giúp họ thay đổi không gian đó trong môi trường ảo, thử xem điều gì sẽ xảy ra và giảm bớt công sức thử nghiệm ngoài thực tế."

---

## 2. MASTER_PITCH.md — Bản định vị và nội dung pitching tổng thể

**Tài liệu tự khai báo:** Nguồn nội dung gốc duy nhất cho pitch deck, landing page, web app, video, PRD, tài liệu dự án. Tháng 10/2026.

### 2.0 Luận điểm và đối chiếu bằng chứng (phần mở đầu)

**Luận điểm trung tâm:** Real2Sim không chỉ chuyển video thành 3D mà biến không gian được ghi hình thành môi trường 3D chỉnh sửa được, dùng để thử robot trước khi thay đổi ngoài đời.

Ba bằng chứng được nêu:
- **Nhu cầu:** KION + NVIDIA + Accenture ứng dụng digital twin chuẩn bị và thử kịch bản vận hành kho. [R1, R2]
- **Thị trường:** IFR ghi nhận ~250.000 robot dịch vụ chuyên nghiệp bán năm 2025, trong đó 117.500 thuộc vận tải/logistics. Đây là **quy mô ngành**, không phải số khách hàng đã xác thực. [R3]
- **Cạnh tranh:** NVIDIA NuRec, World Labs Marble, SimFoundry đã có nhiều khả năng liên quan. Nhóm phải cạnh tranh bằng **workflow và kết quả cụ thể**, không phải tuyên bố "đầu tiên". [R4–R7]

Tài liệu phân biệt 4 loại: bằng chứng thị trường, khả năng đã triển khai, giả thuyết cần benchmark, tầm nhìn dài hạn.

### 2.1 Định vị cốt lõi

| Mục | Nội dung |
|---|---|
| **Product tagline** | *Let robots rehearse the real world before they enter it.* |
| **Vietnamese tagline** | Để robot thử nghiệm trong thế giới ảo trước khi bước vào thế giới thực. |
| **Product category** | Reality-Grounded, Editable Simulation Preparation for Robotics |
| **Định vị** | Chuyển dữ liệu quan sát không gian thực thành scene 3D chỉnh sửa được, quản lý collision và chuẩn bị thử nghiệm robot |
| **Primary audience** | Nhóm phát triển, thử nghiệm, triển khai robot di động trong nhà |
| **Initial use case** | Chuẩn bị và chỉnh sửa môi trường thử robot từ video phòng, khu lưu trữ, kho nhỏ |
| **Long-term vision** | *Spatial Imagination for Physical AI* |

### 2.2 Phần I — Bài pitching chính thức: 18 slide

Mỗi slide gồm: thông điệp chính, nội dung hiển thị gợi ý, lời thuyết trình.

| # | Tiêu đề slide | Thông điệp chính |
|---|---|---|
| 01 | Opening | *Before robots enter a new environment, shouldn't they have a chance to practice in it first?* Vấn đề: rút ngắn khoảng cách từ không gian quan sát được đến môi trường dùng để thử robot. |
| 02 | Real-world scenario | *Every new environment introduces new uncertainties.* Kỹ sư kiểm tra robot có sẵn trong không gian mới. Bản đồ 2D/SLAM có thể đủ cho điều hướng phẳng; cần scene 3D cho hình học, vật cản, va chạm, mô phỏng camera. |
| 03 | The problem | *Capturing a place is not the same as making it simulation-ready.* Chuỗi: Reality Capture → 3D Reconstruction → Metric Alignment → Object Structure → Collision Geometry → Simulator Integration. Gaussian đẹp nhưng robot vẫn có thể đi xuyên vật nếu thiếu collision. |
| 04 | Why it matters | *Engineers should spend more time testing robots, not preparing scenes.* Công việc ẩn: geometry, scale, tách vật, collider, cập nhật khi bố trí đổi, kiểm tra tương thích simulator. Đây là **giả thuyết pain point**. |
| 05 | Market validation | *The industry is already investing in real-world digital twins for robotics.* KION + NVIDIA + Accenture (2025), KION công bố Physical AI và digital twin kho khách hàng (3/2026). Sự tồn tại của nhu cầu mô phỏng **không tự chứng minh** mọi doanh nghiệp cần tái tạo scene từ video. Nguồn: [R1], [R2]. |
| 06 | Market opportunity | *As physical robots expand into more environments…* World Robotics 2026: ~250.000 robot dịch vụ bán năm 2025, 117.500 vận tải/logistics. Số robot bán ≠ số doanh nghiệp mua Real2Sim. Nguồn: [R3]. |
| 07 | Our solution | *Turn captured spaces into editable simulation environments.* Chuỗi: **Capture → Reconstruct → Understand → Edit → Simulate**. Không xây simulator mới, không thay kỹ sư. |
| 08 | How it works | *One connected workflow, multiple specialized technologies.* 7 bước: Capture → Reconstruct (COLMAP + Brush/3DGS) → Calibrate (metric scale) → Objectify (segmentation) → Physics (collision, voxel, convex decomposition) → Edit → Export (OpenUSD/Isaac Sim). Nhấn mạnh: hình ảnh, collision, vị trí vật phải **đồng bộ**. |
| 09 | Editable environment | *Not just a 3D reconstruction. An environment you can work with.* Gaussian thường không biết đâu là Gaussian bàn, sàn, tường. Real2Sim: chọn object được đề xuất, xác nhận, di chuyển; collider riêng theo vật; chế độ **Walk** kiểm tra va chạm trong browser (preview). Độ chính xác phụ thuộc segmentation và ownership → cần cơ chế báo lỗi. |
| 10 | The demo | *What if we could test a layout change before making it in reality?* Scenario A → thay đổi (dịch bàn gần lối đi) → Scenario B. Câu hỏi: robot còn đi qua không? Va chạm mới? Còn va chạm giả ở vị trí cũ? So sánh hai cấu hình. **Điều kiện:** chỉ công bố kết quả Isaac Sim khi bài test thực sự chạy; Walk trong browser phải ghi rõ là *browser physics preview*. |
| 11 | Current alternatives | Không ai "chưa có giải pháp". SLAM/occupancy grid, CAD/BIM, LiDAR, NuRec, World Labs Marble, SimFoundry. Giả thuyết: **workflow chuyên biệt, thuận tiện, dễ kiểm tra** cho kỹ sư cần biến video địa điểm thực thành môi trường thử. |
| 12 | Differentiation | Ba nguyên tắc: **Reality-Grounded** (bắt đầu từ quan sát địa điểm cụ thể), **Editable** (quản lý và điều chỉnh vật độc lập), **Verifiable** (kiểm tra scale, geometry, collision, export readiness, và báo lỗi). Lợi thế muốn chứng minh: **giảm tổng công sức** từ dữ liệu quan sát đến scene đủ điều kiện test. |
| 13 | Who is this for | *Start narrow.* Người dùng: Robotics Simulation Engineers, R&D Teams, System Integrators. Domain: Indoor Mobile Robotics. Người mua: R&D lead/quản lý kỹ thuật — còn là giả thuyết. |
| 14 | What we have built | *Technical foundation implemented. Real-world reliability is the next milestone.* Đã có: pipeline video→3DGS, metric alignment, tách vật, per-object collider, scene editing, browser collision preview + Walk, USD export. **Không** gọi là đã sẵn sàng rộng rãi; collision vẫn phụ thuộc dữ liệu; chưa E2E Isaac Sim. |
| 15 | Dataset strategy | *Our initial market is robotics. Technical validation can begin with controlled indoor environments.* Ba lớp: (1) **Indoor Room** — tích hợp pipeline; (2) **Synthetic Warehouse** (ví dụ Staer Warehouses) — domain benchmark; (3) **Real-world captured scene** — validation thực tế. Room **không** chứng minh hoạt động trên kho công nghiệp. |
| 16 | Success metrics | *Measured by time to a usable scene.* Đo: Time-to-usable-scene, human editing effort, metric accuracy, object completeness, collision correctness, simulator readiness. Hai loại lỗi: vật cản tồn tại nhưng không phát hiện; va chạm giả. **Chưa có benchmark** để khẳng định tỷ lệ tiết kiệm. |
| 17 | Roadmap | Bốn giai đoạn: **Reconstruct** (Video → Metric 3D Scene) → **Edit** (Objects → Colliders → Scene Variants) → **Rehearse** (Robot Tests → Scenario Comparison) → **Learn** (Simulation Data → Evaluation → Improvement). Không nói phiên bản hiện tại đã giúp robot tự học. |
| 18 | Closing | *The future of robotics needs… better ways to prepare the worlds in which they learn, test and operate.* Bắt đầu bằng bài toán hẹp: chuẩn bị môi trường trong nhà cho robot di động từ quan sát. Mở rộng sau: kho, nhà máy, tòa nhà. |

### 2.3 Phần II — Product strategy và định vị chính thức

| Mục | Nội dung |
|---|---|
| **Product Vision** | Làm cho việc tái tạo, chỉnh sửa, thử nghiệm môi trường dựa trên thế giới thực dễ tiếp cận hơn; robot được đánh giá trong điều kiện thực tế hơn trước khi triển khai. |
| **Product Mission** | Nối khoảng cách giữa reality capture và editable robotics simulation. |
| **Product Category** | **Editable Real-to-Sim Workspace for Robotics** (category *nhất quán*) |
| **Không nên định vị là** | General-purpose 3D generator; AI interior design; 3D memory preservation; complete robotics simulator; fully autonomous digital twin platform |
| **Problem statement** | Thử robot cần môi trường 3D tương ứng địa điểm thực. Phải chuẩn bị geometry, scale, object structure, collision. Khi không có CAD/simulation asset, quy trình nhiều bước. |
| **Core pain point** | Khó khăn và công sức chuẩn bị, chỉnh sửa, cập nhật môi trường mô phỏng 3D từ quan sát thực. **Cần kiểm chứng** trong đúng phân khúc. |
| **Value proposition (EN)** | Helps robotics teams turn captured environments into editable 3D scenes, with visual reconstruction, object-level manipulation and collision-aware simulation preparation in one workflow. |
| **Giả thuyết giá trị cần đo** | Giảm thời gian và công sức của con người để chuẩn bị và cập nhật scene đạt yêu cầu mô phỏng. |
| **Functional Job** | Thử robot trong bố trí giống địa điểm thực → tạo scene từ quan sát, không dựng thủ công → bắt đầu test nhanh hơn. |
| **Emotional Job** | Tự tin scene đủ phù hợp để kết quả có ý nghĩa, không lo hình ảnh/kích thước/collision lệch nhau. |
| **Social/Professional Job** | Workflow giải thích được, kiểm tra được, lặp lại được, để cộng tác trong nhóm. |

**Persona:**
- **Primary — Robotics Simulation Engineer:** Chuẩn bị scene, đặt robot, thiết lập test, sửa vấn đề môi trường. Khó khăn: thiếu scene đúng địa điểm, nhiều định dạng, sửa collision thủ công, sửa khi bố trí đổi.
- **Secondary — Robotics System Integrator:** Tích hợp cho nhiều địa điểm khách hàng. Khó khăn: mỗi nơi cấu trúc khác, không phải nơi nào cũng có CAD cập nhật.

**Economic buyer (giả thuyết):** Robotics R&D Lead, Deployment Manager, System Integration Company, Automation Engineering Manager. **Chưa có bằng chứng ai trả tiền.**

**Beachhead:** Indoor Mobile Robotics Simulation Preparation — cảnh trong nhà, cấu trúc đơn giản, một mặt sàn, vật tĩnh, một robot di động. **Không** nhắm nhà máy hay warehouse phức tạp ngay phiên bản đầu.

**Initial use case:** *Scenario-Based Indoor Navigation Testing* — tái tạo indoor từ video → người dùng xác nhận và di chuyển một vật cản → cập nhật scene → test navigation → so sánh hai cấu hình.

**Non-goals của MVP:**
- Thay thế Isaac Sim, Gazebo, simulator khác
- Thay thế SLAM/Nav2 cho bài toán điều hướng không cần 3D chi tiết
- Bản sao hoàn hảo mọi không gian
- Tự đảm bảo metric accuracy chỉ từ một video monocular
- Hỗ trợ mọi vật deformable, articulated, môi trường động
- Chứng nhận an toàn cho robot thật
- Tự học robot policy từ scene trong phiên bản hiện tại

### 2.4 Phần III — Competitive positioning

| Đối thủ / nhóm | Hướng giải quyết | Liên hệ với Real2Sim |
|---|---|---|
| ROS 2 / Nav2 / SLAM | Bản đồ và điều hướng | Thay thế phù hợp khi chỉ cần navigation map |
| Isaac Sim + prebuilt assets | Scene từ asset có sẵn | Baseline mạnh khi không cần tái tạo địa điểm cụ thể |
| CAD / LiDAR | Dữ liệu thiết kế, hình học đo đạc | Phù hợp khi có dữ liệu chính xác hoặc yêu cầu công nghiệp cao |
| NVIDIA NuRec / 3DGRUT | Tái tạo từ ảnh, Gaussian, USD/Isaac | Đối chứng quan trọng |
| World Labs Marble | Tạo/chỉnh thế giới 3D, xuất splat và collider mesh | Đối thủ mạnh về world generation |
| SimFoundry | Video-to-physics-ready scene, OmniGibson | **Đối thủ nghiên cứu trực tiếp nhất** |

**Proposed competitive wedge:** *A focused, human-in-the-loop preparation workflow for reality-grounded robotics simulation scenes.* Ba trụ cột: Reality-Grounded, Editable, Verifiable. **Đây là khác biệt dự kiến, chưa phải lợi thế đã benchmark.**

**Lợi thế có thể phát triển:** Workflow consistency (đổi một vật không làm visual/collider/export lệch); Human control; Scene provenance (biết object đến từ dữ liệu nào, phiên bản nào); Reproducibility; Integration simplicity; Validation transparency (không che geometry không tin cậy bằng fallback đẹp).

### 2.5 Phần IV — Business potential và go-to-market

- **Product opportunity:** Công cụ B2B cho robotics engineering teams, không phải app 3D đại chúng. Khách hàng trả tiền khi công việc nhanh hơn, giảm công chuẩn bị, hoặc hỗ trợ test mà quy trình hiện tại kém thuận tiện.
- **GTM giai đoạn 1:** Robotics labs và research teams (sinh viên nghiên cứu, startup có robot và simulator) → lấy phản hồi, phát hiện trường hợp không phù hợp.
- **GTM giai đoạn 2:** Robotics integrators, pilot → đo time-to-usable-scene, human effort, khả năng tái sử dụng workflow.
- **GTM giai đoạn 3:** Robotics simulation preparation platform, tích hợp vào tổ chức lớn.
- **Business model (giả thuyết):** Team SaaS (theo workspace/thành viên/tính năng); Usage-based (theo khối lượng xử lý GPU); Enterprise/On-premise (dữ liệu hiện trường nhạy cảm); Simulation integration services.
- **Cần đo trước khi chốt giá:** GPU processing cost, support cost, mức sẵn sàng trả tiền.
- **Market size:** **Không đánh đồng** robotics market với Real2Sim TAM. Cần trả lời: bao nhiêu đội làm simulation preparation; bao nhiêu đội cần scene từ địa điểm thực thường xuyên; bao nhiêu đội chưa có công cụ; tần suất; chi phí hiện tại mỗi scene; phần nào họ trả tiền. **Chưa nên đưa TAM/SAM/SOM cụ thể.**

### 2.6 Phần V — Validation plan

**User discovery:** 5–8 người thực sự liên quan (robotics simulation hoặc system integration). Hỏi về **công việc đã làm gần đây**, không hỏi ý kiến về ý tưởng. 10 câu hỏi trọng tâm:
1. Lần gần nhất chuẩn bị môi trường thử robot là khi nào?
2. Đầu vào là CAD, LiDAR, video, bản đồ 2D hay gì khác?
3. Công cụ đã dùng?
4. Phần nào tốn thời gian/thao tác nhất?
5. Khi bố trí thực đổi, cập nhật simulation scene ra sao?
6. Khi nào bản đồ 2D đủ, khi nào cần 3D?
7. Lỗi geometry/collision nào ảnh hưởng kết quả?
8. Nếu công cụ giảm công chuẩn bị, muốn cải thiện phần nào trước?
9. Ai chịu chi phí và quyết định đầu tư?
10. Có đánh giá công cụ trên bài toán/dữ liệu thực của họ không?

**Technical validation — ba nhóm dữ liệu:**
- **Indoor Room:** Test end-to-end, object manipulation, collision.
- **Synthetic Warehouse:** Test reconstruction, object structure, geometry so với ground truth.
- **Real-world captured scene:** Video thật, ánh sáng thật, khoảng cách đo tay, vật có vị trí biết trước.
- **Quy tắc:** Không dùng kết quả loại này để khẳng định độ chính xác loại khác.

**Product benchmark:**
- **Input:** Video phòng/khu lưu trữ có vật cản và ít nhất vài khoảng cách đo được.
- **Goal:** Scene dùng được trong Isaac Sim; test robot trước/sau khi di chuyển vật.
- **Baselines:** Scene từ asset Isaac Sim phù hợp; NuRec + Isaac Sim nếu điều kiện cho phép.
- **Metrics:** Time-to-usable-scene; human effort; metric error; object quality; collision quality (false collision, missed, bề mặt xóa nhầm); edit consistency; simulator compatibility; repeatability.
- Chỉ kết luận nhanh hơn/hiệu quả hơn khi benchmark công bằng.

**Critical technical risks:**
- **Monocular metric ambiguity** — RGB một camera không tự ra mét nếu thiếu metric cues.
- **Reconstruction quality** — thiếu góc nhìn, motion blur, texture kém, occlusion.
- **Segmentation errors** — tách sai, gộp nhầm, mất bộ phận.
- **Collision ownership** — mesh voxel nối vật với sàn/tường; xóa collision nguồn theo vật có thể giữ va chạm giả hoặc mất geometry.
- **Simulation fidelity** — collider không đồng nghĩa mô phỏng chính xác (ma sát, khối lượng, sensor, robot model).
- **Dataset domain gap** — Room và synthetic warehouse không thay test trên video kho thực.
- **System integration** — export USD thành công ≠ robot đã hoàn thành test Isaac Sim.

### 2.7 Phần VI — Master messaging

- **One-liner (EN):** *Real2Sim Studio transforms real-world video into editable 3D environments for robotics simulation preparation.*
- **One-liner (VI):** Real2Sim Studio chuyển video quan sát không gian thực thành môi trường 3D có thể chỉnh sửa, phục vụ chuẩn bị và thử nghiệm robot trong mô phỏng.
- **Short description (EN):** Bridges reality capture and robotics simulation; reconstructs 3D from video; object-level editing; collision-aware scene preparation; export to NVIDIA Isaac Sim.
- **Long description:** Có đầy đủ EN/VI trong tài liệu (mục VI.3), nhấn mạnh: không thay simulator hay kỹ sư; khởi đầu từ indoor mobile robotics.
- **Taglines:**
  - Primary: *From Real-World Video to Editable Robot Simulation.*
  - Emotional vision: *Let robots rehearse the real world before they enter it.*
  - Technical: *Reality-Grounded 3D Reconstruction. Object-Level Editing. Collision-Aware Simulation Preparation.*
  - VI: *Từ video không gian thực đến môi trường thử nghiệm robot có thể chỉnh sửa.*
- **Ba thông điệp chính (phải xuất hiện nhất quán):**
  1. **Reality to Scene** — tái tạo địa điểm quan sát thành scene 3D.
  2. **Scene to Editable Environment** — từ cảnh để xem thành scene quản lý được object/collider.
  3. **Editable Environment to Simulation Preparation** — chuẩn bị và kiểm tra trước khi đưa vào simulator.

### 2.8 Phần VII — Nội dung landing page

- **Eyebrow:** REAL2SIM STUDIO — ROBOTICS SIMULATION PREPARATION
- **Headline:** *Turn Real-World Video into Editable 3D Simulation Environments.*
- **Subheadline:** Reconstruct real spaces, edit individual objects, inspect collision geometry, and prepare scenes for robotics simulation — all through a connected workflow.
- **CTA chính:** Explore Real2Sim Studio · **CTA phụ:** See How It Works
- **Vision line:** Let robots rehearse the real world before they enter it.
- **Problem section:** *From Reality to Simulation Is More Than Reconstruction.*
- **Solution section:** *Capture. Reconstruct. Edit. Rehearse.* — 4 feature: Video-Based Reconstruction; Object-Level Editing; Collision-Aware Scenes; Simulation Preparation (xuất cho Isaac Sim).
- **Use cases:** Indoor Robot Testing; Layout Change Exploration; Scene Preparation from Capture.
  - **Lưu ý:** Không trình bày use case như khách hàng đã triển khai nếu chưa có bằng chứng.
- **Vision section:** *A Step Toward Spatial Imagination for Robots.*

### 2.9 Phần VIII — Web app content

Quy ước đặt tên hiển thị trong sản phẩm:

| Khu vực | Tên hiển thị | Mô tả |
|---|---|---|
| Import | Capture Input | Nhập video/ảnh theo định dạng hỗ trợ |
| Reconstruction | 3D Reconstruction | Tạo bản tái tạo 3D |
| Metric | Scale & Alignment | Kiểm kích thước và hệ tọa độ |
| Segmentation | Object Review | Xem, xác nhận, chỉnh vật được đề xuất |
| Visual | Visual Scene | Xem scene Gaussian |
| Collision | Collision Geometry | Hình học va chạm môi trường và vật |
| Editor | Scene Editor | Chỉnh vị trí/hướng vật |
| Physics preview | Walk & Collision Preview | Kiểm tra di chuyển, va chạm trong browser |
| Export | Simulation Export | Chuẩn bị artifact cho simulator |
| Readiness | Validation & Issues | Lỗi và điều kiện chưa đạt |

**Nguyên tắc UX:**
- Phân biệt rõ **Gaussian visual**, **collider riêng của object** và **collision mesh môi trường**. Không gọi cả ba là một mesh.
- Trạng thái validation phải cho biết: đã kiểm chứng trong browser, đã xuất artifact, hay đã nghiệm thu trong Isaac Sim.

### 2.10 Phần IX — Kịch bản video giới thiệu (90–120 giây)

Tiêu đề: *"What If a Robot Could Practice Before Entering a New Place?"*

| Thời lượng | Nội dung | Voice-over chính |
|---|---|---|
| 0–15s Hook | Robot trong kho/indoor | "Every new environment brings new challenges for a robot…" |
| 15–30s Problem | Video không gian → bước geometry/scale/collision | "…requires more than just 3D reconstruction." |
| 30–45s Introduce | Logo và giao diện Studio | "Meet Real2Sim Studio — a workspace connecting real-world capture with editable robotics simulation preparation." |
| 45–70s Workflow | Input video → reconstruction → segmentation → editing → collision preview | "…without treating the reconstruction as a single uneditable model." |
| 70–95s Demo | Confirm, Move, Rotate, Walk; nếu đã xác minh thì thêm robot Isaac Sim | "…explore how changes in object placement affect the test scene." |
| 95–120s Vision | Từ scene thật sang nhiều bố trí giả định → logo | "…help robots rehearse possible worlds before they encounter them in reality." |

**Yêu cầu trung thực:** Phân biệt footage hệ thống thật với minh họa, mockup, concept render. Không dùng footage Isaac Sim để ngụ ý E2E nếu chưa kiểm chứng.

### 2.11 Phần X — 18 câu hỏi khó và cách trả lời

| # | Câu hỏi | Tóm tắt trả lời |
|---|---|---|
| Q1 | Pain point có thật không? | Có bằng chứng về nhu cầu digital twin/simulation; nhưng scene prep có phải bottleneck đủ lớn cho phân khúc đã chọn thì cần phỏng vấn. Không coi là product-market fit. |
| Q2 | Công cụ hiện có làm được, sao cần Real2Sim? | Không nói công cụ không làm được. Giả thuyết: workflow tập trung vào một địa điểm, object editing, validation giảm công sức. Chỉ thành lợi thế nếu benchmark chứng minh. |
| Q3 | NuRec đã làm video → Isaac Sim, có gì mới? | NuRec mạnh; Real2Sim tập trung workspace human-in-the-loop, collision composition, prep workflow. Chưa tuyên bố vượt NuRec. |
| Q4 | SimFoundry cũng có? | Đúng, rất gần. Khác về use case: Real2Sim indoor mobile robotics + Isaac Sim; SimFoundry tabletop/OmniGibson. Chưa đủ chứng minh vượt trội. |
| Q5 | Sao không dùng CAD? | Khi có CAD đúng hiện trạng, CAD tốt hơn. Real2Sim cho trường hợp không có scene/CAD phù hợp hoặc cần cập nhật từ quan sát. |
| Q6 | Sao không dùng SLAM 2D? | Điều hướng 2D đơn giản thì SLAM/Nav2 đủ. Real2Sim phù hợp khi cần hình học 3D, bố trí vật, hoặc biểu diễn cho perception/simulation. |
| Q7 | Gaussian có physics không? | Chủ yếu là biểu diễn hình ảnh. Cần collider riêng; phải kiểm tra độ đúng, không mặc định visual = physics. |
| Q8 | Video không đủ góc thì sao? | Reconstruction thiếu geometry, bị che khuất. Sản phẩm phải kiểm tra điều kiện dữ liệu, phát hiện vùng không tin cậy, cho người dùng bổ sung quan sát. Không tự suy ra phần chưa thấy đã đúng. |
| Q9 | Làm sao biết kích thước thật? | Monocular không tự có metric scale. Cần metric anchors, LiDAR hoặc tín hiệu có cơ sở, kèm validation. Không đủ dữ liệu → báo giới hạn, không trình bày ước lượng như ground truth. |
| Q10 | Collider không khớp vật thì sao? | Một trong những thách thức quan trọng nhất. Đo false collision và missed collision; kiểm tra source ownership, đặc biệt vùng tiếp xúc vật–sàn/tường. Chất lượng không đạt → sửa hoặc chặn trước khi test yêu cầu cao. |
| Q11 | Chứng minh tiết kiệm thời gian? | Chưa có benchmark đầy đủ. Sẽ đo time-to-usable-scene và human effort so với workflow thay thế. Tốc độ reconstruction không phải chỉ số duy nhất. |
| Q12 | Sao chuyển từ warehouse sang Room, có concept drift? | Warehouse là lĩnh vực ứng dụng ban đầu; Room là môi trường phát triển/kiểm pipeline. Room không chứng minh áp dụng vào kho → cần benchmark kho và cảnh thực. |
| Q13 | Sao không dùng Isaac Sim Editor? | Không thay thế editor. Giá trị: giảm các bước trước khi có scene từ quan sát thực, quản lý reconstruction/object/collision trong một workflow. |
| Q14 | Robot có tin hoàn toàn vào simulation? | Không. Phụ thuộc scene, physics, sensor, robot model. Real2Sim giúp chuẩn bị môi trường, không thay việc nghiệm thu an toàn. |
| Q15 | Ai trả tiền? | Giả thuyết: R&D teams và integrators có nhu cầu nhiều môi trường/cập nhật thường xuyên. Chưa có dữ liệu về người mua, giá, willingness-to-pay. |
| Q16 | Nhóm nhỏ cạnh tranh NVIDIA thế nào? | Không cạnh tranh toàn bộ nền tảng; giải một workflow nhỏ, cụ thể, dùng công nghệ mở. Không tự tạo lợi thế bền vững; cần benchmark và người dùng thật. |
| Q17 | "Trí tưởng tượng cho robot" là gì? | Tầm nhìn dài hạn, không phải khả năng hiện tại. Robot không tự tưởng tượng; tạo phiên bản ảo của môi trường thực để thử. |
| Q18 | Điểm thành công tối thiểu? | Video indoor đạt điều kiện đầu vào → tạo scene, kiểm kích thước, xác nhận và di chuyển một vật, giữ collision đủ tốt, dùng trong test robot đơn giản trong Isaac Sim. Kết quả lặp lại được, có tiêu chí nghiệm thu rõ. |

### 2.12 Phần XI — Claims policy (quy tắc được phép tuyên bố)

**A. Có bằng chứng bên ngoài — được nói (cần gắn nguồn):**
- Doanh nghiệp lớn đang đầu tư digital twin và robotics simulation.
- Đã có workflow chuyển ảnh thực thành Gaussian/USD/Isaac Sim.
- Gaussian Splatting không tự cung cấp collision vật lý.
- Đã có sản phẩm/nghiên cứu giải các phần tương tự.

**B. Đã có implementation và automated test nội bộ — nói theo phạm vi đã kiểm tra:**
- Đã triển khai reconstruction và scene editing pipeline.
- Đã triển khai object-level collider handling.
- Đã bổ sung collision composition và browser physics.
- Test backend/frontend liên quan đã PASS tại thời điểm báo cáo.
- *Không* gọi là production-grade performance.

**C. Đã quan sát trong Studio (theo thử nghiệm nội bộ):**
- Gaussian di chuyển cùng collider của vật.
- Browser Walk chặn người dùng tại collider tương ứng.
- Object editing hoạt động trên scene đã chuẩn bị.
- *Cần kiểm tra lại trên build cuối và ghi bằng video/screenshot thật.*

**D. Chưa được chứng minh — KHÔNG được nói:**
- "Giảm 80–90% thời gian dựng scene."
- "Hoàn toàn tự động."
- "Bản sao chính xác tuyệt đối của môi trường thực."
- "Không còn sai sót collision."
- "Hoạt động tốt với mọi video."
- "Tự động xác định mét thật chỉ từ RGB monocular."
- "Tốt hơn NuRec, Marble hoặc SimFoundry."
- "Robot đã tự học từ môi trường do Real2Sim tạo ra."
- "Đã triển khai thành công cho khách hàng."
- "Đã chứng minh vận hành an toàn ngoài đời."

### 2.13 Phần XII — Canonical story cho mọi kênh

| Kênh | Câu hỏi chính | Nội dung ưu tiên |
|---|---|---|
| Pitch Deck | Vấn đề có đáng giải không, nhóm có cơ hội không? | Problem, persona, evidence, alternatives, differentiation, demo, validation, vision |
| Landing Page | Sản phẩm giúp tôi làm gì? | Value proposition, workflow, capabilities, use cases |
| Web App | Làm gì tiếp, kết quả có đáng tin không? | Nhãn theo tác vụ, actions, progress, readiness, cảnh báo collision/scale |
| Intro Video | Vì sao tôi nên quan tâm? | Robot scenario, problem, transformation, demo, vision |
| PRD | Chính xác giải quyết vấn đề gì? | Personas, JTBD, non-goals, requirements, acceptance |
| Architecture Docs | Input biến thành scene thế nào? | Data contracts, coordinate frames, object lifecycle, collision, provenance |
| README | Project là gì, thử thế nào? | Positioning, capabilities, setup, known limits, demo |
| Investor/Judge Q&A | Nhận định có đáng tin không? | Evidence, alternatives, hypotheses, benchmarks, risks |
| Mentor Reports | Nhóm tiến gần giá trị sản phẩm thế nào? | Milestones đã xác nhận, blockers, evidence, next experiments |

**Ba khái niệm thống nhất trong mọi tài liệu:**
- **Reality Capture** — dữ liệu quan sát đầu vào, *không* đồng nghĩa scene mô phỏng.
- **Editable 3D Scene** — bản tái tạo quan sát và thao tác được với vật đã quản lý.
- **Simulation-Ready Scene** — đạt yêu cầu hình học, kích thước, collision, dữ liệu, tương thích cho một bài test cụ thể.

Một scene có thể thuộc nhóm 2 nhưng chưa đạt nhóm 3.

### 2.14 Phần XIII — Pitch ngắn

- **30 giây:** Real2Sim chuyển video không gian thực thành scene 3D chỉnh sửa được, kết hợp reconstruction, object-level editing, collision-aware preparation, giúp thử thay đổi trước khi triển khai.
- **90 giây:** Kịch bản robot vào nhà kho/tòa nhà → cần thử đường hẹp, vật cản, bố trí khác → simulation cần môi trường tương ứng → Real2Sim: Gaussian, tách vật, collision, Isaac Sim → kéo một vật, kiểm collision, chuẩn bị kịch bản → không tuyên bố đầu tiên → mục tiêu: chứng minh trên một bài toán indoor đo lường được.

### 2.15 Phần XIV — Evidence library

| Mã | Nguồn | Dùng để chứng minh |
|---|---|---|
| R1 | KION Group — Physical AI in Live Warehouse Operations (03/2026) | Doanh nghiệp đang dùng digital twin và virtual commissioning |
| R2 | Accenture — KION teams with NVIDIA and Accenture (01/2025) | Digital twin để thiết kế, tối ưu kho |
| R3 | IFR — World Robotics 2026 Service Robots | Dữ liệu ngành; **không** đo trực tiếp nhu cầu Real2Sim |
| R4 | NVIDIA — Reconstruct a Scene in Isaac Sim Using Only a Smartphone (10/2025) | Đối chứng smartphone → COLMAP → 3DGUT → USD → Isaac Sim |
| R5 | NVIDIA — Simulate Robotic Environments Faster with Isaac Sim and World Labs Marble (12/2025) | Gaussian + collider mesh + robotics sim |
| R6 | World Labs — Marble | World generation, editing, splats, mesh export |
| R7 | NVIDIA Research — SimFoundry | Đối thủ nghiên cứu trực tiếp |
| R8 | ROS Nav2 — Navigating While Mapping | Giải pháp đơn giản hơn cho điều hướng 2D |
| R9 | Isaac Sim — Environment Assets | Đối chứng dựng scene từ asset có sẵn |
| R10 | Staer Warehouses — Hugging Face Dataset | Dataset kho tổng hợp (RGB, depth, poses, annotations); **kiểm tra license và version** |

### 2.16 Final product statement và thứ tự triển khai

**Final statement (EN):**
> Real2Sim Studio is an editable Real-to-Simulation workspace for robotics. We help bridge the gap between captured real-world environments and usable simulation scenes by bringing visual reconstruction, object-level editing and collision-aware scene preparation into one connected workflow. We begin with indoor mobile robotics… Our long-term vision is to enable robots to rehearse possible changes to the real world before encountering them in physical operations.

**Cách dùng tài liệu:** Slide 01–18 là câu chuyện đầy đủ cho giám khảo. Phần sau là nguồn chuẩn để thiết kế sản phẩm và tài liệu.

**Thứ tự triển khai đề xuất:**
1. **Pitch deck:** Rút 18 slide thành khoảng 12–15 slide chính. Đưa bằng chứng thị trường, vấn đề, workflow, demo, khác biệt lên trung tâm; technical details và competitor deep dive vào appendix.
2. **Landing page và web app:** Chuyển sang định vị Robotics Simulation Preparation. Web app dùng thuật ngữ theo từng bước công việc, readiness và khả năng thực tế.
3. **Video giới thiệu:** Mạch xuyên suốt: môi trường thật → tái tạo → chỉnh sửa vật cản → thử nghiệm. Footage thật của Real2Sim; Isaac Sim chỉ đưa vào phần kết quả sau khi kiểm chứng.
4. **PRD, README, Architecture docs:** Chuẩn hóa persona, problem, use case, non-goals, requirements, acceptance. Giữ nguyên sự thật kỹ thuật; đổi cách định vị **không** có nghĩa viết lại chức năng thành những khả năng chưa tồn tại.

**Ba tầng của cùng một câu chuyện:**
- **Định vị chính:** Editable Real-to-Sim for Robotics
- **Ứng dụng MVP:** Indoor mobile robot testing
- **Tầm nhìn dài hạn:** Spatial Imagination for Robots

---

## 3. So sánh hai tài liệu và điểm cần lưu ý

### 3.1 Điểm thống nhất

- Định vị robotics, không phải 3D đại chúng hay kỷ niệm.
- Indoor mobile robotics là beachhead; warehouse là benchmark mở rộng, không phải điều kiện tồn tại.
- Room = kiểm chứng pipeline; warehouse/cảnh thực = kiểm chứng domain. Không dùng kết quả loại này để khẳng định loại kia.
- Phỏng vấn 5–8 người trước khi khẳng định pain point.
- Không tuyên bố tiết kiệm % khi chưa có benchmark; không tuyên bố "đầu tiên".
- Tầm nhìn "Spatial Imagination" / "Counterfactual simulation" là tương lai, không phải năng lực hiện tại.

### 3.2 Khác biệt cần chốt

| Hạng mục | BRAINSTORM.md | MASTER_PITCH.md | Đề xuất |
|---|---|---|---|
| Tagline / thông điệp | "Tái tạo thế giới thực, thử nghiệm những tình huống chưa xảy ra." | "Let robots rehearse the real world before they enter it." | Dùng tagline của MASTER_PITCH (tài liệu này là nguồn gốc duy nhất). |
| Tên persona | Robotics Integration / Simulation Engineer | Robotics Simulation Engineer | Thống nhất theo MASTER_PITCH. |
| Dataset | Có TUM RGB-D `freiburg1_room`, HF `room/kitchen/playroom` | Chỉ nêu Staer Warehouses (R10) | Bổ sung TUM RGB-D và HF vào phần benchmark nếu team dùng. |
| Demo "hai bố trí" | Kéo bàn vào lối đi, chạy lại bài thử | Đổi vị trí bàn gần lối đi (Scenario A → B) | Giống nhau về ý, nhất quán. |

### 3.3 Điểm cần kiểm tra trước khi đưa ra ngoài

1. **Nguồn R3 (IFR):** URL trong MASTER_PITCH là `ifr.org/ifr-press-releases/news/record-4-million-robots-work-in-factories-around-the-globe` — tiêu đề gợi ý thông cáo về **robot công nghiệp (factory)**, trong khi slide 06 dùng số liệu **service robots** (250.000, 117.500 vận tải/logistics). Cần mở lại nguồn và thay URL đúng nếu số liệu nằm ở báo cáo khác. Đây là điểm dễ bị giám khảo bắt lỗi.
2. **Số liệu test trong slide 14:** "623 frontend tests và 391 backend regression tests PASS" — tài liệu tự ghi chú chỉ dùng khi đã xác minh lại trên code cuối.
3. **Chưa có E2E Isaac Sim:** Mọi câu về "robot chạy trong Isaac Sim" phải có điều kiện hoặc ghi rõ là kế hoạch.
4. **Browser Walk:** Phải ghi là *browser physics preview*, không phải Isaac Sim.
5. **Ảnh và link rác trong BRAINSTORM.md:** Có nhiều link `images.openai.com` và một link ảnh tiếng Hàn không liên quan; nên dọn trước khi dùng làm nội bộ hoặc đưa vào repo công khai.

---

## 4. Checklist áp dụng nhanh

Khi viết bất kỳ nội dung nào (slide, landing, video, README, PRD) từ hai tài liệu này:

- [ ] Có dùng category *Editable Real-to-Sim Workspace for Robotics* không? (không dùng "3D generator", "memory app", "full simulator")
- [ ] Có nói "đầu tiên" hay "tốt hơn NuRec/Marble/SimFoundry" không? → Gỡ bỏ.
- [ ] Có số % tiết kiệm thời gian không? → Gỡ bỏ, thay bằng "giả thuyết cần đo".
- [ ] Có dùng footage/kết quả Isaac Sim không? → Chỉ dùng nếu đã chạy thật; ghi rõ nếu là mô phỏng hoặc preview.
- [ ] Có ngụ ý khách hàng đã dùng không? → Gỡ bỏ nếu chưa có bằng chứng.
- [ ] Có tách rõ Reality Capture / Editable 3D Scene / Simulation-Ready Scene không?
- [ ] Có nêu nguồn cho số liệu thị trường (R1–R10) không?
- [ ] Có tách Gaussian visual / object collider / environment collision không?

---

## 5. Tóm tắt một đoạn

Real2Sim Studio được định vị lại từ "công cụ chuyển video thành 3D" sang **không gian làm việc chỉnh sửa được để chuẩn bị môi trường mô phỏng robot từ quan sát thực**. Người dùng đầu tiên là kỹ sư mô phỏng/tích hợp robot di động trong nhà; use case MVP là kiểm tra robot trước và sau khi thay đổi bố trí một vật cản. Giá trị cần chứng minh là **giảm tổng công sức và thời gian** từ video đến scene đủ điều kiện test, qua benchmark có kiểm soát, chứ không phải vì có 3D đẹp hay "đầu tiên". Tầm nhìn dài hạn là giúp robot diễn tập nhiều phiên bản giả định của thế giới thực trước khi gặp chúng. Mọi tuyên bố phải bám theo quy tắc bằng chứng ở Phần XI.
