# T-044 — Báo cáo triển khai

## Kết quả

Đã làm Phần 1 → 2 → 3 trên branch `mvp-pipeline-v2`, bắt đầu từ `0fff8567`. Không push, merge, tạo branch hay thêm Co-Authored-By. Các thay đổi ngoài phạm vi đã có sẵn trong cây được giữ nguyên.

- Mô tả các bước dùng tiếng Việt, tối đa hai câu; có nhánh che mặt/biển số, duyệt bản đã che, tỉ lệ tự đề xuất/đo tay, collision ảnh/LiDAR và bề mặt ObjectGS/vỏ Gaussian.
- Ba bước cuối dùng thẻ số liệu/ảnh đã ghi trong bundle. Export tự thêm tỉ lệ, nguồn, đoạn kiểm C–D/sai số, nguồn collision, số tam giác, số vật ứng viên và ảnh stage đã publish nếu có. Không render ảnh mới.
- `object_geometry` tùy chọn chứa trạng thái, thời lượng và số bề mặt ObjectGS/vỏ Gaussian/collider. Replay thêm hàng Duyệt vật & Tạo mesh khi có mục này; bundle cũ không có thì giữ danh sách cũ. ID giao diện không được thêm vào enum StageId của pipeline.
- `StageProgress.note` tùy chọn được máy chủ soạn từ receipt; parser frontend nhận chuỗi/null/field vắng và từ chối kiểu sai. ProgressTab hiển thị note; hàng hình học hiển thị số vật theo QA lựa chọn bề mặt khi có.
- Contract mirror đã kiểm cả StageProgress trong `studio.ts`, ngoài các model sẵn có trong `api.ts`.

## Quyết định triển khai

1. Tái sử dụng `facts`/`image`, không thêm schema số đo riêng cho từng thẻ. Chỉ thêm mục `object_geometry` tùy chọn.
2. Khi prepare không có thời điểm bắt đầu riêng, hai bước sau để `duration_seconds = null`; bước đầu chỉ ghi khoảng thời gian prepare đo được và ghi rõ **gộp chung 3 bước**. Thiếu cả mốc chung thì cả ba để null. Thời lượng bằng/nhỏ hơn 0 không được xuất thành 0 giả. Replay hiển thị **Thời gian: chưa đo** cho bước hoàn tất có null. Job có started_at/completed_at riêng vẫn dùng số đo đó.
3. Thời gian Tạo mesh chỉ lấy từ request `geometry` hoàn tất có `result_revision` đúng head đang xuất; request cũ hoặc mode khác không được dùng. Request lỗi/hủy gắn đúng Draft hiện tại được xuất là failed.
4. Đọc head đã commit trực tiếp; không gọi `SceneEditor.current()` vì nó có thể tự nhận head legacy. Job thiếu head hợp lệ không được suy số vật/hình học. Số vật ứng viên chỉ đếm `origin = reconstructed`, loại vật người dùng thêm.
5. Cache receipt theo resolver + URI + checksum, tối đa 128 mục; bản kê che đã xác minh cache tối đa 64 mục theo JobManifest. Không đọc mesh, ảnh hay Gaussian trong `/progress`; metadata thông thường giới hạn 4 MiB. Thiếu/hỏng/quá giới hạn thì bỏ kết quả phụ, không tạo note giả. Kiểm bản đã che tái dùng loader đối chiếu checksum của anonymization_review; acceptance phải khớp cả frame set và manifest che.
6. Chỉ exporter đọc collision mesh để đếm tam giác; đây là đọc artifact đã có, không chạy reconstruction hay render. Kiểm thư viện cũ dùng test tạm đọc trực tiếp manifest, không lưu fixture riêng chứa đường dẫn máy.
7. Khi kiểm thử rộng hơn trong đúng phạm vi task, phát hiện test cũ so nguyên văn mô tả cũ. Đã sửa assertion và commit riêng `e31608cb`.

Không có quyết định contract/persisted-data ngoài các trường tùy chọn được plan cho phép. Không chạy lại pipeline, không khởi động lại `r2s-stack`, không ghi vào `data/demo/library`.

## File đã thay đổi

- Mô tả/replay/thẻ: `frontend/src/features/studio/stages.ts`, `demoStages.ts`, `useDemoReplay.ts`, `SampleFlow.tsx`, `DemoShowcase.tsx`, `showcase/registry.tsx`, `PipelineTimeline.tsx`.
- Tiến trình thật/contract: `frontend/src/features/studio/scene/ProgressTab.tsx`, `frontend/src/lib/contracts/studio.ts`, `frontend/src/lib/api/studio.ts`, `src/api/studio/scenes.py`, `src/services/orchestration/jobs/progress.py`, `jobs/stage_results.py`, `scene/objectify_queue.py`.
- Export: `src/services/orchestration/samples/models.py`, `samples/export.py`.
- Kiểm tra: `scripts/check_contract_mirror.py`, `tests/test_api/test_sample_routes.py`, `tests/test_orchestration/test_sample_export.py`, `test_progress_notes.py`, `frontend/tests/stage-descriptions.test.ts`, `studio-demo-showcase.test.tsx`, `geometry-review-step.test.tsx`, `progress-notes-contract.test.ts`, `progress-objectify.test.tsx`.
- Handoff: `.ai/status.md`, `.ai/tasks/T-044/report.md`.

## Kiểm thử

Không chạy full suite.

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_sample_export.py tests/test_api/test_sample_routes.py \
  tests/test_orchestration -q -k 'progress or sample'
```

**106 passed, 1112 deselected in 10.77s.** Có nhánh nguồn tỉ lệ đo tay/ảnh/LiDAR, ObjectGS/vỏ, che/không che, chờ duyệt/chấp nhận/bản chấp nhận cũ/không có vùng che, thiếu note, cache đổi checksum, thời gian prepare chung và request hình học đúng/sai revision/lỗi. Không dùng GPU cho các kiểm thử này.

```bash
.venv/bin/python scripts/check_contract_mirror.py
```

**PASS — 5 enum, 9 model khớp Pydantic.** Test cũng kiểm việc bỏ field note sẽ làm mirror báo lỗi.

```bash
cd frontend
./node_modules/.bin/vitest run tests/pipeline-timeline.test.tsx tests/studio-demo-showcase.test.tsx \
  tests/studio-sample-pipeline.test.tsx tests/progress-objectify.test.tsx tests/geometry-review-step.test.tsx \
  tests/stage-descriptions.test.ts tests/progress-notes-contract.test.ts tests/t044-local-parser.test.ts
npm run typecheck
./node_modules/.bin/eslint <toàn bộ file TypeScript đã sửa>
```

**8 test files / 85 tests passed; typecheck và eslint exit 0.** Trong đó 79 test được giữ trong repo, 6 test đọc parser trên dữ liệu local nằm trong `t044-local-parser.test.ts` tạm đã xóa bằng đường dẫn đầy đủ sau khi chạy. Sáu test này đọc 5 manifest thư viện hiện có và mẫu vừa xuất, không sửa thư viện.

```bash
.venv/bin/ruff check <10 file Python đã sửa>
.venv/bin/ruff format --check <10 file Python đã sửa>
git diff --check
```

**All checks passed; 10 files already formatted; diff không có lỗi whitespace.** Sau bổ sung ca thời gian hình học, file test đó cũng đã qua ruff check/format và 38 test export riêng trước commit.

## Xuất thử từ job có sẵn

Job: `job-b8f744da2286`. Dùng snapshot SQLite đọc từ `data/studio_local/runtime.db` và artifact có sẵn trong `data/studio_local/artifacts`; snapshot nằm trong thư mục tạm riêng để không tác động trạng thái stack.

Đích duy nhất: `/tmp/t044-engineer-KoRNTem5/bundle`. Mẫu được xuất lại tại cùng đích tạm sau bổ sung số tam giác; chỉ xóa bundle do phiên này tạo trước khi xuất lại. Không tạo mẫu thứ hai trong thư viện.

Parser backend `DemoManifest.model_validate_json` và frontend `parseDemoManifest` đều đọc được:

| Trường | Kết quả thực |
| --- | --- |
| Số khung hình | 273, giữ 12 ảnh đại diện |
| File bundle | 14 |
| Tỉ lệ | 3.05522 m/đơn vị |
| Nguồn tỉ lệ | Máy đề xuất từ ảnh |
| C–D đã khai báo / sau quy đổi | 23.17 m / 23.17 m |
| Sai số C–D tính theo bản khai báo | 0 m |
| Nguồn collision | ảnh |
| Số tam giác collision | 288156 |
| Số vật ứng viên | 0 |
| object_geometry | null, không thêm hàng Duyệt vật |

C–D ở job này dùng cùng ước lượng từ ảnh; số 0 trên không phải chứng minh sai số so với thước đo độc lập.

Thời gian xuất của tám bước, theo giây: `44.844376`, `0.00152`, `25.579438`, `643.98785`, `3119.506381`, `307.361841`, `195.259787`, `3.49616`. Job này có các mốc riêng nên không dùng thời gian prepare gộp. Nhánh thiếu mốc có kiểm thử riêng, không sửa artifact job để tạo tình huống thử.

Năm gói cũ đã parse: `aisle-cw`, `aisle-cw-quick`, `room-mip-nerf-360-a14981f7`, `sc-01-01-loidi-kho-thuan-aisle-cw-video-only-b8f744da`, `torwic_scene_01`. Không thêm hàng Duyệt vật cho các gói chưa có mục mới.

## Chi phí tiến trình

Cùng snapshot SQLite, gọi trực tiếp handler `get_job_progress`, mỗi job khởi động một lượt rồi lấy median 10 lượt. Đo trước khi thêm note và sau phiên bản cuối:

| Job | Trước (ms) | Sau (ms) | Chi phí đọc note khi cache trống (ms) |
| --- | ---: | ---: | ---: |
| job-b8f744da2286 | 8.997 | 7.541 | 3.274 |
| job-a14981f78f85 | 9.023 | 7.580 | 12.002 |
| job-f3393ecbfbd6 | 11.211 | 7.454 | 2.987 |

Không diễn giải chênh lệch âm thành tối ưu hiệu năng; đây là dao động của đo local. Chi phí note lạnh lớn nhất 12.002 ms, dưới 50 ms. Cache đã có để tránh đọc lại metadata khi UI poll.

Đo bổ sung HTTP nội bộ qua `FastAPI TestClient`/ASGI, không mở server hay restart stack. Dùng cùng snapshot, tắt/bật riêng `stage_notes`, mỗi cấu hình bỏ một lượt đầu và lấy median 10 lượt:

| Job | Tắt enrichment note (ms) | Bật enrichment note (ms) | Tăng (ms) |
| --- | ---: | ---: | ---: |
| job-b8f744da2286 | 11.637 | 11.734 | 0.097 |
| job-a14981f78f85 | 10.635 | 12.232 | 1.597 |
| job-f3393ecbfbd6 | 10.953 | 12.055 | 1.102 |

Đây là phép đo chi phí HTTP có kiểm soát trên mã cuối, baseline tắt enrichment; không phải HTTP của binary cũ hay endpoint đang phục vụ trong `r2s-stack`. Auth được override chỉ trong app test nội bộ; cấu hình auth của stack không thay đổi.

## Commit và kiểm tra liên quan

| Commit | Phạm vi | Kiểm trước commit |
| --- | --- | --- |
| d2c5d3cb | Phần 1: mô tả | 12 Vitest, typecheck, eslint |
| b0a2c86a | Phần 2: thẻ | 10 Vitest, typecheck, eslint |
| 9da43ea1 | Phần 2: object_geometry + replay | 19 pytest, 25 Vitest, typecheck, eslint, ruff |
| b1f68be1 | Phần 2: xuất số liệu thật | 38 pytest, ruff |
| 1f1fe009 | Phần 2: thời gian | 39 pytest, 26 Vitest, typecheck, eslint, ruff |
| c2f664c2 | Phần 3: backend + contract | 93 pytest, 2 Vitest, mirror, typecheck, eslint, ruff |
| e31608cb | Sửa assertion mô tả cũ | 32 Vitest, eslint |
| fc266076 | Phần 3: hiện note | 50 Vitest, typecheck, eslint |
| b921390c | Bổ sung tam giác, chỉ đếm vật tái dựng | 51 pytest, ruff |
| 023bd109 | Mirror kiểm StageProgress | 13 pytest, mirror 9 model, ruff |
| 918d8352 | Ca request hình học đúng/sai revision/lỗi | 38 pytest export, ruff |

Mọi commit dùng `git add` đúng path. Không stage các file tasks/CFG và tài liệu ngoài phạm vi có sẵn.

## Gate report

Pre-flight (GUIDE.md Rule 13):

- codegraph: đã explore `MVP_STAGES`, `StageProgress`, `job_progress`, `STAGE_PRESENTERS`, `stagesFor`, `parseDemoManifest`, `export_job_bundle`, `_attach_assets`, `SampleFlow`, `useDemoReplay`, `geometryReviewStep`, `ObjectifyState`, `get_job_progress`, `job_bundle`, `SceneEditor.current`, `_check_models`, `_ts_interface_fields`.
- impact: mô tả dùng chung tiến trình thật/mẫu; manifest/parser/API mẫu; timeline/replay; handler progress và ObjectifyState. Không đổi pipeline runner, StageId hay dữ liệu job đang lưu.
- understand: lần theo code/receipt xác nhận mét, bản che + acceptance, bundle collision, head SceneIR và QA `surface_selection`. Không có tool understand-anything trong phiên; đã đọc luồng bằng CodeGraph.
- minimal-code: tái dùng thẻ facts/image, loader anonymization_review, TimelineStageView.note và helper stage metadata; dùng lru_cache chuẩn Python.
- checks: pytest 106 passed; Vitest 85 passed gồm 6 ca local tạm; typecheck/eslint/ruff/mirror xanh.
- DevTools: **UNVERIFIED — kiểm giao diện bằng mắt để chủ dự án làm theo yêu cầu.** Component tests không chứng minh browser/GPU acceptance; không khởi động hay restart stack để kiểm mắt.
- graphify: `graphify update .` exit 0 sau khi xóa test local tạm; 27432 nodes, 85624 edges, 842 communities. Cập nhật AST, không chạy semantic/LLM labeling. Graph output được ignore theo cấu hình repo, không có file graph tracked để stage.

## Bàn giao

Chuyển T-044 sang `implemented | summarizer`. Chủ dự án kiểm giao diện bằng mắt và chạy lại/xuất lại scene mẫu bằng pipeline mới theo kế hoạch riêng. Task này không tạo bằng chứng về một lần chạy pipeline/GPU mới.

Đã xóa `/tmp/t044-engineer-KoRNTem5` bằng chính đường dẫn đầy đủ, gồm bundle, SQLite snapshot, script và JSON đo thời gian. Đã xóa `/tmp/t044-codegraph.txt` và `/home/lqaq/PROJECT/AI20K/P-087/frontend/tests/t044-local-parser.test.ts` bằng đường dẫn đầy đủ. Nội dung kết quả đã được ghi trong báo cáo này; không dọn thư mục tạm của phiên khác.

## Round 2 — Sửa bộ đệm theo review

Đã xử lý mục Required changes trong `.ai/tasks/T-044/review.md`. Quyết định cache ở mục 5 của báo cáo vòng đầu được thay bằng cách dưới đây; phần còn lại là bằng chứng lịch sử của vòng đầu.

### Thay đổi

- Bỏ `lru_cache` khỏi `_read`: mỗi lần gọi hàm này đều kiểm checksum qua resolver và chỉ giữ tài liệu JSON trong thời gian xử lý, vẫn giới hạn 4 MiB.
- `_scene_summary(resolver, uri, checksum)` cache tối đa 256 tuple `_SceneSummary`. Chỉ giữ số vật tái dựng, trạng thái tách vật, các reference collision dưới dạng tuple, trạng thái hình học, tuple lựa chọn bề mặt, số collider và revision. Không giữ danh sách vật, collider, provenance đầy đủ hoặc dict scene.
- `_metric_summary` và `_collision_summary` cũng cache tối đa 256 tuple rút gọn theo resolver, URI và checksum; tỉ lệ có thêm job ID để giữ kiểm tra receipt thuộc đúng job. Các dict trả cho exporter được dựng lại từ tuple, không được giữ trong cache.
- `_redaction_summary` giữ tối đa 64 tuple, khóa theo registry + job ID + checksum của stage bản che. Hàm đọc job qua registry và đối chiếu checksum trước khi dùng loader đã có. Thay đổi trạng thái job không tạo thêm khóa chứa toàn bộ JobManifest.
- Không đổi câu chữ hoặc logic trong hai Suggestions không bắt buộc. Không đổi contract/persisted data, pipeline, hay giao diện.

File sửa: `src/services/orchestration/jobs/stage_results.py`, `tests/test_orchestration/test_progress_notes.py`, `.ai/status.md`, báo cáo này.

### Test đỏ → xanh

Trước khi sửa source, chạy:

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_progress_notes.py -q -k 'cache or caching'
```

**3 failed, 12 deselected in 4.17s** trên mã cũ:

1. `_read` trả dict cache cũ sau khi file thay đổi, không phát hiện checksum sai.
2. Sau 300 revision giả, chưa có `_scene_summary` để kiểm giới hạn và nội dung cache.
3. `stage_notes` còn gọi `job.model_dump_json()` làm khóa redaction cache.

Fixture hồi quy dùng scene 400 vật, mỗi vật kèm 2.000 ký tự không dùng để mô phỏng JSON lớn, gọi `stage_notes` qua 300 revision/checksum. Sau sửa, xác nhận cache scene tối đa 256 mục, summary là tuple chỉ chứa scalar/tuple, không giữ dict/list scene; revision cuối đúng `rev-299`, note và số ObjectGS/collider đúng. Test redaction xác nhận thay đổi checksum job không làm đọc lại cùng bản che, còn checksum stage mới thì đọc lại. Test tỉ lệ/collision xác nhận cache chứa tuple nhỏ, cache hit với checksum cũ và cache miss khi checksum thay đổi, kể cả receipt có dữ liệu dư lớn.

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_progress_notes.py tests/test_orchestration/test_sample_export.py -q
```

**55 passed in 3.22s.** Giữ nguyên kết quả note/facts/export của các ca cũ.

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_sample_export.py tests/test_api/test_sample_routes.py \
  tests/test_orchestration -q -k 'progress or sample'
.venv/bin/python scripts/check_contract_mirror.py
.venv/bin/ruff check src/services/orchestration/jobs/stage_results.py tests/test_orchestration/test_progress_notes.py
.venv/bin/ruff format --check src/services/orchestration/jobs/stage_results.py tests/test_orchestration/test_progress_notes.py
```

**110 passed, 1112 deselected in 12.51s; mirror PASS — 5 enum, 9 model; ruff sạch, 2 file đã đúng format.** Không chạy full suite. Không sửa TypeScript nên không chạy lại frontend/typecheck.

### Đo lại `/progress`

Dùng `sqlite3.backup` từ database local mở chỉ đọc sang `/tmp/t044-round2-liBgMETa/runtime.db`; cả trước và sau sửa dùng cùng snapshot và artifact hiện có. Gọi HTTP nội bộ bằng FastAPI TestClient/ASGI trên mã trước/sau sửa, override auth chỉ trong app test, không mở server và không thay cấu hình stack. Mỗi job bỏ lượt đầu cache lạnh và một lượt khởi động tiếp theo, lấy median 10 lượt. Mỗi lần đo chạy trong process riêng.

| Job | Trước sửa cache (ms) | Sau sửa cache (ms) | Chênh lệch (ms) |
| --- | ---: | ---: | ---: |
| job-b8f744da2286 | 10.244 | 14.870 | +4.626 |
| job-a14981f78f85 | 9.739 | 9.616 | -0.123 |
| job-f3393ecbfbd6 | 9.512 | 9.691 | +0.179 |

Chênh lệch lớn nhất +4.626 ms, dưới ngưỡng tăng 50 ms của plan. Dao động local không chứng minh cải thiện tốc độ. Đây là phép đo HTTP nội bộ trên snapshot, không phải latency endpoint đang phục vụ của `r2s-stack`, và không chứng minh đã sửa tình trạng trình duyệt không phản hồi khi xem giai đoạn.

### Gate và bàn giao Round 2

- codegraph: đọc `_read`, `scene_results`, `recorded_results`, `_redaction_summary`, `stage_notes`, `get_job_progress`, loader anonymization và các caller/exporter.
- impact: chỉ enrichment note/facts của progress và xuất mẫu; public response/contract giữ nguyên. Không có caller ngoài `recorded_results` dùng `scene_results`.
- understand: dùng CodeGraph lần theo receipt/head/checksum và exporter. Không có tool understand-anything trong phiên.
- minimal-code: dùng `lru_cache` chuẩn Python và một `NamedTuple` cho scene summary; tái dùng resolver, loader, cách dựng note/facts và request geometry hiện có.
- checks: 110 pytest passed, mirror/ruff/format sạch; không chạy frontend vì không đổi TypeScript.
- DevTools: không áp dụng cho thay đổi service không đổi giao diện; kiểm giao diện bằng mắt vẫn do chủ dự án thực hiện.
- Commit source + test: `5ebc1703` — `Cache compact progress summaries instead of parsed scene documents`.

Không khởi động lại `r2s-stack`, không chạy pipeline, không xuất hay ghi vào `data/demo/library`; không push/merge/tạo branch. Chỉ stage đúng path; giữ nguyên các thay đổi ngoài phạm vi.

`graphify update .` hoàn tất, exit 0: 27.458 nodes, 85.703 edges, 868 communities. Chỉ cập nhật AST; không chạy labeling LLM. Graph output được ignore, không force-add.

Đã xóa toàn bộ thư mục tạm riêng `/tmp/t044-round2-liBgMETa` bằng đường dẫn đầy đủ, gồm snapshot, script đo/sửa và kết quả đo/test đỏ. Các con số và lỗi hồi quy đã ghi ở Round 2. Không dọn thư mục tạm của phiên khác.

Required changes đã hoàn tất. Đặt T-044 thành `implemented | summarizer` để bàn giao review tiếp.
