# Audit #7 — `InternRobotics/Re3Sim`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`InternRobotics/Re3Sim`](https://github.com/InternRobotics/Re3Sim) (branch `master`, commit `681da6f5d842f0de6c573a077926fe3722924708`, 2026-03-16, ICRA 2026)  
> **License:** CC BY-NC 4.0 (root README) / Gaussian-Splatting License (submodule `gaussian_splatting`, research/evaluation non-commercial) / MIT (`policies/act_plus_plus`)  
> **Ngày audit:** 2026-09-25  
> **Trạng thái:** Hoàn tất Audit #7 (7/7 trong Audit Queue — Hoàn tất chuỗi audit)

---

## Kết luận trước

> **Re3Sim là repo gần architecture tổng thể của Real2Sim Studio nhất trong số các repo chúng ta đã audit, xét riêng đoạn `real RGB → reconstruction → 3DGS visual + mesh geometry → coordinate alignment → USD/collider → Isaac Sim`.**

Nó gần như xác nhận độc lập architecture chúng ta đã chốt:

```text
                 Real RGB
                    │
                    ▼
                  COLMAP
                /        \
               /          \
              ▼            ▼
          3DGS Visual    OpenMVS Mesh
              │            │
              │            ▼
              │        USD + Collision
              │            │
              └─────┬──────┘
                    │
          common coordinate frame
                    │
                    ▼
                 Isaac Sim
```

Điểm rất đáng chú ý là Re3Sim **không cố dùng 3DGS làm physics**. Nó giữ:

```text
3DGS = appearance

Mesh/USD = geometry + collision
```

Đây chính là invariant cốt lõi của chúng ta:

```text
Visual ≠ Geometry ≠ Physics
```

---

## 1. `reconstruct.py` gần như là prototype của EX-REC + đầu EX-SIM của chúng ta

File quan trọng nhất:

```text
re3sim/scripts/reconstruct.py
```

Pipeline code thực tế là:

```text
images/
   │
   ▼
PyCOLMAP
├── SIFT
├── sequential matching
└── incremental mapping
   │
   ├────────────────────────┐
   │                        │
   ▼                        ▼
3D Gaussian Splatting    COLMAP dense prep
   │                        │
   │                        ▼
   │                     OpenMVS
   │                  InterfaceCOLMAP
   │                        ↓
   │                DensifyPointCloud
   │                        ↓
   │                 ReconstructMesh
   │                        ↓
   │                    RefineMesh
   │                        ↓
   │                optional TextureMesh
   │                        │
   ▼                        ▼
3DGS PLY                 Mesh PLY
   │                        │
   ▼                        ▼
GS → marker            Mesh → marker
alignment              alignment
   │                        │
   └──────────┬─────────────┘
              ▼
        Mesh → USD
              ↓
       collision setup
              ↓
          Isaac Sim
```

Khác biệt chủ yếu là Re3Sim dùng vanilla Graphdeco 3DGS, trong khi Real2Sim Studio dùng Brush. Vì vậy không cần đổi Brush.

---

## 2. Re3Sim xác nhận quyết định dùng chung COLMAP cho hai branch là đúng

Một pattern rất tốt của Re3Sim là:

```text
               COLMAP
              /      \
             /        \
        3DGS           OpenMVS
       Visual          Geometry
```

Không phải hai pipeline chạy pose độc lập. Đây chính xác là thiết kế hiện tại:

```text
REC-03 COLMAP
      │
      ├── REC-04 Brush
      │
      └── REC-05 OpenMVS
```

Re3Sim là **strong external implementation reference** củng cố thiết kế EX-REC.

---

## 3. Phần COLMAP orchestration lấy được khá nhiều pattern

Trong `reconstruct.py`:

```python
extract_features(...)
feature_matching(...)
run_colmap(...)
```

sử dụng:

```text
pycolmap.extract_features
pycolmap.match_sequential
pycolmap.incremental_mapping
```

Và tự chọn vocabulary tree theo số ảnh:
- `< 1,000` images: `32K` vocab
- `< 10,000` images: `256K` vocab
- `>= 10,000` images: `1M` vocab

Đây là useful reference cho `REC-03`. Tuy nhiên không copy nguyên xi vì Real2Sim Studio có yêu cầu chặt chẽ hơn về artifact contract, checksum, log và determinism.

---

## 4. OpenMVS pipeline của Re3Sim gần như trùng với REC-05

Nó gọi trực tiếp:

```text
InterfaceCOLMAP
    ↓
DensifyPointCloud
    ↓
ReconstructMesh
    ↓
RefineMesh
    ↓
TextureMesh        (optional)
```

Tham số cụ thể:

```text
ReconstructMesh scene_dense.mvs -p scene_dense.ply
RefineMesh scene_dense.mvs -m scene_dense_mesh.ply -o scene_dense_mesh_refine.mvs --scales 1 --max-face-area 16
```

Đây là code donor/reference rất trực tiếp (**`ADAPT-HIGH`**) cho `REC-05 — OpenMVS Geometry`.

---

## 5. Re3Sim còn làm TextureMesh

Tùy chọn `--texture` chạy `TextureMesh` sinh `scene_dense_mesh_refine_texture.*`.
Đối với chúng ta texture mesh không phải P0 bắt buộc vì Brush chịu trách nhiệm visual fidelity, OpenMVS phục vụ geometry/collider. Tuy nhiên textured mesh hữu ích cho debug, geometry viewer và fallback rendering nên giữ là optional derivative.

---

## 6. Align Visual và Geometry độc lập vào một frame chung

Đây là phần giá trị nhất của repo:

```text
gs_to_marker.npy
mesh_to_marker.npy
```

Cấu trúc:

```text
                    Canonical Frame
                         marker
                       /   |   \
                      /    |    \
                     ▼     ▼     ▼
                  Visual Geometry Isaac
```

Thông qua `FrameTools` (`re3sim/background/__init__.py`), Visual, Geometry và Isaac Sim đều neo vào chung một hệ quy chiếu chuẩn. Đúng 100% tinh thần **Canonical Coordinate System** của dự án.

---

## 7. `FrameTools` — Module frame graph đáng tham khảo

File: `re3sim/utils/frame_tools.py` gồm:

```python
add_frame_transform_relative_to()
get_frame_transform_relative_to()
change_base_frame()
get_frame_translation()
get_frame_rotation()
get_frame_scale()
```

Quản lý frame graph có scale, rotation, translation. Lấy scale bằng determinant của ma trận. Rất phù hợp với `CanonicalTransform` của Real2Sim Studio.

---

## 8. Giải similarity alignment từ camera trajectories

Re3Sim cung cấp:

```python
get_transform_between_two_frames(...)
get_transform_between_two_frames2(...)
```

Ước tính similarity transform $p_B = s R p_A + t$ giữa 2 tập camera poses tương ứng. Đây chính xác là dạng transformation cần thiết để chuyển từ SfM coordinate sang metric coordinate.

---

## 9. Điểm khác biệt về metric reference với TorWIC

Re3Sim dùng ChArUco marker (`DICT_6X6_250`, `CharucoBoard`) trong ảnh thật (`real-deployment/utils/compute_transform_to_marker_aruco.py`).

TorWIC của chúng ta đã có:
- Calibration camera
- Mây điểm LiDAR thực tế
- Geometry đã đăng ký/fused

Do đó, P0 của chúng ta **không phụ thuộc ChArUco marker** trong kho bãi. Re3Sim cung cấp:
- **HOW** to represent coordinate alignment (Frame graph, similarity transform)
chứ không phải **WHICH** metric anchor to use.

---

## 10. Abstraction đúng cho REC-06

```text
MetricCanonicalizer
├── RegisteredLiDARMetricBackend       # P0 TorWIC
├── CalibrationMetricBackend
├── FiducialMetricBackend              # optional / P1
└── ExplicitScaleBackend               # future
```

Re3Sim đóng góp mạnh cho `FiducialMetricBackend` và frame graph architecture.

---

## 11. `obj_to_usd.py` — Code donor trực tiếp cho EX-SIM

File: `re3sim/utils/usd/obj_to_usd.py`:

```text
Mesh
 ↓
IsaacLab MeshConverter
 ↓
USD
 ↓
unit normalization
 ↓
collision setup
```

Sử dụng trực tiếp `MeshConverter` và `MeshConverterCfg` từ IsaacLab:
- Cấu hình collision modes: `convexDecomposition`, `convexHull`, `meshSimplification`, `none`.
- Thiết lập chuẩn USD stage: `Z-up`, `metersPerUnit = 1.0`, `kilogramsPerUnit = 1.0`.
- Thêm `CollisionPropertiesCfg(collision_enabled=True)`.

Rất phù hợp cho `SIM-02` / `SIM-05`.

---

## 12. So sánh Re3Sim và OpenReal2Sim cho EX-SIM

```text
OpenReal2Sim = Primary architecture/code donor cho USD/physics
Re3Sim       = Second independent implementation reference + IsaacLab MeshConverter
```

Cả hai repo bổ trợ cho nhau, giảm thiểu rủi ro triển khai cho `EX-SIM`.

---

## 13. USD và GS là hai asset song song

Config Re3Sim:

```yaml
background:
  usd_path: usd/1024/scene_dense_mesh_refine_texture.usd
  gs_path: gs-data/1024
```

Ánh xạ trực tiếp vào `SceneIR`:
```text
Environment / SceneObject
├── visual_ref    (3DGS PLY / SOG)
├── geometry_ref  (OpenMVS Mesh OBJ/GLB)
├── collider_ref  (USD Physics / Colliders)
└── transform     (Canonical Matrix)
```

Không gộp thành 1 định dạng duy nhất, giữ nguyên tính độc lập để hỗ trợ versioning và human-in-the-loop editing.

---

## 14. Compositing Strategy (GS + Isaac Hybrid Rendering)

Isaac render robot và dynamic objects + Semantic mask (`ground`, `table`, `object`). Re3Sim đồng thời render GS background.
Sau đó composite theo semantic mask:

```python
mixed_image = np.where(mix_mask[..., None], gaussian_rendered_background, sim_only_image)
```

Kết quả: Environment photorealistic từ 3DGS + Vật thể động và robot chính xác về mặt vật lý từ Isaac.
- **P0 Studio:** Chưa cần live pixel compositing này (P0 tập trung scene editing, collision validation, native MP4 replay).
- **P1/P2 Robotics Policy:** Cực kỳ giá trị cho synthetic photorealistic policy training.

---

## 15. Semantic Segmentation từ Isaac Camera

Camera setup trong Isaac:

```python
camera.add_semantic_segmentation_to_frame()
camera.add_distance_to_image_plane_to_frame()
camera.add_motion_vectors_to_frame()
```

Tham chiếu hữu ích cho việc xuất structured evidence artifacts phục vụ review/audit.

---

## 16. Phân biệt Replay MP4

Re3Sim dùng `cv2.VideoWriter` / `imageio` lưu lại frames rollout sang MP4, không dùng `omni.kit.capture.viewport`.
Do đó, baseline P0 của chúng ta **không đổi**:
- Native Omniverse MP4 capture là đường chính (`SIM-06`).
- Frame capture $\rightarrow$ FFmpeg / OpenCV chỉ là fallback khi headless gặp lỗi.

---

## 17. Real-robot Calibration Stack (P1/P2)

Thư mục `real-deployment/calibration/` chứa:
- Camera intrinsics & hand-eye calibration (`cv2.calibrateHandEye` Tsai method)
- ChArUco / RealSense setup
- Camera $\leftrightarrow$ gripper, marker $\leftrightarrow$ robot base

Rất hữu ích khi dự án mở rộng sang triển khai robot thật ở nhà kho vật lý (P1/P2).

---

## 18. Các vấn đề rủi ro & Bug tìm thấy trong code Re3Sim

Khi audit mã nguồn thực tế, phát hiện một số điểm yếu cần tránh:

1. **Subprocess không kiểm tra return code (`check=True` bị bỏ qua)**:
   Trong `reconstruct.py`, code gọi `subprocess.run([...])` rồi tự động ghi `progress.json` là `"mvs": true` ngay cả khi OpenMVS thất bại. Real2Sim Studio bắt buộc phải có validation exit code, verify artifact checksum trước khi chuyển stage.
2. **Bug CLI trong USD handoff**:
   File `obj_to_usd.py` định nghĩa flag `--collision-approximation` (dấu gạch nối `-`), nhưng `reconstruct.py` lại gọi `--collision_approximation` (dấu gạch dưới `_`). Vì `argparse` không coi 2 flag này là một, lệnh có thể crash ngay tại bước cuối.
3. **Hardcode `sparse/0`**:
   Code mặc định lấy `sparse/0`, nhưng khi scene phân mảnh, COLMAP có thể sinh nhiều sub-models (`sparse/1`, `sparse/2`). Real2Sim cần cơ chế chọn largest valid model hoặc fail-fast rõ ràng.
4. **Vocab-tree downloader thiếu kiểm tra**:
   Dùng `requests.get()` ghi file thẳng mà không có timeout, `raise_for_status()`, hay verify checksum.
5. **Class `ForegroundGSRenderer` bị thiếu**:
   Trong `re3sim/background/__init__.py` có import `ForegroundGSRenderer` trong khối `try/except`, nhưng không có file cài đặt trong repo.

---

## 19. Phân tích Bản quyền (License Guardrails)

- **Root License**: `CC BY-NC 4.0` (ghi trong README). Mang tính phi thương mại.
- **Submodule `gaussian_splatting`**: Inria Non-Commercial License.
- **Submodule `policies/act_plus_plus`**: MIT.

**Kết luận:** Tuyệt đối **không vendor toàn bộ repository Re3Sim** vào codebase thương mại hóa. Chỉ **ADAPT / REIMPLEMENT** các pattern thuật toán (orchestration commands, frame tools, `MeshConverterCfg`) dưới dạng code do team tự viết và kiểm soát.

---

## 20. Đề xuất 2 Qualification Spikes từ Re3Sim

1. **`SIM-QUAL-RE3-01` — OpenMVS Mesh $\rightarrow$ Isaac USD Qualification**:
   - Chạy thử nghiệm chuyển đổi mesh thực tế từ TorWIC OpenMVS sang OpenUSD qua IsaacLab `MeshConverter`.
   - Đánh giá 3 chế độ: `convexDecomposition`, `convexHull`, `meshSimplification`.
   - Đo lường thời gian convert, số poly, độ ổn định va chạm và hiện tượng cản trở di chuyển của AMR.
2. **`REC-QUAL-FRAME-01` — Canonical Transform Qualification (`REC-06`)**:
   - Dùng kiến trúc `FrameTools` để chuẩn hóa và chứng minh: Brush Visual, OpenMVS Geometry và Registered LiDAR sau chuẩn hóa đều có chung gốc tọa độ, hệ trục và metric scale ($1.0 = 1\text{m}$).

---

## 21. Code Reuse Matrix — Re3Sim

| Component                         |      Giá trị | Quyết định                  |
| --------------------------------- | -----------: | --------------------------- |
| `reconstruct.py` pipeline design  |      Rất cao | **ADAPT/REFERENCE-HIGH**    |
| PyCOLMAP orchestration            |          Cao | **ADAPT selective**         |
| OpenMVS command orchestration     |      Rất cao | **ADAPT-HIGH**              |
| Stage checkpoint idea             |          Cao | **REIMPLEMENT properly**    |
| `FrameTools`                      |      Rất cao | **REFERENCE/ADAPT concept** |
| similarity transform estimation   |          Cao | **REFERENCE/REIMPLEMENT**   |
| marker alignment                  |   Cao cho P1 | **OPTIONAL BACKEND**        |
| `obj_to_usd.py`                   |      Rất cao | **ADAPT-HIGH concept**      |
| IsaacLab MeshConverter config     |      Rất cao | **ADAPT-HIGH**              |
| collision approximation selection |          Cao | **ADAPT-HIGH**              |
| GS↔mesh↔Isaac frame binding       |  **Rất cao** | **ADAPT-HIGH architecture** |
| hybrid GS+Isaac rendering         |          Cao | **P1 REFERENCE-HIGH**       |
| semantic masking/composition      |          Cao | **P1 ADAPT**                |
| hand-eye calibration              |   Cao future | **P1/P2 REFERENCE**         |
| AddedAsset surface alignment      |   Trung bình | **P1 REFERENCE**            |
| Graphdeco renderer                |      Low fit | **DO NOT VENDOR**           |
| vanilla GS training               |      Low fit | **DO NOT REPLACE BRUSH**    |
| local DearPyGui                   |          Low | **DO NOT USE**              |
| ACT policy training               | Out of scope | **IGNORE**                  |

---

## 22. Classification chính thức

```text
InternRobotics/Re3Sim

Tier-0 SYSTEM ARCHITECTURE REFERENCE
— Real RGB → COLMAP → 3DGS Visual + OpenMVS Geometry → common metric frame → USD/Collision → Isaac

Tier-1 EX-REC Donor / Reference:
- PyCOLMAP orchestration
- OpenMVS orchestration (REC-05 ADAPT-HIGH)
- Metric/similarity alignment & frame graph (REC-06)

Tier-1 EX-SIM Donor / Reference:
- IsaacLab MeshConverter (SIM-05 ADAPT-HIGH)
- USD metric stage
- Collision approximation (SIM-02 ADAPT-HIGH)

P1 Reference:
- GS + Isaac hybrid rendering
- Semantic compositing
- Real robot calibration & added asset alignment

DO NOT vendor wholesale (CC BY-NC root, Graphdeco non-commercial subtree).
```

---

## 23. Hoàn tất chuỗi Audit (Audit Queue Complete)

```text
1. OpenReal2Sim                  ✅
2. R2G                           ✅
3. VR-Robo                       ✅
4. SuperSplat                    ✅
4.5 splat-transform              ✅
5. DISCOVERSE + Real2Sim         ✅
6. Gaussian Grouping             ✅
7. Re3Sim                        ✅
```
