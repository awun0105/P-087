# Audit #10 — Phương pháp cho pipeline v2 (scene theo vật, USD lai cho Isaac)

> **Mục đích:** tìm phương pháp lấp các khoảng trống của ADR 0007: ghép theo vật, vá nền khi
> xoá/di chuyển vật, thêm vật, nhãn từ Isaac, thuộc tính vật lý, mesh/collider, xuất Isaac.
> **Nguồn:** 27 repo trong `private/` (bản clone cục bộ) + tài liệu Isaac Sim/SimReady/3DGRUT.
> **Ngày audit:** 2026-09-30 · **Người audit:** EX-REC (Tech Lead) · **Liên quan:** ADR 0007, ADR 0008,
> audit #6 (Gaussian Grouping), #7 (Re3Sim), #4 (SuperSplat).
>
> Nhãn bằng chứng theo AGENTS.md: **VERIFIED** (đọc code/chạy lệnh), **INFERENCE**, **UNKNOWN**.

## 1. Isaac Sim thực sự nhận gì

| Lớp | Yêu cầu | Bằng chứng |
|---|---|---|
| Vỏ scene | OpenUSD; OBJ/FBX/STL/glTF, URDF/MJCF chuyển sang USD khi import; `.usdz` tham chiếu từ stage `.usd/.usda`, không làm stage gốc rồi thêm asset | Tài liệu importer; NuRec docs 6.0 |
| Hình ảnh | Mesh + vật liệu **hoặc** Gaussian (NuRec / `ParticleField3DGaussianSplat`, Isaac ≥ 5.0); ParticleField được khuyến nghị cho asset mới; PLY → USD bằng 3DGRUT (Apache-2.0) | Blog NVIDIA smartphone→Isaac; NuRec docs; forum NVIDIA; repo 3DGRUT |
| Va chạm | Gaussian **không** có collision; cần `UsdPhysics` collider. Triangle mesh chỉ cho vật tĩnh; rigid body động dùng convex decomposition hoặc SDF | NuRec docs; forum NVIDIA (thông báo `PhysicsUSD: Parse collision …`) |
| Vật lý | RigidBody ở prim gốc, Mass (kg), Physics Material (ma sát, restitution, mật độ), đơn vị mét/kg | SimReady physics best practices |
| Nhãn | `UsdSemantics.LabelsAPI` (Isaac ≥ 5.0), `add_labels(prim, ["pallet"], taxonomy="class")` | Isaac Lab `sim.utils`; Replicator |
| Dẫn đường | Occupancy Map chỉ thấy hình học bật collision | Isaac omap docs |
| LiDAR | Có trúng Gaussian không — tài liệu chính thức không nói | **UNKNOWN** (nguồn phụ nói có, kèm điểm ma từ floater) |

## 2. Repo cục bộ → khoảng trống

| Khoảng trống | Repo (giấy phép) | Phần dùng được | Bằng chứng |
|---|---|---|---|
| Ghép Gaussian theo vật | Pipeline hiện có — SAMPro3D | `consolidate.segment` đã tính chỉ số Gaussian của từng vật (trên tâm Gaussian hệ mét đã crop) nhưng chỉ giữ hộp | VERIFIED (`src/services/scene/sampro3d/consolidate.py`, `scene_extraction.py`) |
| | Gaussian Grouping (Apache-2.0; DEVA CC BY-NC-SA; rasterizer Inria) | Identity encoding theo Gaussian học từ mask SAM + DEVA; xoá vật; **inpaint 3 bước** (mask vùng khuất bằng DEVA → LaMa 2D → fine-tune Gaussian) | VERIFIED (`README.md`, `docs/edit_removal_inpaint.md`, có sẵn `lama/`) |
| | ObjectGS (MIT; cần `gsplat-object` riêng) | `label_ids` theo Gaussian; `export_object_mesh.py` dựng mesh từng vật bằng TSDF từ độ sâu render chỉ Gaussian của vật (`GaussianExtractor`, Open3D) | VERIFIED (đọc `export_object_mesh.py`) |
| | SAGA (Apache-2.0) | Chọn/tách vật bằng click 3D qua affinity feature; có `clip_utils` | VERIFIED (`README.md`) |
| Ẩn/xoá/biến đổi phần hình | SuperSplat (editor đã nhúng) | Trạng thái từng Gaussian (`selected`, `locked`; xoá là bỏ khỏi danh sách), bộ biến đổi nhóm Gaussian đã chọn | VERIFIED (`supersplat/src/splat-state.ts`, `splats-transform-handler.ts`) |
| | splat-transform | Lọc Gaussian theo hộp/cầu (`--filter-box`, `--filter-sphere`) | VERIFIED (`README.md`) |
| Mesh nền/vật | SuGaR, Frosting (Inria non-commercial) | Mesh bám bề mặt + texture; Frosting gắn lớp Gaussian quanh mesh; đầu vào là thư mục kiểu Inria (`cameras.json`, `point_cloud/iteration_N/point_cloud.ply`) | VERIFIED (`frosting_scene/gs_model.py`, `cameras.py`); VRAM tối thiểu UNKNOWN |
| | dn-splatter / AGS-Mesh (Apache-2.0) | Ràng buộc độ sâu/pháp tuyến (DSINE, omnidata), TSDF Open3D, mesh bằng octree | VERIFIED (`README.md`) |
| | Spirula Studio (MIT) | Binary Vulkan, tự nêu 10 triệu Gaussian trong 8 GB; mesh bằng Delaunay 3D + occupancy, UV atlas | VERIFIED (`README.md`, `src/mesh/`); chất lượng INFERENCE |
| | openMVS | Mesh dày đặc + texture từ COLMAP (Re3Sim dùng) | README; giấy phép chưa xác minh |
| | MoGe (MIT) | Độ sâu/pháp tuyến hệ mét từ một ảnh — prior cho train và vùng vá | VERIFIED (`README.md`) |
| Collider vật lý | trimesh (MIT), Open3D | Thể tích, khép kín, vá lỗ; CoACD (phân rã lồi) chưa có trong `private/` | trimesh/Open3D VERIFIED có sẵn; CoACD cần cài |
| Nhãn + thư viện vật | Asset Isaac công khai (S3 `omniverse-content-production`) | `Simple_Warehouse/Props`: `SM_CardBoxA_01.usd` nhãn `box` 0,70×0,50×0,50 m, `SM_PaletteA_01.usd` nhãn `pallet` 1,21×1,00×0,21 m; có mesh collider; **không có MassAPI** | VERIFIED (tải và đọc bằng `usd-core`) |
| | IsaacLab (BSD-3) | `semantic_tags` → `add_labels`; `MassCfg` (mass/density) | VERIFIED (`from_files.py`, `schemas_cfg.py`) |
| Kiến trúc Isaac real-to-sim | Re3Sim (CC BY-NC 4.0) | Nền render 3DGS + collider mesh trong Isaac; vật là mesh USD có `mass`/`density`; ghép ảnh nền 3DGS với vật render theo mask; `set_semantic_label` | VERIFIED (`background/__init__.py`, `envs/config.py`, `tasks/`) |
| Xuất Gaussian sang Isaac | 3DGRUT (Apache-2.0, không có trong `private/`) | Train 3DGUT/3DGRT; chuyển PLY ⇄ ParticleField USD ⇄ NuRec | Tài liệu repo |

Ghi chú: `private/OpenReal2Sim` chỉ có thư mục `.git` (clone chưa đủ) — không audit được.

## 3. Kết luận

- Không repo nào che hết; ADR 0007 ghép: SAM2 (mask video) → Gaussian Grouping/ObjectGS (Gaussian
  có nhãn, xoá + vá nền) → TSDF/ObjectGS mesh + CoACD (collider) → danh mục nhãn Isaac + bảng mật độ
  (vật lý) → 3DGRUT (ParticleField) → USD lai.
- SuGaR/Frosting, dn-splatter, Spirula là ứng viên mesh nền, so trong pha A bằng khoảng cách tới
  LiDAR TorWIC, thời gian, VRAM.
- Khối lượng không lấy được từ asset Isaac đã kiểm; cần bảng mật độ theo nhãn có nguồn hoặc nhập tay.

## 4. Nguồn ngoài

[NVIDIA blog — smartphone → Isaac Sim](https://developer.nvidia.com/blog/reconstruct-a-scene-in-nvidia-isaac-sim-using-only-a-smartphone/) ·
[Isaac Sim 6.0 NuRec](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/assets/usd_assets_nurec.html) ·
[Forum NuRec vs ParticleField](https://forums.developer.nvidia.com/t/question-on-two-3dgs-rendering-pipelines-nurec-vs-particlefield-and-expected-quality-tradeoff-in-isaac-sim-6-0/373260) ·
[3DGRUT](https://github.com/nv-tlabs/3dgrut) ·
[Forum triangle mesh trên rigid body động](https://forums.developer.nvidia.com/t/collider-and-rigid-body-preset-error-physicsusd-parse-collision-triangle-mesh-collision/244203) ·
[SimReady physics](https://docs.omniverse.nvidia.com/simready/latest/simready-asset-creation/physics-best-practices.html) ·
[Isaac Lab sim utils](https://isaac-sim.github.io/IsaacLab/main/source/api/lab/isaaclab.sim.utils.html) ·
[Isaac occupancy map](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/py/source/extensions/isaacsim.asset.gen.omap/docs/index.html) ·
[Importing a new asset — Isaac Lab](https://isaac-sim.github.io/IsaacLab/main/source/how-to/import_new_asset.html)
