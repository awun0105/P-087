# Kế hoạch Tái sử dụng Mã nguồn Tổng thể (Cross-Repo Reuse Plan & Final Matrix)

> **Tài liệu tham chiếu:** Báo cáo Tổng hợp Deep Audit cho Toàn bộ Real2Sim Studio (AI20K RAV-01)  
> **Trạng thái:** Hoàn tất toàn bộ quy trình Audit (7/7 Repositories + 1 Core Utility)  
> **Các tài liệu audit thành phần:**  
> 1. [`01_openreal2sim.md`](./01_openreal2sim.md) — `PointsCoder/OpenReal2Sim` (Tier-0 Code Donor cho `EX-SIM`)  
> 2. [`02_r2g.md`](./02_r2g.md) — `BigCiLeng/R2G` (Tier-0 Algorithm Donor cho `EX-SCENE`)  
> 3. [`03_vr_robo.md`](./03_vr_robo.md) — `zst1406217/VR-Robo` (Tier-0 Integration Donor cho `EX-SIM`)  
> 4. [`04_supersplat.md`](./04_supersplat.md) — `playcanvas/supersplat` (Tier-0 Code Donor cho `EX-PRODUCT`)  
> 4a. [`04a_splat_transform.md`](./04a_splat_transform.md) — `playcanvas/splat-transform` (Tier-0 Core Utility xuyên suốt `REC/PRODUCT/SIM`)  
> 5. [`05_discoverse.md`](./05_discoverse.md) — `discoverse-dev/DISCOVERSE` & `DISCOVERSE-Real2Sim` (Tier-0 Integration Reference & P1 Donor)  
> 6. [`06_gaussian_grouping.md`](./06_gaussian_grouping.md) — `lkeab/gaussian-grouping` (Tier-0 Algorithm Reference & Tier-1 Qualification Candidate)  
> 7. [`07_re3sim.md`](./07_re3sim.md) — `InternRobotics/Re3Sim` (Tier-0 System Architecture Reference)

---

## 1. Kết luận Cấp cao & Xác thực Kiến trúc

Toàn bộ 7 repository và 1 utility sau khi audit trực tiếp từ source code (không chỉ đọc README/Paper) đã **xác nhận độc lập tính đúng đắn của Architecture mà Real2Sim Studio đã khóa**:

1. **Bảo toàn Invariant Cốt lõi:**
   ```text
   Visual ≠ Geometry ≠ Physics
   ```
   Các hệ thống thực tế thành công (`Re3Sim`, `OpenReal2Sim`, `VR-Robo`, `DISCOVERSE`) đều **tách bạch representation thị giác (3DGS) khỏi biểu diễn hình học/vật lý (OpenMVS Mesh / OpenUSD / PhysX)**, tuyệt đối không cố ép 3DGS làm physics truth.
2. **Hai nhánh độc lập từ chung SfM Poses:**
   `COLMAP` cung cấp hệ camera poses duy nhất; từ đó rẽ thành 2 nhánh:
   - Nhánh Thị giác: `Brush` (tối ưu hóa 3DGS photorealistic).
   - Nhánh Hình học: `OpenMVS` (tạo dense point cloud $\rightarrow$ reconstructed mesh).
   Mô hình này trùng khớp hoàn toàn với pipeline của `Re3Sim`.
3. **Phân tách Tiến trình (Process Isolation):**
   Môi trường mô phỏng vật lý (`IsaacLab`) và môi trường render thị giác (`3DGS`) chạy ở các tiến trình độc lập, đồng bộ thông qua camera pose và object transforms (`VR-Robo`, `DISCOVERSE`, `Re3Sim`).
4. **Trực quan hóa & Thao tác trên Web:**
   Sử dụng WebGPU projected splats, multi-layer Splats và transform gizmos (`SuperSplat`), kết hợp tối ưu hóa streaming LOD / SOG (`splat-transform`).

---

## 2. Ma trận Năng lực Toàn diện (Master Cross-Repo Matrix)

Đánh giá mức độ đóng góp thực tế của từng repository đối với các năng lực trong Real2Sim Studio:

| Năng lực / Phân hệ | OpenReal2Sim | R2G | VR-Robo | SuperSplat | splat-transform | DISCOVERSE | Gaussian Grouping | Re3Sim |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Global Reconstruction (SfM/Pose)** | Med | Med | Low | — | — | Low | Low | **Very High** |
| **3DGS Artifact Tooling & LOD** | Low | Med | Med | High | **Very High** | Med | Low | Med |
| **Multi-view Mask Association** | Low | **Very High** | Low | — | Low | Low | High (qual) | Low |
| **Object-level 3DGS Visual** | Med | **High** | High | High | Med | **High** | **Very High** | Low |
| **Web 3D Viewer & Editor** | — | — | — | **Very High** | Utility | — | — | — |
| **Collider Generation / Convex Dec.** | **Very High** | Low | Low | — | Med (fallback) | **High (CoACD)** | Low (heuristic) | **High** |
| **OpenUSD Physics Stage Build** | **Very High** | — | Low | — | — | — | — | **High** |
| **Isaac Sim / IsaacLab Runtime** | High | — | **Very High** | — | — | — | — | **Very High** |
| **Visual ↔ Physics State Sync** | Med | — | **Very High** | — | — | **Very High** | — | **Very High** |
| **Remote GS Streaming (P1)** | — | — | Med | — | — | **Very High** | — | — |
| **Mesh-seeded GS / Asset Gen (P1)** | Med | — | — | — | — | **Very High** | — | — |
| **Real-robot Calibration (P1/P2)** | Low | — | — | — | — | — | — | **Very High** |

---

## 3. Kế hoạch Tái sử dụng theo từng Task (Task-by-Task Implementation Strategy)

### 3.1 Phân hệ Tái tạo Không gian (`EX-REC`)

| Task ID | Tên Task | Primary Donor | Secondary Donor | Chiến lược | Module / File trích xuất cụ thể |
|---|---|---|---|:---:|---|
| **REC-01** | Raw Ingestion & Validation | `SELF-CODE` | — | `SELF-CODE` | FFmpeg video inspection, frame drop check, metric timestamp verification. |
| **REC-02** | Sensor Calibration & Extrinsics | `SELF-CODE` | Re3Sim | `SELF-CODE` + `REFERENCE` | Đọc `TorWIC` calibration matrix; tham chiếu Tsai hand-eye calibration của Re3Sim (`real-deployment/calibration/`). |
| **REC-03** | COLMAP SfM & Camera Poses | `Re3Sim` | `colmap/colmap` | `ADAPT` | Trích xuất PyCOLMAP sequential matching, vocab-tree selection (`re3sim/scripts/reconstruct.py`). Bổ sung fail-fast subprocess và chọn largest valid cluster. |
| **REC-04** | Brush 3DGS Visual Reconstruction | `ArthurBrussee/brush` | `splat-transform` | `REUSE` + `ADAPT` | Brush CLI làm primary backend; `splat-transform` (`readFileInfo`, `validate`, Morton reorder, `fillRatio`) làm QA và chuẩn hóa delivery. |
| **REC-05** | OpenMVS Dense Geometry & Mesh | `Re3Sim` | `cdcseacave/openMVS` | `ADAPT-HIGH` | Trích xuất chuỗi lệnh orchestration: `InterfaceCOLMAP` $\rightarrow$ `DensifyPointCloud` $\rightarrow$ `ReconstructMesh` $\rightarrow$ `RefineMesh` (từ `reconstruct.py`). Bổ sung timeout và checksum. |
| **REC-06** | Metric Canonicalization | `Re3Sim` | `Open3D` | `ADAPT-HIGH` + `REIMPLEMENT` | Trích xuất kiến trúc frame graph từ `re3sim/utils/frame_tools.py` và giải thuật similarity transform giữa trajectories (`compute_transform_to_marker_aruco.py`). Gắn với LiDAR metric ground-truth của TorWIC. Spike `REC-QUAL-FRAME-01`. |
| **REC-07** | ReconstructionBundle Packaging | `SELF-CODE` | — | `SELF-CODE` | Đóng gói bundle bất biến, SHA-256 manifest, verification script. |

---

### 3.2 Phân hệ Phân rã Ngữ cảnh (`EX-SCENE`)

| Task ID | Tên Task | Primary Donor | Secondary Donor | Chiến lược | Module / File trích xuất cụ thể |
|---|---|---|---|:---:|---|
| **SCENE-01** | Fixture Bundle Consumer | `SELF-CODE` | — | `SELF-CODE` | Đọc `ReconstructionBundle` schema, kiểm tra tính toàn vẹn và checksum. |
| **SCENE-02** | 2D Object Mask Propagation | `facebookresearch/sam2` | — | `REUSE` | Tích hợp SAM2 video predictor qua subprocess/worker container, xuất mask frames artifact. |
| **SCENE-03** | Multi-View Mask Association | `BigCiLeng/R2G` (SAMPro3D) | `Gaussian Grouping` | `ADAPT-HIGH` + `QUALIFICATION` | Adapt SAMPro3D (`perform_3dsegmentation`, 3D-to-2D projection, multi-view score voting, DBSCAN spatial filtering, `prompt_consolidation`). Thiết lập spike `SCENE-QUAL-GG-01` đối chứng với loss không gian 3D kNN của Gaussian Grouping. |
| **SCENE-04** | Candidate Object Model | `SELF-CODE` | — | `SELF-CODE` | Định nghĩa candidate state, bounding box OBB, mask references và provenance. |
| **SCENE-05** | Human Confirmation Operations | `SELF-CODE` | — | `SELF-CODE` | Các domain operations: `confirm`, `merge`, `split`, `ignore`, `reassign`, `create`. |
| **SCENE-06** | Scene Decomposition | `BigCiLeng/R2G` | `OpenReal2Sim` + `Gaussian Grouping` | `ADAPT-HIGH` | Trích xuất OBB định hướng qua `get_aabb.py` (R2G); tiện ích đăng ký mây điểm từ `scenario_construction.py` (OpenReal2Sim); quản lý ánh xạ `GaussianObjectMembership` và ẩn/hiện non-destructive (Gaussian Grouping). |
| **SCENE-07** | SceneObject Canonical Model | `SELF-CODE` | `Re3Sim` | `SELF-CODE` + `REFERENCE` | Mô hình hóa `SceneObject` gồm `visual_ref`, `geometry_ref`, `collider_ref`, `transform` (tham chiếu tách đôi USD/GS asset của Re3Sim). |
| **SCENE-08** | Edit Semantics | `SELF-CODE` | — | `SELF-CODE` | Logic dịch chuyển, xoay, ẩn, xóa (soft delete / visibility toggle). |
| **SCENE-08A**| Add Primitive / Asset | `SELF-CODE` | `Re3Sim` + `DISCOVERSE-Real2Sim` | `SELF-CODE` + `REFERENCE P1` | Khởi tạo vật thể hình học cơ bản; tham chiếu `Item.align_surface()` của Re3Sim và quy trình Mesh-seeded GS của DISCOVERSE-Real2Sim. |
| **SCENE-09** | Publish SceneIR | `SELF-CODE` | — | `SELF-CODE` | Serialization JSON, revision provenance, canonical coordinates validation. |
| **SCENE-10** | Worker Entrypoints | `SELF-CODE` | — | `SELF-CODE` | CLI wrappers cho các stage của EX-SCENE. |

---

### 3.3 Phân hệ Mô phỏng Vật lý (`EX-SIM`)

| Task ID | Tên Task | Primary Donor | Secondary Donor | Chiến lược | Module / File trích xuất cụ thể |
|---|---|---|---|:---:|---|
| **SIM-01** | Minimal Isaac Smoke | `VR-Robo` | `Re3Sim` | `ADAPT` | Khởi tạo IsaacLab headless, nạp stage cơ bản qua `UsdFileCfg`, spawn robot và sensor attachments. |
| **SIM-02** | Collider Generation | `OpenReal2Sim` | `DISCOVERSE` (CoACD) + `Re3Sim` + `splat-transform` | `ADAPT-HIGH` | Ground clearance và chống lún sàn (`scenario_collision_optimization.py` - OpenReal2Sim); CoACD convex decomposition (`mesh2mjcf.py` - DISCOVERSE); cấu hình `MeshConverterCfg` (`obj_to_usd.py` - Re3Sim); fallback voxel collision (`splat-transform`). Spike `SIM-QUAL-RE3-01`. |
| **SIM-02A**| Collider Edit Validation | `SELF-CODE` | — | `SELF-CODE` | Kiểm định tính hợp lệ sau khi người dùng chỉnh sửa collider trên Web. |
| **SIM-03** | Physics Enrichment | `SELF-CODE` | `Re3Sim` | `SELF-CODE` + `ADAPT` | Gán vật lý vào SceneIR; tham chiếu thiết lập stage units (`metersPerUnit = 1.0`, `kilogramsPerUnit = 1.0`, `Z-up`) từ `obj_to_usd.py` của Re3Sim. |
| **SIM-04** | Preflight Static Check | `SELF-CODE` | — | `SELF-CODE` | Kiểm tra tĩnh: tính kín của mặt sàn, không va chạm tĩnh giữa các vật thể, tọa độ hợp lệ. |
| **SIM-05** | Candidate OpenUSD Build | `OpenReal2Sim` | `Re3Sim` | `ADAPT-HIGH` | Dịch SceneIR sang Candidate USD: bóc tách logic `MeshConverter`, `UsdPhysics`, `RigidBodyPropertiesCfg`, CCD từ `usd_conversion.py` (OpenReal2Sim) và `obj_to_usd.py` (Re3Sim). Đóng gói CandidatePackage bất biến kèm SHA-256. |
| **SIM-06** | Isaac Validation Run | `VR-Robo` | `Re3Sim` + `DISCOVERSE` | `ADAPT-HIGH` | Vòng lặp simulation stepping, kiểm tra tiếp xúc va chạm, chuyển động robot Start-Goal (`vrrobo_isaaclab`). Replay MP4 qua Omniverse native capture (Gym `RecordVideo` làm fallback). Tách biệt visual process và physics process (`gs_model_dict`). |
| **SIM-07** | ValidationReport Generation | `SELF-CODE` | — | `SELF-CODE` | Xuất báo cáo kiểm định có cấu trúc, gắn với `candidate_checksum`. |
| **SIM-08** | Evaluation Harness | `SELF-CODE` | — | `SELF-CODE` | Benchmark tự động so khớp với metric dataset (evaluator-only). |
| **SIM-09** | Worker Entrypoints | `VR-Robo` | `OpenReal2Sim` | `ADAPT` | Container isolation, headless CLI wrappers. |

---

### 3.4 Phân hệ Sản phẩm & Web Studio (`EX-PRODUCT`)

| Task ID | Tên Task | Primary Donor | Secondary Donor | Chiến lược | Module / File trích xuất cụ thể |
|---|---|---|---|:---:|---|
| **PRODUCT-01**| Web Architecture & Scaffold | `Kiranism/next-shadcn...` | — | `ADAPT` | Next.js 14 App Router, Tailwind, Shadcn/UI, zustand client state. |
| **PRODUCT-02**| Auth & Project/Job API | `SELF-CODE` | — | `SELF-CODE` | FastAPI REST endpoints, Job status polling / SSE, RBAC. |
| **PRODUCT-03**| Pipeline Orchestration | `SELF-CODE` | — | `SELF-CODE` | Celery / Redis worker task queue, artifact storage manager. |
| **PRODUCT-04**| Project & Job Management UI | `Kiranism/next-shadcn...` | — | `ADAPT` | Bảng danh sách job, thanh tiến trình các giai đoạn pipeline, form tạo dự án. |
| **PRODUCT-05**| Human Confirmation HITL UI | `SELF-CODE` | — | `SELF-CODE` | Giao diện duyệt candidate objects: gán nhãn, đổi tên, merge, split, ignore. |
| **PRODUCT-06**| 3D Scene Viewer Shell | `SuperSplat` | `splat-transform` | `ADAPT-HIGH` | WebGPU projected splat renderer, camera orbit/fly, layer visibility toggles, multi-splats management. Spike `PRODUCT-06Q`. Tối ưu streaming qua SOG format (`splat-transform`). |
| **PRODUCT-07**| 3D Object Editing & Actions | `SuperSplat` | `Three.js` | `ADAPT-HIGH` | Transform gizmos (Translate, Rotate), selection tools (brush, lasso, box), Undo/Redo (`EditHistory`). Đồng bộ trạng thái về backend `SceneRevision`. |
| **PRODUCT-08**| Validation & Release Gate | `SELF-CODE` | — | `SELF-CODE` | Xem video replay simulation MP4, duyệt `ValidationReport`, Human Sign-off, phát hành `ReleaseManifest`. |

---

## 4. Danh mục Code và File Cụ thể Cần Trích xuất

### Nhóm 1: Tái tạo Hình học & Không gian (`EX-REC`)
1. **`Re3Sim/re3sim/scripts/reconstruct.py`**:
   - `extract_features()`, `feature_matching()`, `run_colmap()`: PyCOLMAP sequential matching orchestration.
   - Các lệnh gọi OpenMVS: `InterfaceCOLMAP`, `DensifyPointCloud`, `ReconstructMesh`, `RefineMesh`.
2. **`Re3Sim/re3sim/utils/frame_tools.py`**:
   - `FrameTools` class: Quản lý frame graph, trích xuất rotation matrix, scale factor (qua determinant), translation vector.
3. **`Re3Sim/real-deployment/utils/compute_transform_to_marker_aruco.py`**:
   - `get_transform_between_two_frames()`: Thuật toán ước tính similarity transformation (Umeyama / SVD) giữa 2 tập tọa độ camera trajectories.
4. **`playcanvas/splat-transform`**:
   - `readFileInfo()`: Đọc và kiểm định header PLY (số điểm, formats, `SplatRenderMode` metadata từ Brush).
   - `fillRatio` calculation: Đo lường độ overdraw của Gaussian splats phục vụ QA.
   - Morton reorder & SOG packaging: Tối ưu hóa tải dữ liệu 3DGS trên Web.

### Nhóm 2: Phân rã Đối tượng (`EX-SCENE`)
1. **`R2G/src/sampro3d/`**:
   - `perform_3dsegmentation.py`: Chiếu 3D điểm sang 2D views, visibility test, tích lũy điểm số mask.
   - `prompt_consolidation.py`: Nhóm các candidate masks tương đồng, khử nhiễu không gian bằng DBSCAN.
2. **`R2G/src/scripts/get_aabb.py`**:
   - Thuật toán tính minimal Oriented Bounding Box (OBB) sử dụng Open3D từ mây điểm đối tượng.
3. **`OpenReal2Sim/openreal2sim/reconstruction/modules/scenario_construction.py`**:
   - Tiện ích căn chỉnh mặt sàn và centroid alignment giữa mây điểm và lưới đa giác.

### Nhóm 3: Mô phỏng Vật lý & OpenUSD (`EX-SIM`)
1. **`OpenReal2Sim/openreal2sim/simulation/isaaclab/sim_preprocess/usd_conversion.py`**:
   - `convert_obj_to_usd()`: Gọi IsaacLab `MeshConverter` chuyển đổi mesh sang USD stage.
   - Cấu hình PhysX schemas: `UsdPhysics.CollisionAPI`, `PhysxSchema.PhysxRigidBodyAPI`, `RigidBodyPropertiesCfg`, CCD.
2. **`Re3Sim/re3sim/utils/usd/obj_to_usd.py`**:
   - Thiết lập chuẩn stage units (`metersPerUnit = 1.0`, `kilogramsPerUnit = 1.0`, `Z-up`).
   - Cấu hình các chế độ va chạm: `convexDecomposition`, `convexHull`, `meshSimplification`.
3. **`DISCOVERSE/scripts/mesh2mjcf.py`**:
   - Pipeline phân rã CoACD convex decomposition (`coacd` + `trimesh`) cho cấu trúc kệ hàng phức tạp thành các convex parts.
4. **`VR-Robo/vrrobo_isaaclab/`**:
   - Khởi tạo môi trường IsaacLab, `UsdFileCfg`, sensor attachments và vòng lặp `step()`.
   - `gym.wrappers.RecordVideo` pattern làm video capture fallback khi chạy headless.
5. **`DISCOVERSE/discoverse/gaussian_web_renderer/` (P1 Candidate)**:
   - `encoder_gpu.py`: NVENC hardware H.264 video compression trực tiếp từ CUDA tensor không qua CPU round-trip.
   - Giao thức ZeroMQ + binary numpy payload điều khiển camera và object poses giữa simulation worker và render worker.

### Nhóm 4: Giao diện Web 3D (`EX-PRODUCT`)
1. **`SuperSplat/src/`**:
   - `splat-renderer.js` / WebGPU projected splat shader pipeline.
   - `transform-gizmo.js`: Trục điều khiển Move / Rotate trên không gian 3D.
   - `selection/`: Các công cụ chọn điểm Splat (brush, lasso, box).
   - `edit-history.js`: Quản lý stack Undo/Redo cho các thao tác dịch chuyển và ẩn hiện.

---

## 5. Rào cản Bản quyền & Bộ lọc Sở hữu Trí tuệ (License & IP Firewall)

Để đảm bảo Real2Sim Studio là một sản phẩm phần mềm hoàn toàn hợp pháp và có thể thương mại hóa, toàn bộ team và AI coding agents phải tuân thủ nghiêm ngặt **Quy tắc Tường lửa Bản quyền**:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                             IP FIREWALL RULES                               │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ Mã nguồn / Thư viện                  │ Chính sách Xử lý                     │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ Inria Gaussian-Splatting License     │ ❌ CẤM COPY / CẤM VENDOR VÀO CORE     │
│ (VR-Robo renderer, LitMesh2GS,       │ Chỉ tham khảo thuật toán toán học.   │
│  Gaussian Grouping rasterizer,       │ Runtime 3DGS sử dụng Brush (MIT)     │
│  Re3Sim gaussian_splatting)          │ và Web viewer sử dụng SuperSplat.    │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ CC BY-NC 4.0 / CC BY-NC-SA 4.0       │ ❌ CẤM VENDOR VÀO CORE               │
│ (Tracking-Anything-with-DEVA,        │ DEVA bị thay thế bằng SAM2 (Apache). │
│  Re3Sim root repository)             │ Re3Sim chỉ lấy orchestration scripts │
│                                      │ và tự viết lại sạch (Clean-room).    │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ Root Missing License                 │ ⚠️ CHỈ XEM NHƯ REFERENCE             │
│ (DISCOVERSE-Real2Sim)                │ Không sao chép trực tiếp file mã     │
│                                      │ nguồn gốc.                           │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ Permissive Licenses (MIT, Apache)    │ ✅ ĐƯỢC PHÉP ADAPT / REUSE           │
│ (Brush, OpenReal2Sim, R2G top-level, │ Giữ nguyên attribution header và     │
│  SuperSplat, splat-transform,        │ copyright notices trong file port.   │
│  DISCOVERSE root, DiffusionLight)    │                                      │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---

## 6. Danh mục 4 Đợt Thử nghiệm Kỹ thuật (Qualification Spikes) Bắt buộc

Trước khi tiến hành khóa code cho các task trọng điểm, 4 qualification spikes sau đây phải được thực thi và có báo cáo kết quả cụ thể:

1. **`PRODUCT-06Q` — SuperSplat WebGPU Browser Qualification**:
   - **Mục tiêu**: Kiểm tra khả năng khởi tạo WebGPU context và hiệu năng render file Brush PLY 1–2 triệu điểm trên các trình duyệt mục tiêu (Chrome, Edge, Firefox).
   - **Tiêu chí PASS**: Khởi tạo WebGPU ổn định, FPS $\ge 30$, bộ nhớ VRAM được giải phóng sạch khi unmount component. Nếu fail $\rightarrow$ kích hoạt fallback hybrid WebGL2 / Three.js.
2. **`SCENE-QUAL-GG-01` — Gaussian Grouping Identity-Lifting Qualification**:
   - **Mục tiêu**: Đo lường xem việc học vector identity per-Gaussian có cải thiện tính nhất quán đa góc nhìn (cross-view consistency) và giảm hiện tượng vỡ cụm (fragmentation) so với baseline `SAM2 + R2G` trên sequence `TorWIC Aisle_CW` hay không.
   - **Tiêu chí PASS**: Hoạt động được trên file Brush PLY đã đóng băng (không train lại toàn scene), giảm tỷ lệ vỡ cụm, runtime hợp lý. Nếu fail $\rightarrow$ giữ nguyên baseline SAM2 + R2G.
3. **`SIM-QUAL-RE3-01` — OpenMVS Mesh $\rightarrow$ Isaac USD Qualification**:
   - **Mục tiêu**: Thử nghiệm chuyển đổi mesh thực tế từ TorWIC OpenMVS sang OpenUSD qua IsaacLab `MeshConverter`. So sánh 3 chế độ: `meshSimplification`, `convexDecomposition` (CoACD), `convexHull`.
   - **Tiêu chí PASS**: Thời gian chuyển đổi $< 60\text{s}$, không bị xuyên sàn, AMR di chuyển ổn định không bị kẹt va chạm giả.
4. **`REC-QUAL-FRAME-01` — Canonical Transform & FrameTools Qualification**:
   - **Mục tiêu**: Áp dụng kiến trúc frame graph từ Re3Sim `FrameTools` để chứng minh: Brush 3DGS, OpenMVS Mesh và Registered LiDAR sau chuẩn hóa đều có chung gốc tọa độ, hệ trục canonical và tỷ lệ mét ($1.0 = 1\text{m}$).
   - **Tiêu chí PASS**: Sai số đăng ký giữa các đại diện $< 2\text{cm}$ trên dữ liệu kiểm định TorWIC.

---

## 7. Kết luận

Sau 7 đợt audit chi tiết và 1 bài utility deep dive, **toàn bộ các khoảng trống kỹ thuật phức tạp nhất của Real2Sim Studio đã được giải quyết bằng các giải pháp mã nguồn mở hàng đầu**:
- Tái tạo không gian đã có **COLMAP + Brush + OpenMVS + Re3Sim orchestration**.
- Chuẩn hóa mây điểm Gaussian đã có **splat-transform**.
- Phân rã đối tượng đã có **SAM2 + R2G (SAMPro3D)**.
- Mô phỏng vật lý và OpenUSD đã có **OpenReal2Sim + Re3Sim + VR-Robo + DISCOVERSE (CoACD)**.
- Giao diện Web 3DGS Studio đã có **SuperSplat**.

Đội ngũ phát triển và AI agents giờ đây có thể tự tin bước vào giai đoạn cài đặt (Implementation) mà không còn phải mò mẫm hay tự code lại từ đầu các bài toán nền tảng.
