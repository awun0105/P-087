# Execution Plan: Dọn cấu trúc repository (thư mục gốc, API, orchestration, UI cũ)

Date: 2026-10-02

## Status

Completed (02/10/2026) — nhánh `feat/pipeline-v2`, chưa push. Việc còn mở nằm ở mục *Follow-up* cuối file.

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
- Bổ sung 02/10 (owner yêu cầu giữa chừng): dọn `data/` — xoá phần trùng và phần cũ không dùng, gom thư mục bằng chứng
  lẻ, viết bản đồ `data/`. `data/` không nằm trong git nên phần xoá không hoàn tác được.

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
| `data/{rec05_smoke,rec06_smoke,rec07_axis_evidence_20260927,rec05_similarity_audit_20260927,rec06_scale_experiment_20260927,eval_runs}` | `data/evidence/<cùng tên>` | data |
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
- [x] Pha 1: thư mục gốc và tài liệu (commit `ebb7443`, `c3d2803`).
- [x] Pha 2: `src/api/product/`.
- [x] Dọn `data/` (ngoài kế hoạch ban đầu, owner yêu cầu 02/10).
- [x] Pha 3: orchestration theo miền.
- [x] Pha 4a: validation / duyệt / phát hành trong UI mới (commit `e27fc2b`).
- [x] Pha 4b: xoá UI cũ.
- [x] Pha 5: đồng bộ tài liệu cấu trúc.

## Decisions

- 2026-10-02 (owner): `PRODUCT.md` dời thành `docs/STUDIO_UX_SPEC.md`.
- 2026-10-02 (owner): file lẻ của `orchestration` xếp theo miền nghiệp vụ, không tạo thư mục `studio/`.
- 2026-10-02 (owner): đưa phần duyệt / phát hành / validation vào UI mới rồi xoá hẳn các trang cũ và toàn bộ code chỉ
  UI cũ dùng (thay D-10 "giữ legacy sau cờ `LEGACY_UI=1`").
- 2026-10-02: `storage.py`, `benchmark.py`, `environment.py` giữ ở gốc `orchestration` (hạ tầng dùng chung; hai file
  đầu đã là vị trí chuẩn trong ARCHITECTURE).
- 2026-10-02: tách `routes_product.py` theo chủ đề nên **thứ tự đăng ký** của 7 operation đổi so với trước (kế hoạch
  ban đầu ghi "giữ nguyên thứ tự"). Chấp nhận vì không có hai route nào chồng nhau: ánh xạ URL → hàm xử lý của 5.229
  URL mẫu (mọi tham số thử cả tên trùng đoạn tĩnh như `content`, `objects`, `catalog`) trùng hoàn toàn baseline.
- 2026-10-02 (owner): `data/` — xoá mọi file/artifact trùng hoặc cũ không dùng, chỉ giữ thứ phục vụ demo; bố cục chỉ gom
  phần lẻ và viết bản đồ, **không** đổi tên thư mục mà cấu hình/venv đang trỏ tới.
- 2026-10-02: không xoá scene nào trong kho artifact và không đụng `raw/`⇄`normalized/` của TorWIC (xem Result).
- 2026-10-02: 7 file `requirements*`, `Makefile.studio`, `Dockerfile.gpu` giữ ở gốc — cặp với file của ban tổ chức
  cùng tên; ARCHITECTURE không cho tạo thư mục cấp cao nhất mới.

## Validation

- Focused proof: ghi theo từng pha ở mục Result.
- Integration or end-to-end proof: khởi động lại stack local; trình duyệt cho pha 4.
- Repository-required checks: `ruff check`, `ruff format --check`, `pytest tests/`, `scripts.check_foundation`,
  `scripts.check_contract_mirror`; frontend `lint`, `typecheck`, `test`, `build`.

## Result

Xong cả năm pha và phần dọn `data/`. Chi tiết và bằng chứng theo từng pha:

### Pha 1 — thư mục gốc và tài liệu (xong)

- Gốc còn 29 file được track (trước 31). `PRODUCT.md` → `docs/STUDIO_UX_SPEC.md` (46 chỗ / 27 file đổi tên, 35 link
  trong file viết lại), `CONTEXT.md` → `docs/CONTEXT.md` (10 link), notices gộp một file, README có mục "Bản đồ thư
  mục gốc", `AGENTS.md` §2 có dòng authority cho đặc tả UX.
- VERIFIED: `ruff check`/`ruff format --check` exit 0; `scripts.check_foundation` và `scripts.check_contract_mirror`
  exit 0; frontend `tsc` và `eslint` exit 0; kiểm link tương đối của 14 tài liệu sống: không link hỏng. `WORKLOG.md`
  có 7 link hỏng **từ trước** (trỏ file đã bị xoá ở các đợt cũ) — không sửa vì là bản ghi lịch sử.

### Pha 2 — `src/api/product/` (xong)

- `routes_product.py` (669 dòng) → `product/{projects,jobs,artifacts,scene,review,deps}.py` + `__init__.py`; `routes.py`
  đổi một dòng import; 3 file test patch `src.api.product.deps`.
- VERIFIED: OpenAPI (sắp key) trùng byte với baseline (71 path / 77 operation / 142 schema); ánh xạ URL → hàm xử lý
  trùng baseline trên 5.229 URL mẫu; `pytest tests/ -q` 1125 passed / 40 skipped; `ruff`, `check_foundation`,
  `check_contract_mirror` exit 0; `import src.main` và `jobs.worker_cli` trong tiến trình mới chạy được.

### Pha 3 — orchestration theo miền (xong)

- 8 module dời bằng `git mv` theo bảng ánh xạ; 32 chỗ import ở 20 file sửa theo; hai hằng đường dẫn tính theo độ sâu
  thư mục sửa (`scene/objectify.py` `parents[4]`, `review/simulation_package.py` `parents[3]`); 3 chuỗi monkeypatch
  trong test trỏ `…jobs.stage_views.job_bundle`. Gốc `orchestration/` còn `storage.py`, `benchmark.py`,
  `environment.py`.
- Test mới `tests/test_orchestration/test_module_paths.py`: bốn đường dẫn runner (`LIFT_RUNNER`, `CONVEX_RUNNER`,
  `INPAINT_RUNNER`, `HYBRID_RUNNER`) phải trỏ tới file có thật.
- VERIFIED: 17 module (kể cả `src.main`, `jobs.worker_cli`, `jobs.runner`, từng module vừa dời, `projects.registry`)
  import được khi là điểm vào đầu tiên của một tiến trình mới — không có vòng lặp import; `--help` của
  `scripts/scene/reobjectify.py` và `eval.geometry.click_error` chạy được; OpenAPI và ánh xạ URL → hàm trùng baseline;
  `pytest tests/ -q` 1126 passed / 40 skipped; `ruff`, `check_foundation` exit 0; khởi động lại `r2s-stack`: `/health`
  200, worker chạy, log không có lỗi import.
- Chưa kiểm: chạy một job thật qua worker trên GPU sau khi dời (các bước dùng runner theo đường dẫn file đã có test
  khẳng định đường dẫn, nhưng chưa có lượt chạy thật).

### Dọn `data/` (xong phần an toàn)

- Đã xoá (kiểm trước: DB và JSON trong kho artifact không trỏ tới; 3 job liên quan đã `SUCCEEDED`, không có yêu cầu
  scene đang chờ/chạy):
  - `data/studio_local/workers/*` — bản sao làm việc, log và checkpoint của job đã xong, import, backfill: 2,8 GB.
  - `data/demo/{tmp,current,local_job,aisle_cw_params}` — bundle xuất thử cũ và video cắt tạm: 206 MB (giữ
    `data/demo/library` mà stack đang dùng).
  - `data/studio_local/qa/profile` — hồ sơ Chrome của script QA: 300 MB.
  - `data/torwic_slam/derived/aisle_cw/{rec03_smoke_workspace_sub100_200,rec04_smoke_work_10,rec04_smoke_work_10b,rec04_smoke_work_10c}`
    — workspace chạy thử COLMAP/Brush hồi tháng 9: 553 MB. Giữ `rec03_smoke_artifacts_sub100_200`,
    `rec04_smoke_artifacts_10c` (bằng chứng đã publish) và mọi thư mục code còn trỏ tới (`benchmark_split.json`,
    `rec07_prefusion_sub100_119`, `rec07_smoke_sub100_104`, `rec09_alignment_*`).
  - 160 thư mục job do test để lại trong `data/artifacts/jobs` và 3 thư mục upload rỗng không có trong DB.
- Gộp 926 bản sao trùng nội dung trong `data/studio_local/artifacts` bằng hardlink (kho ghi bằng file tạm + đổi tên và
  từ chối ghi đè nên không có sửa tại chỗ): 1,3 GB; mọi đường dẫn artifact giữ nguyên.
- Gom 6 thư mục bằng chứng lẻ vào `data/evidence/`; README có mục "Bản đồ thư mục `data/`".
- VERIFIED: ổ đĩa trống 10,4 GB → 15,6 GB; `data/` 23 GB → khoảng 18 GB. Sau khi dọn: 87/87 artifact mà 13 scene tham
  chiếu qua API khớp checksum SHA-256; đọc SceneIR và preview của 3 scene demo qua API được; `/health` 200.
- Chưa làm, cần owner chọn:
  - **Xoá scene cũ trong Studio.** 13 scene chiếm 4,2 GB; chưa có thao tác xoá scene được hỗ trợ (xoá tay DB + kho dễ
    làm hỏng registry). Các job "Đo chất lượng A/D3/D5" và `job-ac2bfd924cc6` là nguồn của số đo trong `eval/results/`.
  - `data/rec07_runtime` (1,6 GB, môi trường Open3D cho tooling LiDAR offline): không thuộc luồng demo nhưng cần cho
    REC-07/08/09.
  - Ảnh trùng giữa `torwic_slam/raw` và `normalized` (khoảng 1,5 GB) là do thiết kế dataset; không gộp bằng hardlink vì
    công cụ ghi đè tại chỗ ở `normalized` sẽ làm hỏng `raw`.
- Phát hiện: test backend ghi job vào `data/artifacts` (kho mặc định) mỗi lần chạy — rác tích lại, chưa sửa.

### Pha 4a — validation / duyệt / phát hành trong UI mới (xong)

- Backend (chỉ thêm): `ReviewState.isaac_runtime_proof`; quy tắc `has_isaac_runtime_proof` ở
  `orchestration/review/lifecycle.py` dùng chung cho `/review-state` và `/jobs/{id}/validation`. Quy tắc cũ chỉ so đúng
  chuỗi `UNVERIFIED`; nay thiếu khoá `isaac_sim` hoặc giá trị bắt đầu bằng `UNVERIFIED`/`TBD` đều là chưa có bằng chứng
  (validator SIM-06 trên `origin/feat/sim` ghi `UNVERIFIED (local environment)`).
- Frontend: parser chuẩn hoá ở biên API cho `ReviewStateView`; `ValidationReportCard` (S10), `TraceList`, `CopyButton`;
  `ReviewPanel` (cảnh báo kèm thông điệp/bằng chứng, nguồn kết quả của quyết định), thẻ `Bản phát hành` (S12).
- VERIFIED: OpenAPI khác baseline đúng một thuộc tính `isaac_runtime_proof`; pytest review 36 passed (5 case mới);
  `vitest` 39 file / 236 test (9 test mới, dùng `fixtures/validation_report/*.json` qua parser thật); `tsc`, `eslint`,
  `next build` exit 0.
- VERIFIED — trình duyệt, môi trường cô lập (bản gương hardlink của kho artifact + bản sao DB, không ghi vào kho thật;
  gắn một `ValidationReport` **tổng hợp ghi rõ UNVERIFIED** qua `record_validation_report`), 18/18 bước: Editor chỉ đọc;
  Reviewer thấy 4 check + 2 Start–Goal, môi trường UNVERIFIED nguyên văn, bằng chứng và Nguồn kết quả mở được, thẻ
  không tràn ngang; nút duyệt khoá tới khi chấp nhận cảnh báo; duyệt → phát hành → tải zip 24 MB; URL cũ chuyển hướng.
- Limits: chưa có `ValidationReport` từ Isaac thật; link tải từng bằng chứng chưa có (chỉ hiện URI + nút chép vì chưa
  kiểm allow-list cho artifact bằng chứng).

### Pha 4b — xoá UI cũ (xong)

- Xoá 47 file: 38 file nguồn (`app/(legacy)/**`, `components/ui/*`, 4 file lẻ trong `components/`, `features/{scene,
  review,jobs}`, 9 file UI cũ trong `features/viewer`) và 9 file test của chúng; bỏ 8 hàm client chỉ UI cũ gọi, cờ
  `LEGACY_UI`, khối token theme tối cũ và `.legacy-root` trong `globals.css`. Giữ redirect URL cũ về `/overview`.
- Giữ: engine 3D dùng chung trong `features/viewer` (7 file), 16 component shadcn chưa dùng, `StudioHeader.tsx`,
  `lib/contracts/api.ts`, dependency `three`/`@react-three/*` (còn file import).
- VERIFIED: `npm run typecheck` (có `next typegen`), `eslint` exit 0; `vitest` 30 file / 174 test; `next build` còn 15
  route, không còn trang cũ; `rg` không còn import tới đường dẫn đã xoá; trình duyệt 18/18 bước (6 trang chính, 4 tab
  của scene, màn xem bước Hình học & collision, 6 URL cũ chuyển hướng, trang 404).

### Pha 5 — tài liệu cấu trúc (xong)

- `ARCHITECTURE.md` (cây `src/api`, `orchestration`, `frontend/src`), `README.md` (bản đồ thư mục gốc, bản đồ `data/`,
  Project Structure), `docs/README.md`, `docs/STUDIO_UX_SPEC.md` (D-10 sửa, hiện trạng S10–S12, 5 link trỏ file đã
  xoá chuyển sang phần thay thế), `TRACK.md` của EX-PRODUCT, `docs/CONTEXT.md`, `docs/WIREFRAME_AND_UI_FLOW.md`.
- VERIFIED: kiểm link tương đối của các tài liệu sống: không link hỏng. Backend sau cùng: `pytest tests/ -q` 1131
  passed / 40 skipped; `ruff`, `check_foundation`, `check_contract_mirror` exit 0.

## Follow-up (cần owner quyết)

1. **Chặn duyệt khi báo cáo không có bằng chứng Isaac thật?** Hiện chỉ cảnh báo; lượt thử cho thấy Reviewer duyệt và
   phát hành được gói dựa trên báo cáo tổng hợp.
2. **Xoá scene cũ trong Studio** (13 scene, 4,2 GB): cần một thao tác xoá scene được hỗ trợ và danh sách scene giữ lại.
3. **Endpoint backend chỉ UI cũ gọi** (`/projects…`, `/jobs/{id}/transitions`, `/validation`, `/review`,
   `/review/{action}`, `/release`): giữ hay bỏ — là hợp đồng API có test riêng của EX-PRODUCT.
4. **Nối validator SIM-06/07** (`origin/feat/sim`) vào luồng Studio để có báo cáo thật.
5. **Test backend để rác vào `data/artifacts`** mỗi lần chạy (4 thư mục job một lượt).
6. Chạy một job thật qua worker trên GPU sau khi dời module `orchestration` (đã có test đường dẫn runner, chưa có lượt
   chạy thật).
