# PROJECT CONTEXT — REAL2SIM STUDIO

Bạn đang làm việc trên project **Real2Sim Studio — Warehouse / Indoor AMR MVP**.

Mục tiêu của context này là giúp bạn hiểu toàn bộ cách project được tổ chức trước khi nhận các coding task cụ thể.

Không tự ý implement feature chỉ dựa trên context này. Với mỗi task sau đó, phải tuân thủ scope cụ thể của task và các tài liệu trong repository.

---

# 1. Mục tiêu sản phẩm

Project xây dựng một workflow Real2Sim hỗ trợ Simulation Engineer biến dữ liệu thế giới thực thành scene có thể chỉnh sửa và validate trong NVIDIA Isaac Sim.

Primary P0 workflow:

```text
RGB Moving-camera Video
        ↓
3D Reconstruction
        ↓
Visual + Geometry
        ↓
Metric / Canonical Scene
        ↓
Object Extraction
        ↓
Human Confirmation
        ↓
Editable SceneObjects
        ↓
Collider
        ↓
OpenUSD Candidate
        ↓
NVIDIA Isaac Sim
        ↓
Collision / Spawn / Path Validation
        ↓
Human Review
        ↓
Release
```

P0 domain:

```text
Warehouse / Indoor AMR
```

Target simulator:

```text
NVIDIA Isaac Sim
```

Long-term architecture có thể mở rộng domain/simulator khác, nhưng P0 không được scope creep.

---

# 2. Nguyên tắc kiến trúc quan trọng

Các invariant:

```text
Visual Representation
≠
Geometry Representation
≠
Physics Representation
```

3D Gaussian Splatting dùng chủ yếu cho Visual Representation.

Không dùng Gaussian centers trực tiếp làm physics collider.

Global reconstruction cũng không đồng nghĩa với editable scene:

```text
Global Reconstruction
≠
Structured Editable Scene
```

Scene sau cùng phải được tổ chức thành:

```text
Environment
+
Independent SceneObjects
```

Mỗi SceneObject có canonical transform dùng chung cho Visual, Geometry và Physics.

---

# 3. Project không phải research-from-scratch

Triết lý implementation:

> Tận dụng tối đa open-source repositories/tools đã tồn tại. Không tự viết lại các thuật toán lõi như SfM, 3DGS, segmentation, dense reconstruction hoặc physics simulator nếu đã có implementation phù hợp.

Ước lượng cách làm:

```text
60–70% reuse/integrate existing OSS
20–30% adapters + glue + artifact contracts
10–20% project-specific logic
```

Coding work chủ yếu là:

```text
audit repository
→ identify usable entrypoint/module
→ run baseline
→ wrap/adapt
→ normalize input/output
→ expose internal artifact contract
→ test
→ integrate
```

Không copy nguyên hàng loạt research repos vào cùng dependency graph.

---

# 4. Chiến lược reuse source

Có 4 mức:

```text
REUSE
→ dùng tool/model gần như nguyên bản

ADAPT
→ lấy một phần logic/script/module rồi chỉnh cho contract nội bộ

SELF-CODE
→ project-specific glue/domain logic

REFERENCE
→ chỉ học architecture/algorithm, không tạo dependency
```

Ưu tiên:

```text
RUN / WRAP
    ↓
ADAPT
    ↓
COPY source chỉ khi thực sự cần và license cho phép
```

External repository không được quyết định architecture của project.

Project contract mới là source of truth.

---

# 5. System reference baseline

Repo nên được audit/run đầu tiên ở cấp toàn hệ thống:

```text
PointsCoder/OpenReal2Sim
```

Vai trò:

```text
SYSTEM REFERENCE BASELINE
```

Không copy/fork nguyên repo này thành product.

Mục tiêu của việc chạy OpenReal2Sim:

* hiểu một hệ thống Real2Sim end-to-end hiện tại hoạt động ra sao;
* xem cách preprocessing/reconstruction/object/simulation được nối;
* audit reconstruction→simulation boundary;
* reuse/adapt những phần thực sự phù hợp.

Sau đó từng track mới audit thêm các repo chuyên biệt.

Các system/research references quan trọng:

```text
OpenReal2Sim
R2G
Re3Sim
VR-Robo
DISCOVERSE
gs-real2sim
Gaussian Grouping
ObjectGS
SegAnyGaussians
```

Không mặc định tất cả trở thành runtime dependencies.

---

# 6. Core external technologies

## Reconstruction

```text
FFmpeg
COLMAP
Brush
OpenMVS
Open3D
NumPy
```

Mapping:

```text
Video → Frames
        FFmpeg

Camera Pose / SfM
        COLMAP

3DGS Visual
        Brush

RGB Dense Geometry / Mesh
        OpenMVS

LiDAR / Point Cloud Utilities
        Open3D
```

Team không tự implement SfM, Gaussian Splatting hay dense MVS.

---

# 7. Object / Scene technologies

Core:

```text
SAM2
Open3D
NumPy
Pydantic
```

SAM2 dùng cho 2D masks/video propagation.

Phần khó nhất là:

```text
2D masks
+
camera poses
+
canonical geometry
        ↓
multi-view association
        ↓
3D candidate object identity
```

P0 không yêu cầu phát minh thuật toán mới.

Ưu tiên:

```text
projection
spatial consistency
geometry overlap
voting
clustering
human correction
```

Nếu upstream repo có module reuse được sau audit thì ADAPT.

Nếu không, implement một pragmatic baseline.

Ambiguous cases phải được để cho Human-in-the-Loop xử lý.

Research references:

```text
Gaussian Grouping
ObjectGS
SegAnyGaussians
R2G
```

---

# 8. Simulation stack

```text
Python
Open3D
Trimesh
OpenUSD
NVIDIA Isaac Sim
IsaacLab
NumPy
```

Các vấn đề core như physics engine hoặc USD format không được viết lại.

Team tự viết:

```text
ColliderGenerator
SceneIR → USD adapter
PreflightValidator
IsaacValidationWorker
ValidationReport
EvaluationRunner
```

Collider baseline:

```text
floor/wall
→ plane hoặc simplified static mesh

pallet/box
→ box / OBB

complex object
→ convex hull / simplified mesh
```

---

# 9. Product/Web stack

Backend:

```text
FastAPI
Pydantic
Async Job / Worker orchestration
SSE hoặc WebSocket
Artifact API
Scene API
Review API
Release API
```

Frontend:

```text
Next.js
React
TypeScript
Three.js
```

3D viewer:

```text
Three.js
WebGL2        ← P0 baseline
WebGPU        ← optional/advanced path
OrbitControls
TransformControls
Raycasting / Picking
Scene graph / layer controls
```

P0 Web Studio cần ít nhất:

```text
orbit
pan
zoom
select object
hide/show
move
rotate
Visual/Geometry/Collider layer toggle
validation result
review
approve/reject
release
```

Three.js là P0 core.

WebGPU không được trở thành P0 blocker.

Nếu browser 3DGS rendering khó:

```text
P0 Web Studio
→ mesh / point cloud preview bằng Three.js
```

Sau đó mới xem xét:

```text
3DGS
→ browser renderer
→ WebGPU/WebGL
```

---

# 10. 4 execution tracks

Project chia thành 4 ownership tracks.

Không phải 4 project riêng.

Tất cả tạo thành một system duy nhất.

---

## EX-REC — Reconstruction

Mission:

```text
Real-world input
→ ReconstructionBundle
```

Luồng RGB:

```text
Video
→ FFmpeg
→ COLMAP
→ Camera Poses
→ Brush Visual
→ OpenMVS Geometry
→ Metric / Coordinate normalization
→ ReconstructionBundle
```

LiDAR branch:

```text
Registered LiDAR
→ validate/filter/normalize
→ LiDARGeometryArtifact
```

Track chủ yếu reuse:

```text
FFmpeg
COLMAP
Brush
OpenMVS
Open3D
```

Team tự viết:

```text
VideoPreprocessor
ColmapAdapter
BrushAdapter
OpenMVSAdapter
LiDAR ingest
alignment workflow
metric normalization
manifest/provenance
ReconstructionBundle builder
worker/CLI
tests
```

Người phù hợp:

```text
Computer Vision
3D Vision
point cloud
camera geometry
CLI/CUDA/debug integration
```

---

## EX-SCENE — Object Intelligence / Scene Core

Mission:

```text
ReconstructionBundle
→ structured editable SceneIR
```

Luồng:

```text
RGB Frames
+
Camera Poses
+
Canonical Geometry
        ↓
SAM2
        ↓
2D Masks
        ↓
Multi-view Association
        ↓
Candidate Objects
        ↓
Human Confirmation
        ↓
Scene Decomposition
        ↓
Environment + SceneObjects
        ↓
SceneIR
```

Team tự viết nhiều project-specific logic nhất ở đây:

```text
mask artifact normalization
MultiViewObjectAssociator baseline
CandidateObject model
Human Confirmation operations
SceneDecomposer
SceneObject model
SceneIR
```

Human correction P0:

```text
Confirm
Rename
Ignore
Merge
Create Missing Object
Reassign
```

Người phù hợp:

```text
CV / ML
segmentation
3D geometry
Python
algorithmic reasoning
```

---

## EX-SIM — Physics / OpenUSD / Isaac / Evaluation

Mission:

```text
SceneIR
→ physics-validatable simulator scene
→ ValidationReport
```

Luồng:

```text
SceneIR
→ Collider
→ Preflight
→ Candidate OpenUSD
→ Isaac Sim
→ Collision / Spawn / Path
→ ValidationReport
```

Ngoài ra chịu trách nhiệm evaluation harness.

Metrics có thể gồm:

```text
PSNR
SSIM
LPIPS
Chamfer Distance
Geometry Precision / Recall / F1
ATE / RPE
Scale Error
Distance RMSE
Path correctness
```

Người phù hợp:

```text
Robotics
Simulation
3D transforms
OpenUSD
Isaac
environment debugging
```

---

## EX-PRODUCT — Web / API / Orchestration

Mission:

```text
biến các workers thành một usable software workflow
```

Architecture:

```text
               Web Studio
                   ↓
                FastAPI
                   ↓
            Job Orchestrator
           /       |       \
          ↓        ↓        ↓
       EX-REC   EX-SCENE   EX-SIM
```

Backend:

```text
projects
jobs
artifacts
scene revisions
worker invocation
progress
error/retry
review
release
```

Frontend:

```text
Next.js
TypeScript
Three.js
WebGL2
optional WebGPU
```

Người phù hợp:

```text
Full-stack
Backend
API
Frontend
System integration
```

---

# 11. Track communication contract

Tracks không được import implementation nội bộ của nhau.

Sai:

```python
from src.services.reconstruction.colmap import ColmapRunner
```

từ EX-SCENE.

Đúng:

```python
from src.models.contracts.reconstruction import ReconstructionBundle
```

Dependency:

```text
EX-REC
    ↓
ReconstructionBundle

EX-SCENE
    ↓
SceneIR

EX-SIM
    ↓
CandidatePackage
ValidationReport

EX-PRODUCT
    ↓
Review / Release
```

Artifact contracts là boundary chính.

---

# 12. Shared artifacts

Các contract quan trọng:

```text
InputManifest
JobManifest
ReconstructionBundle
LiDARGeometryArtifact
SceneIR
CandidateManifest
CandidatePackage
ValidationReport
EvaluationReport
ReleaseManifest
```

Artifact quan trọng phải có khi relevant:

```text
artifact_type
schema_version
artifact_uri
artifact_checksum
producer_stage
job/source provenance
```

Không hard-code local paths làm identity.

---

# 13. SceneIR

SceneIR là project-owned contract.

Không outsource nó cho research repo.

Concept:

```text
Scene
├── coordinate_system
├── metric_scale
│
├── environment
│   ├── visual_ref?
│   ├── geometry_ref
│   └── collider_ref?
│
├── objects[]
│   └── SceneObject
│       ├── id
│       ├── name
│       ├── state
│       ├── local_frame
│       ├── transform
│       ├── visual_ref?
│       ├── geometry_ref
│       ├── collider_ref?
│       └── provenance
│
└── review_state
```

SceneIR tồn tại theo revision.

Không coi SceneIR là thứ chỉ được tạo sau collider.

Luồng đúng nên là:

```text
Scene Decomposition
        ↓
Draft SceneIR
        ↓
Collider
        ↓
Physics-enriched SceneIR
        ↓
Edit
        ↓
new SceneIR revision
        ↓
Preflight
        ↓
CANDIDATE_READY SceneIR
```

---

# 14. Dataset — TorWIC-SLAM

Dataset chính của MVP:

```text
TorWIC-SLAM
```

Foundation Phase phải chuẩn bị dataset trước khi các track bắt đầu.

Không để mỗi track tự chọn traversal/data riêng.

Suggested structure:

```text
data/
└── torwic_slam/
    ├── raw/
    ├── normalized/
    ├── derived/
    └── evaluation_only/
```

Meaning:

```text
raw
→ immutable source

normalized
→ product-friendly normalized inputs

derived
→ precomputed artifacts

evaluation_only
→ GT/reference data không được feed vào prediction
```

---

# 15. Dataset preparation phải xảy ra trước khi chia track

Foundation Phase phải khóa:

```text
TorWIC scenario/traversal
bring-up traversal
development traversal(s)
benchmark traversal(s)
primary demo traversal
RGB reconstruction/held-out split
registered_lidar.ply
calibration
timestamps
evaluation-only references
manual annotation schema
start-goal references
```

Không để EX-REC phải tự quyết định toàn bộ dataset strategy sau khi team đã chia.

Sau Foundation Lock, maintenance của dataset preparation có thể thuộc EX-REC.

---

# 16. Registered LiDAR rule

Product P0 không ingest raw sequential LiDAR scans.

Offline preparation:

```text
TorWIC raw lidar scans
+
trajectory/calibration
        ↓
offline prefusion
        ↓
registered_lidar.ply
```

Product sees:

```text
registered_lidar.ply
```

Nếu `traj_gt` được dùng để prefuse LiDAR phải khai báo:

```yaml
trajectory_gt_used_for_lidar_prefusion: true
```

Không được sau đó claim independent geometry benchmark chống lại reference nếu GT đã bị dùng trong prediction/preparation không đúng protocol.

---

# 17. P0 input configurations

Primary P0 product path:

```text
RGB-only
```

Đây là full vertical slice:

```text
reconstruction
→ object
→ edit
→ physics
→ Isaac
→ review
→ release
```

Mixed configuration:

```text
RGB + Registered LiDAR
```

P0 chỉ yêu cầu **LiDAR Contribution Evidence**.

Không bắt mixed path phải duplicate toàn bộ product workflow.

P1:

```text
Full Registered-LiDAR-only product configuration
```

Không được biến P1 thành blocker của MVP.

---

# 18. RGB–LiDAR alignment

P0 không yêu cầu automatic calibration.

P0:

```text
already aligned
hoặc
known transform available
```

Nếu không:

```text
reject/fail clearly
```

P1 có thể manual/semi-auto ICP.

P2 mới xem xét fully automatic calibration.

---

# 19. Object deletion

P0:

```text
logical/simulation deletion
```

Delete object:

```text
remove from active SceneIR
remove geometry from active composition
remove collider
invalidate old candidate USD
create new revision
```

Background generative reconstruction/inpainting không phải P0 requirement.

---

# 20. Human-in-the-Loop

Không cần AI/object association hoàn hảo.

Pipeline:

```text
AI candidate
→ Human Confirmation
→ structured SceneObject
```

Human remains final decision maker.

Các case mơ hồ không được tự động “invent truth”.

---

# 21. Candidate / Validation / Release lifecycle

Candidate OpenUSD phải được build trước review.

```text
SceneIR
→ CandidatePackage
→ Isaac Validation
→ ValidationReport
→ READY_FOR_REVIEW
→ Human Approve/Reject
```

Nếu APPROVED:

```text
seal/promote EXACT tested candidate
```

Không regenerate USD sau approval rồi vẫn gọi đó là cùng release.

Nếu scene được edit:

```text
new revision
→ old candidate invalid
→ validation phải chạy lại
```

---

# 22. Validation và Evaluation khác nhau

```text
Isaac Validation
≠
Benchmark Evaluation
```

Validation dùng để kiểm tra candidate có dùng được trong simulator không.

Evaluation dùng ground truth/reference để benchmark chất lượng.

ValidationReport là production/release concern.

EvaluationReport chỉ bắt buộc cho benchmark/acceptance run khi protocol yêu cầu; ordinary user-upload job có thể không có evaluation GT.

---

# 23. Foundation Phase — bắt buộc trước khi 4 track bắt đầu

Không chia track và bắt đầu coding ngay.

Làm trước:

```text
PHASE 0 — FOUNDATION

1. Preserve organizer scaffold
2. Add minimal module boundaries
3. Shared contracts v0
4. TorWIC dataset selection
5. Dataset download/preparation
6. Data directory structure
7. Registered LiDAR preparation
8. RGB benchmark split
9. Evaluation-only separation
10. Dataset/Input manifest
11. Shared fixtures
12. Canonical coordinate convention
13. Runtime/tool version lock
14. Minimal smoke tests
15. Ownership / CODEOWNERS
16. Documentation links
```

Sau đó:

```text
FOUNDATION LOCK
```

rồi mới:

```text
EX-REC
EX-SCENE
EX-SIM
EX-PRODUCT
```

chạy song song.

---

# 24. Fixtures

Fixtures là static sample artifacts dùng để downstream development không phải chờ upstream.

Ví dụ:

```text
fixtures/
├── reconstruction_bundle/
├── scene_ir/
├── validation_report/
└── mock_job/
```

Use:

```text
fixture ReconstructionBundle
→ EX-SCENE code ngay

fixture SceneIR
→ EX-SIM code ngay

fixture ValidationReport
→ EX-PRODUCT code ngay
```

Khi upstream thật hoàn thành:

```text
fixture
→ real artifact
```

mà downstream không phải redesign.

---

# 25. Repository constraint cực kỳ quan trọng

Repository scaffold được cung cấp bởi ban tổ chức.

Do đó:

> Không được phá hoặc redesign mạnh repository.

Không:

```text
delete existing folders
rename existing folders
move existing folders
archive existing scaffold
```

Module không sử dụng:

```text
leave untouched
```

Policy:

```text
KEEP ORGANIZER SCAFFOLD
+
ADD MINIMAL REAL2SIM MODULES
```

---

# 26. Existing repository important paths

Existing scaffold includes:

```text
src/
├── agents/
├── api/
├── llm/
├── models/
├── services/
├── config.py
└── main.py
```

Không chuyển chúng sang monorepo `apps/`, `workers/`, v.v.

Không rename:

```text
eval/
```

Không thay root Dockerfile chỉ vì muốn structure đẹp hơn.

---

# 27. Proposed additive Real2Sim structure

Add:

```text
src/
├── models/
│   └── contracts/
│       ├── __init__.py
│       ├── artifacts.py
│       ├── manifests.py
│       ├── reconstruction.py
│       ├── scene.py
│       ├── validation.py
│       └── release.py
│
└── services/
    ├── reconstruction/
    │   ├── adapters/
    │   ├── rgb/
    │   ├── lidar/
    │   └── alignment/
    │
    ├── scene/
    │   ├── extraction/
    │   ├── association/
    │   ├── candidates/
    │   └── decomposition/
    │
    ├── simulation/
    │   ├── colliders/
    │   ├── preflight/
    │   ├── usd/
    │   ├── isaac/
    │   └── validation/
    │
    └── orchestration/
        ├── jobs/
        ├── artifacts/
        ├── review/
        └── release/
```

Dataset tooling:

```text
scripts/torwic/
```

Shared fixtures:

```text
fixtures/
```

Evaluation continues using:

```text
eval/
```

Frontend may later be added as:

```text
frontend/
```

but do not create a full Next.js app unless a specific task asks for it.

---

# 28. Ownership mapping

```text
EX-REC
→ src/services/reconstruction/
→ scripts/torwic/
→ tests/test_reconstruction/

EX-SCENE
→ src/services/scene/
→ tests/test_scene/

EX-SIM
→ src/services/simulation/
→ eval/
→ tests/test_simulation/

EX-PRODUCT
→ src/api/
→ src/services/orchestration/
→ frontend/
→ tests/test_orchestration/
```

Shared:

```text
src/models/contracts/
fixtures/
tests/test_contracts/
tests/integration/
tests/e2e/
```

Cross-owner changes require review.

---

# 29. CODEOWNERS

Repository already has:

```text
.github/CODEOWNERS
```

Use it to map paths to real GitHub owners once team assignments are known.

Purpose:

```text
folder ownership
→ automatic reviewer assignment
→ reduce accidental cross-track changes
```

Shared contracts should normally have producer + consumer owners.

Example concept:

```text
ReconstructionBundle
→ EX-REC + EX-SCENE

SceneIR
→ EX-SCENE + EX-SIM / EX-PRODUCT

ValidationReport
→ EX-SIM + EX-PRODUCT
```

Do not invent usernames.

---

# 30. Documentation roles

Canonical documentation responsibilities:

```text
docs/PRD.md
→ product requirements, P0/P1/P2, acceptance

docs/DATASET_PLAYBOOK.md
→ dataset preparation, leakage, benchmark

docs/INTEGRATION_PLAYBOOK.md
→ technical baseline, stages, tools, repos

ARCHITECTURE.md
→ repository/module architecture and ownership

docs/execution/TEAM_EXECUTION_PLAN.md
→ who + when

docs/execution/TEAM_EXECUTION_CONTRACT.md
→ interoperability rules

docs/execution/TRACK_IMPLEMENTATION_GUIDE.md
→ how each track implements its part

AGENTS.md
→ short agent instructions + links to source-of-truth docs
```

Không duplicate full repository architecture vào nhiều docs.

`ARCHITECTURE.md` nên là source of truth cho folder structure/module ownership.

---

# 31. Terminology

Project identifiers:

```text
ST
= Stage
= product/runtime pipeline step

DP
= Dataset Preparation
= offline data preparation

EV
= Evaluation
= benchmark/evaluation step

INF
= Infrastructure
= shared infrastructure capability

FR
= Functional Requirement

AC
= Acceptance Criterion

P0
= mandatory MVP scope

P1
= next-priority scope

P2
= future/extended scope

EX-REC
= Reconstruction track

EX-SCENE
= Scene/Object track

EX-SIM
= Simulation/Evaluation track

EX-PRODUCT
= Product/Web/Orchestration track
```

---

# 32. Development model

Production artifact dependency is sequential:

```text
REC
→ SCENE
→ SIM
→ PRODUCT
```

Development is parallel through fixtures:

```text
EX-REC
→ works independently

EX-SCENE
→ uses fixture ReconstructionBundle

EX-SIM
→ uses fixture SceneIR

EX-PRODUCT
→ uses mock SceneIR / ValidationReport
```

Do not force downstream members to wait for upstream production artifacts.

---

# 33. Testing approach

Laptop/local:

```text
Pydantic contracts
manifest/checksum
transform math
FastAPI
frontend
job state
mock workers
unit tests
contract tests
small geometry utilities
```

GPU/heavy environment:

```text
Brush
SAM2 inference
heavy reconstruction
Isaac Sim
full E2E
```

Testing layers:

```text
Unit
Contract
Adapter
Stage Integration
Full E2E
```

Contract tests are especially important because four people work in parallel.

---

# 34. External dependency environments

Do not force everything into one Python environment.

These may have incompatible runtimes:

```text
COLMAP / Brush / OpenMVS
SAM2 / PyTorch
Isaac Sim
```

Use process/container/runtime boundaries when needed.

For now preserve organizer:

```text
Dockerfile
docker-compose.yml
```

Do not redesign Docker infrastructure unless a dedicated task asks for it.

---

# 35. What NOT to do

Do not:

```text
rewrite COLMAP
rewrite Brush
rewrite OpenMVS
train SAM2 replacement
build own physics engine
invent new 3DGS method
build automatic RGB-LiDAR calibration for P0
build perfect generative background reconstruction
introduce new research model without a blocker
clone every research repo into one runtime
redesign organizer scaffold
```

If a task starts requiring:

```text
new model training
new loss function
new research architecture
perfect automatic calibration
perfect object reconstruction
```

flag it as likely scope creep rather than silently expanding P0.

---

# 36. What coding agents should optimize for

For each task:

```text
1. Read relevant project docs.
2. Inspect existing code before changing anything.
3. Audit upstream implementation if reuse is expected.
4. Prefer reuse over rewrite.
5. Keep external implementation behind adapter/boundary.
6. Produce project-standard artifact.
7. Add tests.
8. Validate downstream compatibility.
9. Avoid unrelated refactors.
10. Report exactly what was reused, adapted and self-coded.
```

A component is not done merely because an upstream model/tool runs.

Example:

```text
EX-REC DONE
≠ Brush generated something

EX-REC DONE
= valid ReconstructionBundle
  consumed successfully by EX-SCENE
```

Likewise:

```text
EX-SCENE DONE
= EX-SIM consumes SceneIR

EX-SIM DONE
= EX-PRODUCT consumes ValidationReport

EX-PRODUCT DONE
= complete E2E workflow can be operated by user
```

---

# 37. General decision rule

When choosing between:

```text
A. invent new implementation
B. reuse/adapt existing OSS
```

default to:

```text
B
```

unless:

* upstream does not satisfy contract;
* runtime/license makes integration impractical;
* upstream is unstable;
* adaptation is harder than a small deterministic implementation;
* project-specific logic genuinely does not exist upstream.

The goal is not to demonstrate how much code the team can write.

The goal is to demonstrate a coherent, editable, physics-validatable, human-reviewed Real2Sim workflow built efficiently from strong existing components.
