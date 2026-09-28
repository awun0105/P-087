# Execution Plan: MVP Studio — video → 3DGS scene, kịch bản demo đã xử lý sẵn

Date: 2026-09-29

## Status

Active — chờ owner chốt privacy attestation (xem Decisions/Open) trước Phase 2.

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
  publish stage events), `rgb/frame_extraction.py` (FFmpeg `video_decode`, cần
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
- Privacy gate chặn video user → cần quyết định owner, không tự bỏ gate.
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
- [ ] Phase 1 — upload + prepare input + FRAME_EXTRACT
- [ ] Phase 2 — progress + delivery API
- [ ] Phase 3 — demo import + replay
- [ ] Phase 4 — Studio UI mới
- [ ] Phase 5 — GPU packaging + Aisle_CW run

## Decisions

- 2026-09-29 (owner Quân): giữ UI hiện tại, UI mới tách riêng; demo pre-processed
  qua cùng pipeline, chạy trên GPU thuê qua SSH rồi import.
- 2026-09-29 (owner Quân): UI hiện tại giữ code nhưng ẩn/ngắt khỏi app để dùng lại
  sau; bật lại bằng flag, không xóa.
- 2026-09-29 PROPOSAL: chỉnh sửa ở mức Gaussian bằng SuperSplat nhúng, export
  PLY/SOG; chưa có SceneObject/collider/Isaac. Cần Product Owner ghi vào
  `docs/decisions/` vì khác PRD P0.
- OPEN: privacy attestation cho video user upload (backend yêu cầu
  `VERIFIED_ANONYMIZED` + QA acceptance).

## Validation

- Focused proof: pytest cho dispatch/worker/upload/progress/demo import; vitest
  cho màn hình Studio; `ruff check`, `ruff format --check`, `tsc`, `eslint`.
- Integration: upload video nhỏ → worker local (tools giả lập qua seam) → preview.
- Runtime: GPU run thật Aisle_CW, browser mở scene trong Studio (ghi riêng).

## Result

Chưa có.
