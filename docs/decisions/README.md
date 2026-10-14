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
- [0011: Điều hướng First-Person và Camera ban đầu cho Viewer 3DGS toàn hệ thống](0011-first-person-navigation-and-initial-camera-pose.md) — *Proposed* (2026-10-06)
- [0012: Background collision cho scene chỉnh sửa và capability của USD exporter](0012-editable-collision-and-usd-capabilities.md) — *Proposed* (2026-10-07)
- [0013: Trusted validation và identity bất biến khi phát hành](0013-validation-evidence-and-release-identity.md) — *Proposed* (2026-10-07)
- [0014: Durable heavy operations dùng chung resource admission](0014-durable-heavy-operations.md) — *Proposed* (2026-10-07)
- [0015: Scene revision head trong runtime DB và optimistic CAS](0015-scene-revision-head.md) — *Proposed* (2026-10-07)
- [0016: Collision quality và explicit LiDAR-derived collision source](0016-collision-quality-and-lidar-selection.md) — *Proposed* (2026-10-07)
- [0017: Fast Preview và final artifacts có identity riêng](0017-fast-preview-and-final-artifacts.md) — *Proposed* (2026-10-07)
- [0018: Opt-in LiDAR odometry cho scan sequence thiếu trajectory](0018-opt-in-lidar-odometry.md) — *Proposed* (2026-10-07)
- [0019: Anonymized input copy và QA trước dispatch](0019-anonymized-input-preparation.md) — *Proposed* (2026-10-07)
- [0020: Automatic RGB–LiDAR map registration với floor, BEV, constrained ICP và QA](0020-automatic-rgb-lidar-map-registration.md) — *Proposed* (2026-10-07)
- [0021: Guest identity và resource ownership](0021-guest-identity-and-ownership.md) — *Proposed* (2026-10-07)
- [0022: Guest calendar-day quota và accepted run identity](0022-guest-daily-job-quota.md) — *Proposed* (2026-10-07)
- [0023: Nén video trước upload và geometry/time provenance](0023-client-video-normalization.md) — *Proposed* (2026-10-07)
- [0024: Một khung upload và tự resolve input assembly/recipe](0024-unified-upload-and-input-resolution.md) — *Proposed* (2026-10-07)
- [0025: Imported PLY/SOG continuation thành editable SceneIR và simulation candidate](0025-imported-3dgs-continuation.md) — *Deferred* theo yêu cầu owner (2026-10-07)
- [0026: Hiệu chỉnh ước lượng tài nguyên theo số đo và tách auto-tune RAM/VRAM](0026-decoupled-resource-tuning-and-observed-budget.md) — *Accepted* (2026-10-09)
- [0027: Chẩn đoán lỗi COLMAP theo kết quả, đoạn trích log đã che và hướng khắc phục trên UI](0027-structured-error-diagnostics-and-redacted-excerpts.md) — *Accepted* (2026-10-09)
- [0028: Khoảng tham chiếu chất lượng, khuyến nghị theo quy tắc và số đo tài nguyên trong bảng đánh giá](0028-benchmark-derived-verdicts-and-rule-based-insights.md) — *Accepted* (2026-10-09)
