# Execution Plan: Dọn cấu trúc repository (thư mục gốc, API, orchestration, UI cũ)

Date: 2026-10-02

## Status

Active — nhánh `feat/pipeline-v2` (chưa push).

## Outcome

Mỗi thứ trong repo có một chỗ đúng và tên nói được nội dung, **không đổi hành vi pipeline và hợp đồng HTTP**:

1. Thư mục gốc có bản đồ vai trò từng file; tài liệu của nhóm không thuộc khung ban tổ chức được đưa vào `docs/`.
2. Hết nhầm `PRODUCT.md` / `docs/PRD.md`; một file notices.
3. API product tách theo chủ đề như `src/api/studio/`.
4. `src/services/orchestration/` không còn file lẻ nằm cạnh thư mục cùng chủ đề.
5. Phần validation / duyệt / phát hành có đủ chi tiết trong UI mới (S10–S12), UI cũ được xoá.

## Context

- Yêu cầu và ba quyết định của owner (Tech Lead) ngày 02/10/2026 — xem [Decisions](#decisions).
- Authority: [`AGENTS.md`](../../../AGENTS.md) §1.4 (không rename/move/delete khung ban tổ chức), §2 (authority map);
  [`ARCHITECTURE.md`](../../../ARCHITECTURE.md) (placement, additive-only, không tạo thư mục cấp cao nhất mới);
  đặc tả UX S10–S12 và D-05, D-10 trong `docs/STUDIO_UX_SPEC.md` (trước là `PRODUCT.md`).
- VERIFIED trước khi làm (02/10/2026):
  - 19/31 file ở gốc là khung ban tổ chức (commit `52d85fb` của `phoenix-mentor[bot]`); `WORKLOG.md`, `JOURNAL.md` là
    sản phẩm nộp Demo Day (`README_starter.md` bảng deliverables).
  - Mọi nhánh remote đã nằm trong `feat/pipeline-v2` trừ `origin/feat/sim` (4 commit: SIM-01 Phase A, SIM-06/07,
    playbook metric — chỉ chạm `docs/README.md` trong vùng sẽ sửa) và `origin/feat/scene-01-bundle-consumer` (1 commit
    tài liệu, không chạm vùng sẽ sửa).
  - Backend studio review đã trả đủ `ValidationReport`, `ApprovalRecord`, `ReleaseManifest`; UI cũ gọi endpoint stub
    trả 501.
  - Baseline: `pytest tests/ -q` 1125 passed / 40 skipped; frontend `vitest` 38 file / 227 test; OpenAPI 71 path / 77
    operation / 142 schema.

## Scope

In scope:

- Pha 1: `PRODUCT.md` → `docs/STUDIO_UX_SPEC.md`; `CONTEXT.md` → `docs/CONTEXT.md`; gộp notices; bản đồ thư mục gốc.
- Pha 2: tách `src/api/routes_product.py` thành `src/api/product/`.
- Pha 3: dời 8 module `orchestration` vào thư mục con theo miền.
- Pha 4: (a) chi tiết validation/duyệt/phát hành trong UI mới; (b) xoá UI cũ.
- Pha 5: đồng bộ `ARCHITECTURE.md`, `README.md`, `docs/README.md`.

Out of scope:

- Dời/xoá file của ban tổ chức; thư mục cấp cao nhất mới (`requirements/`, `deploy/`); đổi tên theo mã task
  (`rec04_runtime`, `REC04_BRUSH_*`); chia nhỏ `frontend/src/features/studio`.
- Endpoint backend chỉ UI cũ gọi (`/projects…`, `/jobs/{id}/transitions`, `/validation`, `/review`,
  `/review/{action}`, `/release`): giữ nguyên, là hợp đồng API có test và task PRODUCT riêng.
- Nối producer validation SIM-06/07 (đang ở `origin/feat/sim`, chưa merge) vào luồng Studio.
- **PROPOSAL chưa làm:** `review_state` cho duyệt khi báo cáo PASS dù không có bằng chứng Isaac thật. Đợt này chỉ hiện
  cảnh báo; chặn duyệt hay không là quyết định sản phẩm.

## Approach

`git mv` để giữ lịch sử; mỗi bước một commit; mỗi pha chạy đủ kiểm tra rồi mới sang pha sau. Tài liệu "sống" sửa theo
đường dẫn mới; bản ghi lịch sử (WORKLOG, JOURNAL, task file, plan cũ, ADR) không viết lại — tra bảng dưới.

### Bảng ánh xạ đường dẫn

| Cũ | Mới | Pha |
| --- | --- | --- |
| `PRODUCT.md` | `docs/STUDIO_UX_SPEC.md` | 1 |
| `CONTEXT.md` | `docs/CONTEXT.md` | 1 |
| `frontend/THIRD_PARTY_NOTICES.md` | `THIRD_PARTY_NOTICES.md` (phần *Frontend*) | 1 |
| `src/api/routes_product.py` | `src/api/product/{projects,jobs,artifacts,scene,review,deps}.py` | 2 |
| `src/services/orchestration/scene_objectify.py` | `…/orchestration/scene/objectify.py` | 3 |
| `src/services/orchestration/scene_objectify_queue.py` | `…/orchestration/scene/objectify_queue.py` | 3 |
| `src/services/orchestration/scene_extraction.py` | `…/orchestration/scene/extraction.py` | 3 |
| `src/services/orchestration/simulation_package.py` | `…/orchestration/review/simulation_package.py` | 3 |
| `src/services/orchestration/metric.py` | `…/orchestration/jobs/metric.py` | 3 |
| `src/services/orchestration/stage_views.py` | `…/orchestration/jobs/stage_views.py` | 3 |
| `src/services/orchestration/thumbnails.py` | `…/orchestration/jobs/thumbnails.py` | 3 |
| `src/services/orchestration/imports.py` | `…/orchestration/uploads/scene_imports.py` | 3 |
| `frontend/src/app/(legacy)/**`, `features/{scene,review,jobs}`, `components/ui`, UI cũ trong `features/viewer` | đã xoá (lấy lại từ git trước commit xoá) | 4b |

## Risks And Recovery

- **Vòng lặp import / hằng đường dẫn theo độ sâu thư mục** (`parents[N]`) khi dời module Python → sửa hằng, thêm test
  khẳng định đường dẫn có thật, import từng module trong tiến trình mới theo cả hai thứ tự.
- **Đổi hợp đồng HTTP ngoài ý muốn** → so OpenAPI và thứ tự route với baseline sau pha 2, 3.
- **Xoá nhầm code Studio còn dùng** → danh sách xoá lấy từ đồ thị import (không tới được từ trang Studio); `tsc`,
  `eslint`, `vitest`, `next build` sau khi xoá.
- **Stack local đang chạy bản module cũ** → khởi động lại `r2s-stack`, kiểm `/health` và log worker.
- Recovery: mỗi bước một commit nên `git revert <commit>` từng bước; không có thay đổi dữ liệu/DB.

## Progress

- [x] Pha 0: fetch, baseline test, baseline OpenAPI, bản ghi này.
- [ ] Pha 1: thư mục gốc và tài liệu.
- [ ] Pha 2: `src/api/product/`.
- [ ] Pha 3: orchestration theo miền.
- [ ] Pha 4a: validation / duyệt / phát hành trong UI mới.
- [ ] Pha 4b: xoá UI cũ.
- [ ] Pha 5: đồng bộ tài liệu cấu trúc.

## Decisions

- 2026-10-02 (owner): `PRODUCT.md` dời thành `docs/STUDIO_UX_SPEC.md`.
- 2026-10-02 (owner): file lẻ của `orchestration` xếp theo miền nghiệp vụ, không tạo thư mục `studio/`.
- 2026-10-02 (owner): đưa phần duyệt / phát hành / validation vào UI mới rồi xoá hẳn các trang cũ và toàn bộ code chỉ
  UI cũ dùng (thay D-10 "giữ legacy sau cờ `LEGACY_UI=1`").
- 2026-10-02: `storage.py`, `benchmark.py`, `environment.py` giữ ở gốc `orchestration` (hạ tầng dùng chung; hai file
  đầu đã là vị trí chuẩn trong ARCHITECTURE).
- 2026-10-02: 7 file `requirements*`, `Makefile.studio`, `Dockerfile.gpu` giữ ở gốc — cặp với file của ban tổ chức
  cùng tên; ARCHITECTURE không cho tạo thư mục cấp cao nhất mới.

## Validation

- Focused proof: ghi theo từng pha ở mục Result.
- Integration or end-to-end proof: khởi động lại stack local; trình duyệt cho pha 4.
- Repository-required checks: `ruff check`, `ruff format --check`, `pytest tests/`, `scripts.check_foundation`,
  `scripts.check_contract_mirror`; frontend `lint`, `typecheck`, `test`, `build`.

## Result

Chưa xong — cập nhật sau mỗi pha.
