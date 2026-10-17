# T-008: Nâng cấp ObjectGS theo từng vật (tuỳ chọn)

## Goal
Khi job có `geometry_method = "objectgs"`, bước build chạy thêm ObjectGS (train + export surface). Với **từng vật**:
- Surface ObjectGS qua QA → dùng nó làm đầu vào CoACD và `surface_mesh_ref`.
- Không qua (ví dụ mesh hở) → dùng vỏ Gaussian, ghi rõ lý do.

Quy tắc này phải hiển thị được trong Studio (`surface_selection`), không phải fallback âm thầm.

## Context
`architecture.md` §8.4. Code ObjectGS hiện có trong `objectify()`: nhánh `if objectgs_runtime is not None:`
(dựng mask từ `lift["objectgs_views"]`, `PreparedObjectGSRequest`, `run_prepared_objectgs`,
`publish_surface_artifacts`). Lưu ý: nhánh này hiện **bắt buộc** mọi vật qua QA (raise nếu không). Trong build mới,
điều kiện đó đổi thành "chọn theo từng vật".

Vấn đề phụ thuộc: ObjectGS cần ảnh + mask đa góc nhìn (`objectgs_views`) do lift runner sinh ra lúc tách vật.
Draft (T-005) phải **lưu lại** đường dẫn/artifact quan sát này để build dùng lại. Kiểm xem `lift` có trả
`objectgs_views` khi không có `objectgs_runtime` không (`objectgs_observations_dir` chỉ gửi khi có runtime).

## Files
- Sửa: `src/services/orchestration/scene/objectify.py` (Draft với `geometry_method=objectgs`: gửi
  `objectgs_observations_dir`, publish quan sát thành artifact `ObjectGSObservations` (tar hoặc manifest JSON + ảnh mask
  theo nhãn nguồn), ghi ref vào `scene.provenance.objectgs_observations_ref`)
- Sửa: `src/services/orchestration/scene/object_geometry_build.py`
- Tạo: `tests/test_scene/test_object_geometry_build_objectgs.py`

## Steps
1. Draft + objectgs: bật `objectgs_observations_dir` cho lift; sau lift, đóng gói quan sát (ảnh mask dùng **nhãn nguồn**, chưa map
   sang id compact) thành artifact bất biến có checksum. Test: provenance có ref, checksum đúng. Commit.
2. Build: nếu `geometry_method == "objectgs"`: kiểm runtime ObjectGS cấu hình (thiếu → `ObjectGeometryBuildError`, scene không đổi).
   Giải nén quan sát vào workspace, map mask theo membership **hiện tại** (sau khi người dùng sửa) giống đoạn
   `compact`/`mapped_views` trong objectify. `progress("objectgs")`. Gọi `run_prepared_objectgs`.
   Mask được dựng lại từ nhãn hiện tại nên chỉnh vùng trong Draft được phản ánh (dùng cơ chế của
   `correction_observations.py` nếu đã có hàm map hàng nguồn → mask; đọc file đó trước khi viết mới). Commit.
3. Chọn surface theo vật:
   ```python
   if item.get("quality_passed") is True:   surface = ObjectGS surface; selection = {"chosen": "objectgs"}
   else: surface = vỏ mịn; selection = {"chosen": "gaussian_shell",
                                       "reason": "objectgs_quality_failed",
                                       "quality_reasons": <reasons từ quality report>}
   ```
   Vẫn publish evidence ObjectGS (checkpoint, dataset, quality report) cho mọi vật để truy vết. Commit.
4. Lỗi ObjectGS toàn cục (train lỗi, hết VRAM): **không** âm thầm chuyển sang vỏ. Build thất bại với
   `ObjectGeometryBuildError(retryable=…)`, thông điệp gợi ý đổi `geometry_method=shell` nếu muốn bỏ ObjectGS. Commit.

## Acceptance criteria
1. Monkeypatch ObjectGS trả 2 vật: vật A `quality_passed=True`, vật B False → collider A làm từ surface ObjectGS,
   collider B làm từ vỏ; `surface_selection` đúng cho từng vật; evidence ObjectGS của cả hai được publish.
2. ObjectGS raise lỗi train → build thất bại, scene không đổi, không tạo collider từ vỏ.
3. Runtime ObjectGS chưa cấu hình → build thất bại với thông điệp rõ, scene không đổi.
4. Chỉnh vùng trong Draft (đổi nhãn một nhóm hàng) → mask đưa vào ObjectGS phản ánh nhãn mới (kiểm pixel của mask).
5. `geometry_method=shell` → không gọi ObjectGS (monkeypatch raise nếu bị gọi).

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_object_geometry_build.py \
  tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectgs_objectify_flow.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Không chạy ObjectGS thật trên GPU (chưa train scene mới). Không đổi upstream ObjectGS.
