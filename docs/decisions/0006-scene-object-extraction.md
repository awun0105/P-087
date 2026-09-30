# 0006 Tách vật thể cho SceneIR: SAMPro3D adapt với SAM2, fallback hình học

Date: 2026-09-30

## Status

Accepted (hướng kỹ thuật) — Tech Lead (Quân) chốt ngày 2026-09-30 sau khi đọc source R2G
(`private/R2G/src/sampro3d` @386ac05, `src/assist-gs` @4a382f4). Việc cài runtime PyTorch +
SAM2 (~2,5–3 GB, dependency mới) được owner đồng ý 2026-09-30 ("ok làm đi") và đã cài ở
`data/scene_runtime` (xem §Implementation).

## Context

- Tech Lead giao nhóm EX-REC hoàn thiện tích hợp EX-SCENE/EX-SIM trên `feat/studio-integration`
  (plan 2026-09-29-studio-completion §Quyết định Tech Lead 2026-09-30).
- EX-SCENE hiện là baseline fixture: extractor đọc manifest JSON giả (hỏng với PNG thật), chưa
  có SAM2; decomposition bắt buộc ≥ 1 candidate đã xác nhận.
- Track guide khóa SCENE-02 = SAM2 (REUSE), SCENE-03 = SAMPro3D của R2G (ADAPT), SCENE-06 =
  OBB theo `get_aabb.py` (audit `docs/execution/audits/02_r2g.md`).
- Đọc source SAMPro3D: FPS prompt 3D trên point cloud → chiếu vào frame bằng intrinsics + pose +
  **depth** → SAM point prompt → lọc prompt theo nhiều frame → bỏ phiếu gán điểm 3D → DBSCAN +
  gộp prompt → sàn RANSAC; `get_aabb.py` = OBB tối thiểu Open3D trên point cloud từng vật.

## Decision

1. **Đường chính:** adapt SAMPro3D với SAM2 (image predictor, point prompt), chạy như một
   bước GPU của worker sau REC bundle:
   - point cloud = tâm Gaussian 3DGS hệ mét của bundle; pose/intrinsics canonical của bundle;
   - không có sensor depth → lọc che khuất bằng z-buffer của chính point cloud chiếu vào ảnh;
   - FPS/DBSCAN bằng numpy + `scipy.spatial.cKDTree` (không kéo `pointops`/Open3D vào app);
   - sàn = z = 0 đã xác nhận ở REC-06 (thay RANSAC);
   - OBB bằng `trimesh.bounds.oriented_bounds` (thay Open3D) → SceneObject CANDIDATE.
2. **Fallback:** tách hình học từ collision mesh REC-05 (khối voxel liên thông trên sàn + OBB
   yaw, `src/services/scene/geometric.py`) khi không có GPU/SAM2; gắn nhãn "ứng viên hình học,
   chưa phân loại". Không claim chất lượng segmentation.
3. **Bắt buộc người xác nhận** ứng viên (SCENE-05) trước khi EX-SIM tạo collider; người dùng có
   thể thêm vật cản hộp (EX-SCENE `add_primitive_object`).
4. Runtime SAM2 tách riêng (vd `data/scene_runtime`, như `data/rec07_runtime` cho Open3D),
   checkpoint `sam2.1_hiera_tiny`/`small` cho GPU 4 GB. License: SAM2 Apache-2.0, SAMPro3D/R2G
   Apache-2.0 — ghi nguồn ở THIRD_PARTY_NOTICES khi adapt code. Cutie không dùng.

## Alternatives Considered

1. Chỉ hình học: nhanh, không cần GPU, nhưng gộp vật chạm nhau, không có nhãn loại, nhạy
   Gaussian rác, ngưỡng kích thước heuristic — chỉ giữ làm fallback.
2. SegAnyGaussians / gaussian-grouping (có trong `private/`): cần train lại đặc trưng trên 3DGS,
   không dùng output Brush sẵn có — để P1 nếu SAMPro3D không đạt.

## Consequences

- Thêm runtime GPU cho EX-SCENE; worker có thêm bước tách vật thể sau bundle.
- Chất lượng phụ thuộc 3DGS preview (thưa) và độ chính xác z-buffer; cần đo trên Aisle_CW.

## Implementation (2026-09-30)

- Runtime: `data/scene_runtime` (uv venv Python 3.12, torch 2.7.1+cu126, sam2 @2b90b9f,
  `sam2.1_hiera_tiny.pt` sha256 7402e0d8…). App gọi qua subprocess
  (`src/services/scene/sampro3d/sam2_runner.py`), cấu hình bằng `PRODUCT_SCENE_RUNTIME_PYTHON`,
  `PRODUCT_SAM2_CHECKPOINT`, `PRODUCT_SCENE_TIMEOUT_SECONDS`; thiếu → fallback hình học; lỗi cả
  hai → SceneIR chỉ có môi trường. Bước này không làm hỏng job (tái dựng đã xong).
- Khác Decision §1: OBB theo yaw (`geometric._yaw_box`, PCA trên XY) thay
  `trimesh.bounds.oriented_bounds` vì vật đứng trên sàn; NMS theo Jaccard tập điểm thay box NMS;
  thành phần liên thông lớn nhất theo đồ thị bán kính 0,15 m thay DBSCAN.
- Pipeline: `STUDIO_PIPELINE` thêm `ST-OBJECT-EXTRACT` sau `ST-RGB-GEOMETRY`; worker chạy
  `extract_scene` sau finalize thành công và ghi StageArtifact SceneIR cùng `record_finalize`.
  SceneIR rev-001: môi trường = visual SOG + collision mesh REC-05 của bundle; vật = CANDIDATE,
  `active=false`.
- Xác nhận (SCENE-05/PRODUCT-07) không đổi contract SceneIR (chỉ có CANDIDATE/CONFIRMED + active):
  `confirm` → CONFIRMED + active; `ignore` → giữ CANDIDATE, active=false,
  `provenance.review="IGNORED"` (còn audit/khôi phục; vật đã xác nhận không ignore được);
  `hide` → đổi active; `delete` → active=false. Thêm vật cản (PRODUCT-07A): hộp AABB CONFIRMED,
  `position_xyz` là **tâm hộp** (mét, world); UI Studio đặt tâm ở z = cao/2 (trên sàn).
- Evidence (T2000 4 GB, job-ac2bfd924cc6 Aisle_CW): 16 602 điểm, 400 prompt, 198,5 s,
  `sampro3d_sam2_v1`, 27 ứng viên. Kiểm overlay trước đó: pallet bọc nilon và cột được tách
  đúng; thanh đứng/xà kệ bị tách nhầm thành vật (nhiều ứng viên lơ lửng z ≈ 1,5–3,6 m) — vì vậy
  người dùng bắt buộc xác nhận. Chưa có metric segmentation có nhãn: không claim chất lượng.

## Còn lại

- EX-SIM: collider cho vật đã xác nhận + collider môi trường từ collision mesh, USD candidate
  (hiện `usd/usda.py` chỉ phát ground plane), khoét vật khỏi mesh môi trường.
- **Không** thêm luật lọc ứng viên kệ/xà (owner quyết 2026-09-30): ứng viên sai là hệ quả của 3DGS
  preview kém (job-ac2/123 chỉ dựng từ 50 ảnh trong 20 s đầu của 109 s Aisle_CW, xem
  `recon_visual_quality`), không phải lỗi thuật toán; sửa bằng 3DGS tốt hơn, không bằng heuristic.
