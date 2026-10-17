# T-007 report

## Outcome

`build_object_geometry()` dựng vỏ mịn từ PLY nguồn world + membership theo immutable `source_transform`, publish manifest QA, chạy CoACD strict, dựng nền inpaint/SOG và collision object-aware, rồi publish SceneIR Ready bằng `publish_next(..., commit_guard=...)`.

Giữ transform hiện tại, tên, state, active, review, visual, physics và source ownership đã có. Theo review Round 2, mọi vật có trong membership đều được dựng collider, kể cả IGNORED/DELETED/MERGED; review/state của vật giữ nguyên. Vỏ/placeholder lỗi trả `ObjectGeometryBuildError` có object_id; không tạo collider OBB. Huỷ hoặc lỗi trước commit không đổi committed head. Source ownership thiếu được bind bằng pose nguồn và extraction revision của membership.

## Changed files

- `src/services/orchestration/scene/object_geometry_build.py`: service và helper vỏ/collider/môi trường.
- `src/services/orchestration/scene/object_geometry_steps.py`: thêm keyword `surface_label="ObjectGS surface"`; build từ vỏ truyền `"Gaussian shell"`.
- `tests/test_scene/test_object_geometry_build.py`: 28 ca kiểm thử ban đầu, gồm hai test CoACD thật; Round 2 thêm 3 ca.
- `.ai/tasks/T-007/report.md`.
- `.ai/status.md`: chỉ dòng T-007.

Các commit T-012 xuất hiện trong branch dùng chung khi task đang chạy là phần việc của agent khác, không thuộc danh sách thay đổi/commit T-007.

## Verification

Đúng lệnh Tests required:

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_object_geometry_steps.py tests/test_scene/test_gaussian_shell.py -q
```

**68 passed in 69.77s**, không skip. Không chạy full suite hoặc file test ngoài danh sách plan.

```bash
.venv/bin/ruff check src/services/orchestration/scene/object_geometry_build.py src/services/orchestration/scene/object_geometry_steps.py tests/test_scene/test_object_geometry_build.py
.venv/bin/ruff format --check src/services/orchestration/scene/object_geometry_build.py src/services/orchestration/scene/object_geometry_steps.py tests/test_scene/test_object_geometry_build.py
```

`All checks passed!`; `3 files already formatted`. `git diff --check`: sạch.

`graphify update .`: exit 0; **25.035 nodes, 77.644 edges, 785 communities**. Đã cập nhật graph.json, graph.html và GRAPH_REPORT.md (bị gitignore). Công cụ báo 39 file không có symbol và gợi ý label lại community; không chạy LLM label ngoài scope.

```bash
rg -n 'mesh\.volume|mass|inertia' src/services/orchestration/scene/object_geometry_build.py
```

Không có match. Không tính mass/inertia từ vỏ/collider; test giữ nguyên ObjectPhysics có mass do người dùng đặt là 18 kg.

### CoACD thật

- `test_real_coacd_builds_ready_scene`: Draft hai vật → Ready, collider có số mảnh trong ngân sách 8; chỉ inpaint/package được thay bằng fixture CPU.
- `test_open_bottom_shell_real_coacd_budget_and_bounds`: dữ liệu `open_face_points`, seed 19, 20.000 điểm, bỏ đáy, ShellParams mặc định 0,02 m và smoothing bật. CoACD **8/8 mảnh**, **20,327 giây** trong lượt chạy đo riêng; `solidity=0,432715`. Collider bounds khớp shell bounds trong dung sai **2·voxel = 0,04 m**. Không thêm nắp hoặc đổi QA/ngân sách.
- Lệnh đo riêng trong cùng file: `.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py -k 'real_coacd' -q -s --tb=short`. Lượt đầu test service lỗi vì fixture dùng `Path.resolve()` với Python venv, dẫn đến interpreter hệ thống không có coacd; sửa fixture dùng `absolute()` giữ đường dẫn venv. Test vỏ rỗng đã pass ngay trong lượt đó. Chạy lại service: 1 passed; nhóm đầy đủ cuối cùng 68 passed.

Đây là bằng chứng fixture/CPU và CoACD thật trong runtime cục bộ. Không chạy SAM2/ObjectGS GPU, train scene, browser, Walk, USD hoặc API mới.

### Red → green và commit

1. (a) 3 test đỏ vì chưa có module; scaffold kiểm stale/membership/Draft → 3 passed.
2. (b) Test manifest đỏ vì chưa có `_build_shell`; dựng vỏ + QA + manifest → 4 passed. Sửa annotation fixture trước khi ghi nhận lỗi mục tiêu.
3. (c) Test parts=0 đỏ vì chưa có `_build_colliders`; nối helper strict và surface_label → 20 passed cho build + helper.
4. (d) Test môi trường đỏ vì chưa có `_build_environment`; nối inpaint/SOG và collision object-aware → 6 passed.
5. (e) 12 test đỏ trên scaffold chưa nối publication. Nối service, fence, cancel và bảo toàn state → xanh. Bổ sung checksum hỏng, concurrent edit, commit guard false, source rotation, zero-part trong full service: build 25 passed; build + helper 39 passed trước ca full zero-part bổ sung.
6. (f) CoACD thật + kiểm source ownership thiếu và physics; nhóm Tests required cuối 68 passed. Assertions bounds của test quay source ban đầu chưa tính dilation/closing: cập nhật dung sai theo mức nở hai phía quan sát được, vẫn kiểm đảo chiều kích thước XY và tâm local. Không sửa thuật toán hay ngưỡng QA để qua test.

## Decisions and deviations

- `review` được đọc từ `item.provenance`, đúng data model hiện tại; không có field SceneObject.review riêng.
- Bind source collision chỉ khi thiếu. Không bind lại ownership có sẵn với revision mới, vì metadata nguồn là bất biến. Khi thiếu và vật đã Move, dùng bản tạm mang source pose để bind, sau đó giữ transform hiện tại trong SceneIR.
- `shell_error` là cờ chặn cho tới khi chỉnh vùng thành công loại bỏ lỗi này. Draft T-005 chưa có checksum membership tại thời điểm lỗi để tự suy đoán lỗi đã được khắc phục; service không bỏ qua placeholder chỉ vì đang build lại.
- `build_gaussian_shell` tự chạy QA; `_build_shell` lưu quality/manifest ngay sau khi QA pass. Phase `quality` đánh dấu hoàn tất các báo cáo QA trước bước collider; không chạy lại QA lần hai.
- Voxel trong manifest là `voxel_m_effective`; params vẫn ghi đầy đủ giá trị yêu cầu, gồm voxel 0,02 m.
- Publish artifact idempotent có kiểm bytes; không có upload fallible sau khi SceneIR commit. Artifact trung gian có thể tồn tại khi build lỗi, nhưng không trở thành committed scene.
- Giữ chữ ký `object_ids` và lọc tập vật theo plan; không triển khai API/hàng đợi hoặc claim acceptance rebuild sau chỉnh vùng của T-011.
- Giữ geometry_method của Draft; nguồn thực tế từng collider được ghi `surface_origin=gaussian_shell_v1`, `surface_selection.chosen=gaussian_shell`. ObjectGS nâng cấp thuộc T-008.

## Commits T-007

- `0be187d6` Mark T-007 in progress
- `f3f590b8` Add geometry build service revision and draft preconditions
- `9ece0dd1` Build fine Gaussian shells with source-bound QA manifests
- `31d903b9` Build strict Gaussian shell colliders with source-specific errors
- `98dddd81` Build inpainted and object-aware environments from source membership
- `52e5d72f` Publish ready shell geometry through cancellation and revision fences
- `ec834ca1` Verify ready builds and hollow Gaussian shells with real CoACD

## Pre-flight (GUIDE.md Rule 13)

- codegraph: explore prepare_correction/regenerate_membership, membership decoder/error, SceneObject/SceneEnvironment/ObjectShellManifest, publish_next và helper T-006 trước sửa source; đọc các review T-002/T-005/T-006 và tài liệu .ai.
- impact: callers run_surface_colliders gồm objectify và helper build mới; default ObjectGS message được giữ và test helper cũ pass. build_object_geometry hiện chỉ có callers trong test; không nối API/queue. Đã chạy callers cho service và helper mới.
- understand: nguồn world → immutable object-local → vỏ/QA → CoACD → nền theo source membership → CAS SceneIR. Đã chạy graphify query. UNVERIFIED: understand-anything explain/domain không có tool trong session; dùng codegraph/graphify và tài liệu task.
- minimal-code: rung 2 — dùng Gaussian shell, manifest, geometry steps, artifact store và publisher/fence hiện có; không viết lại runner.
- checks: 68 passed, ruff check/format sạch; TypeScript/eslint/vitest n/a vì chỉ backend Python.
- DevTools: n/a — service chưa nối UI/API.

## Architect review

Không có quyết định contract còn chờ. Vỏ rỗng đạt ngân sách mảnh và bounds theo plan; không cần thay luật khép mặt.


## Round 2 — Required changes

### Outcome

Bỏ điều kiện loại review IGNORED/DELETED/MERGED khỏi tập build. Khi `object_ids is None`, build tất cả vật có trong membership. Khi có `object_ids`, giữ đúng phép giao với tập được yêu cầu. Quy tắc `shell_error` chặn build không đổi.

Compositor object-aware có thể khôi phục source collider theo review/state sau khi Ready. Review không quyết định có tạo collider hay không.

### Changed files

- `src/services/orchestration/scene/object_geometry_build.py`: chỉ bỏ điều kiện lọc review khỏi selected.
- `tests/test_scene/test_object_geometry_build.py`: sửa ba ca tombstone; thêm hai ca build/compose/Restore và một ca kiểm object_ids trên Ready.
- `.ai/tasks/T-007/report.md`: cập nhật outcome và thêm Round 2.
- `.ai/status.md`: chỉ dòng T-007.

### Red → green

Trước sửa source:

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py -k 'review_tombstones or reviewed_build' -q --tb=short
```

**5 failed, 25 deselected**: cả ba review thiếu collider; hai test tích hợp không có source collider để đọc/compose.
Sau bỏ điều kiện review: **5 passed, 25 deselected**.

### Coverage

- IGNORED/DELETED/MERGED đều có shell/collider sau full build; giữ review, state, active, tên, physics, transform và source ownership.
- Ready có IGNORED: compose thành công, các triangle collider được thêm tại immutable source pose. Test đặt current pose tại (20, 30, 40) để bắt nhầm pose.
- Ready có DELETED: compose chỉ còn baseline, không chứa collider của vật này. Gọi `apply_object_action(..., "restore")`, giữ collider, rồi compose lại thành công và kiểm bounds source.
- Ready + `object_ids={candidate-001}` với vật IGNORED: chỉ gọi dựng vỏ cho đúng vật đó, vật thứ hai giữ nguyên.
- Không sửa compositor, review/restore commands, QA, CoACD hoặc hành vi shell_error.

### Verification Round 2

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_object_geometry_steps.py tests/test_scene/test_effective_collision.py tests/test_scene/test_object_aware_composition.py -q
```

**58 passed in 68.07s**, không skip; gồm hai test CoACD thật. Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/object_geometry_build.py tests/test_scene/test_object_geometry_build.py
.venv/bin/ruff format --check src/services/orchestration/scene/object_geometry_build.py tests/test_scene/test_object_geometry_build.py
```

`All checks passed!`; `2 files already formatted`. `git diff --check`: sạch.

`graphify update .`: exit 0, 25.071 nodes, 77.736 edges, 825 communities. Output graph.json/graph.html/GRAPH_REPORT.md được cập nhật và bị gitignore; không chạy LLM label.

### Commits Round 2

- `fb0470f6` Mark T-007 review fixes in progress
- `dc7d547c` Build source colliders for all reviewed membership objects

### Gate report Round 2

- codegraph: explore build_object_geometry, _object_aware_environment, compose_effective_collision, apply_object_action, restore_object trước sửa; callers service hiện chỉ là test.
- impact: bổ sung collider nguồn cho mọi vật trong membership để object-aware composition dùng được sau review/Restore; caller public và chữ ký service không đổi.
- understand: membership → build mọi source collider → compositor quyết định giữ/loại theo review; đã dùng graphify query. Không có tool understand-anything explain/domain trong session.
- minimal-code: bỏ một điều kiện lọc; tái dùng builder và compositor hiện có.
- DevTools: n/a — sửa backend service/test, không UI.

Không có lệch Required changes hoặc quyết định contract cần chốt thêm.
