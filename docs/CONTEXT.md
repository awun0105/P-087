# PROJECT CONTEXT — REAL2SIM STUDIO

Bạn đang làm việc trên project **Real2Sim Studio — Warehouse / Indoor AMR MVP**.

Mục tiêu của context này là giúp bạn định hướng project trước khi nhận coding task.
Đây là **onboarding overview, không phải source of truth**: bắt đầu từ
[`AGENTS.md`](../AGENTS.md) và [`docs/WORKFLOW.md`](WORKFLOW.md); lấy P0
scope/acceptance từ [`docs/PRD.md`](PRD.md), shared schemas từ
[`TEAM_EXECUTION_CONTRACT.md`](execution/TEAM_EXECUTION_CONTRACT.md),
placement từ [`ARCHITECTURE.md`](../ARCHITECTURE.md), task ID/scope từ
[`TRACK_IMPLEMENTATION_GUIDE.md`](execution/TRACK_IMPLEMENTATION_GUIDE.md).
Nếu summary này khác authority, dùng authority và báo drift; không lấy ngày sửa
file hoặc ví dụ ở đây làm lý do đổi contract.

Không tự ý implement feature chỉ dựa trên context này. Với mỗi task sau đó, phải tuân thủ scope cụ thể của task và các tài liệu trong repository.

**Cập nhật 30/09/2026:** đích của pipeline đổi theo
[ADR 0007](decisions/0007-object-centric-hybrid-usd-pipeline.md) — scene theo vật chỉnh sửa
được, xuất USD lai (Gaussian để hiển thị, collider để va chạm) cho Isaac Sim; PRD v1.16 kéo vá nền,
gợi ý nhãn, thay asset vào phạm vi. Một số mô tả công nghệ bên dưới (vd. SAMPro3D-trên-hộp,
collider hộp) là đường tạm hiện tại, không phải đích cuối. Code nghiên cứu phi thương mại được
dùng lại theo [ADR 0008](decisions/0008-research-code-license-policy.md).

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

Ước lượng định hướng ban đầu (chưa đo từ implementation, không phải KPI hay tỷ lệ
bắt buộc cho từng track):

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

# 5. System/research reference strategy

Repo map và mức ưu tiên hiện hành nằm ở
[`INTEGRATION_PLAYBOOK.md` §7.1](execution/INTEGRATION_PLAYBOOK.md).
`VR-Robo`, `R2G` và `Re3Sim` là Tier-0 system references; `OpenReal2Sim`
là research/architecture reference cho background completion và
reconstruction→simulation patterns, **không** phải repo bắt buộc phải chạy đầu
tiên. Audit phần liên quan đến task, không copy/fork nguyên một system thành
product hoặc biến reference thành production dependency.

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
splat-transform (primary geometry có qualification; OpenMVS fallback)
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

RGB Voxel Geometry / Collision
        splat-transform sau confirmed metric transform (OpenMVS surface fallback)

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
PlayCanvas Engine + supersplat-viewer
```

3D viewer:

```text
PlayCanvas Engine 2.22.4 + supersplat-viewer 1.35.2
WebGL2        ← P0 baseline / fallback
WebGPU        ← ưu tiên khi khả dụng
Camera navigation
TranslateGizmo / RotateGizmo
Raycasting / Picking
Scene graph / layer controls
```

P0 Web Studio cần ít nhất:

```text
real Brush 3DGS VisualArtifact trong browser
chuyển/bật các view Geometry mesh, Point Cloud, Collider
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

PlayCanvas Engine và supersplat-viewer là P0 viewer core.

WebGPU không được trở thành P0 blocker.

Theo PRD v1.14/AC-11, direct browser rendering của **real Brush 3DGS** là
P0. Geometry mesh, point cloud và collider là các view kỹ thuật ngang hàng,
không phải fallback thay điều kiện 3DGS. Nếu `VisualArtifact` thiếu hoặc renderer
không tương thích, UI vẫn có thể cho inspect các view khác nhưng phải báo lỗi và
không claim AC-11 pass. WebGL2 là baseline; ưu tiên WebGPU khi khả dụng.
EX-PRODUCT dùng PlayCanvas Engine + supersplat-viewer, adapt dashboard starter
có chọn lọc. Viewer cần qualification bằng Brush output thật và SOG derivative;
source/API audit không thay browser proof.
Không coi PLY point cloud hoặc synthetic fixture là browser 3DGS proof.

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
RGB video/frames
→ validate + privacy gate
→ frame extraction bằng FFmpeg nếu là video
→ COLMAP camera poses / SfM
→ Brush VisualArtifact (3DGS)
→ REC-06 xác nhận anchor/transform → metric working derivative
→ REC-05 splat-transform geometry (OpenMVS fallback từ COLMAP)
→ REC-06 final metric / coordinate verification
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
splat-transform
OpenMVS (fallback)
Open3D
```

Team tự viết:

```text
VideoPreprocessor
ColmapAdapter
BrushAdapter
SplatTransformAdapter / OpenMVSAdapter fallback
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
PlayCanvas Engine + supersplat-viewer
WebGL2 baseline
WebGPU ưu tiên khi khả dụng
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
data_class: product_input | derived | ground_truth | evaluation_only
job/source provenance
```

`data_class` là typed metadata, không suy từ URI/path. Product-facing refs từ
chối raw GT/evaluation-only; GT-assisted derived artifact giữ lineage. Dùng
`artifact://jobs/<job_id>/<artifact-path>` và SHA-256 exact payload bytes, không
hard-code local paths làm identity.

---

# 13. SceneIR

SceneIR là project-owned contract.

Không outsource nó cho research repo.
Review/approval state thuộc workflow/revision record, **không** nằm trong
canonical SceneIR; APPROVED/REJECTED không tự thay SceneIR content checksum.

Concept:

```text
Scene
├── schema_version, scene_id, scene_revision
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
│       ├── origin, active
│       ├── local_frame
│       ├── transform
│       ├── visual_ref?
│       ├── geometry_ref
│       ├── asset_ref?
│       ├── collider?  # ColliderSpec; local_transform chỉ là local offset
│       └── provenance
│
├── provenance
└── scene_ir_checksum
```

SceneIR tồn tại theo revision.

Không coi SceneIR là thứ chỉ được tạo sau collider.

Một luồng hợp lệ; edit có thể tạo revision trước hoặc sau collider enrichment:

```text
Scene Decomposition
        ↓
Draft SceneIR
        ↓
Edit nếu cần → new SceneIR revision
        ↓
Collider enrichment
        ↓
Physics-enriched SceneIR
        ↓
Edit nếu cần → new SceneIR revision
        ↓
Preflight
        ↓
SceneRevisionRecord chuyển sang CANDIDATE_READY khi preflight pass
```

`CANDIDATE_READY` là workflow state gắn với revision, không phải field của
`SceneIR`. Mọi edit sau validation tạo DRAFT revision mới và invalidate
candidate/report/approval cũ.

---

# 14. Dataset — TorWIC-SLAM

Dataset chính của MVP:

```text
TorWIC-SLAM
```

P0 bring-up traversal đã chọn là `Aisle_CW`; `Aisle_CCW` là bổ sung/backup.
TorWIC là dataset adapter/evaluation source, không phải universal shared schema.
Foundation M0 chỉ cần sensor semantics đã kiểm, contract và synthetic fixtures;
không chờ tải/extract toàn bộ TorWIC để bốn track bắt đầu phát triển.

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

# 15. Dataset preparation và milestone gate

M0 đã khóa traversal, quyền sở hữu, raw/derived/GT boundary và contract/provenance.
Các mục còn lại được chuẩn bị sau M0 và phải khóa trước gate tương ứng, đặc biệt
Locked Evaluation Set trước Exit gate M1 (xem Execution Plan/Contract):

```text
extracted structure inspection
primary demo frame range
RGB reconstruction/held-out split
registered LiDAR từ real preparation
independent evaluation references
manual annotation schema
metric anchor + robot footprint
5 Start–Goal pairs và locked expected labels
GPU/Isaac runtime versions sau provisioning
```

EX-REC inspect exact extracted layout trước khi viết normalization/prefusion;
không giả định cấu trúc ZIP. Human/QA owner phải cung cấp và khóa benchmark
inputs; không tự bịa tọa độ, labels hoặc runtime versions để làm fixture pass.

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

Product runtime chỉ nhận registered LiDAR đã chuẩn hóa bằng logical artifact
URI/checksum; `registered_lidar.ply` là tên output offline ví dụ, không phải
identity trong shared contract:

```text
artifact://jobs/<job_id>/<artifact-path>
```

Nếu TorWIC offline preparation dùng `traj_gt.txt`, TorWIC manifest phải khai báo:

```yaml
trajectory_gt_used_for_lidar_prefusion: true
assistance_class: GT-assisted
```

Adapter map thành shared generic dependency `role: pose`,
`origin: ground_truth`, `source_checksum` và `ground_truth_assisted: true`.
`trajectory_gt_used_for_lidar_prefusion` **không** phải required field của
`LiDARGeometryArtifact`/`ReconstructionBundle`; LiDAR từ estimated/external poses
vẫn hợp lệ. Raw GT mặc định thuộc evaluation-only boundary; GT-assisted derived
artifact không được claim independent accuracy theo protocol yêu cầu GT độc lập.

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
→ READY_FOR_REVIEW chỉ khi blocking checks applicable đều PASS
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

M0 Foundation Baseline đã có typed contracts, canonical coordinates,
`ArtifactResolver`/filesystem store, synthetic fixtures và positive/negative
handoff tests. Đây là **fixture/integration proof**, không phải real
reconstruction, Brush/browser compatibility, Isaac/GPU hoặc product E2E proof.
Trước khi branch song song, team dùng cùng baseline commit/SHA và tuân
producer/consumer review khi đổi shared contract.

M0 tối thiểu:

```text
preserve organizer scaffold + ownership boundaries
shared contracts, coordinate/transform rules, artifact store
synthetic fixtures và handoff/negative tests
TorWIC Aisle_CW selection + dataset-side sensor evidence
evaluation-only/GT-assisted provenance rules
runtime manifest với GPU/tool values UNVERIFIED/TBD
documentation/task crosswalk
```

Sau M0, bốn track có thể phát triển song song từ fixtures:

```text
EX-REC
EX-SCENE
EX-SIM
EX-PRODUCT
```

Real dataset extraction, benchmark split/anchors/labels và exact GPU/Isaac
versions thuộc các milestone sau, không được tự điền để tuyên bố M0 pass.

---

# 24. Fixtures

Fixtures là synthetic artifacts nhỏ để downstream development không phải chờ upstream.

Ví dụ:

```text
fixtures/
├── artifact_store/       # payload bytes + SHA-256 thật
├── reconstruction_bundle/
├── scene_ir/
├── validation_report/
├── candidate/
├── evaluation/
├── mock_job/
└── invalid/
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

Bao gồm RGB-only/RGB-D/RGB+LiDAR bundles, edited SceneIR revision và failed
ValidationReport. Fixture phải validate bằng shared Pydantic schema, resolve
artifact refs và verify SHA-256; không dùng fixture để claim real producer,
browser 3DGS hoặc Isaac acceptance.

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

# 27. Additive Real2Sim placement (summary)

Summary để định hướng; [`ARCHITECTURE.md`](../ARCHITECTURE.md) là authority cho
placement và ownership. Tree dưới đây là mục tiêu, không chứng minh từng module
đã được implement:

```text
src/
├── models/
│   └── contracts/
│       ├── __init__.py
│       ├── artifacts.py
│       ├── coordinates.py
│       ├── identity.py
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
    │   ├── decomposition/
    │   └── editing/
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

EX-PRODUCT tạo Next.js/TypeScript Web Studio tại:

```text
frontend/
└── src/features/viewer/
```

`PRODUCT-05` đã giao scaffold frontend; `PRODUCT-06` giao viewer. `frontend/` đã có
(Studio; UI P0 cũ đã xoá 02/10/2026 theo STUDIO_UX_SPEC.md D-10); placement này đã khóa và không phải P1/stretch.

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

EX-REC/Integration Owner có GitHub handle `@awun0105`. Tên owner của ba track
còn lại đã khóa (Đức, Đạt, Cường), nhưng GitHub handles chưa được cung cấp;
giữ `TODO` trong CODEOWNERS, không tự đoán username.

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

docs/execution/INTEGRATION_PLAYBOOK.md
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
→ agent harness + authority/conflict/proof rules

CONTEXT.md / README.md
→ onboarding overview, không override các source of truth trên
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
GPU model/VRAM, driver/CUDA, Isaac/OpenUSD và provider versions vẫn
`UNVERIFIED/TBD` đến khi provision machine thật; runtime manifest ghi exact
versions sau đó. Không biến placeholder thành version lock đã kiểm chứng.

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
