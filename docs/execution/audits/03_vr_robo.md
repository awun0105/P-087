# Audit #3 — `zst1406217/VR-Robo`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`zst1406217/VR-Robo`](https://github.com/zst1406217/VR-Robo)  
> **Commit audit:** `0d519b534158b5abff9246bd3f35a2747f926576` (2025-06-20)  
> **License:** MIT (Top-level) / Inria non-commercial & Gaussian-Splatting License (Submodules/Renderer)  
> **Ngày audit:** 2026-09-24  
> **Trạng thái:** Hoàn tất Audit #3 (3/7 trong Audit Queue)

---

## Kết luận trước

> **VR-Robo là repo mạnh nhất trong 3 repo đã audit về boundary `3DGS visual ↔ IsaacLab physics/runtime`.**  
> Nó không mạnh về reconstruction pipeline, object decomposition hay USD generation. Giá trị lớn nhất là cách **tách visual renderer khỏi physics simulator nhưng vẫn đồng bộ camera/object pose giữa hai bên**.

Phân bố giá trị:

| Track      |                   Giá trị từ VR-Robo |
| ---------- | -----------------------------------: |
| EX-REC     |                                 Thấp |
| EX-SCENE   |                      Thấp–Trung bình |
| **EX-SIM** |                          **Rất cao** |
| EX-PRODUCT | Thấp, nhưng có video/replay patterns |

Docs hiện tại đánh dấu VR-Robo là architecture reference cho simulator boundary. Sau audit này, nâng nó thành **Tier-0 Integration Donor cho EX-SIM**, nhưng chỉ lấy có chọn lọc và tuân thủ chặt chẽ license guardrails.

---

## 1. Architecture thực sự của VR-Robo

VR-Robo chạy **hai environment riêng**:

```text
┌───────────────────────────┐
│ Gaussian Renderer Process │
│ vrrobo_renderer           │
│                           │
│ 3DGS scene                │
│ GPU renderer              │
└────────────┬──────────────┘
             │
      camera/object pose
             │
             ↕
        RPC + TCP
             │
             ▼
┌───────────────────────────┐
│ Isaac Lab Process         │
│ vrrobo_isaaclab           │
│                           │
│ USD physics scene         │
│ robot                     │
│ collision                 │
│ locomotion                │
└───────────────────────────┘
```

README yêu cầu:

```text
terminal 1:
python render_server.py

terminal 2:
python scripts/rsl_rl/play_gs.py --task go2_gs_play
```

Tức là họ đã thực hiện rất rõ nguyên tắc:

```text
Visual Representation
≠
Physics Representation
```

hoàn toàn khớp với invariant của dự án.

---

## 2. Phần đáng học nhất của VR-Robo: Pose Synchronization

Trong Isaac:
- `robot pose`
- `camera pose`
- `dynamic object poses`

được lấy ra, sau đó gửi sang Gaussian renderer:

```text
Isaac
│
├── camera_position
├── camera_rotation
├── object_position
└── ...
        ↓
3DGS Renderer
        ↓
RGB image
        ↓
Isaac / policy
```

Cụ thể nằm ở `vrrobo_isaaclab/.../tasks/vrrobo/mdp/observations.py`, class `gs_image_feature`. Nó lấy robot root position, robot quaternion, camera local offset để tính camera world pose và gọi:

```python
self.conn.root.render(
    camera_pos_r,
    camera_rot_r,
    red_cone,
    green_cone,
    blue_cone,
)
```

Đây là implementation thực tế của luồng: `Physics state → Visual renderer state`.

---

## 3. Giải quyết vấn đề cốt lõi: 3DGS không cần nhét vào USD

Không cần cố ép 3DGS vào USD rồi bắt Isaac Sim render Gaussian. VR-Robo dùng mô hình:

```text
                 SceneIR
                /       \
               /         \
              ▼           ▼
        Visual Scene   Physics Scene
           3DGS          USD/Mesh
              │           │
              │           ▼
              │        Isaac Sim
              │           │
              └──── pose ─┘
                    │
                    ▼
             GS Render Worker
```

Điều này rất khớp với kiến trúc của chúng ta:
- Web: visual preview bằng 3DGS
- Isaac: chạy physics trên mesh + collider
- Khi cần photorealistic rendering: đồng bộ pose sang renderer worker độc lập

---

## 4. `render_server.py`: Logic biến đổi Gaussian

File `vrrobo_renderer/render_server.py` có 4 phần đáng chú ý:

### A. Load nhiều Gaussian asset
Load `scene`, `red object`, `green object`, `blue object` thành các `GaussianModel` riêng. Rất giống mô hình `EnvironmentVisual + SceneObjectVisual[]` trong `SceneIR`.

### B. Transform Gaussian đầy đủ thuộc tính
Hàm `transform_gaussians(gaussians, T, scale)` cập nhật:
- Gaussian XYZ
- Gaussian scale
- Gaussian quaternion rotation
- Spherical Harmonics (SH) coefficients qua `transform_shs()` (Wigner-D rotation cho SH degree 1–3).

Đây là phần toán rất giá trị nếu người dùng xoay/dịch chuyển `SceneObject` và ta muốn visual Gaussian xoay theo tương ứng.

---

## 5. Object Gaussian Filtering

Hàm `filter_gaussians_within_bounding_box()`:
- Đưa centers về bbox local frame
- Kiểm tra inside/outside
- Lọc tất cả thuộc tính: `_xyz`, `_features_dc`, `_features_rest`, `_scaling`, `_rotation`, `_opacity`.

Có thể dùng làm utility phụ trợ để trích xuất visual subset từ global Brush Gaussian sau khi có candidate object bounding volume.

---

## 6. Hạn chế của Renderer VR-Robo

1. **Hard-coded 3 objects**: Thiết kế chỉ phục vụ 3 object `red`, `green`, `blue`, độ phân giải `320×180`, FOV và camera near/far cố định.
2. **Dynamic sync chỉ có translation**: Trong vòng lặp render, họ chỉ cộng/trừ `object_position` (translation). Real2Sim Studio cần full SE(3)/similarity transform (rotation + scale).
3. Cần refactor concept thành:
   ```python
   VisualSceneRenderer(
       environment: VisualArtifact,
       objects: list[VisualSceneObject],
       camera: CameraSpec,
   )
   ```

---

## 7. Camera Synchronization & Coordinate Convention

Isaac side có `convert_camera_frame_orientation_convention(camera_rot_r, "world", "ros")`.

Trong dự án của chúng ta: Không copy ma trận hard-code. Phải map qua canonical contract:
```text
Canonical Coordinate System → IsaacAdapter → RendererAdapter
```

---

## 8. Physical USD Scene Loading trong Isaac

File `.../config/go2/go2_env_cfg.py` load scene qua IsaacLab:

```python
sim_utils.UsdFileCfg(
    usd_path="./exts/scene_data/scene.usd",
    rigid_props=...,
    mass_props=...,
    collision_props=...,
)
```

rồi spawn robot, scene, walls, dynamic objects. Đây là implementation reference trực tiếp cho `SIM-06`:
```text
CandidatePackage → IsaacLab Scene → Robot → Physics → Collision
```

---

## 9. VR-Robo KHÔNG giải quyết `SceneIR → candidate.usd`

VR-Robo không có pipeline biến mesh thành USD hay authoring collider. Họ dùng các file USD dựng sẵn (`scene.usd`, `red.usd`, ...).

Do đó: **`SIM-05 Candidate Build` vẫn lấy `OpenReal2Sim` làm donor chính**, không lấy VR-Robo.

---

## 10. Sự kết hợp hoàn hảo giữa OpenReal2Sim và VR-Robo

```text
SceneIR
   ↓
OpenReal2Sim-derived patterns
   ↓
Collider / Physics / USD
   ↓
CandidatePackage
   ↓
VR-Robo-derived runtime pattern
   ↓
Isaac Sim validation
```

- **OpenReal2Sim**: Cách **BUILD** simulation asset.
- **VR-Robo**: Cách **RUN** simulation asset cùng photorealistic GS visual.

---

## 11. RL Stack: Không cần thiết cho P0

Bỏ qua toàn bộ stack RSL-RL trong `exts/rsl_rl/`: PPO, actor-critic, curriculum, rough terrain, reward shaping. P0 chỉ cần robot spawn, collision checking, Start–Goal navigation validation.

---

## 12. Video Recording trong Simulation: Fallback đã có

File `play_gs.py` và `train_gs.py` dùng:

```python
env = gym.make(..., render_mode="rgb_array")
env = gym.wrappers.RecordVideo(env, video_folder=..., video_length=...)
```

Cung cấp đường fallback chắc chắn cho replay trong `SIM-06`:
- **Primary**: Native Isaac/Omniverse viewport capture (`omni.kit.capture.viewport`).
- **Fallback**: IsaacLab Gym `RecordVideo` wrapper.

---

## 13. Network IPC: Chỉ học ý tưởng, không copy implementation

VR-Robo dùng RPyC (`:18861`) và raw TCP (`:12345`) với `pickle.dumps()` / `pickle.loads()`, bật `allow_pickle = True`.

**Tuyệt đối không dùng cho production**: Lỗ hổng bảo mật nghiêm trọng. Dự án dùng process-local IPC, shared memory hoặc artifact exchange; không expose pickle RPC ra network.

---

## 14. License: Caveat LỚN nhất của VR-Robo

- Top-level `VR-Robo`: **MIT**.
- Renderer (`render_server.py`, `gaussian_model.py`, `diff-plane-rasterization`): **Inria Non-Commercial / Research License**.

**Nguyên tắc**:
- Không copy nguyên source code renderer Inria-derived vào core thương mại hóa.
- Code phía Isaac (`vrrobo_isaaclab`) dựa trên IsaacLab có license permissive, có thể adapt an toàn.
- Phần toán `transform_gaussians()` và `transform_shs()` chỉ nên coi là **REFERENCE / Algorithm study**, tự viết lại hoặc dùng backend có license phù hợp.

---

## 15. Code Reuse Matrix cho VR-Robo

| VR-Robo component                        | Real2Sim phần tương ứng                                    | Quyết định                                          |
| ---------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------- |
| IsaacLab startup & `UsdFileCfg`          | `SIM-01`, `SIM-06`                                         | **ADAPT-HIGH**                                      |
| Robot spawn, sensors & stepping loop     | `SIM-06`                                                   | **ADAPT-HIGH**                                      |
| Gym `RecordVideo` wrapper                | `SIM-06` replay fallback                                   | **ADAPT-HIGH**                                      |
| Visual/Physics process separation        | System architecture                                        | **ADAPT-HIGH**                                      |
| Camera/object pose synchronization       | Visual ↔ Simulation bridge                                 | **ADAPT-HIGH** (viết lại adapter)                   |
| Worker process boundary                  | `SIM-09` worker entrypoint                                 | **ADAPT**                                           |
| `transform_gaussians()` & SH rotation    | SceneObject visual transform                               | **REFERENCE / Algorithm study** (do Inria license) |
| `filter_gaussians_within_bounding_box()` | Visual subset extraction                                   | **REFERENCE**                                       |
| RPyC + TCP pickle network                | IPC                                                        | **DO NOT USE** (security)                           |
| RSL-RL / PPO training stack              | —                                                          | **OUT OF P0 SCOPE**                                 |
| Inria-derived Gaussian renderer source   | —                                                          | **DO NOT COPY DIRECTLY** (license)                  |

---

## 16. Quyết định phân loại sau Audit #3

```text
zst1406217/VR-Robo

Tier-0 Integration Donor — EX-SIM (IsaacLab scene/robot runtime, simulation stepping loop, video replay fallback)
Tier-0 Architecture Reference — Visual/Physics process separation & pose synchronization
Selective Code Donor — SIM-01, SIM-06, SIM-09
Gaussian Renderer — REFERENCE ONLY (due to Inria non-commercial license)
```

---

## 17. Bảng tổng hợp sau 3 audit (OpenReal2Sim, R2G, VR-Robo)

| Capability                 |  OpenReal2Sim |           R2G |       VR-Robo | Nguồn ưu tiên hiện tại          |
| -------------------------- | ------------: | ------------: | ------------: | ------------------------------- |
| Raw reconstruction         |           Med |           Med |           Low | COLMAP / Brush / OpenMVS        |
| Object segmentation        |           Med |      **High** |           Low | SAM2                            |
| 2D→3D association          |           Low | **Very High** |           Low | **R2G-derived (SAMPro3D)**      |
| Object decomposition       |           Med | **Very High** |           Low | **R2G-derived**                 |
| Object Gaussian            |           Low |      **High** |           Med | R2G fallback                    |
| Background completion      |      **High** |           Low |           Low | OpenReal2Sim P1                 |
| Collider authoring         |      **High** |           Low |           Low | OpenReal2Sim + Trimesh          |
| USD build                  | **Very High** |          None |           Low | **OpenReal2Sim-derived**        |
| Isaac scene runtime        |          High |          None | **Very High** | **VR-Robo-derived**             |
| Robot spawn/run            |          High |          None | **Very High** | **VR-Robo-derived**             |
| GS ↔ Isaac synchronization |           Low |          None | **Very High** | **VR-Robo pattern**             |
| Simulation video           |           Med |          None |      **High** | Isaac native + VR-Robo fallback |
| Web editor                 |          None |          None |          None | Kế hoạch: SuperSplat            |

Audit tiếp theo: **#4 SuperSplat** (trọng tâm: EX-PRODUCT Web Studio & 3D Viewer).
