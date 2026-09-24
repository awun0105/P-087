# Audit #1 — `PointsCoder/OpenReal2Sim`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim)  
> **License:** MIT (Top-level) / Các submodule có license riêng  
> **Ngày audit:** 2026-09-24  
> **Trạng thái:** Hoàn tất Audit #1 (1/7 trong Audit Queue)

---

## Kết luận trước

`OpenReal2Sim` **rất đáng lấy code**, nhưng giá trị lớn nhất của nó đối với chúng ta nằm ở:

```text
EX-SIM        → RẤT CAO
EX-SCENE      → TRUNG BÌNH–CAO
EX-REC        → THẤP–TRUNG BÌNH
EX-PRODUCT    → THẤP
```

Nó **không nên thay COLMAP → Brush → OpenMVS** của P0. OpenReal2Sim dùng một reconstruction philosophy khác: preprocess depth/camera bằng Mega-SAM/MoGe, segmentation, sinh object mesh, background completion, rồi ráp scene. Trong khi baseline của ta cố ý giữ Visual = Brush và Geometry = OpenMVS tách nhau. 

Nhưng phần **scene construction → physical asset → USD → IsaacLab** của OpenReal2Sim có nhiều code thực tế mà ta không nên tự viết lại.

---

## 1. OpenReal2Sim thực sự làm được tới đâu?

Repo chia thành bốn subsystem:

```text
preprocess/
reconstruction/
motion/
simulation/
```

User guide mô tả trực tiếp:

```text
images / video
→ preprocess depth + camera
→ segmentation
→ physical scene reconstruction
→ portable scene assets
→ USD conversion
→ IsaacLab
→ robot simulation
```

Repo hiện hỗ trợ IsaacLab import, camera setup/rendering và robotic simulation; reconstruction tạo `simulation/scene.json` cùng các mesh assets.

Đây là overlap khá lớn với nửa sau pipeline của chúng ta:

```text
Our project:

ReconstructionBundle
→ SceneIR
→ Collider
→ OpenUSD
→ Isaac
→ Validation
```

---

## 2. Phần quan trọng nhất: USD / PhysX / Isaac

Đây là nơi có giá trị reuse cao nhất.

File:

```text
openreal2sim/simulation/isaaclab/
└── sim_preprocess/
    └── usd_conversion.py
```

không chỉ là script đổi extension. Nó đã chứa logic sử dụng:

```text
IsaacLab MeshConverter
UsdPhysics
PhysxSchema
RigidBody
CollisionAPI
Convex decomposition
CCD
mass properties
contact/rest offsets
GLB/OBJ → USD
URDF → USD
```

Ví dụ code có `convert_obj_to_usd()`, dựng `MassPropertiesCfg`, `RigidBodyPropertiesCfg`, `CollisionPropertiesCfg` và gọi `MeshConverter`; phía sau còn apply rigid-body/PhysX configuration.

### Đây map trực tiếp vào EX-SIM của chúng ta

Thay vì tự code từ đầu:

```text
SceneIR
→ parse geometry
→ create USD
→ apply physics
→ create colliders
→ set rigid/static properties
→ configure PhysX
```

ta có thể lấy rất nhiều implementation pattern từ đây.

Đề xuất:

```text
OpenReal2Sim
usd_conversion.py
        ↓ ADAPT
Real2Sim Studio
IsaacUsdAdapter / CandidateBuilder
```

Các phần đáng port trước:

```text
convert_obj_to_usd()
rigid-body application
collision properties
convex decomposition configuration
CCD configuration
USD stage post-processing
mesh → USD conversion pattern
```

### Mức reuse

**`ADAPT-HIGH`**, không copy nguyên script.

Lý do: script hiện hard-code:

```python
args_isaaclab.headless = False
```

tức đang ép GUI mode. Worker P0 của chúng ta phải hỗ trợ runtime được lock theo deployment chứ không được phụ thuộc GUI.

Ngoài ra các PhysX parameter của họ như số hull, voxel resolution, contact offset... là policy của OpenReal2Sim, **không được bê nguyên thành Real2Sim default** mà chưa test warehouse scene.

---

## 3. Scene construction cũng có code đáng lấy

File:

```text
reconstruction/modules/scenario_construction.py
```

có implementation thực cho:

```text
mesh registration
centroid alignment
uniform scaling
ICP
mesh ↔ point-cloud registration
ground alignment
object placement
scene composition
```

Nó dùng chính `Open3D + Trimesh`, cũng là hai core utilities mà project chúng ta đã chọn.

Ví dụ flow trong repo:

```text
generated object mesh
+
masked metric point cloud
        ↓
coarse centroid/bbox alignment
        ↓
ICP / mesh registration
        ↓
registered object
        ↓
scene placement
```

### Chỗ này hữu ích cho chúng ta

Không thay:

```text
ST-RGB-LIDAR-ALIGN
```

và cũng không được thay Canonical Coordinate Contract.

Nhưng có thể lấy các utility:

```text
mesh ↔ point cloud registration
object geometry alignment
mesh simplification before registration
ground-plane orientation
AABB extraction
```

cho:

```text
EX-SCENE
→ SceneObject geometry registration

EX-SIM
→ geometry/collider preparation
```

Mức đề xuất:

```text
ADAPT-MEDIUM
```

---

## 4. Collision optimization có thể giảm code EX-SIM/preflight

OpenReal2Sim có riêng:

```text
scenario_collision_optimization.py
```

với hai kiểu xử lý:

```text
SDF-based
plane-clearance based
```

Ý tưởng là phát hiện/đẩy object ra khỏi penetration với background/ground trước simulation.

Đây khá gần:

```text
OBJECT_OUT_OF_BOUNDS
penetration
floor/object sanity
```

của chúng ta.

Nhưng **không dùng nó như source of truth validation**.

Ta có thể lấy:

```text
SDF query utilities
ground clearance calculation
penetration remediation logic
```

làm:

```text
optional remediation utility
```

trước Candidate Build.

Validation thật vẫn phải do:

```text
Preflight
+
Isaac Validation
```

quyết định.

Mức:

```text
ADAPT-MEDIUM
```

---

## 5. Background completion: code thật đã có

Đây là một phát hiện đáng chú ý.

OpenReal2Sim không chỉ nói về inpainting. Nó có:

```text
background_pixel_inpainting.py
background_point_inpainting.py
background_mesh_generation.py
```

Pixel inpainting gọi `ObjectClearPipeline`; sau đó point/background geometry được completion và dựng thành background mesh.

Flow:

```text
object masks
↓
remove foreground
↓
inpaint RGB background
↓
inpaint point/depth background
↓
generate textured background mesh
```

Nó gần đúng architecture `BackgroundCompletionBackend` mà docs chúng ta đã để ở P1/Stretch. Hiện docs ta đã định nghĩa abstraction nhưng chưa khóa backend. 

### Điều này có nghĩa

Sau MVP, chúng ta **không cần thiết kế Background Completion từ zero**.

Có thể tạo:

```text
BackgroundCompletionBackend
        ↓
OpenReal2SimObjectClearBackend
```

Mức:

```text
ADAPT-HIGH cho P1
NOT P0
```

---

## 6. Object mesh generation cũng đã được code

OpenReal2Sim dùng:

```text
mask
↓
crop RGBA object
↓
Hunyuan3D-2 shape generation
↓
texture generation
↓
.glb
```

Code cụ thể nằm trong:

```text
object_mesh_generation.py
```

và khởi tạo:

```text
Hunyuan3DDiTFlowMatchingPipeline
Hunyuan3DPaintPipeline
```

để tạo object mesh.

Đây **không phải representation chính của P0 chúng ta** vì chúng ta muốn giữ geometry quan sát/reconstructed chứ không generatively thay object thật bằng Hunyuan asset.

Nhưng rất hữu ích cho:

```text
missing geometry completion
user-added object
P1 asset generation
object reconstruction fallback
```

Do đó:

```text
REFERENCE/ADAPT P1
```

không đưa vào P0 core.

---

## 7. Segmentation/Object workflow

OpenReal2Sim còn có GUI:

```text
segmentation_annotator.py
```

cho phép:

```text
click object
→ mask
→ name
→ propagate over video
```

Sau đó mask được dùng xuyên suốt object reconstruction.

Về product UX, điều này rất giống:

```text
candidate object
→ Human Confirmation
→ propagate/associate
→ object scene representation
```

của chúng ta.

Nhưng UI của họ là tool local, trong khi chúng ta cần Web Studio.

Vì vậy:

```text
Không reuse UI.

Reuse:
- interaction semantics
- mask metadata organization
- propagation workflow
- object naming/ID pattern
```

Mức:

```text
REFERENCE / selective ADAPT
```

---

## 8. Orchestration của OpenReal2Sim

Có:

```text
PreprocessManager
ReconAgent
```

`ReconAgent` chạy tuần tự các stage:

```text
mask propagation
→ background pixel inpainting
→ background point inpainting
→ background mesh
→ object mesh
→ scenario construction
→ FoundationPose
→ collision optimization
```

Đây là một orchestration implementation thực, nhưng không phù hợp để thay orchestration của chúng ta.

Project của ta đã có invariant:

> heavy stage độc lập và giao tiếp bằng artifact contract/process boundary. 

Trong khi OpenReal2Sim truyền rất nhiều state bằng:

```text
scene.pkl
```

và shared Python dictionaries.

Do đó:

```text
ReconAgent
→ REFERENCE only
```

Không đưa nó vào core.

---

## 9. Artifact contract của họ không nên bê sang

OpenReal2Sim chủ yếu dùng:

```text
outputs/<key>/
scene.pkl
scene.json
*.glb
*.usd
```

Trong `scene.pkl` chứa trực tiếp:

```text
images[]
depths[]
intrinsics
extrinsics
masks
pointmaps
object info
paths
```

Trong project chúng ta, đây là anti-pattern cho cross-track handoff.

Ta cần:

```text
ArtifactRef
URI
checksum
schema_version
provenance
immutable candidate
```

và `SceneIR` là canonical representation. Docs hiện đã định nghĩa artifact URI/checksum và provenance chain rõ ràng. 

Cho nên:

```text
Lấy algorithm/code
KHÔNG lấy data-contract architecture.
```

---

## 10. Runtime isolation của họ thì rất đáng học

OpenReal2Sim đã tách Docker:

```text
openreal2sim reconstruction container
isaaclab container
mujoco container
```

Đúng với architecture của chúng ta:

```text
heavy provider
→ independent worker/container
```

Họ thậm chí cung cấp riêng image `openreal2sim:dev` và `isaaclab:dev`.

Điểm này rất phù hợp với project và nên được audit sâu khi thiết kế EX-SIM deployment. Repo hiện dùng IsaacLab 2.0.2 + Isaac Sim 4.5.0, nên code phải được port/test với runtime mà project chúng ta khóa; docs hiện vẫn ghi GPU/driver/CUDA/IsaacLab/OpenUSD versions là `UNVERIFIED/TBD`.

---

## 11. License

Top-level `OpenReal2Sim` là **MIT**, nên source do repository này sở hữu khá thuận lợi để adapt/copy có attribution phù hợp.

Nhưng có một điểm cực quan trọng:

```text
OpenReal2Sim MIT
≠
mọi thứ trong third_party đều MIT
```

Repo kéo ít nhất:

```text
Mega-SAM
Grounded-SAM-2
Hunyuan3D-2
FoundationPose
ObjectClear
PromptDA
GraspGen
WiLoR
sam-3d-objects
```

qua submodule.

Vì vậy khi lấy **wrapper code của OpenReal2Sim** thì dễ hơn; nếu muốn lấy hoặc phụ thuộc trực tiếp code/model từ các submodule thì phải audit license riêng.

---

## 12. Code Reuse Matrix — OpenReal2Sim → Real2Sim Studio

| Phần OpenReal2Sim            | Track của ta | Action                   |
| ---------------------------- | ------------ | ------------------------ |
| `usd_conversion.py`          | EX-SIM       | **ADAPT-HIGH**           |
| MeshConverter / Physics APIs | EX-SIM       | **ADAPT-HIGH**           |
| Convex decomposition config  | EX-SIM       | **ADAPT**, calibrate lại |
| Isaac scene import pattern   | EX-SIM       | **ADAPT-HIGH**           |
| Isaac camera setup           | EX-SIM       | **ADAPT**                |
| Docker IsaacLab isolation    | EX-SIM/Infra | **ADAPT-HIGH**           |
| `scenario_construction.py`   | EX-SCENE/SIM | **ADAPT-MEDIUM**         |
| mesh↔point registration      | EX-SCENE     | **ADAPT-MEDIUM**         |
| ground alignment             | EX-SCENE/SIM | **ADAPT-MEDIUM**         |
| collision optimization       | EX-SIM       | **ADAPT-MEDIUM**         |
| background inpainting        | EX-SCENE P1  | **ADAPT-HIGH P1**        |
| background mesh completion   | EX-SCENE P1  | **ADAPT P1**             |
| Hunyuan object generation    | P1           | **REFERENCE/ADAPT**      |
| segmentation annotator       | EX-SCENE     | **REFERENCE**            |
| `ReconAgent` orchestration   | Infra        | **REFERENCE only**       |
| `scene.pkl` state model      | —            | **DO NOT ADOPT**         |
| manipulation/grasp pipeline  | —            | **OUT OF P0 SCOPE**      |

---

## 13. Các task hiện tại có thể giảm code nhờ repo này

Các vùng cho Codex / team audit và extraction sau này:

```text
EX-SIM
SIM-02 Collider generation
SIM-03 Physics enrichment
SIM-05 Candidate OpenUSD build
SIM-06 Isaac validation/runtime setup
```

Đây là vùng tiết kiệm code lớn nhất.

Sau đó:

```text
EX-SCENE
scene geometry registration
ground/canonical alignment utilities
P1 background completion
```

Trong khi:

```text
REC-03 COLMAP
REC-04 Brush
REC-05 OpenMVS
SAM2 core
Web Product
HITL lifecycle
Artifact Contract
SceneIR
Approval/Release
```

**không nên thay bằng OpenReal2Sim**.

---

## 14. Quyết định tạm thời sau Audit #1

Repo Map hiện đang gọi OpenReal2Sim là:

```text
Research / architecture reference
```

Sau audit code, classification này **đang đánh giá thấp repo**.

Candidate classification sau khi audit đủ 7 repo nên là:

```text
PointsCoder/OpenReal2Sim

Tier-0 Code Donor — EX-SIM
Secondary Code Donor — EX-SCENE
Reference — EX-REC
```

Đặc biệt:

> **Không nên tự viết từ đầu phần GLB/mesh → USD + PhysX configuration trước khi thử port `usd_conversion.py` của OpenReal2Sim.**

Đây là kết quả quan trọng nhất của Audit #1.

### Audit queue

```text
1. OpenReal2Sim                  ✅ AUDITED
2. R2G                           ← NEXT
3. VR-Robo
4. SuperSplat
5. DISCOVERSE + DISCOVERSE-Real2Sim
6. Gaussian Grouping
7. Re3Sim
```

Sau #7, mới nên tạo **final Cross-Repo Reuse Matrix** để quyết định chính xác repo nào trở thành code donor cho từng task và repo nào bị loại vì overlap/runtime/license.
