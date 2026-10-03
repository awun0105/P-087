# 0010 Nhân vật 3D và vật lý trong trình duyệt cho scene tương tác

Date: 2026-10-03

## Status

- **Mục 1 (nhân vật): Accepted** — owner (Quân) yêu cầu ngày 03/10/2026 "asset issacsim tự do, hãy research thử";
  kết quả research ở mục Context cho thấy giấy phép không cho dùng trên web, nên dùng nhân vật CC0 thay thế (mục
  Decision 1). Owner xác nhận lại khi đọc ADR này.
- **Mục 2 (vật lý): Accepted** — owner chốt ngày 03/10/2026 "ok hãy làm như bạn suggest": ammo.js cho H5.
- **Mục 3 (asset preview của danh mục Isaac): Proposed, bước 1 đã làm** (03/10/2026) — owner hỏi "nên giải quyết thế
  nào"; Claude đề xuất và làm bước 1 (đảo lại được bằng một biến cấu hình), bước 2 chờ owner đồng ý.

Liên quan: kế hoạch `docs/plans/active/2026-10-02-interactive-scene-and-metric-scale.md` (H4, H5).

## Context

**Giấy phép asset của Isaac Sim (VERIFIED từ văn bản, 03/10/2026).** Asset 3D, texture và vật liệu NVIDIA cung cấp
kèm Isaac Sim thuộc *NVIDIA Isaac Sim Additional Software and Materials License* (bản ngày 9/6/2025; FAQ giấy phép của
Isaac Sim dẫn tới văn bản này cho "NVIDIA-provided assets"). Văn bản định nghĩa "Software" là "the NVIDIA Omniverse Kit and
other software and materials that NVIDIA delivers to you"; quyền cấp là "install and use copies of the Software in
systems with NVIDIA GPUs"; điều 2 cấm "sell, rent, sublicense, transfer, distribute or otherwise make available to
others" và cấm "modify or create derivative works". INFERENCE (không phải ý kiến pháp lý): chuyển USD nhân vật sang GLB
là tạo bản phái sinh, và phục vụ nó cho trình duyệt của mọi người dùng là phân phối, kể cả máy không có GPU NVIDIA —
nằm ngoài quyền được cấp. Mã nguồn Isaac Sim trên GitHub là Apache 2.0 nhưng điều đó không áp dụng cho asset.

Nguồn: https://www.nvidia.com/en-us/agreements/enterprise-software/isaac-sim-additional-software-and-materials-license/ ,
https://docs.isaacsim.omniverse.nvidia.com/latest/common/license-faq.html

**Viewer.** `@playcanvas/supersplat-viewer` 1.35.2 tạo app PlayCanvas chỉ với các hệ component camera, light, render,
gsplat, script (VERIFIED trong `dist/viewer.js`); không có `anim`, `collision`, `rigidbody`. Engine chung với Studio
(peer dependency `playcanvas`), nên Studio thêm được hệ component vào app của viewer lúc chạy
(`app.systems.add(...)`).

## Decision

1. **Nhân vật:** dùng "Worker" của Quaternius — CC0 1.0, GLB 1,3 MB, 5.240 tam giác, có khung xương và các clip
   `Idle`, `Walk`, `Run` (cùng nhiều clip khác), cao khoảng 1,6 m theo đơn vị mét. Nguồn: https://poly.pizza/m/Yg2bQZO6Hj ,
   file `https://static.poly.pizza/3a5f3056-ffe6-42eb-bd52-122afcbd22b2.glb`, sha256
   `9c28614f465b7dc105f908c20c22fc045f4b07caf8c5ef0e9f8049eceb6dd38d`. Commit vào `frontend/public/characters/worker.glb`
   (CC0 cho phép), ghi ở `THIRD_PARTY_NOTICES.md`. Hoạt ảnh chạy qua hệ `anim` mà Studio thêm vào app của viewer. Không
   dùng asset người của Isaac Sim trong trình duyệt.
2. **Vật lý trình duyệt (H5):** ammo.js (bản build WebAssembly chính thức của Bullet, giấy phép zlib; repo
   `kripken/ammo.js`, commit `c8779e6`, `frontend/public/vendor/ammo/`), chỉ tải khi người dùng vào chế độ Đi bộ trong
   scene có vật động. Gọi ammo.js trực tiếp với một thế giới vật lý riêng ở hệ canonical (Z lên) thay vì hệ
   `rigidbody`/`collision` của PlayCanvas: vật của Studio nằm dưới một entity gốc đã xoay sang không gian hiển thị, còn
   hệ rigidbody làm việc theo toạ độ thế giới của entity — tự chạy thế giới riêng thì pose đọc/ghi thẳng như SceneIR.
   Thành phần: sàn z = 0; lưới va chạm của scene đã khoét vùng gốc của vật động (backend, cùng file với lưới đi bộ của
   viewer), chỉ giữ phần trong 6 m quanh vật động; vật động là bao lồi của collider (≤ 256 đỉnh) hoặc hộp, khối lượng và
   ma sát theo `physics` của SceneIR; người đi là con nhộng động học (bán kính 0,3 m, cao 1,6 m) bám vị trí người đi của
   viewer. Tương tác chỉ ở phía trình duyệt, không ghi SceneIR; nút "Đặt lại vị trí vật" và việc rời chế độ Đi bộ đưa
   vật về pose của SceneIR.
3. **Bản xem trước asset Isaac của danh mục vật thể:** `scripts/scene/build_asset_previews.py` chuyển asset Isaac sang
   GLB và API phục vụ chúng cho trình duyệt khi người dùng thêm vật từ thư viện — cùng rủi ro giấy phép như ở Context.
   Gói xuất cho Isaac Sim không có rủi ro này (USD chỉ trỏ tới asset gốc, người mở gói tự dùng Isaac theo giấy phép
   của họ).
   - **Bước 1 (đã làm):** `PRODUCT_ISAAC_ASSET_PREVIEWS` (mặc định: bật ở development/test, tắt ở staging/production).
     Khi tắt, danh mục báo `has_preview=false` và route `/scene/catalog/{family}/preview.glb` trả 404, nên Studio vẽ hộp
     đúng kích thước — kể cả khi gói dữ liệu của deployment có kèm `data/asset_previews`.
   - **Bước 2 (đề xuất):** bản xem trước CC0 cho các loại vật hay dùng (pallet, thùng carton), ghi nguồn ở
     `THIRD_PARTY_NOTICES.md`; hình trên web khi đó khác asset Isaac trong gói xuất.
   - Hỏi NVIDIA xin phép dùng bản chuyển đổi trên web: làm song song nếu muốn, không chặn deploy.

## Consequences

- Nhân vật không phải người mẫu của Isaac: trên web và trong gói Isaac có thể khác hình (gói Isaac không chứa nhân vật).
- Thêm hệ `anim` vào app của viewer phụ thuộc API nội bộ ổn định của engine PlayCanvas 2.22; nâng viewer/engine thì
  kiểm lại.
- Người đi của viewer chỉ va chạm với lưới tĩnh: vật bị đẩy không chặn lại người đi, và vùng gốc của vật động trong lưới
  đi bộ là chỗ trống. Đổi tập vật động (gán/bỏ lớp có vật lý) tạo lại viewer vì lưới đi bộ đổi.
- Nhân vật là lưới thường trong scene 3DGS: ánh sáng/bóng không hoà hoàn toàn.
