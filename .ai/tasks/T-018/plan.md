# T-018: Tương thích scene cũ + Walk/USD với collider vỏ

## Goal
Chứng minh bằng test rằng:
1. Scene cũ (legacy, ObjectGS cũ, không có `object_geometry`) vẫn mở, chỉnh, Walk, xuất USD như trước.
2. Scene build từ vỏ (T-007) đi qua Walk collision compositor và USD đúng: collider vật theo pose, môi trường không giữ
   khối vật ở vị trí cũ, không double-transform/double-scale/double-carve, không dùng collider cũ.

## Context
`architecture.md` §2.4, §8. Code:
- Compositor Walk: `src/services/orchestration/scene/effective_collision.py` (`compose_effective_collision`).
- USD: `src/services/simulation/usd/builder.py` (`_collect_scene_refs` thêm `surface_mesh_ref` vào geometry — dòng ~98),
  `hybrid_runner.py`.
- Test mẫu end-to-end: `tests/test_scene/test_objectgs_objectify_flow.py::test_objectgs_surface_reaches_real_coacd_and_publishes_separate_background`
  (đoạn corrected → USD đọc lại bounds bằng pxr).
- Test USD: `tests/test_simulation/test_object_aware_usd.py`.

## Files
- Tạo: `tests/test_scene/test_shell_geometry_walk_usd.py`
- Sửa (chỉ khi test lộ lỗi): `effective_collision.py`, `usd/builder.py`, chỗ đọc `surface_mesh_ref` nếu giả định `ObjectSurfaceMesh`.

## Steps
1. Grep mọi nơi đọc `surface_mesh_ref`, `ObjectSurfaceManifest`, `surface_manifest_ref`; liệt kê trong report. Nơi nào giả định
   chỉ có ObjectGS → cho chấp nhận `ObjectShellManifest` (`provenance.shell_manifest_ref`). Test từng chỗ. Commit mỗi chỗ.
2. Test e2e (fixture Draft → build T-007 với CoACD thật nếu runtime có, skip rõ nếu không):
   - Confirm vật A → Move (+1 m x) + Rotate 90° → compose Walk collision: collider A ở pose mới; tại vị trí cũ của A không có
     tam giác môi trường cao hơn sàn (ghost); sàn dưới vị trí cũ vẫn có (support suy ra).
   - Xuất USD (cùng cách test ObjectGS hiện có): bounds collider A đọc bằng pxr khớp pose mới; scale = 1 (mét);
     môi trường không bị khoét thêm lần nữa.
   - Pose-only Move/Rotate không xếp việc build/train (không có bản ghi queue mới).
   Commit.
3. Test tương thích: nạp fixture scene legacy (Room-style, không có khóa) + fixture ObjectGS cũ hiện có → `object_geometry_state`
   = ready, Walk/USD route không bị khoá, test cũ PASS. Commit.

## Acceptance criteria
1. Mọi nơi đọc surface chấp nhận cả vỏ lẫn ObjectGS.
2. Test e2e vỏ: không ghost collision, sàn còn, pose đúng trong Walk và USD, không double-carve.
3. Scene legacy và ObjectGS cũ không đổi hành vi.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_shell_geometry_walk_usd.py tests/test_scene/test_effective_collision.py \
  tests/test_scene/test_object_aware_composition.py tests/test_simulation/test_object_aware_usd.py \
  tests/test_scene/test_objectgs_objectify_flow.py tests/test_orchestration/test_simulation_package.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Isaac Sim thật, browser thật.
