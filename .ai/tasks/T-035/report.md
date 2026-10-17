# T-035 — Regression và hướng dẫn đo

## Outcome

Đã triển khai ba việc dọn nhỏ, viết handoff đủ giới hạn và chạy đủ lệnh regression. Full backend: **3687 passed, 1 failed, 28 skipped**; lỗi duy nhất là test pin schema 19 cũ, đã sửa bằng commit riêng và xác nhận **65 test liên quan PASS**. Full frontend trên source đã commit: **936 PASS**. Không tuyên bố full backend đã PASS sau sửa khi chưa chạy lại toàn bộ.
Branch giữ nguyên `mvp-pipeline-v2`; HEAD lúc nhận task `b59eee850e9ba5cbb41e99484f33f30cf92f526f`.
Không push, merge, tạo branch hoặc PR. Không thêm Co-Authored-By.

## Thay đổi

- `frontend/src/features/studio/MetricSceneView.tsx`: khi inspection chọn điểm, tạm tắt collision môi trường,
  collider vật, box, surface marker và vỏ nền; kết thúc/huỷ thì khôi phục lựa chọn lớp phủ. Callback inspection giữ ổn định
  để thay đổi trạng thái đo không khởi tạo lại viewer.
- `frontend/src/features/studio/value/BenchmarkPanel.tsx`: nút bỏ chọn vật cản không còn trong scene ghi
  “Bỏ chọn vật đã xoá (id)” cả chữ hiển thị và accessible name; bỏ chọn vẫn lưu đúng danh sách.
- `src/services/orchestration/value/scorecard.py`: đầu `benchmark_markdown` ghi “Khe khớp: —” khi tổng khe bằng 0;
  có khe vẫn hiện tỉ lệ thật.
- `frontend/tests/metric-effective-collision.test.tsx`: kiểm tắt/khôi phục các lớp ở biên viewer/overlay,
  vỏ được clear/nạp lại, callback không đổi và state vẫn truyền tới caller. Mock WebGL, không phải kiểm UI bằng mắt.
- `frontend/tests/benchmark-panel.test.tsx`: cập nhật regression nhãn vật đã xoá và kiểm thao tác bỏ chọn gửi đúng payload.
- `tests/test_orchestration/test_value_scorecard.py`: tổng benchmark rỗng không giả thành 0/0; tổng có khe giữ 1/2.
- `docs/plans/active/2026-10-16-value-metrics/HANDOFF.md`: nguồn 5 metric, nhập ground truth, xuất bảng,
  đủ “Giới hạn đã biết”, danh sách “đã có” để Architect cập nhật Playbook.
- `tests/test_orchestration/test_registration_operations.py`: bỏ ép schema latest=19 trong regression registration khi Sprint 6 đã thêm v20/21.
- `.ai/status.md`, `.ai/tasks/T-035/report.md`: trạng thái và bàn giao theo quy trình.

## Điều tra và RED → GREEN

Dùng skill systematic-debugging, test-driven-development và verification-before-completion.

1. Review T-033 và code cho thấy Picker nhìn cả app.scene. `MetricSceneView` truyền onState trực tiếp,
   các effect collision/box/vỏ không xét trạng thái measuring. Test bật collision, bắt đầu đo rồi kiểm lớp vẫn bật:
   đỏ đúng sai khác true/false. Bản mở rộng có vỏ cũng đỏ trên code cũ.
2. `benchmark_markdown` nội suy tử/mẫu vô điều kiện. Test benchmark rỗng đỏ vì trả `Khe khớp: 0/0` thay “—”.
3. Nút xoá mục thiếu dùng id thô. Test bỏ chọn qua accessible name mới đỏ vì không tìm được nút mô tả vật đã xoá.

Kết quả RED trước khi sửa source:
- `pytest tests/test_orchestration/test_value_scorecard.py -q`: **34 passed, 1 failed, 0 skipped**;
  fail `test_benchmark_markdown_without_gaps_does_not_claim_a_zero_measurement`.
- Vitest benchmark-panel + metric-effective-collision: **23 passed, 2 failed, 0 skipped**; hai failure là nhãn nút và lớp collision.
- Metric test mở rộng vỏ riêng trên source cũ: **11 passed, 1 failed, 0 skipped**.

GREEN:
- `.venv/bin/python -m pytest tests/test_orchestration/test_value_scorecard.py -q`: **35 passed, 0 failed, 0 skipped**.
- `cd frontend && ./node_modules/.bin/vitest run tests/benchmark-panel.test.tsx tests/metric-effective-collision.test.tsx tests/object-review.test.tsx tests/region-editor.test.tsx`:
  **4 file, 148 passed, 0 failed, 0 skipped**, 13,15 s ở lần cuối.

Xác nhận cuối trên source đã commit: `.venv/bin/python -m pytest tests/test_orchestration/test_registration_operations.py::test_registration_operation_migration_is_latest_and_additive tests/test_orchestration/test_value_scorecard.py -q` → **36 passed / 0 failed / 0 skipped**, 1,53 s.

## Full regression (bước 1)

| Lệnh | Kết quả thực tế |
| --- | --- |
| `.venv/bin/python -m pytest tests -q` | Exit 1: **3687 passed / 1 failed / 28 skipped**, 15 warnings, 569,36 s. Lỗi duy nhất T-035/REG-01 đã sửa riêng, focused sau sửa 65 PASS |
| `.venv/bin/ruff check src/ tests/` | PASS, All checks passed; không lỗi |
| `.venv/bin/ruff format --check src/ tests/` | PASS, 684 files already formatted |
| `.venv/bin/python scripts/check_contract_mirror.py` | PASS, 5 enum và 8 model khớp Pydantic |
| `cd frontend && npm test` trước sửa | PASS, 90 file, 935 passed / 0 failed / 0 skipped, 35,79 s |
| `cd frontend && npm test` sau ba sửa | PASS, 90 file, 936 passed / 0 failed / 0 skipped, 38,78 s ở lần cuối trên source đã commit |
| `cd frontend && npm run typecheck` | PASS, route types generated và tsc không lỗi; đã chạy lại sau thay đổi callback cuối |
| `cd frontend && npm run lint` | PASS, 0 error / 0 warning; đã chạy toàn frontend trước và sau sửa |
| `cd frontend && ./node_modules/.bin/eslint src/features/studio/MetricSceneView.tsx src/features/studio/value/BenchmarkPanel.tsx tests/benchmark-panel.test.tsx tests/metric-effective-collision.test.tsx` | PASS, output rỗng; sau callback cuối |
| `git diff --check` | PASS |
| `graphify update .` | PASS, exit 0; AST-only; lần cuối 488 uncached file, 26683 nodes / 83106 edges / 824 communities. Có cảnh báo 39 file không sinh symbol và community labels cũ; graph ở graphify-out/ bị gitignore. Không chạy graphify label dùng LLM. |

Full npm test đã chạy lại trên source commit `03168b1d`: **936 passed, 0 failed, 0 skipped**, 38,78 s.
148 test liên quan, typecheck và eslint cũng đã chạy lại sau điều chỉnh callback cuối.

### Vướng môi trường regression

- Full pytest trong sandbox không xuất kết quả và đứng ở đầu; collection độc lập thu được **3716 test trong 3,38 s**.
- Một lượt thêm traceback cũng đứng. Không đếm hai lượt này thành pass/fail/skip của suite.
- Chạy lại đúng `.venv/bin/python -m pytest tests -q` ngoài sandbox hoàn tất, kết quả như bảng trên. Chỉ dừng hai PID pytest do phiên này tạo
  (3543716, 3558244), SIGINT không thoát nên dùng SIGTERM. Không sửa source để né sandbox và không đụng process phiên khác.
- Lượt focused migration/API chạy trong sandbox dừng sau phần test thuần; PID 3579872 của phiên được SIGTERM sau khi lượt ngoài sandbox đã PASS 65 test.
- 28 test SKIP là kết quả thực tế của full run, không được tính PASS. Không có nghiệm thu UI bằng mắt, PostgreSQL thật, Isaac hoặc benchmark thực địa trong task này.
- 15 warning từ tests/test_api/test_error_view.py là DeprecationWarning của httpx về cookies theo request; không đổi dependency hay sửa ngoài scope.

### REG-01 — test migration cũ chặn schema Sprint 6 (đã sửa)

- Test `test_registration_operation_migration_is_latest_and_additive` ép latest = 19.
  Commit T-027 `22d4b892` thêm v20 (events), T-030 `60c02e64` thêm v21 (ground truth).
- Tái hiện focused trước sửa: **1 failed**, `assert 21 == 19`.
- Sửa riêng test: schema sau migration phải ≥19 và bằng LATEST_SCHEMA_VERSION; giữ các assertion dữ liệu project cũ
  và bảng registration. Không sửa production migration hay hạ schema.
- Sau sửa: `.venv/bin/python -m pytest tests/test_orchestration/test_registration_operations.py tests/test_orchestration/test_value_events.py tests/test_api/test_value_routes.py -q`
  ngoài sandbox → **65 passed / 0 failed / 0 skipped**, 3,59 s. Ruff check/format file sửa PASS.
- Commit riêng `e2d99ccb` Allow additive value migrations in the registration schema regression.
- Theo dõi tại T-035/REG-01: đã xử lý, không cần Architect quyết thiết kế.

## Handoff và giới hạn

Handoff có đủ: nhánh PostgreSQL T-030 chưa chạy thật; lệch đồng hồ >60 s làm lô thao tác 422 và bỏ im lặng;
link `<a download>` có thể tải JSON lỗi khi hết phiên; “Mở Benchmark” chỉ về Studio rồi người dùng bấm Benchmark;
L4 là khai báo; phút công chỉ trong trang scene. Các mục đã có T-027–T-035 được liệt kê để Architect cập nhật trang Playbook.
Không chỉnh trang Playbook bên ngoài.

## Commits

- `03168b1d` Keep benchmark point picks on splats and clarify missing measurements — bước 3 và test.
- `0056c5dd` Document value metric sources and benchmark handoff limits — bước 2 và danh sách bước 4.
- `e2d99ccb` Allow additive value migrations in the registration schema regression — xử lý T-035/REG-01.
- Commit report/status: xem git log sau khi hoàn tất.

## Quyết định lệch plan và việc còn dở

- T-035 chỉ định full regression rõ ràng, thực hiện theo user và plan dù README/architecture còn nói chỉ task regression cũ được chạy full.
- Dọn nhỏ và handoff đều commit riêng; commit dọn nhỏ trước handoff để hướng dẫn mô tả đúng hành vi đã test.
- Dùng `.ai/status.md` tập trung, cùng cách các task trước ghi trạng thái; không tạo status riêng trong thư mục task.
- Các thay đổi có sẵn ngoài T-035 (tasks/CFG, tasks/reports bị xoá, BRAINSTORM, MASTER_PITCH, thumnail và ghi chú .ai)
  được giữ nguyên, không stage hay xoá.
- Không chạy lại full backend 9 phút 29 giây sau khi chỉ đổi assertion test; đã chạy trọn 65 test migration/event/API liên quan, không đổi production database. Full run đỏ được giữ nguyên số và theo dõi tại T-035/REG-01 đã xử lý.
- Kiểm UI bằng mắt giao chủ dự án theo chỉ dẫn. Architect cập nhật Playbook bên ngoài.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: explore BenchmarkPanel, benchmark_markdown, ObjectReviewView, MetricSceneView và các hàm tổng hợp metric;
  callers benchmark_markdown, BenchmarkPanel, ObjectReviewView, MetricSceneView. Graphify query dùng để định hướng.
- impact: benchmark_markdown → route download_benchmark_markdown; BenchmarkPanel → ObjectReviewView → StudioTab;
  MetricSceneView dùng trong ObjectReviewView và StageLayer, đã kiểm test object-review/region-editor/effective-collision.
- understand: thay đổi cục bộ chế độ chọn điểm, nhãn vật thiếu và export metric chưa đo; không đổi contract hay thuật toán hình học.
- minimal-code: dùng lại inspection state, các effect/overlay methods và render hiện có; một điều kiện cho tổng khe. Không thêm dependency.
- checks: ruff check/format PASS; contract mirror PASS; tsc sạch; eslint sạch; full vitest 936 PASS, focused vitest 148 PASS; full pytest 3687 PASS / 1 FAIL / 28 SKIP, lỗi duy nhất sửa riêng và focused migration/event/API 65 PASS; scorecard 35 PASS.
- DevTools: UNVERIFIED — chủ dự án kiểm UI bằng mắt theo yêu cầu; không tuyên bố nghiệm thu viewer/WebGL.

## Trạng thái bàn giao

`T-035 | Regression + hướng dẫn đo | implemented | summarizer`. Không còn quyết định thiết kế cần Architect trong phần sửa.
Architect cập nhật Playbook từ handoff; chủ dự án kiểm UI bằng mắt. Regression T-035/REG-01 đã sửa; full-suite xanh sau sửa chưa được khẳng định.
