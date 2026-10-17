# T-006 report

## Outcome

Tách ba bước dùng chung sang `src/services/orchestration/scene/object_geometry_steps.py`:

- `SurfaceInput` + `run_surface_colliders`: gửi surface object-local/mét cho CoACD, trả kết quả theo key, từ chối thiếu output, thiếu parts hoặc lỗi; giữ thông điệp cấm Gaussian/OBB fallback.
- `run_inpaint_and_package`: inpaint → SOG → publish GaussianPLY/VisualArtifact theo đường dẫn content-addressed cũ.
- `build_environment_collision`: support sàn theo footprint nguồn → loại nhãn vật trước meshing → publish collision GLB và ObjectAwareEnvironmentManifest.

`objectify()` dùng các helper, vẫn chạy CoACD và inpaint bằng `ThreadPoolExecutor(max_workers=2)`; package/publish nền sau khi nhận kết quả. Legacy, ObjectGS, correction và Draft đều qua regression; assertions trong các test cũ không sửa.
Hàm `objectify()` giảm từ 716 xuống 654 dòng, đo bằng AST so với commit bắt đầu `8ad6c0e1`. Ba khối logic đã chuyển ra, không giữ bản sao trong orchestrator.

## Changed files

- `src/services/orchestration/scene/object_geometry_steps.py`: helper mới.
- `src/services/orchestration/scene/objectify.py`: gọi helper; giữ các execution primitives và provider patch points hiện có.
- `tests/test_scene/test_object_geometry_steps.py`: 15 ca test đơn vị.
- `.ai/tasks/T-006/report.md`.
- `.ai/status.md`: chỉ dòng T-006.

## Verification

Trước refactor:

```bash
.venv/bin/python -m pytest tests/test_scene/test_objectgs_objectify_flow.py tests/test_scene/test_objectify_config_override.py -q
```

**36 passed in 7.86s**.

Sau refactor, lệnh đúng Tests required:

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_steps.py tests/test_scene/test_objectgs_objectify_flow.py tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_scene/test_object_aware_composition.py tests/test_scene/test_objectify_draft.py -q
```

**93 passed in 15.06s**. Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/object_geometry_steps.py src/services/orchestration/scene/objectify.py tests/test_scene/test_object_geometry_steps.py
.venv/bin/ruff format --check src/services/orchestration/scene/object_geometry_steps.py src/services/orchestration/scene/objectify.py tests/test_scene/test_object_geometry_steps.py
```

`All checks passed!`; `3 files already formatted`. `git diff --check`: sạch.

`graphify update .`: exit 0; **24.939 nodes, 77.149 edges, 796 communities**. Đã cập nhật graph.json, graph.html và GRAPH_REPORT.md; các output này bị gitignore. Công cụ báo 39 file không có symbol và gợi ý label lại community; không chạy LLM label ngoài scope.

### Red → green

1. Environment: viết test trước, **4 failed** vì chưa có module/helper. Sau extraction, fixture sàn thưa tạo tiếp xúc chéo nên assertion watertight đỏ; đổi fixture thành lưới sàn liên tục có vùng thiếu dưới footprint. Thêm ca sàn nghiêng/tâm nguồn cũ và budget. Kết quả **6 passed**; regression + 4 ca đầu **40 passed**.
2. Surface collider: thêm test trước, **5 failed, 6 passed** vì chưa có SurfaceInput/helper. Sau extraction: **47 passed** cho test helper + hai file chụp hành vi.
3. Inpaint/SOG: thêm test trước, **3 failed, 11 passed** vì chưa có helper. Sau extraction và thêm cancellation: helper **15 passed**, nhóm yêu cầu cuối **93 passed**.
4. Mỗi commit helper được tạo sau test liên quan và ruff xanh.

## Decisions and deviations

- Thêm helper nhỏ `run_inpaint` cho phần provider chạy song song. `run_inpaint_and_package` nhận `inpaint_result` tùy chọn để dùng lại kết quả đó; T-007 có thể gọi đủ chuỗi bằng cách bỏ tham số này. Đây là cách tách hai pha thay cho cờ `package=False` được plan cho phép.
- `before_publish` tùy chọn giữ thứ tự cũ cho legacy: package SOG thành công → publish membership nếu chưa có → kiểm cancel → đọc và publish nền. Không đẩy membership publication lên trước package.
- `footprint_centers` tùy chọn giữ điểm kiểm tiếp xúc từ `part.center` ở nhánh correction. Tâm source pose cũ có thể khác tâm AABB membership mới trên sàn nghiêng. Orchestrator truyền tâm cũ; caller chỉ truyền footprint thì dùng tâm footprint. Test sàn nghiêng bảo vệ khác biệt này.
- Helper import `_run`, `_reference`, ObjectifyError và các provider dùng chung từ objectify ở thời điểm gọi. Không chuyển infrastructure/error class sang module khác trong task này; giữ monkeypatch/consumer hiện có. Module helper không đọc config/job toàn cục. `package_splat` và `build_background_collision` tiếp tục được re-export tại objectify làm các patch points cũ.
- Không đổi persisted schema, artifact types/URI templates, SceneIR hay source frame. Không sửa runner SAM2/ObjectGS/CoACD, không train scene.

## Commits

- `8ad6c0e1` Mark T-006 in progress
- `5bcf981d` Extract object-aware environment collision publication
- `bc28c20f` Extract strict object-local surface collider execution
- `691e499c` Extract inpaint packaging and background artifact publication

## Pre-flight (GUIDE.md Rule 13)

- codegraph: explore objectify, _run, _reference và build_background_collision trước sửa source; đọc ba khối được tách và review T-005.
- impact: callers objectify gồm objectify_with_retry và các test; các helper mới được gọi từ objectify, và run_inpaint còn được gọi bởi run_inpaint_and_package. Đã chạy `codegraph callers` cho objectify và bốn helper. Không đổi chữ ký objectify/objectify_with_retry/reobjectify.
- understand: SAM2/lift/membership/Draft giữ nguyên; ObjectGS surface → CoACD song song inpaint → SOG/publish nền → collision môi trường. Đã chạy graphify query. UNVERIFIED: understand-anything explain/domain không có tool trong session; dùng codegraph, graphify và tài liệu task.
- minimal-code: rung 2 — chuyển logic hiện có và tái dùng execution/artifact primitives, không tạo provider mới.
- checks: baseline 36 passed; nhóm cuối 93 passed; ruff check/format sạch; TypeScript/eslint/vitest n/a vì chỉ sửa backend Python.
- DevTools: n/a — không sửa UI. Bằng chứng gồm fixture và CPU/runtime hiện có của test; không phải ObjectGS/SAM2 GPU E2E hay browser acceptance.

## Architect review

Không có câu hỏi contract hoặc dữ liệu lưu cần chốt. T-007 có thể dùng ba helper; các tham số tùy chọn phục vụ bảo toàn thứ tự publication và source contact của orchestration cũ đã nêu ở trên.
