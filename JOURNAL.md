# Weekly Journal — Team P-087 (Real2Sim Studio)

> Ghi theo nhóm kết quả, quyết định và bài học của từng tuần. Mỗi tuần được chia thành 4 khung riêng cho 4 thành viên phụ trách 4 track kỹ thuật để theo dõi sát sao đóng góp và tiến độ độc lập. Giai đoạn 17–23/09 là chuẩn bị/Foundation M0; theo [Execution Plan](docs/execution/TEAM_EXECUTION_PLAN.md), Tuần 1 subsystem bring-up bắt đầu 24/09.

---

## Tuần chuẩn bị / Foundation M0: 17/09/2026 - 23/09/2026

### 1. Lâm Quang Anh Quân (`EX-REC` — Reconstruction / Lead)
- **Mục tiêu tuần này:**
  - [x] Khóa phạm vi Warehouse/Indoor AMR MVP và tài liệu sản phẩm làm source of truth.
  - [x] Khóa ownership, shared handoff contracts và bộ task cho bốn track.
  - [x] Chuẩn bị Foundation fixtures/tests để các track có thể bắt đầu phát triển độc lập.
- **Đã hoàn thành:**
  - Đồng bộ [BRIEF](docs/BRIEF.md), [PRD](docs/PRD.md), [Dataset Playbook](docs/DATASET_PLAYBOOK.md) và [execution docs](docs/execution/). TorWIC `Aisle_CW` được chọn làm traversal P0, `Aisle_CCW` là backup; bằng chứng REC-01B được ghi với phần chưa xác nhận tách riêng.
  - Thiết lập [harness](AGENTS.md), [kiến trúc](ARCHITECTURE.md), track/task cards và Foundation code: typed contracts, artifact store, synthetic fixtures, positive/negative contract tests và handoff checker.
  - Khóa yêu cầu EX-PRODUCT: Web Studio có view **3DGS thật** ở P0 và kỹ sư chuyển sang geometry, point cloud, collider để kiểm tra; bổ sung source map/references đồ họa.
  - Nâng cấp backend scaffold đa provider và luồng AI-log, chuẩn hóa Python 3.12/dependency setup.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Tài liệu mô tả không thống nhất về SceneIR, ReconstructionBundle, validation, task ID và ranh giới dữ liệu GT. | Phân quyền source of truth, sửa contract/crosswalk và kiểm tra bằng shared schemas/fixtures. | Bốn track có handoff mẫu cùng schema; không cần chờ upstream chạy GPU để bắt đầu code. |
  | Dễ nhầm dataset-native TorWIC facts với quy ước universal hoặc đánh đồng synthetic proof với real acceptance. | Tách TorWIC adapter/evaluation provenance khỏi canonical models; ghi rõ mức độ bằng chứng trong docs/checker. | Foundation không hard-code một traversal vào shared contract; real reconstruction/Isaac vẫn là việc sau M0. |
- **Bài học:**
  - Universal ở contract, concrete ở adapter: không để TorWIC, Brush hay Isaac định nghĩa dữ liệu trao đổi của toàn hệ thống.
  - Fixture/contract pass giúp phát triển song song, nhưng không thay thế acceptance của pipeline thật, trình duyệt hay GPU runtime.

### 2. Lê Mạnh Cường (`EX-PRODUCT` — Product/Orchestration)
- **Mục tiêu tuần này:**
  - [x] Onboarding kiến trúc hệ thống và nhận diện ranh giới track EX-PRODUCT.
  - [x] Khảo sát yêu cầu Web Studio và bộ contract giao tiếp với backend FastAPI.
- **Đã hoàn thành:**
  - Nắm vững kiến trúc Web Studio, yêu cầu hiển thị 3DGS thật P0 cùng các view kỹ thuật (geometry, point cloud, collider).
  - Chuẩn bị môi trường phát triển Next.js 16, React 19 và TypeScript.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Cần làm rõ ranh giới giữa backend nghiệp vụ và frontend client. | Nghiên cứu kỹ shared contracts và tài liệu kiến trúc ARCHITECTURE.md. | Xác định mô hình phát triển mock-first API trước khi tích hợp pipeline thật. |
- **Bài học:**
  - Bám sát Pydantic models của shared contracts giúp định hình TypeScript interfaces cho frontend chuẩn xác.

### 3. Đức (`EX-SCENE` — Scene/Object)
- **Mục tiêu tuần này:**
  - [x] Onboarding tài liệu kỹ thuật và ranh giới track EX-SCENE.
  - [x] Khảo sát các giải pháp phân đoạn vật thể 3D (SAM2, Open3D).
- **Đã hoàn thành:**
  - Nghiên cứu tài liệu kiến trúc `ARCHITECTURE.md` và hợp đồng `src/models/contracts/scene.py`.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Dữ liệu đầu vào từ Reconstruction chưa có sẵn trong tuần M0. | Dùng synthetic fixture `fixtures/` để mô phỏng dữ liệu đầu vào. | Có thể thiết kế trước cấu trúc dữ liệu SceneIR mà không bị tắc nghẽn. |
- **Bài học:**
  - Tách bạch giữa hình học vật thể và thuộc tính ngữ nghĩa giúp linh hoạt trong việc chỉnh sửa cảnh.

### 4. Nguyễn Thọ Đạt (`EX-SIM` — Simulation/Evaluation)
- **Mục tiêu tuần này:**
  - [x] Onboarding tài liệu kỹ thuật và ranh giới track EX-SIM.
  - [x] Khảo sát pipeline OpenUSD và môi trường NVIDIA Isaac Sim / IsaacLab.
  - [x] Xây dựng bản thiết kế Wireframe & UI Flow cho toàn bộ hệ thống và chuẩn hóa tooling hook.
  - [x] Tích hợp bộ công cụ RunPod GPU serverless và HTML Prototype.
- **Đã hoàn thành:**
  - Nghiên cứu hợp đồng `src/models/contracts/simulation.py` và quy chuẩn kiểm thử mô phỏng.
  - Xây dựng tài liệu thiết kế giao diện `docs/WIREFRAME_AND_UI_FLOW.md` cho 5 màn hình chính của RAV-01 và báo cáo phân tích sâu `docs/RAV01_Real2Sim_Problem_Deep_Dive_Report.md` (commit `dce97b0`).
  - Sửa script PowerShell `scripts/setup_hooks.ps1` tạo pre-push hook UTF-8 no BOM chuẩn hóa môi trường Windows/Linux (commit `63fc867`).
  - Tích hợp kỹ năng RunPod GPU serverless (`.agents/skills/runpod*`, `skills-lock.json`), tài liệu `docs/TODO.md` và bản mẫu giao diện tương tác `docs/prototype/index.html` (commit `bcbc517`).
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Cần môi trường phần cứng đủ mạnh để cài đặt và chạy Isaac Sim. | Chuẩn bị trước các script nạp mô hình và kịch bản thử nghiệm dạng headless; tích hợp bộ công cụ RunPod để sẵn sàng scale lên GPU cloud. | Tối ưu hóa việc sử dụng tài nguyên máy tính khi mô phỏng, sẵn sàng cho hạ tầng đám mây. |
  | Git pre-push hook trên Windows bị lỗi encoding BOM gây crash bash script. | Cấu hình PowerShell hook tạo file encoding UTF-8 without BOM với LF line endings. | Git hook chạy mượt mà trên cả Windows PowerShell và Linux Bash. |
- **Bài học:**
  - Mô phỏng robotics đòi hỏi mô hình va chạm phải có cấu trúc hình học chuẩn xác (watertight mesh), không thể chỉ dùng đám mây điểm.
  - Tách bạch sớm giao diện người dùng và luồng dữ liệu (UI Flow) giúp các track hiểu rõ điểm xuất phát và đích đến của artifact.

### Kế hoạch tuần sau (Toàn team)
- [ ] Bốn track branch từ cùng baseline SHA sau khi hoàn tất review/CI; giữ shared contract change dưới producer–consumer review.
- [ ] EX-REC inspect dữ liệu TorWIC thực trước REC-02; EX-SCENE, EX-SIM, EX-PRODUCT phát triển từ fixtures tương ứng.
- [ ] EX-PRODUCT scaffold frontend/backend workflow và kiểm chứng riêng browser 3DGS bằng Brush output thật.

---

## Tuần 1 — Subsystem Bring-up: 24/09/2026 - 28/09/2026

### 1. Lâm Quang Anh Quân (`EX-REC` — Reconstruction)
- **Mục tiêu tuần này:**
  - [x] Khóa ma trận tái sử dụng mã nguồn 9 open-source repos và frozen split TorWIC-SLAM.
  - [x] Hoàn thành REC-01, REC-02, REC-02A (data ingestion, privacy gate, frame extraction).
  - [x] Hoàn thành REC-03 (COLMAP SfM, camera poses, sparse point cloud).
  - [x] Hoàn thành REC-04 (Brush 3DGS adapter, SOG web packaging, GPU smoke thực tế, preview render).
  - [ ] Khởi động REC-05 (Voxel Geometry & Collision Mesh) và khóa điều kiện Metric Scale REC-06.
- **Đã hoàn thành:**
  - Hoàn thiện 10 tài liệu audit kỹ thuật (`docs/execution/audits/`) và Cross-repo Reuse Matrix phân tầng Tier 1/2/3 trong `INTEGRATION_PLAYBOOK.md`.
  - Bộ công cụ trích xuất ảnh chuẩn TorWIC và Cổng lọc bảo vệ quyền riêng tư (Privacy Gate) tự động làm mờ khuôn mặt/biển số nhạy cảm.
  - COLMAP SfM adapter đăng ký thành công 65/65 khung hình TorWIC `Aisle_CW` (100%), sinh 6.202 điểm thưa.
  - Brush 3DGS adapter và module nén SOG chạy thực tế trên GPU tích hợp Intel UHD 630 qua Vulkan backend (23.15 giây), xuất `preview.webp`, 27 unit tests pass 100%, 226/226 toàn bộ test suite pass.
  - Khởi động REC-05 với kế hoạch 10 bước chi tiết cho Voxel Collision Mesh.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Máy tính cá nhân không có card đồ họa Nvidia rời đắt tiền để chạy CUDA 3DGS. | Khai thác backend Vulkan/LibTorch của thư viện Brush trên GPU tích hợp Intel UHD 630 onboard. | Chạy GPU smoke thực tế thành công trong 23.15s, xuất `scene.sog` và `preview.webp` chuẩn xác mà không cần phần cứng đắt đỏ. |
  | File PLY 3DGS gốc quá nặng (hàng trăm MB), gây quá tải RAM và giật lag khi mở trên trình duyệt web. | Tích hợp công nghệ nén SOG (Splat Octree Geometry) qua `splat-transform` (cầu nối Node.js). | Nén file 3D xuống kích thước nhỏ gọn (giảm 5-10 lần), giúp Web Studio hiển thị mượt mà. |
- **Bài học:**
  - Phần cứng đồ họa phổ thông (Intel UHD / Vulkan) hoàn toàn có thể chạy tốt mô hình 3DGS hiện đại nếu được tối ưu hóa pipeline.
  - Luôn tách biệt mô hình thị giác (`visual.ply`/`scene.sog`) với mô hình va chạm (`collision.glb`) để phục vụ tối ưu cho từng mục đích (nhìn đẹp mắt vs va chạm vật lý).

### 2. Lê Mạnh Cường (`EX-PRODUCT` — Product/Orchestration)
- **Mục tiêu tuần này:**
  - [x] Lập kế hoạch hành động 13 tasks cho track EX-PRODUCT theo milestone M1–M6.
  - [x] Triển khai API mock-first cho project/job/artifact kèm privacy gate (PRODUCT-01).
  - [x] Triển khai Job state machine và cơ chế persistence (PRODUCT-02).
  - [ ] Hoàn thiện Web shell Next.js (PRODUCT-05) và Scene viewer 3 view (PRODUCT-06).
- **Đã hoàn thành:**
  - 8 endpoint `/api/v1` quản lý project/job, bộ lọc artifact theo `data_class` và kiểm tra quyền riêng tư.
  - State machine bất biến cho job lifecycle (QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED).
  - Dựng scaffold frontend `frontend/` (Next.js 16 + React 19 + Tailwind 4), 8 route chức năng; 54 unit tests pass, npm run build thành công.
  - Scene viewer backend với cơ chế optimistic concurrency (409 khi revision cũ) và frontend viewer 3 layer.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Cần tránh lỗi CORS giữa Next.js frontend và FastAPI backend mà không được sửa file `main.py` và `config.py` ngoài ownership. | Cấu hình proxy `/api/v1/*` bằng Next.js rewrites trong `next.config.ts`. | Frontend gọi API backend thông suốt mà vẫn giữ đúng nguyên tắc ranh giới quyền sở hữu file. |
- **Bài học:**
  - Dựng API mock-first dựa trên typed contract giúp frontend có thể chạy kiểm thử và hoàn thiện giao diện ngay lập tức mà không cần chờ toàn bộ worker backend thật hoàn thành.

### 3. Đức (`EX-SCENE` — Scene/Object)
- **Mục tiêu tuần này:**
  - [ ] Thiết lập môi trường chạy SAM2 và thuật toán liên kết điểm ảnh 2D với không gian 3D.
  - [ ] Tiếp nhận camera poses và sparse point cloud từ REC-03 để xây dựng cấu trúc SceneIR cho candidate object.
- **Đã hoàn thành:**
  - Rà soát tài liệu kiến trúc và hướng dẫn track EX-SCENE; chuẩn bị kịch bản tích hợp SAM2.
  - Tiếp nhận thông số 65 camera poses và đám mây điểm `sparse.ply` từ REC-03 để thử nghiệm phân đoạn sơ bộ.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Chờ dữ liệu camera pose và point cloud thực tế từ khâu Reconstruction. | Sử dụng dữ liệu synthetic fixture để viết trước cấu trúc dữ liệu SceneIR. | Tiến độ không bị chặn hoàn toàn, sẵn sàng kết nối dữ liệu thật ngay khi REC-03 hoàn tất. |
- **Bài học:**
  - Handoff contract và fixture giúp các track độc lập tiến độ ngay cả khi dữ liệu thực tế đang trong quá trình xử lý.

### 4. Nguyễn Thọ Đạt (`EX-SIM` — Simulation/Evaluation)
- **Mục tiêu tuần này:**
  - [x] Hoàn thành task SIM-04: Deterministic Preflight (6 quy tắc P0, preflight engine, checksum validation).
  - [x] Hoàn thành task SIM-02: Collider Generation Utilities (AABB, OBB, Convex Hull, Simplified Mesh, Safeguard 1 & 2).
  - [x] Chuẩn hóa test harness, sửa cấu hình LLM/conftest và dọn sạch linter repository.
  - [ ] Tiếp tục nghiên cứu OpenUSD generator (SIM-01) và kịch bản nạp robot AMR vào Isaac Sim.
- **Đã hoàn thành:**
  - `SIM-04` (commit `49e9660`): Cài đặt engine thẩm định tĩnh độc lập với 6 quy tắc P0 (`METRIC_SCALE_MISSING`, `COLLIDER_MISSING`, `TRANSFORM_INVALID`, `OBJECT_OUT_OF_BOUNDS`, `REQUIRED_ARTIFACT_MISSING`, `OBJECT_CONFIRMATION_INCOMPLETE`), niêm phong SHA-256 `report_checksum`, 9/9 unit tests pass.
  - `SIM-02` (commit `bdf5f4d`): Cài đặt bộ sinh collider proxy với Trimesh + Scipy, Safeguard 1 mặt sàn `create_ground_plane_collider`, Safeguard 2 ưu tiên Box `generate_object_collider`, 8/8 unit tests pass.
  - Chuẩn hóa test harness (commit `7e8e453`): Cấu hình mock key mặc định trong `conftest.py`, sửa 5 cảnh báo `UP022` ruff bằng `capture_output=True`. Nguyễn Thọ Đạt17/17 tests pass cho `EX-SIM`, `ruff check .` sạch 100%.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | Điểm đám mây hoặc mesh suy biến (planar/coplanar point cloud) làm thuật toán Quickhull của Trimesh bị lỗi phân giải (simplex crash). | Cài đặt cơ chế an toàn Safeguard 2 trong `generator.py`: bắt lỗi QhullError và tự động fallback về Box/AABB dựa trên `primitive_dimensions_xyz_m`. | Sinh proxy collider ổn định 100%, không bị crash dù dữ liệu điểm thô có nhiễu hoặc phẳng. |
  | `conftest.py` yêu cầu `GEMINI_API_KEY` khiến test chạy ở môi trường CI/local thiếu key bị gián đoạn. | Thêm giá trị mock fallback `"mock-api-key-for-testing-only"` vào `conftest.py`. | Chạy `pytest` cục bộ hoàn toàn độc lập, không phụ thuộc vào API key bên ngoài. |
- **Bài học:**
  - Phân tách triệt để logic hình học/thẩm định tĩnh thuần Python (Local) khỏi engine mô phỏng nặng (GPU Isaac Sim) giúp phát triển nhanh, kiểm thử tự động đạt độ tin cậy cao và không bị nghẽn phần cứng.
  - Luôn có phương án fallback hình học (AABB/Box) khi xử lý dữ liệu point cloud thực nghiệm.

### Kế hoạch tuần sau (Toàn team)
- [ ] Hoàn thành task REC-05 (Voxel Collision Mesh) và REC-06 (Metric Scale Anchor) để bàn giao lưới va chạm thật cho EX-SIM.
- [ ] Tích hợp loader SOG (`supersplat-viewer` trên PlayCanvas Engine) vào Web Studio để hiển thị `scene.sog` trực tiếp trên trình duyệt.
- [ ] EX-SCENE triển khai trích xuất candidate object với SAM2 từ mô hình `visual.ply`.
- [ ] EX-SIM nạp thử nghiệm `collision.glb` vào Isaac Sim và chạy kịch bản va chạm robot AMR đầu tiên.

---

## Tuần 2 — Build + Integration #1: 29/09/2026 - 05/10/2026

### 1. Lâm Quang Anh Quân (`EX-REC` — Reconstruction)
- **Mục tiêu tuần này:**
  - [ ] Triển khai hoàn tất REC-05 (Voxel Geometry & Collision Mesh) và xuất file `collision.glb` watertight. *(collision mesh chạy thật trong pipeline; tiêu chí chặn giả ghost-block chưa đạt, watertight chưa kiểm — xem REC-05)*
  - [x] Triển khai REC-06 (Metric Scale Anchor) để chuẩn hóa kích thước mét thật cho mô hình 3D. *(xác nhận tỉ lệ từ UI, PR #15; sai số `e` đo lần 1 ≈ 15,6 cm, chưa khoá)*
- **Đã hoàn thành (đến 30/09):**
  - Tích hợp đầu-cuối trên `feat/studio-integration` (PR #16): tách vật SAMPro3D + SAM2, sửa SceneIR theo vật, gói mô phỏng USD + preflight (PASS 6/6 trên `job-123dfd4868d8`), duyệt/phát hành, refactor UI theo PRODUCT.md.
  - Đo chất lượng 3DGS: `seg-5fps-cap600k` PSNR 28,80 / SSIM 0,927 / LPIPS 0,268.
  - Audit repo + tra cứu Isaac Sim → chốt pipeline v2 (ADR 0007): scene theo vật, xuất USD lai.
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | 3DGS hệ mét nằm lệch trục trong viewer | Viewer luôn xoay splat theo quy ước COLMAP; đặt riêng phép xoay cho nội dung Z-up | Hiển thị đúng, camera mở tại góc quay đầu tiên |
  | Brush crash khi 5 fps (663k splat, GPU 4 GB) | Giới hạn `max_splats` 600k | Lượt chấm hoàn tất, điểm tốt nhất hiện có |
  | Video train-split có khoảng trống làm COLMAP vỡ nhiều mảnh | Dùng đoạn liền 154–527 | Sweep so sánh được |
  | Ẩn/xoá vật chỉ đổi màu hộp, hình không đổi | Tra cứu Isaac + audit repo, đổi đích pipeline | ADR 0007 |
- **Bài học:**
  - Kiểm tra "đầu vào thật sự" của hệ đích (Isaac nhận cả Gaussian) trước khi thiết kế pipeline.
  - Ba lớp dữ liệu cùng hệ toạ độ chưa phải là scene chỉnh sửa được; cần ghép theo vật từ đầu.

### 2. Lê Mạnh Cường (`EX-PRODUCT` — Product/Orchestration)
- **Mục tiêu tuần này:**
  - [ ] Tích hợp PlayCanvas Engine và supersplat-viewer vào Web Studio shell.
  - [ ] Hoàn thiện kết nối API giữa Web Studio và worker backend.
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 3. Đức (`EX-SCENE` — Scene/Object)
- **Mục tiêu tuần này:**
  - [ ] Hoàn thiện liên kết mask 2D từ SAM2 sang đối tượng 3D (3D bounding boxes).
  - [ ] Xuất bản bản ghi `SceneIR` có thể chỉnh sửa đối tượng cho Web Studio.
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 4. Nguyễn Thọ Đạt (`EX-SIM` — Simulation/Evaluation)
- **Mục tiêu tuần này:**
  - [ ] Nạp `collision.glb` vào môi trường NVIDIA Isaac Sim 4.0 qua OpenUSD.
  - [ ] Chạy mô phỏng di chuyển cơ bản của robot AMR trong lối đi kho hàng.
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### Kế hoạch tuần sau (Toàn team)
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Tuần 3 — E2E + Feature Freeze: 06/10/2026 - 12/10/2026

### 1. Lâm Quang Anh Quân (`EX-REC` — Reconstruction)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu tuần 3 của EX-REC]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 2. Lê Mạnh Cường (`EX-PRODUCT` — Product/Orchestration)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu tuần 3 của EX-PRODUCT]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 3. Đức (`EX-SCENE` — Scene/Object)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu tuần 3 của EX-SCENE]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 4. Nguyễn Thọ Đạt (`EX-SIM` — Simulation/Evaluation)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu tuần 3 của EX-SIM]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### Kế hoạch tuần sau (Toàn team)
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Giai đoạn Integration Buffer + Pitch Sprint: 13/10/2026 - 19/10/2026

### 1. Lâm Quang Anh Quân (`EX-REC` — Reconstruction)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu sprint pitch của EX-REC]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 2. Lê Mạnh Cường (`EX-PRODUCT` — Product/Orchestration)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu sprint pitch của EX-PRODUCT]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 3. Đức (`EX-SCENE` — Scene/Object)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu sprint pitch của EX-SCENE]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### 4. Nguyễn Thọ Đạt (`EX-SIM` — Simulation/Evaluation)
- **Mục tiêu tuần này:**
  - [ ] [Mục tiêu sprint pitch của EX-SIM]
- **Đã hoàn thành:**
  - [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:**
  | Khó khăn | Giải pháp | Kết quả |
  |----------|-----------|---------|
  | [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |
- **Bài học:**
  - [Bài học từ công việc thực tế]

### Kế hoạch tuần sau (Toàn team)
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Ngày 20/10/2026 — Nhật ký bổ sung (chưa có milestone trong Execution Plan)

### 1. Lâm Quang Anh Quân (`EX-REC` — Reconstruction)
- **Mục tiêu:** [Mục tiêu cá nhân]
- **Đã hoàn thành:** [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:** [Vấn đề & cách giải quyết]
- **Bài học:** [Bài học rút ra]

### 2. Lê Mạnh Cường (`EX-PRODUCT` — Product/Orchestration)
- **Mục tiêu:** [Mục tiêu cá nhân]
- **Đã hoàn thành:** [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:** [Vấn đề & cách giải quyết]
- **Bài học:** [Bài học rút ra]

### 3. Đức (`EX-SCENE` — Scene/Object)
- **Mục tiêu:** [Mục tiêu cá nhân]
- **Đã hoàn thành:** [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:** [Vấn đề & cách giải quyết]
- **Bài học:** [Bài học rút ra]

### 4. Nguyễn Thọ Đạt (`EX-SIM` — Simulation/Evaluation)
- **Mục tiêu:** [Mục tiêu cá nhân]
- **Đã hoàn thành:** [Chỉ điền kết quả đã có bằng chứng]
- **Khó khăn & Giải pháp:** [Vấn đề & cách giải quyết]
- **Bài học:** [Bài học rút ra]

### Kế hoạch tuần sau (Toàn team)
- [ ] [Bước tiếp theo khi đã xác nhận]

---
