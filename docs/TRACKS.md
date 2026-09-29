Team mình chia project thành 4 track chính. Mỗi người chọn 1 track làm owner chính, nhưng vẫn phối hợp qua shared contracts và integration chung.

### 1. EX-REC — Reconstruction & Dataset Pipeline

**Mục tiêu:** biến dữ liệu đầu vào RGB/LiDAR thành các artifact 3D chuẩn để các track sau sử dụng.

**Công việc chính:**

- Chuẩn bị và chuẩn hóa TorWIC-SLAM.
- Video → frames.
- Camera pose / SfM bằng COLMAP.
- Visual Reconstruction bằng Brush / 3D Gaussian Splatting.
- RGB Geometry bằng OpenMVS.
- Registered LiDAR ingest bằng Open3D.
- RGB–LiDAR alignment và metric scale.
- Xuất `ReconstructionBundle` chuẩn cho EX-SCENE.

**Công nghệ chính:**
Python, Open3D, FFmpeg, COLMAP, Brush, OpenMVS, NumPy, Docker/process integration.

**Phù hợp nếu thích:**
Computer Vision, 3D Reconstruction, point cloud, geometry, sensor data, pipeline AI.

**Output chính:**

```text
RGB / LiDAR
→ Camera Poses
→ Visual 3D
→ Geometry
→ Metric/Canonical ReconstructionBundle
```

------

### 2. EX-SCENE — Object Intelligence & Scene Core

**Mục tiêu:** biến reconstruction toàn cục thành scene có cấu trúc gồm Environment và các object độc lập có thể chỉnh sửa.

**Công việc chính:**

- Object segmentation bằng SAM2.
- Mask propagation và metadata.
- Multi-view association: xác định cùng một object giữa nhiều camera view.
- Map mask/object từ 2D sang geometry 3D.
- Candidate Object generation.
- Human confirmation:
  - confirm;
  - rename;
  - ignore;
  - merge;
  - create missing object;
  - reassign region.
- Scene decomposition.
- Xây dựng `SceneIR`, `SceneObject`, transform và revision logic.

**Công nghệ chính:**
Python, PyTorch, SAM2, Open3D, NumPy, Pydantic.

**Phù hợp nếu thích:**
Computer Vision, segmentation, 2D→3D reasoning, object representation, thuật toán và data model.

**Output chính:**

```text
ReconstructionBundle
+ RGB frames
→ Masks
→ Object identities
→ Human confirmation
→ Environment + SceneObjects
→ SceneIR
```

------

### 3. EX-SIM — Physics, OpenUSD, Isaac Sim & Evaluation

**Mục tiêu:** biến SceneIR thành scene có physics, export sang Isaac Sim và chứng minh scene có thể dùng cho simulation.

**Công việc chính:**

- Collider generation.
- Box / OBB / convex / simplified mesh.
- Static preflight validation.
- SceneIR → OpenUSD.
- Load scene vào NVIDIA Isaac Sim.
- Robot spawn test.
- Collision / penetration test.
- Floor test.
- Start–Goal path feasibility.
- Demo `CLEAR → BLOCKED` khi di chuyển pallet.
- Sinh `ValidationReport`.
- Làm evaluation harness:
  - visual;
  - geometry;
  - pose;
  - object;
  - path.

**Công nghệ chính:**
Python, Open3D, Trimesh, OpenUSD, NVIDIA Isaac Sim, IsaacLab.

**Phù hợp nếu thích:**
Robotics, simulation, physics, 3D geometry, OpenUSD, evaluation/benchmark.

**Output chính:**

```text
SceneIR
→ Collider
→ OpenUSD
→ Isaac Sim
→ Collision / Path Validation
→ ValidationReport
```

Đây cũng là track có rủi ro environment/GPU cao nhất, nên cần người chịu khó setup và debug hệ thống.

------

### 4. EX-PRODUCT — Backend, Web Studio & Orchestration

**Mục tiêu:** biến các pipeline kỹ thuật phía trên thành một sản phẩm Web hoàn chỉnh để người dùng có thể chạy, chỉnh sửa, review và release scene.

**Công việc chính:**

- FastAPI backend.
- Project / Job APIs.
- Async job orchestration.
- Gọi EX-REC → EX-SCENE → EX-SIM.
- Artifact registry/storage.
- Job progress/error/retry.
- Next.js frontend.
- 3D Viewer: PlayCanvas + supersplat-viewer, editor SuperSplat (cập nhật 29/09;
  bản đầu dùng Three.js).
- Hiển thị:
  - Visual;
  - Geometry;
  - Collider.
- Select / move / rotate / hide / delete object.
- Human Object Confirmation UI.
- Validation result UI.
- Review / Approve / Reject.
- Release đúng Candidate đã được validation.

**Công nghệ chính:**
FastAPI, Python, Next.js, TypeScript, PlayCanvas/SuperSplat, REST/SSE/WebSocket, Docker.
Triển khai cloud (ADR 0003): Vercel, Railway + PostgreSQL, Cloudflare R2, RunPod GPU.

**Phù hợp nếu thích:**
Full-stack, backend architecture, frontend 3D, software engineering, system integration, product UX.

**Output chính:**

```text
User
→ Web Studio
→ Jobs
→ REC / SCENE / SIM
→ Viewer + Editing
→ Validation
→ Review
→ Release
```

------

### Luồng chung của cả team

```text
EX-REC
   ↓ ReconstructionBundle

EX-SCENE
   ↓ SceneIR

EX-SIM
   ↓ CandidatePackage + ValidationReport

EX-PRODUCT
   ↓ Web / Review / Release
```

Các track **không import implementation của nhau**. Mọi phần giao tiếp qua artifact/shared contract để mọi người có thể phát triển song song.

Nếu muốn chọn nhanh theo sở thích:

```text
CV / 3D Reconstruction / LiDAR
→ EX-REC

Segmentation / Object Understanding / 2D→3D
→ EX-SCENE

Robotics / Physics / Isaac Sim / Benchmark
→ EX-SIM

Full-stack / Backend / Web / System Integration
→ EX-PRODUCT
```