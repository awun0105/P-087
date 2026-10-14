TASK: CFG-01-TOOL-INSPECT
STATUS: COMPLETED (Done on 2026-10-13)

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Pipeline của Real2Sim Studio trải qua 8 chặng phức tạp với nhiều công cụ mã nguồn mở khác nhau (FFmpeg, COLMAP, Brush, MoGe-2, splat-transform, SAM2, CoACD, LaMa, OpenUSD). Rất nhiều tham số kỹ thuật cốt lõi (như `--collision-mesh smooth`, `--voxel-external-fill`, CoACD threshold, matching modes) đang bị gán cứng (hardcode) trong code backend hoặc file cấu hình ẩn mà người dùng không thể biết hoặc tùy chỉnh. Nếu không audit toàn diện trước, các lập trình viên sẽ sửa chắp vá và dễ bỏ sót các cờ quan trọng.
- **Yêu cầu cốt lõi (What):** Rà soát toàn bộ codebase và các file cấu hình hiện có, đối chiếu với tài liệu/mã nguồn mở chính thức trên GitHub, lập thành tài liệu chuẩn hóa `docs/execution/CONFIG_CATALOG.md` ghi rõ tên tham số, giá trị mặc định, khoảng an toàn, ý nghĩa thực tế và phân loại (UI, Profile hay Hardcoded).

GOAL:
Rà soát toàn bộ các công cụ và chặng trong pipeline (từ ST-INPUT-VALIDATE đến ST-SIMULATION-READY), trích xuất tất cả các tham số kỹ thuật (parameters, defaults, types, ranges, constraints, flags) và lập thành tài liệu chuẩn hóa `docs/execution/CONFIG_CATALOG.md`.

INPUT CONTRACT:
- Mã nguồn hiện tại trong `src/services/` (reconstruction, scene, simulation, orchestration).
- Các file profile hiện có trong `configs/product/` (processing_presets_v1.json, geometry_indoor_v1.json, geometry_v1.json, upload_quality_v2.json).

OUTPUT CONTRACT:
- File tài liệu `docs/execution/CONFIG_CATALOG.md` phân loại rõ ràng 8 chặng:
  1. ST-INPUT-VALIDATE & ST-FRAME-EXTRACT (FFmpeg / Sampling / Quality)
  2. ST-CAMERA-POSE (COLMAP: feature extraction, matching modes, mapper, bundle adjustment)
  3. ST-VISUAL-RECON (Brush 3DGS: train iters, max res, max splats, sh degree, sog iterations)
  4. ST-METRIC-CANONICALIZE (MoGe-2: scaling, confidence thresholds, segments)
  5. ST-RGB-GEOMETRY (Voxel grid, resolution_m, external_fill_size_m, floor_fill, capsule carving, marching cubes)
  6. ST-OBJECT-EXTRACT (SAM2 / SAMPro3D, lifting parameters, CoACD convex decomposition, LaMa inpainting)
  7. ST-SIMULATION-READY (USD export, physics properties, carve margin)
  8. Bằng chứng kiểm chứng mã nguồn mở từ GitHub.

OWNED FILES:
- `docs/execution/CONFIG_CATALOG.md`

FILES YOU MAY MODIFY:
- `docs/execution/CONFIG_CATALOG.md`

FILES YOU MUST NOT MODIFY:
- `src/` (Không sửa mã nguồn trong task này, đây là task inspect & tài liệu hóa).
- `configs/`

PRIMARY TOOL:
- Python inspect script hoặc ripgrep / CodeGraph / Web search.

IMPLEMENT:
1. Đọc và phân tích các schema config trong `src/services/` và `configs/product/`.
2. Lập danh mục chi tiết từng tham số gồm các cột:
   - Tên tham số (Code key & UI label)
   - Chặng sở hữu (Stage ID)
   - Công cụ thực thi (Tool / Library)
   - Kiểu dữ liệu & Đơn vị (Type & Unit)
   - Giá trị mặc định (Default)
   - Khoảng hợp lệ (Min / Max / Choices)
   - Ý nghĩa thực tế và tác động hiệu năng / VRAM / thời gian
   - Hiện trạng: Đã đưa lên UI hay đang hardcoded ngầm trong code
3. Ghi tài liệu đầy đủ vào `docs/execution/CONFIG_CATALOG.md`.

TEST:
- Kiểm tra file `docs/execution/CONFIG_CATALOG.md` tồn tại và có đầy đủ 8 chặng.
- Kiểm tra không có file mã nguồn nào bị thay đổi: `git status --porcelain src/` phải rỗng.

DONE WHEN:
- File `docs/execution/CONFIG_CATALOG.md` được tạo hoàn chỉnh, rõ ràng, chi tiết, đóng vai trò là "nguồn sự thật" (Source of Truth) cho các task cấu hình tiếp theo.

EVIDENCE:
- File `docs/execution/CONFIG_CATALOG.md` (265 dòng, phủ kín 8 chặng pipeline).
