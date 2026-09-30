# 0006 Tách vật thể cho SceneIR: SAMPro3D adapt với SAM2, fallback hình học

Date: 2026-09-30

## Status

Accepted (hướng kỹ thuật) — Tech Lead (Quân) chốt ngày 2026-09-30 sau khi đọc source R2G
(`private/R2G/src/sampro3d` @386ac05, `src/assist-gs` @4a382f4). Việc cài runtime PyTorch +
SAM2 (~2,5–3 GB, dependency mới) vẫn cần owner xác nhận riêng trước khi thực hiện.

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
- Chưa làm: cài runtime (chờ owner), adapter SAM2, voting/consolidation, UI xác nhận.
