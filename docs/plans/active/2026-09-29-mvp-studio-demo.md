# Execution Plan: MVP Studio — video → 3DGS scene, kịch bản demo đã xử lý sẵn

Date: 2026-09-29

## Status

Active.

## Outcome

Trước deadline MVP (4 ngày, tới 2026-10-02), có một **Studio UI mới** (tối giản,
beige + cam) chạy song song với UI hiện tại, gồm hai chế độ trên cùng một luồng:

1. **Người dùng thật:** upload video → chọn video → pipeline EX-REC thật
   (tách frame → camera pose COLMAP → train 3DGS Brush → preview) với tiến trình
   theo stage → mở scene 3DGS trong editor kiểu SuperSplat (chọn/xóa/di chuyển
   Gaussian, đo) → export PLY/SOG.
2. **Kịch bản demo:** cùng các màn hình, nhưng dùng artifact của TorWIC
   `Aisle_CW` đã được chạy **qua chính pipeline này** trên GPU thuê (SSH), import
   vào app; tiến trình phát lại nhanh; UI gắn nhãn "Kịch bản demo · kết quả đã xử
   lý trước".

## Context

- Yêu cầu owner (EX-REC, Quân) 2026-09-29 trong session Claude Code: giữ UI hiện
  tại, xây UI mới; tận dụng API hiện có, thêm API khi cần; demo pre-processed nhưng
  đi đúng luồng user thật; đóng gói backend/pipeline để chạy trên GPU qua SSH.
- PRD §4.1/§4.3 (P0 gồm SceneObject/collider/Isaac) rộng hơn MVP này; EX-SCENE và
  EX-SIM chưa có producer. Đây là **thu hẹp scope cho demo MVP**, cần Product Owner
  (Cường) ghi nhận vào `docs/decisions/` — xem Decisions.
- Code nền: `src/services/reconstruction/preview_worker.py` (COLMAP→Brush→preview,
  publish stage events), `rgb/frames/frame_extraction.py` (FFmpeg `video_decode`, cần
  quality report + `PrivacyDispatchProof`), `orchestration/jobs/{dispatch,worker_cli,preview_cli}.py`
  (queue consumer Codex để dở, chưa commit), viewer PlayCanvas trong
  `frontend/src/features/viewer/`.
- Reference editor: `../private/playcanvas-supersplat/supersplat` v3.4.2, MIT, hỗ
  trợ `?load=<url>` (`src/main.ts:296`).

## Scope

In scope:

- Hoàn thiện queue worker chưa commit (format, regression, commit).
- API upload video (stream vào artifact store, checksum) + tạo InputManifest.
- Worker stage chuẩn bị input: quality → privacy proof → `FRAME_EXTRACT` → gắn
  frame set vào job → preview worker hiện có.
- API tiến trình theo stage (đọc stage events đã publish) và phục vụ file PLY/SOG.
- Demo: import artifact đã xử lý (script import có checksum), job demo có cờ
  `demo`, API phát lại tiến trình nhanh.
- Frontend Studio mới trong route group riêng (`frontend/src/app/(studio)/...` hoặc
  `/studio`), theme token mới, 3 màn hình: Scenes, Scene mới (upload/chọn video,
  progress), Scene editor (nhúng SuperSplat editor self-host cùng origin).
- Script/đóng gói chạy pipeline trên GPU qua SSH + hướng dẫn.

Out of scope:

- Xóa/đổi tên file route hoặc component UI hiện tại (chỉ ẩn sau flag).
- SceneObject/collider/OpenUSD/Isaac (EX-SCENE/EX-SIM).
- Metric confirmation qua backend, LiDAR evidence, review/release lifecycle mới.
- Lưu edited Gaussian revision lên backend (export chỉ tải về client) — follow-up.

## Approach

Phase 0 — Chốt phần Codex để dở (independent)
- ruff format 3 file; regression cho `dispatch.prepared_frame_reference`,
  `require_profile`, `worker_cli.dispatch_next`, `transition_job(expected_checksum)`,
  `persistence.job_ids_after`; chạy focused pytest; commit.

Phase 1 — Input pipeline backend (REC ↔ PRODUCT)
- `POST /api/v1/product/projects/{id}/videos` (multipart, giới hạn size, stream +
  sha256) → artifact `raw_input`; `GET .../videos`.
- Job tạo từ video đã upload; worker thêm bước prepare: probe/quality → privacy
  proof (theo quyết định owner) → `RGBFrameExtractor` (`video_decode`) → publish
  `FRAME_EXTRACT` stage vào JobManifest → dispatch preview như hiện tại.
- Sampling frame cho COLMAP (giới hạn số frame) nếu `quality_accepted` giữ quá
  nhiều frame — cần kiểm config hiện có trước khi thêm.

Phase 2 — Progress + delivery API
- `GET /jobs/{id}/progress`: stage list + trạng thái từ JobManifest và attempt
  events; ETA không bịa, chỉ elapsed.
- Phục vụ delivery PLY/SOG của preview qua route allow-list hiện có.

Phase 3 — Demo scenario
- Script `scripts/demo/import_prepared_run.py`: import output GPU run (frames,
  poses, visual, preview, events) vào artifact store, tạo project/job demo, verify
  checksum qua REC public verifier. Không dùng `evaluation_only`.
- Job demo mang nhãn demo; API progress trả timeline thật đã ghi và frontend phát
  lại nhanh.
- Tạm dùng `rec04_smoke_work_10b` để dựng UI trước khi có GPU run đầy đủ.

Phase 4 — Studio UI mới
- UI cũ: giữ nguyên file/component, **ẩn khỏi app** — Studio mới là trang gốc; các
  route cũ (`/projects`, `/jobs/...`, `/viewer`) bị chặn/redirect về Studio sau một
  feature flag (ví dụ `NEXT_PUBLIC_LEGACY_UI=1` để bật lại). Kiểm cơ chế Next 16
  (`proxy.ts`/middleware) theo version thật trước khi làm; không xóa/đổi tên file.
- Theme token beige/cam, viewport ấm tối; font Inter/Geist.
- `/studio` (Scenes) · `/studio/new` (upload/chọn video + guided steps + progress)
  · `/studio/scenes/[jobId]` (SuperSplat editor nhúng, export).
- SuperSplat build static vào `frontend/public/supersplat/` với MIT notice; load
  preview qua `?load=`.

Phase 5 — Packaging GPU/SSH + demo run
- Dockerfile/script cài COLMAP, Brush, splat-transform (theo pinned versions hiện
  có) hoặc hướng dẫn venv; chạy Aisle_CW → export bundle → import local.

## Risks And Recovery

- COLMAP fail trên video tự quay → error stage rõ ràng, demo không phụ thuộc live.
- Train lâu / GPU cloud chưa sẵn → demo dùng smoke artifact tạm, thay khi có run.
- Privacy gate: owner chốt chế độ MVP self-attestation (xem Decisions).
- SuperSplat build/iframe cross-origin → self-host cùng origin; fallback là viewer
  PlayCanvas hiện có (chỉ xem + đo).
- Rollback: mọi thay đổi additive; UI cũ và API cũ giữ nguyên.

## Progress

- [x] Phase 0 — chốt queue worker Codex (2026-09-29, chưa commit — chờ owner):
  ruff format 3 file; thêm `tests/test_orchestration/test_prepared_queue.py`
  (8 regression: frame ref, profile, stale CAS, paging, skip/claim/failure);
  sửa `tests/integration/test_product_rec_preview.py` thiếu `completed_at` (lỗi
  có sẵn từ `f011254`, contract không đổi). `pytest tests -q`: 831 passed,
  22 skipped; `ruff check src tests` + `ruff format --check` pass.
  Còn lại: `frontend/src/components/job-lifecycle.tsx` vẫn có nút mock-worker
  (backend trả 409) — UI cũ sẽ bị ẩn ở Phase 4 nên không sửa.
- [x] Phase 1 — upload + prepare input + FRAME_EXTRACT (2026-09-29):
  REC stride (`5f0bf63`), SelfAttestedPrivacyGate (`70bfd42`), `prepare_cli`
  (`d9f0e38`); PRODUCT privacy theo project (`8dad63a`), StreamingPublication
  (`9facadb`), uploads + r2s_uploads (`2d65ec5`), project từ upload (`89ded01`),
  API `/uploads`, `/scenes/from-upload` (`29bd650`), reducer prepare (`9afcabf`),
  worker `run_video_job` (`066448b`). Proof: FFmpeg thật qua subprocess REC CLI,
  preview COLMAP/Brush là stub (tests/integration/test_upload_to_prepared_job.py).
- [x] Phase 2 — progress API (2026-09-29): REC `--progress-file` (`7a33f27`),
  worker cập nhật stage đang chạy (`9ab074b`), `GET /jobs/{id}/progress`
  (`fbdb147`), `GET /scenes` (`552790a`). Delivery SOG dùng API artifact sẵn có.
- [~] Phase 3 — demo bundle (2026-09-29): API `/demo`, `/demo/files/{name}`
  (`107922c`), script export `job`/`smoke` (`8929a23`). Bundle tạm local từ smoke
  `rec04_smoke_work_10b` (origin=smoke_run, không commit vì data/ ignored). Còn:
  export từ job GPU thật Aisle_CW (Phase 5).
- [ ] Phase 4 — Studio UI mới
  - [x] Vendor SuperSplat 3.4.2 nguyên bản vào `frontend/vendor/supersplat/`
    (`09ab2ee`), script `npm run build:editor` → `public/editor/` (`061a5cf`),
    theme nâu ấm + cam, nền viewport #1f1b17, splat chọn màu cam (`f26c675`).
    Build rollup pass; tsc pass; eslint 0 error. Chưa mở editor trong browser.
  - [x] UI cũ vào route group `(legacy)` (`e0a3dff`), ẩn bằng `redirects()` trong
    next.config + flag `LEGACY_UI=1` (`a112f1e`; bỏ `proxy.ts` vì buộc Next buffer
    body 10MB). Gỡ Publish superspl.at khỏi editor (`7ae8d37`).
  - [x] Studio: primitives shadcn-adapt (`34e62fc`), Scenes (`f77afff`), demo 4 bước
    có hướng dẫn + phát lại theo thời lượng thật (`201d53e`), Scene mới với upload
    đo tiến độ thật + xác nhận dữ liệu (`2b5a208`), trang scene theo stage + hủy/thử
    lại + editor (`77b38e7`), WebGPU check + fallback viewer WebGL2 (`e98f23d`),
    route handler stream upload qua Next (`7b67e7c`).
  - [x] Sửa viewer có sẵn: `settings: {}` làm supersplat-viewer crash → dùng
    `defaultSettings("environment")` (`870aed5`).
- [~] Phase 5 — packaging (2026-09-29): runtime manifest từ version thật
  (`b6ec915`, fix checksum `8871b3f`), processing config local/GPU, `run_stack.sh`,
  env mẫu, runbook `scripts/gpu/README.md` (`2ec7ba0`). **Local E2E thật** trên
  Quadro T2000: video Aisle_CW 200 frame upload → prepare 16 s → COLMAP 53 s →
  Brush 3000 bước 89 s → preview SOG ~1 MB (job-95697015634c, `data/studio_local`),
  export demo bundle origin=pipeline_job. Còn: chạy cấu hình GPU 30k trên máy thuê,
  export bundle chính thức.

## Decisions

- 2026-09-29 (owner Quân): giữ UI hiện tại, UI mới tách riêng; demo pre-processed
  qua cùng pipeline, chạy trên GPU thuê qua SSH rồi import.
- 2026-09-29 (owner Quân): UI hiện tại giữ code nhưng ẩn/ngắt khỏi app để dùng lại
  sau; bật lại bằng flag, không xóa.
- 2026-09-29 PROPOSAL: chỉnh sửa ở mức Gaussian bằng SuperSplat nhúng, export
  PLY/SOG; chưa có SceneObject/collider/Isaac. Cần Product Owner ghi vào
  `docs/decisions/` vì khác PRD P0.
- 2026-09-29 (owner): adapt nguyên repo SuperSplat (không chỉ tham khảo) và dùng
  skill ui-ux-pro-max + `private/UI-UX` (shadcn dashboards, MIT) làm reference UI.
  Đây là chỉ định rõ của owner, vượt quy tắc chung "không copy cả reference repo";
  provenance ở `frontend/vendor/supersplat/PROVENANCE.md`.
- 2026-09-29 Design: skill đề xuất Minimalism & Swiss; palette navy/xanh của skill
  bị thay bằng beige/cam theo owner (tham chiếu preset `tangerine` của
  next-shadcn-admin-dashboard). Chrome sáng beige, viewport/editor nâu than ấm.
  Font Inter; icon SVG (lucide), không emoji.
- 2026-09-29 (owner): commit từng nhóm thay đổi nhỏ liên tục.
- 2026-09-29 (owner): MVP chỉ cần luồng chạy được để demo; privacy QA gate và
  review/duyệt scene 2 kỹ sư là luồng nghiệp vụ, chưa implement và **không được
  chặn** upload → xử lý → xem scene. Cách làm: setting chế độ MVP
  (self-attestation của người upload đủ để dispatch), ghi nhãn "tự khai (MVP)"
  trong dữ liệu/UI, không giả `VERIFIED_ANONYMIZED` do QA. Code gate giữ nguyên,
  tắt setting để quay lại luồng nghiệp vụ.
- 2026-09-29 (owner): privacy MVP = cách 1 — người upload tick xác nhận video không
  chứa mặt/biển số (hoặc đã làm mờ), hệ thống ghi nhận là tự khai rồi chạy. Chưa có
  code auto detect/blur (PRD §2.3/NFR-05 không bắt buộc cho MVP).
- 2026-09-29 Audit follow-up (sau MVP): xóa người/vật thể + inpainting, tham khảo
  `private/spirula-studio` (commit d8e6a267). Kết quả audit:
  - License **GPLv3** → không copy code vào repo MIT; chỉ tham khảo thuật toán hoặc
    gọi binary qua subprocess (INTEGRATION_PLAYBOOK §7.2).
  - Spirula **không có inpainting**. Nó xóa vật thể động (người, xe) *trước khi
    train*: text prompt ("person") → SAM 2/3 hoặc lang-sam/BiRefNet sinh mask theo
    frame → `masks/` cạnh ảnh → trainer bỏ qua loss ở pixel bị mask; nền được lấp
    bằng các góc nhìn khác (`src/sam/README.md`, `docs/datasets.md` §Masks,
    `docs/notes/mask-editor.md`).
  - Brush source (`private/brush` 5f6e45cc) cũng đọc `masks/` cho COLMAP dataset
    (`AlphaMode::Masked`); binary runtime đang dùng (build 2025-09-15) chưa kiểm
    có hỗ trợ không — UNKNOWN.
  - Hướng đề xuất: stage mask người/vật thể động sau `ST-FRAME-EXTRACT` bằng SAM2
    (Apache-2.0, EX-SCENE đã dùng) + text detector → Brush train có mask. Vùng nền
    chưa từng thấy vẫn bị thủng/floater; inpainting 3D thật là P1/P2 (BRIEF §6,
    INTEGRATION_PLAYBOOK §5.4) và cần nguồn khác ngoài Spirula.
  - MVP chỉ có xóa Gaussian thủ công trong editor SuperSplat, không inpainting.
- OPEN — CONFLICT / AUTHORITY GAP (ghi 2026-09-29 sau khi đọc docs/execution):
  quyết định MVP self-attestation ở trên mâu thuẫn với
  `docs/execution/tracks/ex_product/TRACK.md` §Authority Gates ("source-rights/
  privacy gates không được bypass cho demo") và Contract §3.3.1 (QA/Validation
  Lead Đạt chấp nhận `VERIFIED_ANONYMIZED` trước public/demo use). Cần Product
  Owner (Cường) + QA Lead (Đạt) xác nhận và ghi `docs/decisions/`. Phần an toàn:
  demo TorWIC `Aisle_CW` đi theo đường chuẩn (privacy report cho dataset public do
  QA chấp nhận); self-attestation cho upload tùy ý chỉ bật bằng setting, mặc định tắt.
- 2026-09-29 Demo: dùng demo bundle (output thật từ GPU run, có manifest +
  checksum) phục vụ qua API riêng; Studio dựng cùng màn hình từ job thật hoặc
  bundle. Trước khi có GPU run đầy đủ, bundle tạm từ smoke `rec04_smoke_work_10b`.

- [x] Phase 6 — cấu hình xử lý chung + bảng thông số (2026-09-29, yêu cầu owner):
  REC chọn frame nét nhất theo cửa sổ + chỉ decode frame được chọn (`de5ce26`),
  prepare lấy mẫu theo fps × thời lượng (`601066e`); file chung
  `configs/product/processing_presets_v1.json` + module `processing` (preset,
  đo máy worker, ước lượng VRAM/RAM/đĩa heuristic, "tối đa cho máy này") (`403fe2b`);
  config riêng từng job `config/processing.json` = `config_checksum` (`197ef2a`),
  worker validate lại theo file chung (`75a12f7`), heartbeat đo máy (`6b20292`);
  API options/evaluate + chặn cấu hình đỏ ở server (`3b0e65a`); UI bảng thông số
  chỉnh được (Scene mới) / chỉ đọc (demo) (`d03a7f2`, `7de978b`); bundle ghi thông
  số + máy (`e744840`); nén SOG bằng WebGPU (`c4a70b2`): 7,7 s so với >15 phút CPU.
  Job thật `job-ac2bfd924cc6` (50 frame, 7k bước, 960px, T2000): tổng 7 phút 41 s;
  bundle `data/demo/aisle_cw_params` (pipeline_job, có thông số).
- [x] Phase 7 — gộp kịch bản demo vào Scene mới (2026-09-29, yêu cầu owner):
  thư viện video mẫu `PRODUCT_DEMO_DIR` = thư mục chứa nhiều bundle, API
  `/samples`, `/samples/{id}`, `/samples/{id}/files/{name}` thay `/demo` (`0530e0b`,
  runbook `8b5cf8e`). Bước "Tải video lên" có lưới "Hoặc thử với video mẫu"; chọn
  mẫu → Chọn video (video, xác nhận dữ liệu, thông số chỉ đọc) → Xử lý (phát lại
  artifact thật theo tỉ lệ thời lượng đo được) → Mở scene tại
  `/samples/{id}/scene` (`06653ff`…`94cbdee`). `/new?sample=<id>` chọn sẵn mẫu;
  `/demo` redirect về `/new`; Scenes home và header bỏ mục "Kịch bản demo".
  QA headless Chrome (CDP): /demo→/new, chọn mẫu, phát lại, link scene, editor
  fallback WebGL2 đều hiển thị. Lưu ý: commit `06653ff` vô tình gồm cả phần xóa
  DemoFlow/GuideCallout/route demo (đã stage trước); không rewrite history.
- [x] Phase 8 — dọn cấu trúc repo (2026-09-29, yêu cầu owner; không xóa code):
  audit dựa trên git history (scaffold ban tổ chức = 108 file của `52d85fb`),
  đồ thị import Python/TS, không dựa vào docs. Đã làm: tách fixture/smoke REC
  khỏi thư mục test (`7b787c1`); `merge*.py/sh` → `scripts/torwic/migrations/`
  (`24a5585`); ignore `target/` (`9a56ac1`); `jobs/preview_cli` → `jobs/runner`
  (`1ad9024`); `orchestration/demo` → `samples` (`8b16f27`); `routes_studio.py` →
  package `src/api/studio/` + `deps.py` (`e00ae60`, OpenAPI giữ đủ 35 route);
  `rgb/` chia theo stage `preflight/frames/pose/splat/geometry/canonical`
  (`00bf49e`, docs `581f8d4`, `5fa3a51`); README/CONTEXT (`ad1aaa0`) và
  ARCHITECTURE (`7a08465`) theo checkout thật. Proof: pytest 886 passed / 22
  skipped trước và sau; ruff sạch trừ lỗi có sẵn ở `scripts/check_contract_mirror.py`;
  các CLI `-m` của REC/worker chạy `--help` được; `npm run typecheck` pass.
  Cố ý không làm: đổi tên `orchestration/scene` và tách `routes_product.py`
  (module của Cường, WORKLOG/task link nhiều); chuyển UI "(legacy)" vào
  `legacy/` (thực chất là tính năng P0 PRODUCT-07/07A/09/10 sẽ dùng lại); xóa
  package placeholder SCENE/SIM, `reconstruction/worker.py`, `AddObstacle`/
  `ObjectActions` (owner yêu cầu giữ code dùng sau); bỏ bắt buộc API key LLM
  khi khởi động (validator của `Settings` có test khóa). `import
  scripts.torwic.prefusion_cloud` lỗi thiếu `open3d` là có sẵn từ trước.
  Commit `1ad9024`/`8b16f27` lẫn file do rename stage sẵn; gộp lại vẫn đúng.

## Validation

- Focused proof: pytest cho dispatch/worker/upload/progress/demo import; vitest
  cho màn hình Studio; `ruff check`, `ruff format --check`, `tsc`, `eslint`.
- Integration: upload video nhỏ → worker local (tools giả lập qua seam) → preview.
- Runtime: GPU run thật Aisle_CW, browser mở scene trong Studio (ghi riêng).

## Result

Checkpoint 2026-09-29 (chưa DONE; còn GPU run chính thức và QA editor thật).
Cập nhật sau Phase 6: `pytest tests -q` 885 passed, 22 skipped; ruff/eslint sạch;
`npm run build` pass; vitest 96 passed + 4 fail cũ của UI legacy. QA CDP headless:
bảng thông số tô đỏ khi vượt VRAM/đĩa, demo bước 2 chỉ đọc, bước 3 phát lại đúng
thời lượng thật.

Checkpoint trước:

- Validation đã chạy: `pytest tests -q` 867 passed, 22 skipped; `ruff check` +
  `ruff format --check` (src, tests, scripts/demo, scripts/gpu) pass; frontend
  `npm run typecheck` pass, `eslint .` 0 error (1 warning có sẵn), `npm run build`
  pass; `vitest` 96 passed, 4 failed — cả 4 thuộc UI cũ ReviewLifecycle/Release và
  fail y hệt ở `89e7410` (trước thay đổi của đợt này), UI đó đã ẩn.
- Runtime: API + worker + Next dev chạy local với tool thật; upload 15 MB qua Next
  route handler 201 (checksum khớp); legacy route → 307 về `/`.
- Browser (Chrome headless, SwiftShader): Scenes/Demo/Scene mới render đúng; trang
  scene không có WebGPU → fallback WebGL2 render SOG thật của job local.
- Chưa kiểm: editor SuperSplat trên WebGPU thật (headless không tạo được WebGPU
  device) — cần mở bằng Chrome/Edge có GPU; bước tương tác demo (click) chưa E2E tự
  động; GPU 30k chưa chạy.
- Privacy tự khai + scope Studio: ADR 0002 **Proposed**, chờ Cường/Đạt.
