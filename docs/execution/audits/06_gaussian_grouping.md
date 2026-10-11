# Audit #6 — `lkeab/gaussian-grouping`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`lkeab/gaussian-grouping`](https://github.com/lkeab/gaussian-grouping) (branch `main`, commit `0ab60afed3385b717c985af1d30a20f7b0884c89`, 2024-07-04, ECCV 2024)  
> **License:** Apache-2.0 (root repo) / Inria non-commercial & Gaussian-Splatting License (submodule `diff-gaussian-rasterization`) / CC BY-NC-SA 4.0 (`Tracking-Anything-with-DEVA`)  
> **Ngày audit:** 2026-09-25  
> **Trạng thái:** Hoàn tất Audit #6 (6/7 trong Audit Queue)

---

## Kết luận trước

Gaussian Grouping là repo rất liên quan đến **EX-SCENE**, nhưng sau khi đọc code kỹ, kết luận chính là:

> **Không thay SAM2 + R2G hiện tại bằng Gaussian Grouping trong baseline P0.**
>
> Giá trị lớn nhất của repo này là một ý tưởng/implementation reference cho bước **2D object masks → persistent per-Gaussian object membership**, tức biến global 3DGS từ một đám Gaussian vô danh thành một representation biết “Gaussian nào thuộc object nào”. Đây chính xác là khoảng giữa `ReconstructionBundle` và `SceneIR`.

---

## 1. Gaussian Grouping thực sự giải bài toán gì?

Vanilla 3DGS có:

```text
Gaussian_i
├── position
├── scale
├── rotation
├── opacity
└── SH appearance
```

Nó không biết:

```text
Gaussian này thuộc pallet?
Gaussian này thuộc shelf?
Gaussian này thuộc floor?
```

Gaussian Grouping thêm một vector identity vào **mỗi Gaussian**:

```text
Gaussian_i
├── geometry
├── appearance
└── identity encoding
```

Paper mô tả nó là một compact **Identity Encoding** được học từ các mask 2D của SAM và regularization không gian 3D.

Code hiện tại hard-code:

```cpp
#define NUM_OBJECTS 16
```

và Python:

```python
self.num_objects = 16
self._objects_dc = ...
```

Tức mỗi Gaussian mang:

```text
16-dimensional identity feature
```

chứ **không phải 16 object**.

---

## 2. Sau đó 16D identity được classify thành object IDs

Trong `train.py`:

```python
classifier = torch.nn.Conv2d(
    gaussians.num_objects,
    num_classes,
    kernel_size=1,
)
```

với default:

```text
identity dimension = 16
num_classes        = 200
```

Pipeline thực tế:

```text
Gaussian
   │
   ├── RGB feature
   │
   └── 16D identity feature
              │
              ▼
   differentiable rasterizer
              │
              ▼
      16 × H × W feature map
              │
              ▼
          1×1 Conv
              │
              ▼
      object ID probability
```

Điểm này rất quan trọng:

```text
16D feature ≠ object ID
```

Classifier mới map feature sang:

```text
ID 0 ... ID 199
```

---

## 3. Repo sửa cả CUDA rasterizer để render identity

Đây không phải một classifier chạy bên ngoài 3DGS.

Họ sửa `diff-gaussian-rasterization` để đồng thời rasterize:

```text
RGB
+
object identity features
```

CUDA code allocate:

```cpp
out_color   = [3, H, W]
out_objects = [16, H, W]
```

và gradient cũng backpropagate vào:

```text
dL_dobjects
```

Architecture là:

```text
                    Gaussian
                 /            \
                /              \
        SH appearance      Identity feature
             │                  │
             └────────┬─────────┘
                      ▼
             Gaussian Rasterizer
                 /           \
                ▼             ▼
              RGB        Identity image
```

Đây là phần kỹ thuật cốt lõi của Gaussian Grouping.

---

## 4. Nó không đơn giản là “SAM rồi project mask vào 3D”

Training loss cho identity có **hai nguồn supervision**.

### 2D supervision

Render identity feature:

```python
objects = render_pkg["render_object"]
```

sau đó:

```python
logits = classifier(objects)
loss_obj = CrossEntropy(logits, gt_obj)
```

Trong đó:

```text
gt_obj
```

đến từ mask theo từng frame.

Tức:

```text
2D tracked object masks
         ↓
supervise rendered Gaussian identity
```

---

## 5. Và thêm 3D spatial consistency

Đây mới là phần làm nó đáng chú ý.

Code:

```python
loss_cls_3d(
    gaussians._xyz,
    prob_obj3d,
    k=5,
    ...
)
```

Lấy các Gaussian gần nhau trong không gian:

```text
Gaussian A
├── nearest Gaussian B
├── nearest Gaussian C
├── nearest Gaussian D
└── ...
```

rồi dùng KL divergence để ép object distributions gần nhau.

Concept:

```text
2D masks
   │
   ▼
identity supervision
   │
   │       spatial neighborhood
   │              │
   └──────┬───────┘
          ▼
  coherent 3D grouping
```

Đây là một pattern rất phù hợp với Real2Sim của chúng ta.

---

## 6. Đầu vào của Gaussian Grouping gần với dữ liệu chúng ta đã có

Repo yêu cầu:

```text
images/
COLMAP camera poses
COLMAP sparse points
object_mask/
```

Mask preparation của repo là:

```text
RGB frames
→ SAM
→ DEVA temporal association
→ persistent object-ID masks
```

Docs nhấn mạnh chất lượng mask giữa các view ảnh hưởng trực tiếp đến chất lượng 3D grouping.

Trong project của chúng ta đã có:

```text
RGB
→ SAM2
→ mask propagation
→ multi-view association
```

Nghĩa là **không cần dùng DEVA của họ để áp dụng concept Gaussian Grouping**.

---

## 7. Thực tế SAM2 hiện tại phù hợp với chúng ta hơn DEVA

Gaussian Grouping được xây vào 2023–2024:

```text
SAM
+
DEVA
```

Repo thậm chí vendor nguyên:

```text
Tracking-Anything-with-DEVA/
```

Trong pipeline hiện tại:

```text
SAM2
→ video/mask propagation
```

đã giải đúng vai trò đó với architecture đơn giản hơn.

Vì vậy tôi không đưa:

```text
DEVA
```

vào P0.

Ta chỉ lấy:

```text
stable multi-view mask IDs
→ 3D Gaussian identity learning
```

là idea.

---

## 8. Đây là điểm Gaussian Grouping overlap trực tiếp với R2G

Architecture hiện tại của ta:

```text
SAM2 masks
      ↓
R2G-derived multi-view association
      ↓
candidate objects
      ↓
Human Confirmation
```

Gaussian Grouping cung cấp một hướng khác:

```text
SAM2 masks
      ↓
identity-feature optimization
      ↓
per-Gaussian grouping
      ↓
candidate objects
```

Do đó về architecture, hai cái nên nằm sau một abstraction:

```text
ObjectAssociationBackend
├── R2GAssociationBackend
└── GaussianGroupingBackend
```

chứ không chain bắt buộc:

```text
R2G
→ Gaussian Grouping
```

---

## 9. Tuy nhiên Gaussian Grouping hiện tại bị tightly coupled với reconstruction

Đây là lý do tôi **không đổi P0 sang nó ngay**.

Repo làm:

```text
COLMAP
→ vanilla 3DGS training
   ├── appearance
   └── identity
```

đồng thời.

Trong khi project của ta:

```text
COLMAP
→ Brush
→ finished Global Visual
```

rồi mới:

```text
EX-SCENE
```

Gaussian Grouping hiện tại không có API:

```text
existing Brush PLY
+
SAM2 masks
→ add identity only
```

---

## 10. Thậm chí `load_ply()` không nhận vanilla PLY trực tiếp

Nó bắt buộc PLY phải có:

```text
obj_dc_0
obj_dc_1
...
obj_dc_15
```

Code đọc thẳng:

```python
objects_dc[:, idx, 0] = plydata["obj_dc_" + str(idx)]
```

Một Brush/vanilla 3DGS PLY chưa chứa các field đó sẽ không load được bằng implementation này.

Do đó:

```text
Brush output
→ Gaussian Grouping
```

**không phải plug-and-play**.

Cần adapter hoặc implementation mới.

---

## 11. Nhưng design PLY của họ rất đáng học

Khi save:

```text
point_cloud.ply
├── x y z
├── SH
├── opacity
├── scale
├── rotation
├── obj_dc_0
├── ...
└── obj_dc_15
```

Tức identity được version cùng Gaussian.

Trong project chúng ta, tôi không khuyến nghị mutate canonical Brush PLY theo cách này.

Tốt hơn:

```text
GlobalVisualArtifact
├── visual.ply
└── checksum

GaussianObjectMembership
├── visual_checksum
├── group_ids[]
├── confidence[]
└── provenance
```

Lý do là:

```text
visual representation
≠
scene semantics
```

và chúng ta muốn giữ invariant đó.

---

## 12. Candidate Group ID cũng không nên trở thành `SceneObject.object_id`

Ví dụ Gaussian Grouping sinh:

```text
group 12
group 17
group 23
```

Human có thể quyết định:

```text
12 + 17
→ cùng một shelf
```

hoặc:

```text
23
→ actually 2 pallets
```

Do đó:

```text
Gaussian group ID
```

chỉ là machine candidate identity.

Canonical product identity phải là:

```text
SceneObject.object_id
```

sau HITL.

Flow đúng:

```text
Gaussian groups
     ↓
CandidateObject[]
     ↓
HITL #1
     ├── merge
     ├── split
     ├── ignore
     ├── rename
     └── confirm
     ↓
SceneObject[]
```

---

## 13. Open-world của Gaussian Grouping không có nghĩa Gaussian tự biết “pallet”

Đây là một nuance rất quan trọng.

Identity training chủ yếu tạo:

```text
object instance IDs
```

không phải semantic labels như:

```text
pallet
forklift
shelf
box
```

Để query bằng text, code `render_lerf_mask.py` thực hiện:

```text
render first view
      ↓
GroundingDINO + SAM
      ↓
text mask
      ↓
match text mask with predicted object IDs
      ↓
selected group IDs
```

Sau đó dùng group IDs đó cho các view khác.

Tức:

```text
semantic name
```

được gắn **sau** vào instance group.

Không nằm sẵn trong 16D identity.

---

## 14. Điều này xác nhận HITL của chúng ta vẫn cần thiết

Gaussian Grouping không loại bỏ:

```text
Human Object Confirmation
```

Nó chỉ giúp tốt hơn ở:

```text
“đám Gaussian nào cùng thuộc một physical/visual entity?”
```

Human vẫn quyết:

```text
đó là cái gì?
có cần editable không?
merge/split thế nào?
static hay movable?
collider policy nào?
```

---

## 15. Object removal của repo rất thú vị

Sau training:

```text
object ID
→ classifier
→ Gaussian probabilities
→ threshold
→ selected Gaussian mask
```

Sau đó họ còn mở rộng vùng bằng convex hull:

```text
selected Gaussians
      ↓
3D convex hull
      ↓
include points inside hull
```

rồi xóa Gaussian tương ứng.

Concept:

```text
Object Membership
→ Object Visual Extraction/Removal
```

Đây rất phù hợp với EX-SCENE decomposition.

---

## 16. Nhưng convex-hull removal không nên copy nguyên xi

Ví dụ:

```text
U-shaped shelf
```

convex hull có thể bao cả:

```text
air
box bên trong shelf
object khác đứng giữa
```

và làm:

```text
over-removal
```

Code còn dùng `scipy.spatial.Delaunay` trực tiếp mà không có robust handling cho:

```text
quá ít point
coplanar points
degenerate hull
Qhull failure
```

Trong warehouse, rất nhiều object có geometry gần planar.

Do đó:

```text
convex-hull expansion
```

chỉ nên xem là heuristic reference.

Không dùng làm canonical object extraction hay collider truth.

---

## 17. Object inpainting cũng đáng nghiên cứu, nhưng chỉ cho Visual

Repo inpaint theo:

```text
1. remove object Gaussians
2. detect unseen hole
3. LaMa 2D inpaint các view
4. dùng ảnh inpaint làm pseudo-label
5. optimize new Gaussians
```

Code còn khởi tạo Gaussian mới từ:

```text
nearest remaining Gaussians
```

rồi chỉ optimize phần mới.

---

## 18. Đây là candidate tốt cho `BackgroundCompletionBackend`

Trước đây chúng ta phân biệt:

```text
DiffusionLight inpaint
≠
background completion
```

Gaussian Grouping thì khác.

Object-removal/inpaint của repo **thực sự có liên quan tới background completion**.

Potential P1:

```text
Remove shelf
      ↓
hidden wall/floor hole
      ↓
2D completion
      ↓
multi-view Gaussian completion
```

Do đó có thể định nghĩa:

```text
BackgroundCompletionBackend
└── GaussianInpaintBackend
```

nhưng chỉ cho:

```text
visual completeness
```

không cho physical ground truth.

---

## 19. Inpaint của nó không tạo trustworthy hidden geometry

Đây là ranh giới phải giữ.

Nó tạo appearance plausible từ 2D pseudo-label.

Không có sensor evidence chứng minh:

```text
bức tường thật nằm đúng ở đây
floor thật có shape này
```

Do đó:

```text
inpainted 3DGS
```

không được trực tiếp dùng làm:

```text
collision geometry
metric geometry
physics truth
```

Architecture vẫn phải:

```text
Visual completion
≠
Geometry completion
≠
Physics
```

---

## 20. Một điểm rất hay trong code: densification bảo toàn identity

Khi Gaussian bị clone/split:

```python
new_objects_dc = self._objects_dc[selected_pts_mask]
```

Tức:

```text
Gaussian A
identity=A_group
    ↓ split
Gaussian A1 → same identity
Gaussian A2 → same identity
```

Điều này giúp grouping không bị mất trong quá trình densification.

Đây là một implementation detail rất đáng học nếu sau này ta làm identity-aware Gaussian optimization.

---

## 21. Tuy nhiên implementation hard-code quá nhiều

Ví dụ:

```cpp
NUM_OBJECTS 16
```

nằm compile-time trong CUDA.

Muốn:

```text
32D identity
```

phải sửa/recompile rasterizer.

Trong product architecture nên là:

```text
identity_dim: config
```

hoặc ít nhất backend-specific config.

Không leak:

```text
16
200
```

thành SceneIR contract.

---

## 22. `200 classes` cũng là implementation-specific

DEVA có option:

```text
short id in [0,199] for classification
```

và Gaussian Grouping default:

```text
num_classes = 200
```

Nó không phải domain rule.

Warehouse lớn có thể có:

```text
200+
```

candidate instances.

Do đó Real2Sim không nên đặt:

```text
MAX_OBJECTS = 200
```

dựa theo repo này.

---

## 23. Spatial regularization hiện tại khá tốn GPU

Default:

```text
reg3d_interval = 2
max_points      = 300000
sample_size     = 1000
```

Code gọi:

```python
torch.cdist(sample_features, features)
```

Worst configured shape:

```text
1000 × 300000 = 300,000,000 distances
```

Float32 riêng matrix này khoảng:

```text
~1.2 GB
```

chưa tính:

```text
top-k
gradients
renderer
Gaussian tensors
```

và nó có thể chạy mỗi 2 iterations.

Do đó spatial loss idea tốt, nhưng implementation không phải lựa chọn production-efficient.

Ta có thể thay bằng:

```text
precomputed kNN graph
FAISS
radius graph
PyTorch Geometric
Open3D KD-tree
```

nếu sau này implement.

---

## 24. Repo hiện cũng khá cũ về runtime

Installation khóa:

```text
Python 3.8
PyTorch 1.12.1
torchvision 0.13.1
CUDA 11.3
```

Trong khi hiện tại là 2026.

Repo không có release formal và commit cuối được audit là giữa 2024.

Do đó không nên biến nó thành core dependency của hệ thống.

---

## 25. Có một latent bug trong renderer hiện tại

Trong:

```python
gaussian_renderer/render()
```

`sh_objs` chỉ được gán ở branch:

```python
pipe.convert_SHs_python == False
```

nhưng phía dưới luôn truyền:

```python
sh_objs=sh_objs
```

Nếu bật `convert_SHs_python = True` thì có khả năng `sh_objs` chưa được define.

Tương tự path dùng `override_color` cũng không initialize rõ biến này.

Default config tránh bug đó, nhưng đây là dấu hiệu code research-oriented, không phải robust library.

---

## 26. Còn có một số robustness issue khác

Trong inpainting:

```python
mask_to_bbox()
```

giả sử mask luôn non-empty. Nếu không: `torch.where(rows)[0][[0, -1]]` sẽ fail.

Convex hull có thể fail với degenerate points như nói trên.

Config loader dùng:

```python
eval(cfgfile_string)
```

để đọc `cfg_args`.

Điều này không được phép xuất hiện trong production service với input không tin cậy.

Không có dedicated automated test suite cho Gaussian Grouping core; test code chủ yếu đến từ vendored dependencies.

---

## 27. License là caveat lớn

Root repository hiển thị: `Apache-2.0`.

Nhưng không được kết luận: “toàn bộ repo Apache → copy thoải mái”, vì bên trong có nhiều boundary khác:
- `diff-gaussian-rasterization` mang Gaussian-Splatting license: research/evaluation non-commercial.
- Vendored `Tracking-Anything-with-DEVA`: `CC BY-NC-SA 4.0`.

Do đó:

```text
DO NOT vendor entire Gaussian Grouping stack
```

Cách an toàn về engineering:

```text
paper/algorithm reference
→ independent implementation
```

---

## 28. Điểm quan trọng nhất: không nên train lại toàn bộ scene chỉ để lấy grouping

Nếu ta làm:

```text
TorWIC
   ├── Brush reconstruction
   │
   └── Gaussian Grouping reconstruction
```

thì sẽ có hai Gaussian fields:

```text
Brush coordinate/geometry
GaussianGrouping coordinate/geometry
```

rồi lại phải alignment. Đó là duplication không cần thiết. P0 không nên đi theo hướng này.

---

## 29. Architecture tốt hơn cho project của chúng ta

Nếu muốn tận dụng ý tưởng Gaussian Grouping:

```text
Brush VisualArtifact
        +
COLMAP Cameras
        +
SAM2 Persistent Masks
        │
        ▼
Gaussian Identity Lifter
        │
        ▼
GaussianObjectMembership
        │
        ▼
Candidate Objects
        │
        ▼
Human Confirmation
        │
        ▼
SceneIR
```

Trong đó `geometry/appearance của Brush` được **freeze**. Chỉ học `identity features` hoặc tính Gaussian membership.

Backend interface sạch:

```python
class GaussianObjectAssociationBackend:
    def associate(
        visual_artifact,
        camera_poses,
        masks,
    ) -> GaussianObjectMembership:
        ...
```

Output là deterministic artifact:

```text
GaussianObjectMembership
├── source_visual_checksum
├── mask_manifest_checksum
├── camera_manifest_checksum
├── groups[]
│   ├── group_id
│   ├── gaussian_indices/ref
│   └── confidence
├── backend
├── config_checksum
└── checksum
```

---

## 30. So với R2G, Gaussian Grouping nên là qualification candidate

Architecture hiện tại:

```text
SAM2
→ R2G-derived association
→ HITL
```

Đề xuất thêm đúng một qualification task:

```text
SCENE-QUAL-GG-01
Gaussian Grouping Identity-Lifting Qualification
```

Mục tiêu: Đánh giá xem per-Gaussian identity learning có cải thiện association so với SAM2 + R2G trên sequence `TorWIC Aisle_CW` hay không.

### Acceptance cho spike:

```text
PASS only if:
1. Can consume our real artifacts (Brush PLY + SAM2 masks).
2. Does not require a second global reconstruction.
3. Produces deterministic group-membership artifact.
4. Improves measurable cross-view object consistency or reduces fragmentation/leakage.
5. Runtime/VRAM is acceptable.
6. No GT/evaluation leakage.
```

Nếu fail: retain SAM2 + R2G, giữ Gaussian Grouping ở mức reference.

---

## 31. Code reuse matrix

| Component                           | Giá trị với Real2Sim       | Quyết định                   |
| ----------------------------------- | -------------------------- | ---------------------------- |
| Identity Encoding concept           | Rất cao                    | **ADAPT concept**            |
| Per-Gaussian object feature         | Rất cao                    | **ADAPT concept**            |
| `loss_cls_3d()` spatial consistency | Cao                        | **REIMPLEMENT**              |
| Object feature persistence in PLY   | Trung bình                 | **REFERENCE**                |
| Custom CUDA identity rasterizer     | Cao kỹ thuật, cao coupling | **DO NOT VENDOR P0**         |
| SAM+DEVA mask pipeline              | Thấp với stack hiện tại    | **DO NOT USE**               |
| Grounded-SAM → group matching       | Trung bình                 | **REFERENCE P1**             |
| Object removal                      | Cao cho visual editing     | **REFERENCE/ADAPT**          |
| Convex-hull expansion               | Thấp–Trung bình            | **HEURISTIC ONLY**           |
| Gaussian inpainting                 | Cao P1 visual              | **REFERENCE P1**             |
| LaMa pipeline                       | P1                         | Separate qualification       |
| LERF-mask evaluation                | Trung bình                 | **REFERENCE metrics**        |
| Full training repo                  | Thấp                       | **DO NOT INTEGRATE AS CORE** |

---

## 32. Classification chính thức sau audit

```text
lkeab/gaussian-grouping

Tier-0 Algorithm Reference
for:
2D mask → persistent per-Gaussian object identity

Tier-1 Qualification Candidate
for:
EX-SCENE object association/decomposition (SCENE-QUAL-GG-01)

P1 Reference
for:
visual object removal
background visual completion
open-vocabulary group selection

NOT:
primary reconstruction backend
geometry backend
collider backend
Isaac backend
canonical SceneIR implementation
```

---

## 33. Ảnh hưởng đến architecture hiện tại

Sau audit này architecture **không cần đổi**:

```text
RGB
 ↓
COLMAP
 ↓
Brush ──────────────── Global Visual
 ↓
OpenMVS ────────────── Global Geometry
                          │
                          ▼
                       EX-SCENE
                          │
                        SAM2
                          │
                    Object Masks
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       R2G-derived                GG-style
       Association               Qualification
              │                       │
              └───────────┬───────────┘
                          ▼
                  Candidate Objects
                          │
                          ▼
                 HITL Confirmation
                          │
                          ▼
                       SceneIR
```

---

## 34. Bảng phân bố vai trò so với các repo đã audit

| Repo                  | Vai trò nổi bật nhất                        |
| --------------------- | ------------------------------------------- |
| OpenReal2Sim          | Geometry/physics → USD/Isaac                |
| R2G                   | Multi-view/object association               |
| VR-Robo               | Isaac ↔ Gaussian runtime sync               |
| SuperSplat            | Human visual editor                         |
| splat-transform       | Low-level Gaussian transforms               |
| DISCOVERSE            | Visual ↔ physics sync + remote rendering    |
| DISCOVERSE-Real2Sim   | Mesh → object-level visual GS               |
| **Gaussian Grouping** | **Per-Gaussian persistent object identity** |

---

## Audit queue

```text
1. OpenReal2Sim                  ✅
2. R2G                           ✅
3. VR-Robo                       ✅
4. SuperSplat                    ✅
4.5 splat-transform              ✅
5. DISCOVERSE + Real2Sim         ✅
6. Gaussian Grouping             ✅
7. Re3Sim                        ← NEXT
```
