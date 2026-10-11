# Audit #5 — `discoverse-dev/DISCOVERSE` & `discoverse-dev/DISCOVERSE-Real2Sim`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repositories:**  
> - [`discoverse-dev/DISCOVERSE`](https://github.com/discoverse-dev/DISCOVERSE) (branch `main`, commit `d67f47c084aba0e0cf422a8725235f8b9238655a`, 2026-02-24) — MIT (root)  
> - [`discoverse-dev/DISCOVERSE-Real2Sim`](https://github.com/discoverse-dev/DISCOVERSE-Real2Sim) (branch `master`, commit `1fd9ecdbb02fe3b28bce5db28a3b968b4d3d4d57`, 2025-10-29) — Root license NULL, LitMesh2GS Inria/non-commercial, DiffusionLight MIT  
> **Ngày audit:** 2026-09-24  
> **Trạng thái:** Hoàn tất Audit #5 (5/7 trong Audit Queue)

---

## Kết luận trước

Hai repo này **không thay thế pipeline P0 hiện tại của chúng ta**, nhưng `DISCOVERSE` có hai cụm code rất đáng lấy mà ban đầu dễ bị bỏ qua:

```text
1. Physics body ↔ 3DGS object synchronization

2. Remote 3DGS rendering
   → GPU render
   → NVENC H.264
   → network streaming
```

Trong khi `DISCOVERSE-Real2Sim` mạnh ở một hướng khác:

```text
mesh object
→ multi-view RGB/depth
→ environment relighting
→ mesh-seeded 3DGS
```

Đây rất hữu ích cho **P1 user-added/generated assets**, nhưng không phải primary warehouse reconstruction.

Đánh giá tổng thể:

| Track                    |     DISCOVERSE | DISCOVERSE-Real2Sim |
| ------------------------ | -------------: | ------------------: |
| EX-REC global warehouse  |           Thấp |                Thấp |
| EX-SCENE object identity |           Thấp |                Thấp |
| Object visual assets     |            Cao |         **Rất cao** |
| Visual ↔ Physics sync    |    **Rất cao** |                Thấp |
| Collider preprocessing   | Trung bình–Cao |                Thấp |
| Isaac/OpenUSD            |          Không |               Không |
| Web editor               |           Thấp |               Không |
| Remote GS streaming      |    **Rất cao** |               Không |
| Relighting               |           Thấp |             **Cao** |
| Mesh → 3DGS              |           Thấp |         **Rất cao** |

---

## 1. DISCOVERSE thực chất là một simulator có hai representation song song

Kiến trúc chính của nó là:

```text
             Physics
               │
             MuJoCo
               │
      body pose / camera pose
               │
               ▼
         GS Renderer
               │
               ▼
       photorealistic RGB
```

Đây chính xác là invariant mà chúng ta đã khóa:

```text
Visual ≠ Physics
```

Trong `discoverse/envs/simulator.py`, MuJoCo giữ physical scene, trong khi:

```python
self.gs_renderer = GSRendererMuJoCo(
    self.config.gs_model_dict,
    self.mj_model,
)
```

giữ visual scene.

Mỗi simulation step, code thực hiện:

```python
self.gs_renderer.update_gaussians(self.mj_data)
```

rồi:

```python
self.gs_renderer.render(...)
```

Tức:

```text
MuJoCo body state
       ↓
update Gaussian transforms
       ↓
render exact visual state
```

Đây không phải concept trong paper; code runtime thực sự tồn tại.

---

## 2. `gs_model_dict` rất gần `SceneObject.visual_ref` của chúng ta

Config của DISCOVERSE định nghĩa:

```python
gs_model_dict = {}
```

và documentation nói rõ:

```text
key   = simulator body name
value = corresponding 3DGS PLY
```

Ví dụ concept:

```text
background → warehouse.ply
pallet     → pallet.ply
forklift   → forklift.ply
```

Physics simulator cũng có:

```text
body "pallet"
body "forklift"
```

Do đó mapping là:

```text
Physical Body ID
       ↕
Gaussian Visual Asset ID
```

Đây rất gần:

```text
SceneObject
├── object_id
├── visual_ref
├── geometry_ref
├── collider_ref
└── transform
```

của Real2Sim Studio.

### Điểm đáng lấy

Không phải `gs_model_dict` literal.

Mà là pattern:

```text
stable SceneObject ID
      ├── Visual binding
      └── Physics binding
```

sau đó mọi transform từ simulation đều propagate bằng identity đó.

---

## 3. DISCOVERSE và VR-Robo giải cùng một bài toán, nhưng theo hai implementation khác

VR-Robo trước đó:

```text
Isaac
→ RPyC/TCP
→ Gaussian renderer
```

DISCOVERSE:

```text
MuJoCo
→ direct GSRendererMuJoCo

hoặc

MuJoCo
→ ZMQ
→ remote Gaussian renderer
```

Đối với project chúng ta:

```text
Isaac
→ VisualSyncAdapter
→ GS Render Worker
```

là abstraction đúng.

Có nghĩa là:

```text
VR-Robo
+
DISCOVERSE
```

cho chúng ta hai implementation reference độc lập để thiết kế một interface sạch.

---

## 4. `gaussian_web_renderer` là phát hiện quan trọng nhất

DISCOVERSE có subsystem:

```text
discoverse/
└── gaussian_web_renderer/
    ├── server.py
    ├── client.py
    └── gaussian_steamer/
        ├── encoder.py
        ├── encoder_gpu.py
        ├── encoder_cpu.py
        └── decoder.py
```

README gọi nó là:

```text
GaussianSteamer
```

Mục tiêu là:

```text
GS Render
→ CUDA Tensor
→ hardware video encoder
→ compressed H.264
→ network
```

Đây là code khá gần P1 live simulation streaming mà chúng ta từng nói đến.

---

## 5. Protocol body/camera của nó rất đáng lấy

`client.py` lấy body state trực tiếp từ simulator:

```python
self.last_pos = mj_data.xpos[self.gs_body_ids]
self.last_quat = mj_data.xquat[self.gs_body_ids]
```

Camera:

```text
cam position
cam rotation matrix
field of view
```

Sau đó đóng gói:

```text
header
├── num_bodies
├── num_cameras
├── width
└── height

body payload
└── N × [x y z qw qx qy qz]

camera payload
└── M × [position + rotation matrix + fovy]
```

rồi gửi sang renderer.

Server nhận:

```text
object transforms
+
camera transforms
```

và gọi:

```python
renderer.update_gaussian_properties(pos, quat)
```

rồi:

```python
renderer.render_batch(...)
```

Đây là một contract rất hữu ích.

---

## 6. Nó giúp chúng ta thiết kế P1 `VisualSyncProtocol`

Thay vì để Isaac renderer integration dính chặt vào Isaac API:

```text
Isaac-specific data
→ renderer-specific implementation
```

ta có thể định nghĩa:

```text
VisualSyncFrame
├── candidate_id
├── simulation_frame
├── timestamp
├── objects[]
│   ├── scene_object_id
│   ├── position
│   └── quaternion
└── cameras[]
    ├── camera_id
    ├── position
    ├── rotation
    ├── projection
    └── fov
```

Isaac chỉ chịu trách nhiệm:

```text
Isaac
→ VisualSyncFrame
```

Renderer:

```text
VisualSyncFrame
→ photorealistic output
```

Đó là architecture tốt hơn cả việc copy thẳng code VR-Robo hoặc DISCOVERSE.

---

## 7. Remote renderer của DISCOVERSE tốt hơn VR-Robo ở transport layer

VR-Robo dùng:

```text
RPyC
+
pickle
+
raw TCP
```

khá research-oriented.

DISCOVERSE dùng:

```text
ZeroMQ
+
binary numpy-like payload
+
H.264
```

sạch hơn đáng kể cho remote rendering.

Architecture:

```text
Simulator Client
      │
      │ object/camera transforms
      ▼
 ZMQ Render Server
      │
      ▼
 Gaussian Renderer
      │
      ▼
 CUDA RGB tensor
      │
      ▼
 H.264 encoder
      │
      ▼
 network
```

Nếu P1 chúng ta cần live simulator viewport trong Web, DISCOVERSE là donor tốt hơn ở phần transport.

---

## 8. `encoder_gpu.py` đặc biệt đáng reuse

File có MIT header riêng.

Nó dùng:

```text
NVIDIA VideoProcessingFramework
PyNvCodec
PytorchNvCodec
NVENC
```

Pipeline:

```text
PyTorch CUDA RGB Tensor
        ↓
GPU Surface
        ↓
RGB → YUV420 → NV12
        ↓
NVENC
        ↓
H.264 bitstream
```

Pixel data không phải round-trip về CPU trước encoding.

Điều này chính là kiểu architecture ta muốn nếu sau này:

```text
Isaac/GS Render Worker
→ live Web stream
```

với latency thấp.

### Classification

```text
encoder_gpu.py
→ ADAPT-HIGH for P1
```

---

## 9. Nó còn có CPU fallback

`encoder_cpu.py` dùng:

```text
PyAV
libx264
preset = ultrafast
tune = zerolatency
B-frames = 0
```

Flow:

```text
CUDA tensor
→ CPU numpy
→ PyAV
→ H.264
```

Không nhanh bằng NVENC nhưng tốt cho fallback.

Điều này gợi ý interface:

```text
VideoEncoder
├── NvencVideoEncoder
└── CpuH264Encoder
```

thay vì business logic biết VPF.

---

## 10. Nhưng remote renderer có một thiếu hụt quan trọng: depth không được truyền

Server thực tế render:

```python
rgb_tensor, depth_tensor = renderer.render_batch(...)
```

nhưng encoded stream chỉ chứa RGB.

Client sau đó tạo:

```python
depth_slice = np.zeros(...)
```

Tức:

```text
remote RGB    ✅
remote depth  ❌
```

Do đó code này **không thể làm validation truth**.

Với chúng ta:

```text
ValidationReport
```

vẫn phải đến từ Isaac / physical validation.

Remote stream chỉ là:

```text
visual evidence
live visualization
```

---

## 11. Đây cũng là lý do không dùng streamer cho P0

P0 đã có đường sạch hơn:

```text
SceneIR
→ SuperSplat
```

cho Web inspection.

Và:

```text
Isaac
→ simulation.mp4
```

cho Final Review.

Không cần thêm ngay:

```text
ZeroMQ
NVENC
remote GS server
live stream
```

vì sẽ làm tăng runtime complexity.

Tôi xếp:

```text
GaussianSteamer
→ P1
```

chứ không P0.

---

## 12. `mesh2mjcf.py` lại có code collider đáng chú ý

DISCOVERSE có:

```text
scripts/mesh2mjcf.py
scripts/mesh2mjcf_batch.py
```

Tên là MuJoCo-specific, nhưng bên trong có một phần rất usable:

```text
mesh
↓
CoACD convex decomposition
↓
part_0.obj
part_1.obj
...
```

Nó dùng:

```python
coacd
trimesh
```

và có config cho scene:

```python
{
    "threshold": 0.01,
    "preprocess_resolution": 100
}
```

---

## 13. Quan trọng hơn: code đã tách Visual Geometry và Collision Geometry

Khi convex decomposition bật:

```text
full mesh
→ visual

convex part 0
convex part 1
...
→ collision
```

Tức họ đã encode tư duy:

```text
Visual mesh
≠
Collision mesh
```

rất đúng với architecture chúng ta.

Có thể lấy:

```text
CoACD invocation
mesh decomposition
convex-part asset handling
```

cho `SIM-02`.

Không lấy:

```text
MJCF XML generation
```

vì target chúng ta là OpenUSD/PhysX.

---

## 14. Đây có thể tạo thêm một collider backend candidate

Hiện EX-SIM có thể có:

```text
ColliderBackend
├── primitive approximation
├── Trimesh/Open3D processing
├── convex decomposition
└── splat-transform fallback
```

Sau audit DISCOVERSE, có thể cụ thể hóa convex backend:

```text
CoACDColliderBackend
```

dựa trên CoACD.

Flow:

```text
SceneObject.geometry_ref
        ↓
Trimesh
        ↓
CoACD
        ↓
convex_parts[]
        ↓
OpenUSD / PhysX
```

Đây thực tế hữu ích hơn việc reuse MJCF generator.

---

## 15. Nhưng không copy default mass/inertia của họ

Script có default kiểu:

```text
mass = 0.001 kg
diaginertia = 2e-5 ...
```

Đó là tool-specific convenience value.

Không được bê sang Real2Sim physics policy.

Physics properties của chúng ta phải:

```text
explicit
or
policy-generated
or
human-confirmed
```

không dùng arbitrary universal defaults.

---

## 16. `SceneAlignmentGUI` là reference UX tốt nhưng code reuse thấp

Repo có:

```text
discoverse/envs/scene_alignment_gui.py
```

cho phép chỉnh:

```text
position
quaternion
joint positions
```

và simulator update ngay.

Đây khá gần:

```text
Human aligns visual/physics object
```

nhưng implementation:

```text
Matplotlib
hard-coded body(1)
position range ±0.1
local desktop UI
```

nên không phù hợp với Web Studio.

Classification:

```text
REFERENCE ONLY
```

---

## 17. Có một drift trong docs DISCOVERSE cần lưu ý

Docs nói có:

```text
scripts/gsply_edit.py
```

cho:

```text
translation
rotation
scale
SH rotation
```

nhưng trên commit hiện tại tôi không tìm thấy file đó.

GitHub search chỉ tìm thấy documentation tham chiếu tới nó.

Tức:

```text
docs claim
≠
current repository content
```

Nên **không tính `gsply_edit.py` là reusable code hiện tại**.

Hơn nữa `playcanvas/splat-transform` mà ta vừa audit mạnh hơn nhiều cho use case này.

---

## 18. DISCOVERSE main không có Isaac/OpenUSD implementation

Tôi đã search trực tiếp:

```text
Isaac Sim
IsaacLab
OpenUSD
UsdPhysics
```

không có implementation liên quan.

Simulator chính là:

```text
MuJoCo + MJCF
```

Do đó DISCOVERSE **không cạnh tranh với OpenReal2Sim** ở:

```text
SceneIR
→ OpenUSD
→ PhysX
→ Isaac
```

và không cạnh tranh với VR-Robo ở Isaac runtime.

---

## 19. Vậy DISCOVERSE giải quyết phần nào độc đáo?

Chủ yếu:

```text
                    DISCOVERSE

Physics bodies ──────────────┐
                            │
GS assets keyed by body ─────┤
                            ▼
                  visual synchronization
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
             local renderer      remote renderer
                                      │
                                    H.264
```

Đây chính là phần nó mạnh nhất.

---

# DISCOVERSE-Real2Sim

Phần này cần tách riêng vì nó khác hẳn main repo.

## 20. Đây không phải một generic Real2Sim-from-video system như tên có thể khiến ta tưởng

README pipeline thực tế là:

```text
Object:
single image
→ TRELLIS/external 3D generation
→ textured mesh

Background:
scanner or multiview RGB
→ 3DGS

Object Appearance:
RGB background
→ DiffusionLight
→ HDR
→ Blender relighting

Textured Object Mesh
→ multi-view RGB + depth
→ Mesh2GS
→ object 3DGS
```

Tức trọng tâm lớn là:

> **tạo photorealistic object assets đồng bộ ngoại hình với reconstructed background**.

Nó không làm:

```text
raw warehouse video
→ segmentation
→ automatic editable SceneIR
→ physics
```

như product của chúng ta.

---

## 21. Step 1 TRELLIS không phải code donor của repo

README hướng dẫn dùng external:

```text
Microsoft TRELLIS
```

nhưng không vendor một integration backend hoàn chỉnh trong repo này.

Nên không tính:

```text
DISCOVERSE-Real2Sim
→ TRELLIS implementation
```

Nó chỉ là workflow recommendation.

Nếu P1 cần:

```text
Image → Generated 3D Object
```

ta phải audit TRELLIS riêng.

---

## 22. Background reconstruction cũng không có implementation đủ mạnh để lấy

README khuyên:

```text
LixelKity K1
+
Lixel CyberColor
```

hoặc:

```text
vanilla 3DGS
```

nhưng không có một pipeline tương đương:

```text
video
→ poses
→ global geometry
→ metric reconstruction
```

của chúng ta.

Vì vậy:

```text
REC-03 COLMAP
REC-04 Brush
REC-05 OpenMVS
```

không bị thay thế.

---

## 23. Phần rất thú vị là Mesh → 3DGS

Đây là nơi `DISCOVERSE-Real2Sim` có giá trị thật.

Flow:

```text
textured mesh
      ↓
Blender
      ↓
multi-view RGB
multi-view depth
camera poses
mask
      ↓
LitMesh2GS
      ↓
object-level 3DGS
```

Đây gần như là một **VisualAssetBuilder**.

---

## 24. Blender renderer đã tạo dữ liệu khá đầy đủ

`blender_renderer/glb_render.py`:

```text
GLB/OBJ asset
↓
normalize scene
↓
sample cameras on sphere
↓
Cycles GPU render
↓
RGB
Depth EXR
Camera pose
Mesh
```

Output concept:

```text
images/
poses/
depths/
1.obj
norm.obj
```

Nó còn dùng HDR environment map làm illumination.

---

## 25. Một chi tiết kỹ thuật hay: nó normalize để render rồi khôi phục metric/object scale sau

Blender script:

```text
original mesh
↓
measure bbox
↓
scale longest side to 1
↓
center around origin
↓
render efficiently
```

Sau đó `tocolmap.py` lấy original mesh:

```python
mesh = trimesh.load_mesh("1.obj")
```

tính:

```text
original scale
original center
```

rồi đưa camera translations và depth trở về original coordinate/scale trước khi tạo COLMAP model.

Đây là một pattern rất tốt:

```text
temporary normalized working space
        ↓
explicit inverse transform
        ↓
source coordinate system
```

Điều này hợp với canonical-coordinate discipline của project.

---

## 26. Tuy nhiên không được copy transform convention của họ trực tiếp

`glb_render.py` có nhiều conversion:

```text
Blender
→ CV
→ custom 90° X rotation
```

và `tocolmap.py` lại xử lý:

```text
C2W
W2C
scale
center
```

Đây là workflow-specific.

Ta chỉ reuse concept:

```text
NormalizationTransform
+
InverseNormalizationTransform
```

không reuse hardcoded axes thành canonical convention.

---

## 27. LitMesh2GS không phải vanilla point-cloud initialized 3DGS

Đây là điểm rất đáng chú ý.

Trong:

```text
LitMesh2GS/scene/gaussian_model.py
```

có:

```python
create_from_manifold(mesh, spatial_lr_scale)
```

Nó lấy mỗi triangle:

```python
face_verts = mesh.verts[mesh.faces]
```

rồi Gaussian initial center:

```python
central_points = (v0 + v1 + v2) / 3
```

Tức:

```text
mesh triangles
→ Gaussian seed centers
```

Do đó 3DGS visual được neo trực tiếp vào known mesh geometry.

---

## 28. Điều này cực kỳ phù hợp với user-added object

Ví dụ user muốn thêm:

```text
pallet
safety cone
box
barrier
```

vào warehouse.

Nếu có mesh:

```text
pallet.glb
```

ta có thể có:

```text
GeometryArtifact
      ↓
mesh-seeded GS training
      ↓
VisualArtifact
```

Hai representation sinh từ cùng object source nên alignment tự nhiên hơn.

Đây là một use case rất tốt cho:

```text
AddedAsset
├── Geometry = mesh
├── Visual = 3DGS
└── Collider = derived geometry
```

---

## 29. Training loss cũng khá phù hợp với mesh-conditioned asset building

`train.py` không chỉ RGB loss.

Nó dùng:

```text
RGB image loss
+
Depth loss
+
Mask loss
```

Cụ thể:

```python
image_loss = L1(rendered_rgb, gt_rgb)
depth_loss = L1(rendered_depth, gt_depth)
mask_loss  = BCE(alpha, gt_mask)
```

Điều này giúp 3DGS:

```text
stay near actual object surface
respect silhouette
respect depth
```

hơn pure appearance fitting.

Đây là algorithm pattern đáng học.

---

## 30. Nhưng LitMesh2GS KHÔNG nên thay Brush

Brush của chúng ta giải:

```text
real RGB observations
→ global reconstructed visual
```

LitMesh2GS giải:

```text
known mesh
→ synthetic rendered observations
→ object visual 3DGS
```

Hai bài toán khác nhau.

Vì vậy architecture hợp lý là:

```text
Global environment:
Brush

Added/generated object:
Mesh2GS-like backend
```

chứ không:

```text
replace Brush with LitMesh2GS
```

---

## 31. Nó có thể trở thành `AddedAssetVisualBackend` P1

Concept:

```python
class AddedAssetVisualBackend:
    def build_visual(
        geometry_ref,
        appearance_context,
    ) -> VisualArtifact:
        ...
```

Potential implementation:

```text
MeshSeededGaussianBackend
```

Workflow:

```text
Geometry
→ multiview synthetic rendering
→ visual optimization
→ object.ply
```

Đây là phần độc đáo mà những repo trước chưa giải quyết tốt bằng implementation trực tiếp.

---

## 32. DiffusionLight dùng để align lighting, không phải object-removal inpainting

Repo vendor:

```text
DiffusionLight/
```

có MIT license riêng.

Flow:

```text
background RGB
↓
inpaint chrome ball / illumination inference
↓
environment maps
↓
HDR .exr
```

Sau đó Blender dùng HDR này để render object.

Nghĩa là:

```text
object inserted into warehouse
```

có màu/illumination gần scene background hơn.

---

## 33. Không được nhầm DiffusionLight `inpaint.py` với Background Completion

Tên file:

```text
inpaint.py
```

có thể gây hiểu nhầm.

Nó nằm trong lighting estimation workflow.

Không phải:

```text
remove pallet
→ fill hidden floor/wall
```

mà chúng ta cần ở `BackgroundCompletionBackend`.

Do đó:

```text
DiffusionLight
→ lighting/appearance P1

NOT
→ scene hole completion
```

---

## 34. Đây có thể tạo một P1 pipeline rất đẹp

Sau này:

```text
Engineer: Add pallet
       ↓
Asset Catalog
       ↓
mesh / generated mesh
       ↓
Collider
       │
       ├─────────────────┐
       │                 │
       ▼                 ▼
Geometry          DiffusionLight
                    ↓
               scene HDR
                    ↓
                Blender
                    ↓
             RGB/depth/mask
                    ↓
              Mesh2GS-like
                    ↓
                 3DGS
       │                 │
       └────────┬────────┘
                ▼
            SceneObject
```

Đây là một P1 feature khá mạnh.

---

## 35. Nhưng automation của DISCOVERSE-Real2Sim chưa production-ready

README còn yêu cầu:

> mở Blender và chạy script trong `Scripting` panel.

Thậm chí họ nói không khuyến nghị standalone `bpy` vì version mismatch.

Điều này nghĩa là current workflow:

```text
manual / research pipeline
```

chứ chưa phải:

```text
backend worker API
```

Để dùng trong Studio, phải containerize/refactor đáng kể.

---

## 36. License của hai repo khác nhau rất nhiều

Đây là phần phải cực kỳ cẩn thận.

### `DISCOVERSE`

Root có:

```text
MIT
```

Nên project-owned source như:

```text
gaussian_web_renderer/server.py
client.py
encoder_gpu.py
encoder_cpu.py
mesh2mjcf.py
```

về nguyên tắc khá thuận lợi để reuse/adapt với attribution phù hợp.

Nhưng:

```text
DISCOVERSE MIT
≠
gaussian_renderer package MIT
≠
all Git submodules MIT
```

`gaussian_renderer` là dependency bên ngoài. License của nó phải audit riêng nếu chúng ta muốn lấy source của renderer.

---

## 37. `DISCOVERSE-Real2Sim` root không có LICENSE

Đây là caveat lớn.

GitHub API hiện báo:

```text
license = null
```

và root không có `LICENSE`.

Nghĩa là **không nên mặc định copy root source code** như:

```text
blender_renderer/glb_render.py
tocolmap.py
```

chỉ vì repository public.

Public source ≠ permission to reuse.

Do đó các file root này nên classification:

```text
REFERENCE
```

trừ khi tác giả làm rõ license.

---

## 38. LitMesh2GS có license còn rõ ràng hơn — nhưng restrictive

`LitMesh2GS/LICENSE.md` là:

```text
Gaussian-Splatting License
Inria / MPII
```

và ghi rõ:

```text
research/evaluation only
non-commercial
```

Không được dùng thương mại nếu chưa có permission.

Nhiều source file cũng mang Inria non-commercial header.

Do đó:

```text
LitMesh2GS
→ rất tốt để học thuật toán
→ phù hợp đồ án research theo terms
→ KHÔNG nên copy vào commercializable core
```

---

## 39. DiffusionLight lại MIT

Phần:

```text
DiffusionLight/
```

có MIT license riêng.

Do đó nếu sau này cần HDR estimation:

```text
DiffusionLightBackend
```

có thể là candidate reuse thực tế hơn LitMesh2GS.

---

## 40. DISCOVERSE không nên thay OpenReal2Sim

Sau audit:

```text
OpenReal2Sim
→ mesh/physics/USD/Isaac

DISCOVERSE
→ visual/physics synchronization
→ remote visual streaming
→ MuJoCo asset/collider patterns
```

Không overlap hoàn toàn.

Với simulator target của chúng ta:

```text
OpenReal2Sim
```

vẫn có fit trực tiếp hơn.

---

## 41. DISCOVERSE cũng không thay VR-Robo

VR-Robo:

```text
Isaac-specific
physics + GS visual synchronization
```

DISCOVERSE:

```text
better remote transport/streaming pattern
but MuJoCo-specific physics side
```

Tôi sẽ kết hợp:

```text
VR-Robo
→ Isaac-side state extraction/runtime

DISCOVERSE
→ remote rendering protocol + H264 transport
```

nếu làm P1.

---

## 42. Nó không thay R2G

R2G trả lời:

```text
“Gaussian/geometry nào thuộc object nào?”
```

DISCOVERSE giả sử mapping đã có:

```text
body_name → PLY
```

Nó không solve:

```text
real scene
→ discover pallet
→ multi-view associate pallet
```

Do đó:

```text
SAM2 + R2G-derived association
```

vẫn giữ.

---

## 43. Và không thay SuperSplat

DISCOVERSE Gaussian streamer gửi:

```text
H.264 pixels
```

SuperSplat nhận:

```text
actual Gaussian data
```

và cho:

```text
select
edit
transform
layer control
```

Hai use case khác nhau.

P0:

```text
SuperSplat
```

P1 live simulator:

```text
DISCOVERSE-like H264 stream
```

---

## 44. Code Reuse Matrix — DISCOVERSE

| File/module                       | Real2Sim use               | Quyết định                       |
| --------------------------------- | -------------------------- | -------------------------------- |
| `envs/simulator.py`               | Physics→GS sync lifecycle  | **REFERENCE/ADAPT pattern**      |
| `gs_model_dict` mapping           | SceneObject visual binding | **ADAPT-HIGH concept**           |
| `gaussian_web_renderer/server.py` | P1 GS render worker        | **ADAPT-HIGH**                   |
| `gaussian_web_renderer/client.py` | P1 pose/camera protocol    | **ADAPT-HIGH**                   |
| `encoder_gpu.py`                  | NVENC live stream          | **REUSE/ADAPT-HIGH P1**          |
| `encoder_cpu.py`                  | CPU H264 fallback          | **REUSE/ADAPT P1**               |
| `mesh2mjcf.py` CoACD portion      | Collider decomposition     | **ADAPT-HIGH selective**         |
| MJCF generator                    | Isaac                      | **DO NOT USE**                   |
| `scene_alignment_gui.py`          | Human alignment UX         | **REFERENCE**                    |
| `gsply_edit.py`                   | GS transform               | **DO NOT DEPEND — file missing** |
| MuJoCo-LiDAR                      | Isaac P0                   | **NO**                           |
| imitation/RL stack                | Real2Sim Studio            | **OUT OF SCOPE**                 |

---

## 45. Code Reuse Matrix — DISCOVERSE-Real2Sim

| Module                        | Real2Sim use                         | Quyết định                                 |
| ----------------------------- | ------------------------------------ | ------------------------------------------ |
| Blender multiview rendering   | AddedAsset visual pipeline           | **REFERENCE due root license**             |
| `tocolmap.py`                 | normalization/coordinate restoration | **REFERENCE**                              |
| Mesh→COLMAP synthetic dataset | AddedAsset training                  | **REFERENCE**                              |
| `create_from_manifold()`      | Mesh-seeded 3DGS                     | **REFERENCE-HIGH, non-commercial license** |
| RGB+Depth+Mask loss           | Mesh→GS algorithm                    | **REFERENCE-HIGH**                         |
| LitMesh2GS training           | AddedAsset visual                    | **P1, licensing constraint**               |
| DiffusionLight                | HDR estimation                       | **REUSE/ADAPT P1**                         |
| TRELLIS recommendation        | Generated mesh                       | External repo, separate audit              |
| Background reconstruction     | EX-REC                               | **NO significant code donor**              |
| Physics packaging             | EX-SIM                               | **NONE**                                   |
| Isaac/OpenUSD                 | EX-SIM                               | **NONE**                                   |

---

## 46. Impact lên P0 hiện tại

Điều quan trọng là **không cần redesign P0** sau audit này.

Giữ:

```text
EX-REC
COLMAP
→ Brush
→ OpenMVS
```

Giữ:

```text
EX-SCENE
SAM2
→ R2G-derived association
→ Human Confirmation
→ SceneIR
```

Giữ:

```text
EX-SIM
OpenReal2Sim-derived USD/physics
→ Isaac
→ VR-Robo-derived runtime patterns
```

Giữ:

```text
EX-PRODUCT
splat-transform
→ SuperSplat-derived editor
```

DISCOVERSE bổ sung một vài utility/pattern, không phá architecture.

---

## 47. Một thứ có thể đưa vào P0 ngay: audit CoACD

Nếu `SIM-02` chưa khóa convex decomposition implementation, DISCOVERSE đã cho thấy một implementation sử dụng:

```text
Trimesh
+
CoACD
```

rất hợp với:

```text
complex shelf mesh
→ multiple convex colliders
```

Nên trước khi tự viết convex decomposition pipeline, có thể qualification:

```text
OpenMVS mesh
→ CoACD
→ convex parts
→ OpenUSD/PhysX
→ Isaac
```

Nếu pass thì lấy phần preprocessing này.

---

## 48. Một thứ KHÔNG cần đưa vào P0: remote GS streaming

Không cần vội thêm:

```text
ZMQ
NVENC
VPF
H264 live stream
```

Hiện P0:

```text
Web scene editing
+
Isaac validation
+
simulation replay
```

đã đủ.

Remote live simulator viewport chỉ nên:

```text
P1
```

---

## 49. Nhưng nên ghi lại P1 architecture ngay từ bây giờ

Có thể để future adapter:

```text
SimulationVisualBridge
```

với:

```text
P0:
No live bridge required

P1:
Isaac
→ VisualSyncFrame
→ GSRenderWorker
→ H264
→ Web
```

Implementation donor:

```text
VR-Robo
+ DISCOVERSE GaussianSteamer
```

---

## 50. Một P1 khác đáng ghi lại: generated/additional object visual

```text
AddedAssetVisualBackend
```

potential flow:

```text
mesh
↓
multiview rendering
↓
RGB + depth + masks
↓
mesh-seeded GS optimization
↓
VisualArtifact
```

Concept donor:

```text
DISCOVERSE-Real2Sim / LitMesh2GS
```

Nhưng nếu cần commercial-safe implementation, **không copy LitMesh2GS source trực tiếp**; cần tìm permissive backend hoặc tự implement trên license phù hợp.

---

## 51. Mức độ “lấy được code” thực tế

Nếu mục tiêu là maximize reuse:

### DISCOVERSE main

Có lượng code **thực sự có thể lấy khá nhiều**:

```text
remote renderer server
remote renderer client
H264 encoder abstraction
NVENC path
CPU fallback
CoACD pipeline
asset/body mapping pattern
```

và top-level MIT thuận lợi.

### DISCOVERSE-Real2Sim

Có nhiều algorithm/workflow hay, nhưng lượng code chúng ta **nên copy trực tiếp ít hơn** vì:

```text
root license missing
+
LitMesh2GS non-commercial license
```

Nó mạnh hơn ở vai trò:

```text
architecture/algorithm reference
```

---

## 52. Classification sau Audit #5

Tôi đề xuất sau vòng audit cuối cùng Repo Map ghi:

```text
discoverse-dev/DISCOVERSE

Tier-0 Integration Reference
— Visual ↔ Physics object synchronization

Tier-0 P1 Code Donor
— Remote Gaussian rendering / H264 streaming

Secondary Utility Donor
— CoACD collider preprocessing

NOT primary simulator backend
NOT EX-REC backend
```

Và:

```text
discoverse-dev/DISCOVERSE-Real2Sim

P1 Asset Generation Reference
— Mesh → 3DGS
— RGB/depth/mask optimization
— Lighting alignment

DiffusionLight:
— permissive P1 code donor

LitMesh2GS:
— research algorithm reference
— commercial licensing constraint

NOT P0 Core
```

---

## 53. Cross-repo picture sau audit này

Bây giờ vai trò của từng repo khá rõ:

```text
                       REAL INPUT
                           │
                           ▼
                        EX-REC
                           │
           COLMAP + Brush + OpenMVS
                           │
                   splat-transform
                           │
                           ▼
                  ReconstructionBundle
                           │
                           ▼
                       EX-SCENE
                           │
                          SAM2
                           │
                   R2G-derived
                MultiView Association
                           │
                           ▼
                        SceneIR
                       /       \
                      /         \
                 Visual         Physics
                   │               │
                   │          OpenReal2Sim
                   │           patterns
                   │               │
                   │          OpenUSD/PhysX
                   │               │
                   │               ▼
                   │            Isaac
                   │               │
                   │       VR-Robo patterns
                   │               │
                   │               ▼
                   │       ValidationReport
                   │
                   ▼
        SuperSplat-derived Editor
```

P1 thêm:

```text
Isaac
  │
  └── transforms
        ↓
DISCOVERSE-derived VisualSyncProtocol
        ↓
GS Render Worker
        ↓
NVENC / H264
        ↓
Live Web View
```

và:

```text
New Mesh Asset
      ↓
DISCOVERSE-Real2Sim-inspired
Mesh → GS visual backend
      ↓
SceneObject.visual_ref
```

---

## 54. Bảng sau 6 audit units

| Capability            |  OpenReal2Sim |           R2G |       VR-Robo |    SuperSplat | splat-transform |                 DISCOVERSE |
| --------------------- | ------------: | ------------: | ------------: | ------------: | --------------: | -------------------------: |
| Global reconstruction |           Med |           Med |           Low |             — |               — |                        Low |
| GS artifact tooling   |           Low |           Med |           Med |          High |   **Very High** |                        Med |
| Object association    |           Low | **Very High** |           Low |         Human |             Low |                        Low |
| Object-level visual   |           Med |      **High** |          High |          High |             Med |                   **High** |
| Web editor            |             — |             — |             — | **Very High** |         Utility |                          — |
| Collider prep         |      **High** |           Low |           Low |             — |    Med fallback |         **High via CoACD** |
| USD build             | **Very High** |             — |           Low |             — |               — |                          — |
| Isaac runtime         |          High |             — | **Very High** |             — |               — |                          — |
| GS↔physics sync       |           Med |             — | **Very High** |             — |               — |              **Very High** |
| Remote GS stream      |             — |             — |           Med |             — |               — |              **Very High** |
| Mesh→GS asset         |           Med |             — |             — |             — |               — |      **Very High concept** |
| Relighting            |           Low |             — |             │ |             — |               — | **High via Real2Sim repo** |

---

## 55. Điều quan trọng nhất rút ra từ DISCOVERSE

Có ba thứ đáng giữ:

```text
1. SceneObject ID nên là bridge
   giữa visual asset và physical body.

2. Visual renderer hoàn toàn có thể
   chạy process/server riêng,
   nhận transform từ simulator.

3. Với object được thêm mới,
   Geometry có thể có trước,
   rồi Visual 3DGS được sinh từ Geometry,
   không nhất thiết mọi Visual đều phải
   được reconstructed từ global scene.
```

Điểm thứ 3 đặc biệt hữu ích để mở rộng Real2Sim Studio sau MVP.

---

## Audit queue

```text
1. OpenReal2Sim                  ✅
2. R2G                           ✅
3. VR-Robo                       ✅
4. SuperSplat                    ✅
4.5 splat-transform              ✅
5. DISCOVERSE
   + DISCOVERSE-Real2Sim         ✅

6. Gaussian Grouping             ← NEXT

7. Re3Sim
```

Sau `Gaussian Grouping` và `Re3Sim`, lúc đó đủ dữ liệu để làm **Final Cross-Repo Reuse Matrix** và quyết định chính thức từng task của Real2Sim Studio sẽ `REUSE / ADAPT / SELF-CODE` từ repo nào.
