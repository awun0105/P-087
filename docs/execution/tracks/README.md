# Execution Tracks

Real2Sim Studio được triển khai qua bốn track dùng chung artifact contracts và
integration gates.

| Track | Entry point | Primary output |
|---|---|---|
| EX-REC | [ex_rec/TRACK.md](./ex_rec/TRACK.md) | `ReconstructionBundle`, `LiDARGeometryArtifact` |
| EX-SCENE | [ex_scene/TRACK.md](./ex_scene/TRACK.md) | `SceneIR` |
| EX-SIM | [ex_sim/TRACK.md](./ex_sim/TRACK.md) | physics `SceneIR`, `CandidatePackage`, reports |
| EX-PRODUCT | [ex_product/TRACK.md](./ex_product/TRACK.md) | product lifecycle, approval và release |

Owners: EX-REC `@awun0105`; EX-SCENE Đức; EX-SIM Đạt; EX-PRODUCT Cường.

## Hiện trạng trên `develop` (2026-09-29)

| Track | Code đã có (quan sát từ repo) | Chưa có |
|---|---|---|
| EX-REC | Kiểm video, privacy gate, tách frame, COLMAP, Brush, SOG (GPU), LiDAR ingest, alignment, bundle; chạy thật local trong Studio | Chạy trên GPU thuê; metric scale cho video người dùng |
| EX-SCENE | `bundle_consumer` đọc `ReconstructionBundle` (SCENE-01) | Mask/association/decomposition/SceneIR thật (package còn placeholder) |
| EX-SIM | Preflight rules, collider generator (SIM-02/04) | OpenUSD, Isaac runtime (package còn placeholder) |
| EX-PRODUCT | API product + Studio, queue worker, Studio UI + editor SuperSplat, UI P0 ẩn | Đăng nhập/role, cloud (ADR 0003), review/release thật |

Nơi chạy Isaac Sim trong kiến trúc cloud chưa được quyết định (ADR 0003 chỉ phủ
REC). EX-SCENE/EX-SIM chưa push phần code mới; bảng này chỉ ghi code đã có trên
`develop`.

## Rules For Coding Agents

1. Đọc `TRACK.md`, task file được giao và các source sections được link trong task.
2. Không tự tạo, đổi tên hoặc mở rộng task ID.
3. Không tạo top-level source folder mới; dùng placement trong `ARCHITECTURE.md`.
4. Không import implementation nội bộ của track khác; handoff qua shared contract và published artifact.
5. Contract change cần producer + consumer review và versioning phù hợp.
6. Không dùng evaluation-only data trong product prediction/runtime.
7. Chỉ đổi task status khi có observable evidence; `DONE` cần implementation, tests, artifact/handoff phù hợp và evidence.
8. Policy chưa được authority khóa phải được ghi thành blocker; fixture, default hoặc ví dụ không phải authority.

## Shared Handoff

```text
InputManifest
→ EX-REC → ReconstructionBundle
→ EX-SCENE → SceneIR
→ EX-SIM → CandidatePackage + ValidationReport + EvaluationReport?
→ EX-PRODUCT → ApprovalRecord + ReleaseManifest
```

Không sửa JSON/file bằng tay giữa các track. Mọi deterministic conversion phải
thành adapter hoặc stage có version trong repository.
