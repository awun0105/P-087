# T-068: SOG xem nhanh — bản màu bậc 0 và LOD cho job mới

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Xem 3DGS ở các bước và trong Studio hiện ra nhanh và quay mượt trên máy yếu: có bản nhẹ để hiện ngay, bản đầy đủ khi người
dùng muốn.

## Context (đã kiểm trong code và dữ liệu)
- SOG đang phục vụ: 9,8–29,8 MB, 0,54–2,0 triệu splat, màu bậc 3 (3 dải SH thêm) — số đọc từ `meta.json` của SOG trong
  `data/studio_local/artifacts/jobs`. Không job nào có `lod-meta.json`; viewer supersplat 1.35.2 hỗ trợ LOD
  (`node_modules/@playcanvas/supersplat-viewer/dist/viewer.js:11279-11320`).
- SOG preview tạo trong pipeline preview (ref `delivery_ref`, kiểm ở `reconstruction/preview_validation.py:73-98`); SOG hệ mét
  tạo ở finalize (`visual_delivery_ref`, `reconstruction/finalize.py:342,552`). Hàm ghi/kiểm SOG:
  `reconstruction/imports.py:67-129` (`validate_sog_runtime` nhận `expected_sh_bands`).
- splat-transform cố định v3.6.6 (`adapters/voxel.py:230`).

## Thiết kế
1. **Kiểm khả năng công cụ trước** (Step 1): chạy `splat-transform --help` trong runtime của worker local; ghi vào report các
   tuỳ chọn có sẵn cho (a) bỏ dải SH, (b) xuất LOD / `lod-meta.json`, (c) giảm số splat. Chỉ làm phần công cụ hỗ trợ; phần
   không hỗ trợ ghi lại, không nâng phiên bản splat-transform trong task này (nâng là quyết định riêng).
2. **Bản nhẹ:** sau khi có SOG preview và SOG hệ mét, tạo thêm `scene.quick.sog` với màu bậc 0 (và giảm splat nếu công cụ
   hỗ trợ, mục tiêu ≤ 500 nghìn splat). Publish artifact `QuickViewSog` cùng stage với SOG gốc; kiểm bằng
   `validate_sog_runtime(..., expected_sh_bands=0)`. Lỗi tạo bản nhẹ không làm hỏng job.
3. **LOD** (nếu công cụ hỗ trợ): xuất kèm `lod-meta.json` và các khối; artifact `LodSog`; viewer dùng khi có.
4. **Hợp đồng:** `StageView` (`jobs/stage_views.py`) thêm `quick_refs: list[ProductArtifactRef] = []` (tùy chọn); allow-list
   gồm ref mới. SceneIR môi trường: tìm trường đang trỏ SOG môi trường; thêm `visual_quick_ref: ProductArtifactRef | None = None`
   cạnh nó.
5. **Giao diện:** mặc định tải bản nhẹ khi có; nút "Chất lượng đầy đủ" tải bản gốc và thay tại chỗ (giữ camera). Job cũ không
   có bản nhẹ → bản gốc như hiện nay.
6. **Job cũ:** lệnh tay `python -m scripts.studio.backfill_quick_sog --job <id>` chạy trên máy worker (có splat-transform),
   tạo và publish bản nhẹ cho job đã có. Không tự chạy.

## Steps
1. Kiểm công cụ (thiết kế 1), ghi report. Nếu không bỏ được dải SH bằng v3.6.6: dừng task ở `changes-requested` với ghi chú
   "cần Architect: nâng splat-transform?" — không tự nâng.
2. `tests/test_reconstruction/test_quick_view_sog.py`: `test_quick_sog_published_with_sh0`, `test_quick_sog_failure_keeps_job`,
   `test_stage_view_has_quick_ref`, `test_legacy_job_without_quick_ref`. Cài thiết kế 2, 4. Commit
   `feat(recon): publish a quick-view SOG with base colour only`.
3. (Nếu có) LOD + test `test_lod_artifacts_published`. Commit.
4. Giao diện thiết kế 5 + `frontend/tests/quick-view-sog.test.tsx`: tải bản nhẹ trước; nút chất lượng đầy đủ tải bản gốc;
   job cũ dùng bản gốc. Commit.
5. Lệnh backfill (thiết kế 6) + test với runtime giả. Commit.
6. Đo trên một job local (chạy backfill cho `job-f9f14e7fbfb1` trên máy local nếu có runtime; một việc nặng một lúc, theo
   dõi nhiệt): kích thước bản nhẹ / bản gốc. Ghi report.

## Acceptance criteria
1. Job mới có bản nhẹ; giao diện hiện bản nhẹ trước.
2. Job cũ không đổi hành vi.
3. Không nâng phiên bản công cụ ngoài quyết định của Architect.

## Tests required
```
.venv/bin/python -m pytest tests/test_reconstruction/test_quick_view_sog.py tests/test_reconstruction -q -k "sog or preview or finalize"
cd frontend && ./node_modules/.bin/vitest run tests/quick-view-sog.test.tsx tests/preview-scene-camera.test.tsx && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
