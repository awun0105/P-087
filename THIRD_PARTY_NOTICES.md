# Third-party notices (backend)

Ghi nguồn cho code bên thứ ba được ADAPT/REUSE trong `src/`. Notice của frontend nằm ở
`frontend/THIRD_PARTY_NOTICES.md`.

## SAMPro3D (qua R2G)

- Upstream: https://github.com/BigCiLeng/R2G — thư mục `src/sampro3d` (SAMPro3D của Mutian Xu,
  Xingyilang Yin), submodule @`386ac05`, bản R2G đọc tại @`e93b621`.
- License: Apache License 2.0 (`src/sampro3d/LICENSE` của upstream).
- Dùng ở: `src/services/scene/sampro3d/sam2_runner.py` (ADAPT `3d_prompt_proposal.py`),
  `src/services/scene/sampro3d/consolidate.py` (ADAPT `main.py`: `prompt_filter`,
  `perform_3dsegmentation`, `prompt_consolidation`).
- Thay đổi so với bản gốc (ADR 0006): SAM2 thay SAM ViT-H; z-buffer của point cloud thay ảnh
  depth; NMS theo tập điểm thay box NMS; đồ thị bán kính (`scipy.spatial.cKDTree`) thay DBSCAN;
  sàn z = 0 đã xác nhận (REC-06) thay RANSAC; không dùng CUDA extension `pointops`.

## SAM 2 (Segment Anything Model 2)

- Upstream: https://github.com/facebookresearch/sam2 @`2b90b9f`, checkpoint
  `sam2.1_hiera_tiny.pt`.
- License: Apache License 2.0.
- Dùng như thư viện (REUSE, không sửa) trong runtime riêng `PRODUCT_SCENE_RUNTIME_PYTHON`;
  code app chỉ gọi `sam2.build_sam.build_sam2` và `SAM2ImagePredictor` từ
  `src/services/scene/sampro3d/sam2_runner.py`. Không vendor source SAM2 vào repository.

## Pipeline v2 — tách scene theo vật (ADR 0007)

Phương pháp/quy ước tham khảo từ các nguồn dưới đây; code trong `src/` tự viết, không chép file nguồn.
Thư viện chạy trong runtime riêng (`scripts/gpu/setup_scene_runtime.sh`), không vendor vào repository.

| Nguồn | Giấy phép | Dùng gì | Ở đâu |
|---|---|---|---|
| FlashSplat — https://github.com/florinshen/FlashSplat @`3e3b147` | xem repo upstream | Ý tưởng gán nhãn Gaussian từ mask 2D theo đóng góp khi render (không train) | `src/services/scene/association/lift_runner.py` |
| Gaussian Grouping — https://github.com/lkeab/gaussian-grouping @`0ab60af` | Apache-2.0 | Quy trình xoá vật → vá 2D bằng LaMa → đưa lên 3D (`docs/edit_removal_inpaint.md`); bản này gieo Gaussian theo độ sâu thay bước fine-tune | `src/services/reconstruction/rgb/inpaint/inpaint_runner.py` |
| 3DGRUT — https://github.com/nv-tlabs/3dgrut @`e6f4552` | Apache-2.0 | Quy ước ghi 3DGS vào `UsdVol.ParticleField3DGaussianSplat` (opacity/scale sau kích hoạt, quaternion wxyz, thứ tự hệ số SH) | `src/services/simulation/usd/hybrid_runner.py` |
| gsplat 1.5.3 — https://github.com/nerfstudio-project/gsplat | Apache-2.0 | Thư viện rasterizer (REUSE) cho gán nhãn và vá nền | runtime |
| CoACD 1.0.14 — https://github.com/SarahWeiii/CoACD | MIT | Thư viện phân rã lồi (REUSE) | `src/services/simulation/colliders/convex_runner.py` |
| LaMa `big-lama.pt` (TorchScript, bản phát hành của `enesmsahin/simple-lama-inpainting` v0.1.0; mô hình gốc `advimman/lama`) | Apache-2.0 | Trọng số vá ảnh 2D, tải lúc cài runtime (sha256 `7ba7aa7a…`) | runtime |
| usd-core 26.8 (OpenUSD) | Giấy phép OpenUSD (Apache-2.0 sửa đổi) | Ghi stage USD | runtime |
| Asset `Simple_Warehouse/Props` của NVIDIA Isaac Sim 5.1 (S3 công khai) | Giấy phép asset NVIDIA Omniverse — chỉ đọc metadata (nhãn, kích thước) và tham chiếu URL; không chép asset vào repository | Danh mục `configs/product/object_catalog_v1.json` | `scripts/scene/build_isaac_catalog.py` |

Dùng code nghiên cứu phi thương mại theo ADR 0008 (đồ án học tập): hiện chưa có file nào trong `src/` chép từ
nguồn phi thương mại.
