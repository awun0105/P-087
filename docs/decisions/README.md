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
- [0006: Tách vật thể cho SceneIR — SAMPro3D adapt với SAM2, fallback hình học](0006-scene-object-extraction.md) — *Accepted* hướng kỹ thuật; cài runtime chờ xác nhận (2026-09-30)
