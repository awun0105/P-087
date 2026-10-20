# T-067: Vật nhẹ — SOG cho vật, tải giới hạn đồng thời, vỏ không tải lại khi chọn

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Mở Studio scene Ready không kéo 50–100 MB PLY của 60 vật cùng lúc. Bấm chọn vật không tải lại file.

## Context (đã kiểm trong code và dữ liệu)
- Scene Ready: 59–60 file PLY Gaussian của vật, tổng 47–96 MB, lớn nhất 10,7 MB, mỗi vật một request
  (`viewer/scene-overlay.ts:746-776` thêm mỗi vật một asset gsplat riêng). PLY lớn gấp 5–10 lần SOG.
- Gaussian vật được publish dạng PLY ở `src/services/orchestration/scene/object_geometry_build.py:881` và
  `scene/objectify.py:349,959` (`ObjectGaussians`, `objects/{digest}.ply`).
- splat-transform v3.6.6 đã dùng trong pipeline để ghi SOG (`src/services/reconstruction/imports.py:67-84`) và kiểm SOG
  (`validate_sog_runtime`, dòng 88-129).
- Draft: 59–60 vỏ GLB (1,1–2,7 MB tổng). `studio/MetricSceneView.tsx:497`: memo `shells` phụ thuộc `selected` → mỗi lần
  bấm chọn, `setShell` (`viewer/shell-glow.ts:151-158`) giải phóng asset cũ và tải lại GLB của vật cũ và vật mới.

## Thiết kế
1. **SOG cho vật (job mới).** Khi publish `ObjectGaussians` PLY ở hai chỗ trên, đồng thời tạo SOG bằng hàm dùng chung
   `def gaussians_to_sog(ply: Path, workspace: Path) -> Path` (tách từ `imports.py:67-84`, cùng kiểm runtime) và publish
   artifact `ObjectGaussiansSog` (`objects/{digest}.sog`). Trong SceneIR, `object.visual` giữ ref PLY (không đổi hợp đồng);
   thêm `object.visual_preview_ref: ProductArtifactRef | None = None` (tùy chọn, không bắt buộc, scene cũ không có). Allow-list
   (`_build_product_visible_references`) gồm ref mới. Lỗi tạo SOG **không** làm hỏng Tạo mesh: log và để `None`.
2. **Giao diện chọn file:** dùng `visual_preview_ref` khi có, không thì PLY.
3. **Tải giới hạn đồng thời:** hàng đợi tải vật tối đa 4 request cùng lúc; thứ tự: vật đang chọn → vật trong tầm nhìn
   camera (theo hộp bao) → còn lại. Vật chưa tải hiện vỏ (nếu có) hoặc hộp bao mờ.
4. **Vỏ không tải lại khi chọn:** tách khoá asset khỏi kiểu hiển thị; đổi chọn chỉ đổi vật liệu/độ sáng trên asset sẵn có.
   Đệm asset vỏ theo URL trong phiên.
5. Không tự chuyển đổi scene cũ trên API (API có thể không có splat-transform). Ghi lệnh chạy tay trên máy worker trong
   report nếu muốn chuyển scene cũ (không bắt buộc trong task này).

## Steps
1. `tests/test_scene/test_object_sog_publication.py`: `test_geometry_build_publishes_object_sog` (splat-transform giả theo
   cách test `imports.py` hiện có), `test_sog_failure_keeps_build_successful`, `test_legacy_scene_without_preview_ref_reads`
   (SceneIR fixture cũ), `test_preview_ref_is_in_allow_list`. Cài thiết kế 1. Commit
   `feat(scene): publish a compact SOG beside each object's Gaussians`.
2. Frontend `frontend/tests/object-visual-loading.test.ts`: dùng SOG khi có; tối đa 4 request đồng thời (mock fetch đếm);
   vật được chọn tải trước. Cài thiết kế 2, 3. Commit `perf(viewer): load object splats as SOG with bounded concurrency`.
3. `frontend/tests/shell-select-no-refetch.test.ts`: bấm chọn 5 vật liên tiếp → 0 request GLB thêm. Cài thiết kế 4. Sửa
   `shell-glow.test.ts` nếu cần (đọc bản mới nhất của phiên khác). Commit.
4. Đo: tổng byte vật của một scene Ready tạo mới trên dữ liệu local (nếu không chạy được Tạo mesh, chuyển thử 5 file PLY vật
   của `job-a14981f78f85` sang SOG bằng `gaussians_to_sog` và báo tỉ lệ). Ghi report.

## Acceptance criteria
1. Scene Ready mới: vật tải dạng SOG; scene cũ vẫn mở bằng PLY.
2. Không quá 4 tải vật cùng lúc; vật đang chọn ưu tiên.
3. Đổi chọn không tải lại vỏ.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_sog_publication.py tests/test_scene/test_object_geometry_build.py tests/test_orchestration/test_artifact_download_links.py -q
cd frontend && ./node_modules/.bin/vitest run tests/object-visual-loading.test.ts tests/shell-select-no-refetch.test.ts tests/shell-glow.test.ts tests/object-review.test.tsx && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
