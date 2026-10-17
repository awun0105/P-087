# T-011 report

## Outcome

Ready region edit đi qua durable queue mode `region`: worker đọc command đã lưu, tính membership mới và dựng lại đúng tập vật bị ảnh hưởng. Nền inpaint/SOG và collision môi trường luôn dựng lại theo nhãn mới. Chỉ publish một SceneIR revision sau khi mọi bước thành công, qua commit guard hiện có.

Brush/Lasso qua `membership/regenerate` cũng dùng builder này, không còn gọi `objectify_with_retry(correction=...)`. Rebuild một phần không chạy ObjectGS dù geometry_method=objectgs: vật bị ảnh hưởng dùng vỏ với `surface_selection.reason="partial_rebuild_uses_shell"`; vật còn lại giữ nguyên surface/collider cũ. Vật trong object_ids vẫn được dựng dù review IGNORED/DELETED/MERGED.

`region/apply`: Draft giữ 201 đồng bộ; Ready trả 202 ObjectifyState. Giữ contributor/ownership/quota/audit guard. Busy/stale/checksum → 409; vùng không hợp lệ hoặc để vật dưới 50 hàng → 422. Kiểm cả vật bị claim trước enqueue.

## Changed files

- `src/services/orchestration/scene/object_geometry_build.py`: MembershipOverride, kiểm nguồn/nhãn/evidence, shell policy cho partial rebuild, cập nhật visual/dimensions vật bị ảnh hưởng, membership mới cho environment, correction provenance và một CAS commit.
- `src/services/orchestration/scene/membership_regeneration.py`: giữ phần chuẩn bị command/nhãn/evidence, thay producer cả scene bằng partial builder.
- `src/services/orchestration/scene/object_region.py`: validate/rebuild Ready, kiểm số hàng mọi vật bị ảnh hưởng, cancellation trước publication.
- `src/services/orchestration/scene/objectify_queue.py`: lưu object_id/command, đưa command vào config checksum, worker dispatch, admission/progress/cancel/lease fence; đổi membership gate sang Ready và sửa projection retryable cho lỗi build.
- `src/api/product/scene.py`: Ready 202 và Draft 201, response/error mapping.
- `src/services/orchestration/scene/editor.py`: allowlist evidence nhận thêm đúng ObjectRegionEdit theo plan; giữ kiểm cùng job.
- Test: `test_object_geometry_build.py`, `test_membership_regeneration.py`, `test_object_region.py`, `test_scene_objectify_queue.py`, `test_scene_v2_routes.py`, và fixture tương thích bị ảnh hưởng trong `test_objectgs_objectify_flow.py`.
- `.ai/tasks/T-011/report.md`, `.ai/status.md` chỉ dòng T-011.

Frontend ObjectifyMode đã có region trong commit `815cb30b`; T-011 không chép lại hay sửa frontend source. Đã chạy typecheck toàn frontend.

## Verification

Đúng nhóm Tests required:

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_membership_regeneration.py \
  tests/test_scene/test_object_region.py tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py -q
```

**183 passed in 126.00s (0:02:06), 0 failed, 0 skipped.** Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/object_geometry_build.py src/services/orchestration/scene/editor.py src/services/orchestration/scene/membership_regeneration.py src/services/orchestration/scene/objectify_queue.py src/services/orchestration/scene/object_region.py src/api/product/scene.py tests/test_scene/test_object_geometry_build.py tests/test_scene/test_membership_regeneration.py tests/test_scene/test_object_region.py tests/test_scene/test_objectgs_objectify_flow.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py
.venv/bin/ruff format --check src/services/orchestration/scene/object_geometry_build.py src/services/orchestration/scene/editor.py src/services/orchestration/scene/membership_regeneration.py src/services/orchestration/scene/objectify_queue.py src/services/orchestration/scene/object_region.py src/api/product/scene.py tests/test_scene/test_object_geometry_build.py tests/test_scene/test_membership_regeneration.py tests/test_scene/test_object_region.py tests/test_scene/test_objectgs_objectify_flow.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py
```

All checks passed; 12 files already formatted. `git diff --check` sạch.

Trong `frontend/`, `npm run typecheck` (`next typegen && tsc --noEmit`) exit 0.

### Kiểm từng bước, red → green

- MembershipOverride: 12 failed khi chưa có interface → 12 passed sau triển khai. Mở rộng fixture Ready ba vật và surface ObjectGS cũ giả lập: hai vật không bị ảnh hưởng giữ nguyên ref; review tombstone vẫn nhận collider. Thiếu ids, nhãn/nguồn sai, stale, huỷ và lỗi vỏ giữ head cũ.
- Test inventory evidence phát hiện SceneEditor từ chối ObjectRegionEdit. Mở đúng loại này, giữ same-job guard; cả file build đạt **43 passed in 76.09s**, gồm các ca CoACD thật có sẵn.
- Brush/Lasso: **5 failed, 2 passed** vì vẫn gọi producer cũ → **7 passed** sau đổi dispatch. Thêm integration với builder thật cho source ownership cũ và pose đã Move → **8 passed in 2.06s**.
- Ba test service Ready ban đầu lỗi tên entrypoint trong test, sau nối đúng rebuild_region_ready → **3 passed**. Các integration Ready được gom vào test_object_region.py theo plan; file này cuối cùng **24 passed in 9.10s**.
- Queue region mới: **2 failed, 7 passed**, phát hiện retryable bị che và gate membership vẫn chỉ cho ObjectGS. Test validation riêng cũng đỏ vì chưa chặn claim làm donor dưới 50 hàng. Sau sửa, nhóm region + queue đạt **63 passed in 10.45s** trước khi bổ sung các integration Ready còn lại.
- HTTP + role matrix: **62 passed in 2.19s**. Năm ca dùng queue/DB thật với registry fixture: 202 lưu command/object_id/actor, không đổi SceneIR; busy/stale/checksum 409; vùng quá nhỏ 422.

Các fixture CPU thay provider inpaint/SOG/GPU, ngoại trừ ca CoACD thật đã có trong test build. Surface ObjectGS giả lập chứng minh giữ ref và không dispatch, không phải bằng chứng train GPU/ObjectGS, browser hay deployed service. Fixture test_objectgs_objectify_flow.py đã được điều chỉnh và lint; file này nằm ngoài sáu file Tests required nên không chạy riêng trong lượt T-011 này.

## Decisions và lệch plan

1. Theo review T-008 quyết định 2, architecture §7.4 và tiêu chí 0b thay cho câu retrain còn sót trong mục Interfaces của plan. Partial rebuild không gọi cả bước chuẩn bị runtime/observations ObjectGS. Full Draft ObjectGS build giữ nguyên.
2. MembershipOverride kiểm source visual/geometry, extraction revision, coordinate system, số hàng và tập chủ không đổi; nhãn int32 phải khớp chính xác file đã publish. Object ids phải có trong membership/scene. Evidence phải cùng job và thuộc một trong hai loại correction được cho phép.
3. PLY mới theo source frame của chính vật, gồm đổi quaternion khi đủ rot_0..3; không căn tâm lại. Ready cũ thiếu provenance.source_transform chỉ được lấy pose từ source_collision khớp geometry/extraction. Full Draft giữ kiểm frame trước đây.
4. Builder cập nhật cả visual/dimensions của vật bị ảnh hưởng để visual không giữ membership cũ. Vật không bị ảnh hưởng giữ nguyên toàn bộ object, gồm transform, physics, review và source refs.
5. Thêm ObjectRegionEdit vào inventory của SceneEditor là phần nối cần thiết để evidence dưới membership_correction được đọc qua cơ chế authorize/inventory hiện có, không mở loại artifact tuỳ ý.
6. Mode region dùng lại GPU resource profile, admission, heartbeat, resource wait, cancellation và commit guard. Không bịa estimate hay tạo queue mới. Field optional mặc định null cho record cũ; checksum gồm object_id và command. Sửa object_id trong record làm worker từ chối trước dispatch.
7. Artifact bất biến có thể còn lại khi lỗi/thua CAS; không được gắn vào scene head khi failed/cancelled, đúng quy tắc writer đã accepted ở T-010.
8. Không xoá producer objectify(correction=...) cũ; T-011 chỉ ngừng gọi từ membership regeneration. Dọn producer để task sau.

### Lý do đổi assertion cũ

- Regeneration stub build_object_geometry/MembershipOverride thay objectify_with_retry/CorrectedMembership để kiểm affected object_ids, nhãn đã publish và evidence đi vào service mới.
- Source_poses argument không còn: thay bằng integration kiểm source_collision/source_transform và pose đã Move vì builder đọc khung nguồn từ SceneIR.
- wrong_receipt đổi thành typed build_failure: builder trả revision đã commit, không trả ObjectifyResult. Test build riêng kiểm nhãn/nguồn override sai. Giữ assertion huỷ và stale không đổi head.
- Fixture ObjectGS cũ kiểm correction evidence thay receipt pipeline mới vì partial rebuild không chạy lại extraction/training. Fixture thưa 100 hàng dùng voxel thô chỉ trong test, không nới tham số production. USD bounds so với collider đã publish đổi một lần sang world, thay số cố định của surface ObjectGS cũ.
- HTTP Ready đổi deferred 422 → queued 202; Draft vẫn 201. Ready legacy thiếu membership vẫn 422 fail closed. Không bỏ contributor/ownership guard.

## Commits T-011

- `46dff52e` Mark T-011 in progress
- `1beebc1d` Rebuild affected Ready geometry from a verified membership override
- `07166cbf` Route Ready membership corrections through partial shell rebuilds instead of retraining ObjectGS
- `67465cdb` Queue Ready region commands with selective rebuilds and lease fencing
- `8c452297` Queue Ready region apply requests while keeping Draft edits synchronous

## Pre-flight (GUIDE.md Rule 13)

- codegraph: đã đọc build_object_geometry/callers, prepare_correction/regenerate_membership, queue request/process_next, region service/callers và inventory SceneEditor; review T-007/T-008/T-010, architecture/roadmap; đã chạy graphify query.
- impact: jobs worker → process_next; membership/region route → queue → partial builder. Direct build giữ optional arguments hiện có. Inventory giữ same-job evidence guard.
- understand: nhãn nguồn → tập chủ bị ảnh hưởng → shell/quality/collider → nền/environment mới → một fenced Ready revision. Không suy policy từ chat memory.
- minimal-code: tái dùng shell builder, membership encoding/region resolver, artifact store, durable queue, admission và SceneIR CAS.
- checks: pytest 183 passed, ruff sạch; frontend typecheck exit 0. DevTools n/a — task không sửa rendered UI.

## Architect review

Không còn câu hỏi contract cần chốt. Partial ObjectGS theo đúng quyết định dùng vỏ đã review. Dừng ở implemented chờ review; UI và xoá producer cũ ngoài phạm vi.

`graphify update .`: exit 0; 25.434 nodes, 79.164 edges, 859 communities. Đã cập nhật graph.json/graph.html/GRAPH_REPORT.md; không chạy LLM label.
