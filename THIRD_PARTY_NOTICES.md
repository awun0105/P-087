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
