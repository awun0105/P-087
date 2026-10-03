# Architecture And Product Decisions

Thư mục này dành cho lasting decisions chưa phù hợp để ghi trực tiếp vào PRD,
Architecture hoặc execution contract. Dùng `docs/templates/decision.md`.

Decision phải có owner/authority và trạng thái `Accepted` trước khi coding agent
dùng nó như policy. `Proposed` decision không phải authority.

## Danh sách quyết định

- [0001: Chiến lược và Lộ trình Khôi phục Tỷ lệ Mét (Metric Scale Recovery)](0001-metric-scale-strategy-and-roadmap.md) — *Accepted* (2026-09-26)
- [0002: Studio MVP — lát cắt video → 3DGS có editor, demo xử lý sẵn](0002-studio-mvp-video-to-3dgs.md) — *Proposed* (2026-09-29)
- [0003: Kiến trúc cloud client–server, vai trò người dùng và ngân sách trình duyệt](0003-cloud-architecture-roles-and-browser-budget.md) — *Accepted* (2026-09-29)
- [0004: Nhận diện loại đầu vào và định tuyến luồng xử lý](0004-input-kinds-and-routing.md) — *Accepted* (2026-09-29)
- [0005: Xem kết quả từng bước của pipeline trên Web Studio](0005-stage-results-viewer.md) — *Accepted* (2026-09-29)
- [0006: Tách vật thể cho SceneIR — SAMPro3D adapt với SAM2, fallback hình học](0006-scene-object-extraction.md) — *Accepted*; runtime đã cài (2026-09-30). Đường tạm cho tới khi pipeline v2 (0007) thay chặng tách vật
- [0007: Pipeline v2 — video → scene 3D theo vật chỉnh sửa được → USD lai cho Isaac Sim](0007-object-centric-hybrid-usd-pipeline.md) — *Accepted* hướng kiến trúc; phương pháp chặng 5–7 chọn sau pha A (2026-09-30)
- [0008: Dùng lại code nghiên cứu có giấy phép phi thương mại](0008-research-code-license-policy.md) — *Accepted* (2026-09-30)
- [0009: LiDAR của người dùng — loại đầu vào và ba luồng xử lý](0009-user-lidar-input-and-routing.md) — mục 1–3 *Accepted*, mục 4–6 *Proposed* (2026-10-02)
- [0010: Nhân vật 3D và vật lý trong trình duyệt cho scene tương tác](0010-interactive-character-and-browser-physics.md) — *Accepted* (2026-10-03)
