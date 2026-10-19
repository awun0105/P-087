# T-010 report

## Outcome

Thêm hai route contributor/ownership guarded:

- `POST /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/preview`: 200, không ghi artifact hoặc revision; bộ đếm chính xác, mẫu điểm local tối đa 20.000 mỗi loại, vỏ GLB base64 hoặc shell_error rõ ràng.
- `POST /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/apply`: 201 SceneEditResponse trên Draft. Membership labels/manifest, Gaussian và vỏ thô của vật đích + vật bị claim được publish trước SceneIR revision mới. Không train, không CoACD, không tạo collider.

Revision/checksum cũ → 409; command/ownership không hợp lệ hoặc vật còn dưới 50 hàng → 422 trước publication. Ready kể cả legacy thiếu membership → 422 với đúng detail trong plan. Preview vẫn dùng được trên Ready có membership.

Apply giữ `source_transform` và transform hiện tại của từng vật. Đổi hàng nguồn world về local theo `Rᵀ(p_world − t)`; không gọi split(), không căn tâm lại. Vật không bị ảnh hưởng giữ nguyên. Ghi evidence ObjectRegionEdit chứa command, thống kê không có mẫu điểm, actor và membership cũ/mới.

## Changed files

- `src/services/orchestration/scene/membership_regeneration.py`: MembershipSource, loader dùng chung, cache LRU hai mục có Lock; prepare_correction giữ hành vi.
- `src/services/orchestration/scene/object_region.py`: validation, resolve, preview, apply Draft, vỏ thô và publication.
- `src/api/product/scene.py`: hai route region, guard và map lỗi 409/422.
- `tests/test_scene/test_object_region.py`: fixture integration, preview read-only, frame regression, claim, validation, shell errors và benchmark 300k.
- `tests/test_scene/test_membership_regeneration.py`: loader + cache bounded, mảng immutable, labels riêng cho mỗi lần đọc.
- `tests/test_api/test_scene_v2_routes.py`: HTTP 200/201/409/422, ownership dispatch và Ready legacy detail.
- `tests/test_api/test_role_matrix.py`: đăng ký hai route authenticated.
- `.ai/tasks/T-010/report.md`, `.ai/status.md` chỉ dòng T-010.

## Verification

Đúng nhóm Tests required:

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_scene/test_region_box.py \
  tests/test_scene/test_membership_regeneration.py tests/test_scene/test_membership_selection.py \
  tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py -q
```

**129 passed in 4.33s**, không skip. Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/object_region.py src/services/orchestration/scene/membership_regeneration.py src/api/product/scene.py tests/test_scene/test_object_region.py tests/test_scene/test_membership_regeneration.py tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py
.venv/bin/ruff format --check src/services/orchestration/scene/object_region.py src/services/orchestration/scene/membership_regeneration.py src/api/product/scene.py tests/test_scene/test_object_region.py tests/test_scene/test_membership_regeneration.py tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py
```

`All checks passed!`; `7 files already formatted`. `git diff --check`: sạch.

### Test-first và kiểm tra từng bước

1. Loader: test mới đỏ AttributeError (**1 failed, 5 passed**). Tách loader → regeneration + selection **15 passed**.
2. Preview: **4 failed** khi chưa có module → **4 passed** sau triển khai. Test đọc lại GLB watertight, kiểm cả danh sách URI và file trên đĩa không đổi; Move pose hiện tại không đổi kết quả.
3. Apply: **7 failed, 4 passed** vì chưa có entrypoint. Sau triển khai, sửa một lỗi import trong test; object_region **11 passed**. Thêm shell error placeholder regression; object_region + region_box **55 passed**.
4. Routes: **10 failed** với 404 trước khi có route → route file + role matrix **56 passed**. Guard ownership được spy tại HTTP fixture; contributor dependency được role matrix kiểm.
5. Benchmark trước sampling: **1,701 s** trên 300.000 hàng; test đỏ do chưa có shell_sample_rows. Cache test đỏ AttributeError trước khi có cache. Sau cache/stride, object_region + regeneration **20 passed**, preview cold **0,491 s**, 100.000 hàng cho vỏ. Counts vẫn 300.000, không lấy mẫu membership.
6. Ready legacy: test đỏ vì trả detail thiếu membership. Đưa gate Draft lên sau revision gate, trước đọc membership → nhóm Tests required cuối **129 passed**.

Benchmark dùng PLY/store thật và shell/QA thật; floor mask được stub để đo đường preview/đọc source/resolve/shell. Số đo không chứng minh cold floor fitting trên scene thật, 2 triệu hàng, GPU, live deployment hay browser acceptance.

## Decisions and deviations

- Loader public đúng signature plan. `_load_membership_source` là phần đọc chung; prepare_correction gọi nó với protect_floor chỉ khi chọn nền như hành vi cũ. Loader region luôn bảo vệ sàn và cache. Không ép legacy correction fit floor khi không cần.
- Cache chỉ chứa positions/rows/floor_protected immutable, khoá đúng `(job_id, labels checksum, source visual checksum)`, tối đa hai mục và đổi thứ tự khi hit. Không cache labels sửa; luôn decode/verify labels_ref mới thành mảng riêng.
- Áp stride deterministic cho vỏ preview sau khi đo vượt 1,5 s; luôn trả shell_sample_rows. Apply dựng trên đầy đủ hàng vì cần publication chính xác.
- Shell lỗi ở Apply giữ vật với ObjectShellMesh placeholder chỉ hiển thị, provenance.shell_error/shell_display và collider=null, cùng quy tắc Draft T-005. Khi thành công xoá shell_error/shell_display cũ và ghi shell_preview mới. Không dùng placeholder làm collider.
- Khi nguồn có đủ rot_0..3, quaternion Gaussian cũng đổi sang frame nguồn local cùng tâm; không sửa scale hay các field còn lại. Fixture regression xác nhận tâm world qua pose nguồn xoay 90 độ và khác translation giữa hai vật.
- Membership manifest JSON được publish riêng và tham chiếu trong evidence, đồng thời SceneIR vẫn nhúng ObjectMembershipArtifact như contract hiện có.
- Source/validation/shell bytes của mọi vật bị ảnh hưởng được chuẩn bị trước publication. publish_next dùng CAS hiện có; race phát sinh sau validation có thể để lại artifact bất biến không được head tham chiếu như các writer khác, không thay head nếu stale.
- Đã tạm ngắt T-010 theo chỉ đạo để sửa T-009 Round 3, commit/report riêng. T-009 hiện implemented; không tính các commit đó vào T-010.

## Commits T-010

- `6433d83d` Mark T-010 in progress
- `7fc249e6` Extract reusable immutable membership source loading
- `ea906f51` Preview revision-bound object regions without publishing artifacts
- `adb437a7` Apply Draft region edits in immutable source frames
- `b1b380fb` Expose authorized Draft region preview and apply endpoints
- `9738a37e` Bound preview shell sampling and cache immutable membership source data
- `800873c1` Reject Ready region application before reading source membership

## Pre-flight (GUIDE.md Rule 13)

- codegraph: đọc prepare_correction, region_box resolve/apply/preview, Draft publication, source frame/build, SceneEditor publish_next và routes membership trước sửa. Đã đọc review T-002/T-004/T-005, architecture §7.1 và plan/roadmap. Đã chạy graphify query.
- impact: prepare_correction có hai caller preview_correction/regenerate_membership. Loader region → _resolve → preview/apply → hai route API; CodeGraph callers đã kiểm. Không đổi signature cũ.
- understand: flow membership nguồn bất biến → source frame → region resolution → preview không ghi / Apply labels + affected visuals/shell → evidence → SceneIR CAS. Đây là flow đã đọc, không refactor business rule ngoài plan.
- minimal-code: tái dùng region_box, build_gaussian_shell, membership encoding, artifact store và publish_next; không thêm provider hoặc queue.
- checks: pytest 129 passed, ruff check/format sạch. TypeScript không sửa. DevTools n/a — service/API không sửa UI.

## Architect review

Không có quyết định contract cần chốt thêm. Ready rebuild và UI giữ ở T-011/T-016. Dừng ở implemented chờ review.

`graphify update .` sau T-010: exit 0; 25.268 nodes, 78.574 edges, 837 communities. Đã cập nhật graph.json/graph.html/GRAPH_REPORT.md; không chạy LLM label.
