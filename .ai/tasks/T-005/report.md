# T-005 report

## Outcome

`objectify()` trả Draft khi `geometry_review=required`, `geometry_method` là `shell` hoặc `objectgs`, và không có correction.
Draft publish membership, Gaussian từng vật, vỏ thô object-local, source transform và provenance `awaiting_review`.
Không chạy ObjectGS, CoACD, inpaint, package SOG hay dựng collision nền. SAM2 vẫn bắt buộc.
Vỏ lỗi giữ vật và publish hộp chỉ để hiển thị, có `shell_error` và `shell_display=bounding_box_placeholder`, collider luôn null.

## Changed files

- `src/services/orchestration/scene/objectify.py`: cờ Draft, `_publish_draft`, bỏ alias `job_requires_objectgs`, thêm `shell` vào type hint hai entrypoint.
- `src/services/orchestration/scene/extraction.py`: tên `strict_geometry_required` và thông điệp lỗi cho shell/ObjectGS.
- `tests/test_scene/test_objectify_draft.py`: 10 test cho Draft, artifact, provider guards, sealed config, extraction và cleanup.
- `tests/test_scene/test_objectify_config_override.py`: thêm regression `legacy`, `auto`, `shell + auto`.
- `.ai/status.md`: chỉ dòng T-005.
- `.ai/tasks/T-005/report.md`.

## Verification

```bash
.venv/bin/python -m pytest tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectify_config_override.py tests/test_scene/test_objectgs_objectify_flow.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_scene_extraction.py -q
```

**75 passed in 13.48s**. Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/objectify.py src/services/orchestration/scene/extraction.py tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectify_config_override.py
.venv/bin/ruff format --check src/services/orchestration/scene/objectify.py src/services/orchestration/scene/extraction.py tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectify_config_override.py
```

`All checks passed!`; `4 files already formatted`.
`git diff --check`: sạch.

`graphify update .`: exit 0; 24.875 nodes, 76.957 edges, 818 communities. Cập nhật graph.json, graph.html và GRAPH_REPORT.md trong graphify-out; các đầu ra này bị gitignore. Có cảnh báo 39 file không có symbol và tên community cần label lại; không chạy bước LLM label ngoài scope.

### Red → green evidence

- Bước (a): test đỏ vì thiếu runtime ObjectGS. Sau sửa cờ, fixture lộ thiếu field PLY; đã bổ sung field 3DGS và sửa lint, test xanh: 1 passed.
- Bước (b): thêm 3 test, 3 failed/1 passed vì chưa rẽ Draft; thêm helper và return: 4 passed.
- Bước (c): thêm environment/provider guards, mở rộng test ObjectGS đến hết Draft: 2 failed/4 passed vì thiếu provenance; thêm provenance: 68 passed trên nhóm test yêu cầu.
- Bước 7: test đỏ cho thông điệp strict và alias: 2 failed/7 passed; sửa tên, alias, type hints: xanh.
- Thêm test extraction/source ownership; sửa đường dẫn fixture từ tests/fixtures thành fixtures; kết quả cuối nhóm yêu cầu: 75 passed.

## Decisions and deviations

1. `gaussian_split.split()` đã trừ tâm world khi tạo `ObjectPart.rows`. Dùng trực tiếp `positions(part.rows)`; không trừ `part.center` lần nữa như snippet trong plan. Test dùng hai vật ở tâm world khác zero và kiểm tâm cả GLB/PLY local để bắt lệch này. Không đổi contract object-local.
2. Giữ `bind_source_collision_ownership` trong extraction và reobjectify: hàm chỉ ghi immutable source OBB metadata, không yêu cầu hay tạo collider. Test qua `extract_scene()` xác nhận SceneIR Draft giữ collider null và source ownership đúng.
3. Environment tối thiểu được tạo cùng helper ở commit (b) để trả `ObjectifyResult` hợp lệ; provenance đầy đủ và test environment/provider được hoàn tất ở (c).
4. Có một commit sửa fixture/lint riêng sau (a). Commit (a) đã được tạo khi lượt chạy còn lỗi fixture; đây là lệch quy trình commit-sau-test. Đã sửa ngay ở `f55678e9`, không sửa lịch sử commit. Các bước sau chỉ commit sau test xanh.
5. Bổ sung regression và test sealed config trong đúng các file thuộc lệnh Tests required. Không đổi logic `objectify_with_retry` ngoài type hint và bỏ alias.

## Commits

- `2748ee4f` Mark T-005 in progress
- `422b1d42` Defer ObjectGS runtime validation during draft extraction
- `f55678e9` Correct draft fixture Gaussian fields and lint findings
- `91d8685f` Publish draft objects with local Gaussian shell previews
- `0afcb72f` Preserve draft environment membership and geometry review provenance
- `5f12970a` Align strict geometry entrypoints and retain legacy review behavior

## Pre-flight (GUIDE.md Rule 13)

- codegraph: đọc objectify đầy đủ, extract_scene, objectify_with_retry, reobjectify, publish_membership, bind_source_collision_ownership, build_gaussian_shell, split và scene_from_bundle; dùng explore trước sửa source.
- impact: `codegraph callers` cho objectify, objectify_with_retry, reobjectify, extract_scene, job_requires_strict_geometry và `_extract_scene_stage`. Production callers gồm job runner, extraction, objectify queue, membership regeneration và script reobjectify; giữ chữ ký public ngoài mở rộng Literal theo plan.
- understand: luồng SAM2 → lift → split → membership → Draft; correction và đường legacy/ObjectGS hiện hữu tiếp tục qua nhánh cũ. Đã dùng `graphify query`. UNVERIFIED: understand-anything — tool explain/domain không có trong session; dùng codegraph, graphify và tài liệu task làm bằng chứng luồng.
- minimal-code: rung 2 — tái dùng split, publish_membership, artifact reference, Gaussian shell và SceneIR models; chỉ thêm helper Draft.
- checks: pytest 75 passed; ruff check và format sạch. TypeScript/eslint/vitest n/a: chỉ backend Python.
- DevTools: n/a — backend service, không sửa UI. Đây là bằng chứng fixture/CPU; chưa kiểm GPU/SAM2 thật hoặc browser.

## Architect review

Không có quyết định contract cần chốt thêm. T-007 cần từ chối build vật có `shell_error`/placeholder cho tới khi sửa vùng, như plan đã yêu cầu; T-005 chỉ tạo preview.
