# Third-party notices

Ghi nguồn cho code, mô hình và asset bên thứ ba được ADAPT/REUSE trong repository. Một file cho cả repo:
phần *Backend và pipeline* cho `src/` và runtime GPU, phần *Frontend* cho `frontend/`. Đưa code bên thứ ba vào thì
cập nhật file này trong cùng commit (ADR 0008).

## Backend và pipeline

### SAMPro3D (qua R2G)

- Upstream: https://github.com/BigCiLeng/R2G — thư mục `src/sampro3d` (SAMPro3D của Mutian Xu,
  Xingyilang Yin), submodule @`386ac05`, bản R2G đọc tại @`e93b621`.
- License: Apache License 2.0 (`src/sampro3d/LICENSE` của upstream).
- Dùng ở: `src/services/scene/sampro3d/sam2_runner.py` (ADAPT `3d_prompt_proposal.py`),
  `src/services/scene/sampro3d/consolidate.py` (ADAPT `main.py`: `prompt_filter`,
  `perform_3dsegmentation`, `prompt_consolidation`).
- Thay đổi so với bản gốc (ADR 0006): SAM2 thay SAM ViT-H; z-buffer của point cloud thay ảnh
  depth; NMS theo tập điểm thay box NMS; đồ thị bán kính (`scipy.spatial.cKDTree`) thay DBSCAN;
  sàn z = 0 đã xác nhận (REC-06) thay RANSAC; không dùng CUDA extension `pointops`.

### SAM 2 (Segment Anything Model 2)

- Upstream: https://github.com/facebookresearch/sam2 @`2b90b9f`, checkpoint
  `sam2.1_hiera_tiny.pt`.
- License: Apache License 2.0.
- Dùng như thư viện (REUSE, không sửa) trong runtime riêng `PRODUCT_SCENE_RUNTIME_PYTHON`;
  code app chỉ gọi `sam2.build_sam.build_sam2` và `SAM2ImagePredictor` từ
  `src/services/scene/sampro3d/sam2_runner.py`. Không vendor source SAM2 vào repository.

### MoGe-2 (đề xuất tỉ lệ mét tự động, ADR 0001 §2)

- Upstream: https://github.com/microsoft/MoGe @`b942f00` (bản thời MoGe-2; nhánh main hiện là MoGe-3 với
  dependency khác), trọng số `Ruicheng/moge-2-vitb-normal` (`model.pt`, sha256 `16b8110e…`).
- License: MIT cho mã và cho trọng số (theo `LICENSE` của repository và model card, kiểm 02/10/2026);
  phần DINOv2 trong repository theo Apache License 2.0.
- Phụ thuộc đi kèm: `utils3d` (https://github.com/EasternJournalist/utils3d @`3fab839`, MIT).
- Dùng như thư viện (REUSE, không sửa) trong runtime `REC06_MOGE_PYTHON`; code app chỉ gọi
  `moge.model.v2.MoGeModel` từ `src/services/reconstruction/adapters/moge_runner.py`. Không vendor source vào
  repository. Cài `--no-deps` để không đổi phiên bản thư viện của SAM 2 và gsplat trong cùng runtime.
- Ý tưởng ghép độ sâu thưa COLMAP với độ sâu mét (DN-Splatter) và giải tỉ lệ scale-only (MonoSplat) được viết
  lại theo ADR 0001, không chép mã của hai dự án đó.

### Pipeline v2 — tách scene theo vật (ADR 0007)

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

## Frontend

### PlayCanvas / SuperSplat integration

`frontend/src/features/viewer/inspection-history.ts` adapts the FIFO command queue and
history cursor discipline from `playcanvas/supersplat` (commit `f76e676`,
`src/command-queue.ts`, `src/edit-history.ts`). The inspection controller follows
the two-point measurement interaction of `src/tools/measure-tool.ts`, but does
not copy its local rescaling behavior: Real2Sim metric confirmation belongs to
the backend. PlayCanvas `Picker` and `supersplat-viewer` are used via their pinned
library APIs; renderer/selection algorithms are not reimplemented here.

Upstream: https://github.com/playcanvas/supersplat

Copyright (c) 2011-2026 PlayCanvas Ltd.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

### Nhân vật "Worker" (Quaternius) — CC0 1.0

`frontend/public/characters/worker.glb`: "Worker" của Quaternius, phát hành Public Domain (CC0 1.0). Nguồn:
https://poly.pizza/m/Yg2bQZO6Hj (tải từ `https://static.poly.pizza/3a5f3056-ffe6-42eb-bd52-122afcbd22b2.glb`,
sha256 `9c28614f465b7dc105f908c20c22fc045f4b07caf8c5ef0e9f8049eceb6dd38d`). Không chỉnh sửa file. Dùng cho góc nhìn
thứ ba trong viewer (ADR 0010).

### ammo.js (Bullet Physics cho WebAssembly) — zlib

`frontend/public/vendor/ammo/ammo.wasm.js` và `ammo.wasm.wasm`: bản build chính thức trong `builds/` của
https://github.com/kripken/ammo.js (commit `c8779e60159d428f11ff1eb553dc9b6b6e2d317a`), không chỉnh sửa. sha256
`8481c5250507d3f2c0cecff7cc55a34727f52f96590a2304556a43ca4cf4e0b3` (js) và
`de36b300b25d244a79ae56ef0e7fee5efe2a3281f346a134945eef0b2fbaa5d8` (wasm). Dùng cho đẩy vật thể trong viewer (ADR 0010).

Copyright (c) 2011 ammo.js contributors

This software is provided 'as-is', without any express or implied warranty. In no event will the authors be held
liable for any damages arising from the use of this software. Permission is granted to anyone to use this software for
any purpose, including commercial applications, and to alter it and redistribute it freely, subject to the following
restrictions: 1. The origin of this software must not be misrepresented; you must not claim that you wrote the original
software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated
but is not required. 2. Altered source versions must be plainly marked as such, and must not be misrepresented as being
the original software. 3. This notice may not be removed or altered from any source distribution.

### Vendored SuperSplat editor

`frontend/vendor/supersplat/` là bản copy của `playcanvas/supersplat` v3.4.2 (commit
`f76e676`) theo MIT License ở trên, được build thành `frontend/public/editor/` và nhúng
vào Studio. Chi tiết nguồn gốc và chỉnh sửa: `frontend/vendor/supersplat/PROVENANCE.md`.

### next-shadcn-admin-dashboard (UI nền Studio)

Component `frontend/src/components/shadcn/*`, hook `frontend/src/hooks/use-mobile.ts` (viết lại) và khung
sidebar/header của `frontend/src/features/shell/` lấy từ
[`arhamkhnz/next-shadcn-admin-dashboard`](https://github.com/arhamkhnz/next-shadcn-admin-dashboard)
commit `3502692` (2026-09-28), MIT License — Copyright (c) 2024 Mohammed Arham Khan. Đã đổi đường
dẫn import và theme; không chép các trang domain mẫu (STUDIO_UX_SPEC.md §3.2).

`frontend/src/styles/shadcn-variants.css` chép từ gói npm `shadcn@4.21.0` (`dist/tailwind.css`), MIT License.
Dependency thêm: `radix-ui@1.6.7` (MIT), `tw-animate-css@1.4.0` (MIT).

### Rerun web viewer

`@rerun-io/web-viewer-react@0.24.1` + `@rerun-io/web-viewer@0.24.1` (MIT OR Apache-2.0, © Rerun Technologies AB):
viewer Rerun nhúng cho chế độ xem "Quá trình train" của bước 3DGS. Ghim đúng 0.24.1 vì phải khớp SDK Rerun mà
Brush 0.3.0 nhúng.
