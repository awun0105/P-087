# Report T-008: Nâng cấp ObjectGS theo từng vật

## Done

Làm theo 4 bước của plan, mỗi bước một commit. Test được viết trước code, trừ phần gói quan sát của bước 1 (xem Deviations 8).

- **Bước 1** (`288a459e`): gói quan sát ObjectGS (`src/services/orchestration/scene/objectgs_observations.py`). Gói là tar không nén, xác định byte, gồm manifest, ảnh RGB đã khử méo (PINHOLE), mask theo nhãn nguồn và camera của mỗi view. Draft với `geometry_method=objectgs` yêu cầu lift ghi quan sát ngay cả khi không có runtime ObjectGS, rồi ghi `provenance.objectgs_observations_ref`. Checksum khớp với bytes đã publish.
- **Bước 2** (`759d39ca`): build objectgs. Trước khi publish bất cứ thứ gì, build kiểm runtime và tham chiếu quan sát. Store xác minh checksum khi đọc gói. Mask được render lại từ **nhãn hiện tại** bằng `correction_observations` (cùng bộ render đang dùng cho hiệu chỉnh membership), rồi đổi nhãn nguồn sang id compact theo quy ước của `prepare_dataset`. Sau đó chạy `run_prepared_objectgs`, publish checkpoint, dataset và `ObjectSurfaceManifest` cho từng vật. ObjectGS chạy trước mọi collider.
- **Bước 3** (`7d348ea4`): chọn surface theo vật. Vật qua QA dùng surface ObjectGS, `surface_selection = {"chosen": "objectgs"}`. Vật không qua dùng vỏ của chính nó, `surface_selection = {"chosen": "gaussian_shell", "reason": "objectgs_quality_failed", "quality_reasons": [...]}`. Evidence (raw, quality report, repair report, candidate mesh) được publish cho mọi vật để truy vết.
- **Bước 4** (`a45e6347`): lỗi ObjectGS toàn cục ném `ObjectGeometryBuildError`. Scene không đổi, không có collider nào được dựng, thông điệp gợi ý đổi `geometry_method=shell`. `retryable` theo loại lỗi (xem Deviations 6). `ProcessCancelledError` đi qua nguyên vẹn. Hành vi này đã đúng từ bước 2; bước 4 khoá nó bằng test.

## Acceptance criteria

| # | Tiêu chí | Test |
| --- | --- | --- |
| 1 | Monkeypatch ObjectGS: vật A qua QA → collider từ surface ObjectGS, vật B không qua → collider từ vỏ; `surface_selection` đúng từng vật; evidence của cả hai được publish | `test_failing_objectgs_surface_falls_back_to_its_shell_with_a_recorded_reason`, `test_objectgs_build_uses_objectgs_surfaces_and_publishes_evidence` |
| 2 | ObjectGS lỗi train → build thất bại, scene không đổi, không collider từ vỏ | `test_global_objectgs_failure_keeps_scene_and_builds_no_colliders`, `test_global_objectgs_errors_offer_shell_and_say_whether_to_retry` |
| 3 | Runtime chưa cấu hình → build thất bại có thông điệp rõ, scene không đổi | `test_missing_objectgs_runtime_fails_before_touching_the_scene` |
| 4 | Chỉnh nhãn một nhóm hàng trong Draft → mask đưa vào ObjectGS phản ánh nhãn mới (kiểm pixel) | `test_masks_handed_to_objectgs_follow_the_current_labels` |
| 5 | `geometry_method=shell` → không gọi ObjectGS | `test_shell_geometry_never_calls_objectgs` |

Test bổ sung: `test_damaged_observation_reference_fails_before_objectgs` (checksum sai hoặc thiếu ref), `test_objectgs_build_rejects_partial_object_ids`, các test gói quan sát (`test_package_is_byte_stable_and_round_trips_views_in_order`, `test_undeclared_or_escaping_members_are_rejected`, `test_empty_observation_list_is_a_valid_package`), test Draft `test_objectgs_draft_publishes_observations_with_matching_checksum`.

## Files changed

- `src/services/orchestration/scene/objectgs_observations.py` (mới): `package_observations`, `unpack_observations`.
- `src/services/orchestration/scene/objectify.py`: lift nhận `objectgs_observations_dir` khi `geometry_method=objectgs`; `_publish_draft` đóng gói và ghi `objectgs_observations_ref`; tách helper `objectgs_runtime_for()`.
- `src/services/orchestration/scene/object_geometry_build.py`: nhánh objectgs (`_objectgs_surfaces`, `_rasterize_current_labels`, `_compact_masks`, `_publish_verified`, `_objectgs_runtime`, `_observations_ref`, `_source_pose`); `_Surface`; `_publish_colliders` (gom theo nguồn surface, mỗi nguồn một lần CoACD); `_build_colliders` giữ nguyên chữ ký cũ cho nhánh vỏ.
- `src/services/scene/objectgs.py`: tham số `raise_on_quality_failure` (mặc định `True`, hành vi cũ giữ nguyên); receipt có thêm `quality_reasons`.
- `tests/test_scene/test_object_geometry_build_objectgs.py` (mới): 16 test.
- `tests/test_scene/test_objectify_draft.py`: thêm 1 test cho Draft có quan sát.
- `.ai/tasks/T-008/report.md`, `.ai/status.md` (chỉ dòng T-008).

## Tests

- Bộ Tests required của plan: `pytest tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_object_geometry_build.py tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectgs_objectify_flow.py -q` → **64 passed, 2 failed**. Hai ca lỗi thuộc T-005, không thuộc T-008. Xem Known issues mục đầu tiên.
- `tests/test_scene/test_objectgs.py` (module ObjectGS): passed.
- `ruff check` và `ruff format --check` trên 6 file đã sửa: passed.
- `graphify update .` đã chạy.
- Không chạy ObjectGS, CoACD hay bộ render thật (GPU). Các provider được thay bằng fake có đúng hình dạng receipt, report và surface, theo đúng yêu cầu "dùng monkeypatch như plan".

## Deviations from plan

1. **Thứ tự phase**: `shell → objectgs → quality → collider → environment → publish`. Architecture §7.4 ghi collider trước objectgs. Tôi đảo lại vì acceptance 2 yêu cầu lỗi ObjectGS không được tạo collider từ vỏ.
2. **`run_prepared_objectgs`** có thêm tham số `raise_on_quality_failure` (mặc định `True`, các caller cũ không đổi) và receipt có thêm `quality_reasons`. Plan không liệt kê file `objectgs.py` trong Files; thay đổi này cần để quyết định theo từng vật và để ghi lý do.
3. **Tách `objectgs_runtime_for()`** khỏi `objectify()` để build dùng cùng cách dựng runtime. Thông điệp lỗi giữ nguyên.
4. **Nguồn mask**: mask được render lại từ nhãn hiện tại. Mask SAM2 lúc tách (chỉ số seed) được đóng gói làm bằng chứng nhưng build không dùng, vì chúng không phản ánh chỉnh vùng. Xem câu hỏi 1.
5. **Dựng riêng từng vật với ObjectGS** (`object_ids` khác None): báo lỗi rõ ràng. ObjectGS cần đủ mọi vật, nên việc này cần quyết định ở T-011.
6. **Phân loại `retryable`**: `RuntimeError` và `OSError` là `True`, `ValueError` là `False`. Plan để việc này cho engineer quyết.
7. **Lỗi CoACD trên surface ObjectGS**: ném `ObjectGeometryBuildError`, không lùi về vỏ. Nhánh vỏ cũng hành xử như vậy.
8. **Thứ tự test**: module gói quan sát (bước 1) được viết trước test của nó, vi phạm nguyên tắc test trước cho phần này. Test viết ngay sau và đều xanh.
9. **Test trong `test_objectify_draft.py`**: plan không liệt kê file này trong Files, nhưng nó có trong Tests required. Tôi thêm đúng một test.
10. **Không đặt `in-progress` lúc bắt đầu.** Quên bước này; đã đặt `implemented` khi xong.

## Known issues / TODO

- **Hai ca đỏ thuộc T-005, do commit của T-009 gây ra.** `test_objectify_draft::test_strict_extraction_error_names_shell_and_objectgs` và `::test_extraction_publishes_draft_with_source_ownership`. Nguyên nhân: `extraction.py:192` (commit `3b109112`/`afe537e1`) gọi `load_job_config(job.job_id, job.config_checksum, ...)` ngay sau `job_requires_strict_geometry`, trước khi kiểm tra nghiêm ngặt. Ca đầu truyền `job=None`, nên lỗi `'NoneType' object has no attribute 'job_id'` xảy ra trước khi lỗi "Job hình học nghiêm ngặt" được ném. Không sửa ở đây vì file thuộc T-009 và đã được accept. **Cần T-009 sửa thứ tự gọi, hoặc đổi test.**
- `objectify_queue.py:251` (T-009): `object_centric` chỉ nhận `provenance.geometry_method == "objectgs"`. Cần kiểm lại khi hàng đợi chạy build mới.
- Gói quan sát lưu một PNG cho mỗi view mà lift chấp nhận, nên kích thước tăng theo số view. Chưa đo trên scene thật. Đề xuất đo ở T-019.
- Bộ render mask cần CUDA và gsplat, nên build phải chạy trên worker GPU giống như objectify.
- Chất lượng ObjectGS thật chưa được kiểm. Logic quality gate không đổi, chỉ thêm tham số để caller chọn.

## Câu hỏi cho Architect

1. **Nguồn mask cho ObjectGS.** Tôi chọn render lại từ nhãn hiện tại, đúng với "mask dựng lại từ nhãn hiện tại" và acceptance 4. Hệ quả: ObjectGS học trên mask render từ 3DGS hiện tại, không phải mask SAM2 lúc tách. Chất lượng có thể khác. Xác nhận đây là lựa chọn mong muốn.
2. **Dựng riêng từng vật với ObjectGS (T-011).** Hiện báo lỗi rõ ràng. Cần quyết: dựng lại toàn bộ scene, hay không hỗ trợ.
3. **Thứ tự phase trong §7.4.** Cập nhật architecture theo thứ tự thực tế (objectgs trước collider), hoặc xác nhận thứ tự đã chọn.
4. **Phân loại `retryable`** (Deviations 6). Xác nhận.
