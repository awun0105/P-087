# Kiểm kê Markdown và đề xuất chuẩn hóa tài liệu

**Ngày khảo sát:** 20/10/2026. **Snapshot code:** `develop`, HEAD `ae7e3aca`; có thay đổi chưa commit.
**Trạng thái:** Đề xuất để chủ dự án xem xét. Chưa chuẩn hóa, di chuyển hoặc xóa tài liệu cũ trong lượt này.

## 1. Phạm vi và cách đọc kết quả

- Kiểm kê hợp nhất file đã track và file chưa track không bị Git ignore, chỉ lấy `.md`/`.markdown` còn tồn tại trên worktree. File đã xóa khỏi worktree không được đếm lại theo Git index.
- Có **541 Markdown**, loại **39 file trong `docs/guide/`** theo yêu cầu, còn **502 file**, tổng **80.656 dòng**. Đây là snapshot trước khi tạo chính báo cáo này; báo cáo không tính vào 502.
- Không đi vào `.git`, `node_modules`, môi trường Python, `data/`, output build hoặc tài liệu sinh tự động bị ignore. Vì vậy đây là danh sách docs trong source worktree, không phải toàn bộ file Markdown trên ổ đĩa.
- `GUIDE.md` ở root là quy tắc agent, khác sổ tay `docs/guide/`, nên vẫn được liệt kê.
- Các file `.harness-core/`, vendor, fixture và agent được liệt kê để đủ danh sách; chúng không tự trở thành đối tượng xóa.
- Đã đọc code hiện hành qua CodeGraph và kiểm tra cấu hình/route; đã đọc các phần nội dung trọng tâm của BRAINSTORM, MASTER_PITCH, kiến trúc, pipeline, PRD, UX, runbook và các báo cáo mới. Toàn bộ 502 file được đọc bằng công cụ để thống kê tiêu đề, cấu trúc, số dòng, nội dung trùng và liên kết Markdown.
- **Chưa audit từng phát biểu trong 80.656 dòng với từng nhánh code.** Cột xử lý bên dưới là định hướng sơ bộ, không phải xác nhận từng tài liệu sai hoặc lệnh xóa đã được duyệt. Việc đó thực hiện từng tài liệu khi chuẩn hóa.
- Có thay đổi sẵn: BRAINSTORM/MASTER_PITCH được chuyển vào `docs/`, task CFG chuyển sang `.ai/tasks/CFG/`, README và pitch deck đang thay đổi. Khảo sát giữ nguyên tất cả.

## 2. Nguồn để chuẩn hóa

1. **Định vị và câu chuyện sản phẩm:** `docs/BRAINSTORM.md` và `docs/MASTER_PITCH.md`, theo chỉ định hiện tại của chủ dự án. Giữ nội dung gốc; PRD rút yêu cầu từ đây, không tạo thêm bản tóm tắt cạnh tranh.
2. **Hành vi đang thực thi:** source + cấu hình + test tương ứng. Khi có code mà chưa có runtime evidence, chỉ ghi “đã có implementation”.
3. **Chạy thật và chất lượng:** log/job/artifact/checksum/báo cáo kiểm chứng có ngày và môi trường. Báo cáo lịch sử không chứng minh trạng thái production hôm nay.
4. **Mục tiêu chưa triển khai:** ghi riêng trong scope/backlog. Không đổi mục tiêu sản phẩm theo giới hạn implementation hiện tại.

Đây là đề xuất authority mới. Trong thời gian chuyển đổi, không tự tuyên bố đã thay thế authority map trong `AGENTS.md`; chỉ cập nhật khi các docs đích đã hoàn tất và được thống nhất.

## 3. Hiện trạng code cần phản ánh

| Phần | Nguồn code/config đã dò | Nội dung cần giữ trong bộ docs mới |
| --- | --- | --- |
| API/control plane | `src/main.py`, `src/api/routes.py`, `src/api/studio/__init__.py` | FastAPI; auth, product, Studio và demo session; health/ready khác nhau |
| Nhập dữ liệu | `src/api/studio/assemblies.py`, `src/api/studio/imports.py`, `src/services/orchestration/inputs/` | Input assembly/recipe, cấu hình và runtime có identity; nhánh video, nhiều loại sensor và imported 3DGS có điều kiện |
| Worker | `src/services/orchestration/jobs/worker_cli.py` | Queue ngoài HTTP, lease/heartbeat, retry/cancel, recovery; một queue lỗi không làm chết toàn vòng poll |
| Reconstruction | `src/services/orchestration/jobs/runner.py`, `configs/product/processing_presets_v1.json` | FFmpeg → COLMAP → Brush; preview, xác nhận mét, canonical bundle; mô tả rõ điểm dừng người dùng |
| Vật thể/hình học | `src/services/orchestration/scene/objectify.py`, `src/services/scene/geometry_state.py` | Draft → duyệt vùng/membership → build geometry → Ready; preset hiện dùng shell + required review, ObjectGS là lựa chọn |
| Biểu diễn | `src/models/contracts/`, `src/services/orchestration/review/` | Gaussian visual, shell preview, surface mesh, collider và collision môi trường có vai trò khác nhau; revision/checksum phải khớp |
| UX hiện tại | `frontend/src/app/`, `frontend/src/features/studio/ScenePage.tsx` | Route scene/import/benchmark/demo workspace; tab tiến trình, Studio, duyệt và kết quả; pipeline polling hợp nhất |
| Demo | `src/api/demo_sessions.py`, `src/services/orchestration/samples/` | Session demo tạm có scope và thời hạn, khác tài khoản Guest và khác job dựng scene mới |
| Isaac/release | `src/services/orchestration/review/validation_gate.py`, `src/services/simulation/isaac/process.py` | Đã có worker/process boundary và trusted validation gate; cần runtime được kiểm chứng; có code không có nghĩa đã qua Isaac acceptance |
| GPU/cloud | `src/services/orchestration/gpu/controller.py`, `deploy/studio/`, Docker/Makefile | Có RunPod controller, release catalog và runtime publication; phân biệt cấu hình triển khai, evidence lịch sử và trạng thái dịch vụ sống |

Khảo sát này không khởi động dịch vụ, không chạy pipeline, không truy cập provider và không xác minh cloud/browser/GPU/Isaac live.

## 4. Các vấn đề đã xác nhận

| Vấn đề | Bằng chứng | Hướng xử lý |
| --- | --- | --- |
| Mục lục docs còn lấy 30/09 làm “mới nhất” | `docs/README.md` | Viết lại thành bản đồ 12 docs, bỏ nhật ký tiến độ ở mục lục |
| PRD có metadata v1.16/30-09 nhưng changelog đã có v1.19/08-10 | `docs/PRD.md` phần đầu | Viết lại scope theo định vị mới, một trạng thái có ngày, acceptance tách implementation |
| Frontend README ghi route cũ và nói Visual chưa là 3DGS thật/chờ REC-04 | `frontend/README.md` so với route và viewer hiện tại | Gộp hướng dẫn chạy vào root README, UX vào docs/UX.md |
| Kiến trúc tự mâu thuẫn về auth/DB | `ARCHITECTURE.md`: đã mô tả Guest/Editor/Reviewer nhưng phần Security còn hai role; bảng cuối ghi cơ chế DB/auth chưa khóa | Viết lại từ code, bỏ appendix template không mô tả ứng dụng |
| Sơ đồ cũ còn chat agent/vector store | `docs/architecture_diagram.md` | Gộp sơ đồ hiện hành vào ARCHITECTURE.md |
| Kế hoạch, hồ sơ task và trạng thái lẫn với mô tả hệ thống | `docs/plans/active/`, `docs/execution/tracks/`, `.ai/` | Một STATUS cho trạng thái; task giữ scope/report của chính task, không là tài liệu kiến trúc thứ hai |
| Nhiều runbook triển khai trùng mục đích | `docs/RUNPOD_GUIDE.md`, `docs/runpod/`, `deploy/studio/`, `scripts/gpu/README.md` | Một OPERATIONS làm đầu mối; link tới script/config và sổ tay được giữ |
| Xóa docs có thể làm CI hỏng | `scripts/check_foundation.py:239`, `.github/workflows/ci.yml` | Chuyển document projection check trước khi bỏ bốn đường dẫn được kiểm |

Không kết luận tất cả docs kỹ thuật đều vô dụng. `docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md`, ADR, handoff gần đây và báo cáo có provenance chứa nội dung cần giữ/đối chiếu, nhưng không nên cùng đóng vai trò nguồn trạng thái hiện hành.

## 5. Đề xuất tối đa 12 tài liệu chính

Giới hạn **12 tài liệu sản phẩm/kỹ thuật được duy trì như nguồn hiện hành**, tính cả README, mục lục và hai bản định vị. Đây là đề xuất, chưa phải chính sách đã chốt.

| # | Tài liệu đích | Trách nhiệm duy nhất | Nguồn cần gộp/đối chiếu |
| --- | --- | --- | --- |
| 1 | `README.md` | Dự án là gì; cài/chạy lại nhanh; link đi tiếp | README hiện tại; phần chạy frontend |
| 2 | `docs/README.md` | Bản đồ tài liệu; authority; quy tắc cập nhật | Mục lục hiện tại; authority map |
| 3 | `docs/BRAINSTORM.md` | Lập luận định vị gốc để tham khảo | Giữ nguyên |
| 4 | `docs/MASTER_PITCH.md` | Câu chuyện, thông điệp, đối tượng dùng, claims policy | Giữ nguyên theo chỉ định chủ dự án |
| 5 | `docs/PRD.md` | Phạm vi, use case, yêu cầu, non-goals, acceptance | Pitch/brainstorm; PRD/BRIEF/mô tả cũ; không sao chép toàn bài pitch |
| 6 | `ARCHITECTURE.md` | Thành phần, ranh giới, storage, deployment model, quyết định còn hiệu lực | Architecture/diagram; ADR liên quan; mô tả từ code |
| 7 | `docs/PIPELINE.md` | Luồng và nhánh xử lý, I/O từng stage, điểm chờ, cấu hình quan trọng | Pipeline hiện tại; integration/track/config docs |
| 8 | `docs/CONTRACTS.md` | Input/artifact identity, tọa độ, unit, revision/CAS, lifecycle, API contract sources | Execution contract; models/schemas/OpenAPI; không chép lại mọi field/schema |
| 9 | `docs/UX.md` | User flow, role/ownership/quota, trạng thái và thao tác UI | UX spec, wireframe, route/frontend code; không ghi lịch sử thiết kế |
| 10 | `docs/OPERATIONS.md` | Local/Docker/cloud/GPU, cấu hình, bootstrap, backup/restore, nâng cấp và lỗi thường gặp | RunPod, deploy, GPU runbook; link sổ tay giữ nguyên |
| 11 | `docs/EVALUATION.md` | Dataset/GT/split/leakage, metric, benchmark, cách tái lập và đọc evidence | Dataset playbook; eval protocols/results; chỉ dẫn tới artifact thay vì chép số cũ |
| 12 | `docs/STATUS.md` | Bảng năng lực: có code, test, chạy thật, giới hạn, backlog | `.ai/status.md`, báo cáo/handoff; mỗi claim có ngày và nguồn |

Không tính vào 12: 39 file sổ tay được loại trừ; `AGENTS.md`, `GUIDE.md`, `plain-prose.md`, CONTRIBUTING/SECURITY/CODE_OF_CONDUCT/THIRD_PARTY_NOTICES và giấy phép; WORKLOG/JOURNAL/hồ sơ nộp bài; task đang làm; bằng chứng gốc có provenance; template/harness/vendor. Các nhóm này vẫn được rà để bỏ bản trùng khi phù hợp, nhưng không xóa chỉ để đạt một con số tổng Markdown.

Không tạo thêm BRIEF/CONTEXT/OVERVIEW/diagram/status cạnh tranh với 12 đầu mối trên. API field/version lấy từ OpenAPI/Pydantic; dependency version lấy từ lock/pins; cấu hình đầy đủ lấy từ source/config. Tài liệu chỉ giải thích ý nghĩa và trỏ đúng nguồn.

## 6. Thứ tự chuẩn hóa từng tài liệu

1. **Chốt danh mục và authority.** Xác nhận 12 đầu mối; giữ brainstorm/pitch nguyên vẹn. Ghi rõ scope chuyển từ warehouse-only sang indoor robotics theo định vị đã chỉ định.
2. **PRD.** Chuyển định vị thành yêu cầu kiểm chứng được; không dùng test/mock thay robot thật.
3. **ARCHITECTURE.** Viết mô hình hệ thống hiện tại và boundary; tách topology triển khai dự kiến khỏi môi trường đã được kiểm chứng.
4. **PIPELINE.** Trace luồng thật và từng nhánh; mô tả Draft/Ready, can thiệp người dùng, thất bại/thử lại.
5. **CONTRACTS.** Chắt lọc invariant; liên kết model/validator/caller/test. Chưa xóa execution docs đang bị check Foundation phụ thuộc.
6. **UX.** Đối chiếu route/component và quyền; chỉ gọi browser-verified khi có bằng chứng trình duyệt.
7. **OPERATIONS.** Đối chiếu entrypoint/env/config, quy trình chạy lại và nâng cấp. Chỉ chạy lệnh không gây tác động ngoài phạm vi; live deploy có giai đoạn riêng.
8. **EVALUATION.** Gộp quy tắc input/GT và protocol; phân biệt chuẩn bị dữ liệu, fixture, local và real-scene acceptance.
9. **STATUS.** Tổng hợp bằng chứng hiện có; phần thiếu ghi thiếu, không gắn nhãn DONE theo task status đơn thuần.
10. **README + docs/README.** Kiểm tra lại onboarding và liên kết sau khi các tài liệu đích ổn định.
11. **Chuyển authority và consumer.** Cập nhật AGENTS, CONTRIBUTING, `.ai` entrypoint, check Foundation/CI và liên kết từ code/docs. Đây là patch riêng, có kiểm tra tương ứng nếu sửa code.
12. **Dọn tài liệu cũ theo manifest đã review.** Gộp xong mới xét xóa; giữ lại phần lịch sử/bằng chứng độc nhất cần truy vết.

Mỗi lượt chỉ chuẩn hóa **một tài liệu**: đọc source/callers/config/test liên quan → đối chiếu docs nguồn → viết bản gọn → kiểm path/link/claim → báo thay đổi và phần chưa kiểm → chốt trước khi sang tài liệu kế. Không viết lại cả bộ trong một patch.

## 7. Điều kiện trước khi dọn

- Lập mapping từng file cũ → tài liệu đích hoặc bằng chứng giữ lại; ghi lý do nếu bỏ hoàn toàn.
- Các nhãn trong inventory là ứng viên. Chỉ chuyển thành danh sách xóa sau khi nội dung độc nhất đã được xử lý.
- Giữ task đang làm và các báo cáo giữ bằng chứng riêng. Task completed không đồng nghĩa tài liệu đó được phép xóa ngay.
- ADR: đưa quyết định còn hiệu lực vào docs đích; không xóa quyết định duy nhất chỉ vì ngày cũ. Lịch sử cần thiết có thể lưu tập trung; không archive mọi file theo mặc định.
- Không sửa 39 file sổ tay trong phạm vi này. Nếu phát hiện consumer trong sổ tay/công cụ phụ thuộc đường dẫn cũ, giữ đường dẫn tương thích hoặc hoãn xóa tới khi thống nhất phạm vi.
- Rà tham chiếu trong source, test, CI, AGENTS, docs và template; chạy lại kiểm tra liên kết và check document projection đã chuyển đổi.
- Chỉ xóa đúng file trong manifest dọn đã được thống nhất; không xóa `data/`, artifact/runtime, vendor hay scaffolding.
- Không commit/push/đổi branch trong công việc này nếu chưa được yêu cầu riêng.

## 8. Kiểm kê liên kết và trùng nội dung

Scanner tĩnh chỉ kiểm link Markdown inline trỏ tới `.md`/`.markdown`, bỏ khối fenced code và URL ngoài. Không kiểm anchor, reference-style link, ảnh, URL mạng hoặc ý nghĩa từng link. Có **6 lượt link nghi hỏng**, cần sửa khi xử lý đúng tài liệu:

- `WORKLOG.md` → `docs/RAV01_Real2Sim_Problem_Deep_Dive_Report.md`
- `WORKLOG.md` → `docs/TODO.md`
- `docs/execution/tracks/ex_product/METRIC_BASELINE.md` → `../../PRD.md`
- `docs/execution/tracks/ex_product/METRIC_BASELINE.md` → `../../PRD.md`
- `docs/execution/tracks/ex_product/METRIC_BASELINE.md` → `../../PRD.md`
- `docs/runpod/README-runpod.md` → `../docs/RUNPOD_GUIDE.md`

Hai cặp trùng byte: template decision và exec-plan trong `docs/templates/` trùng với bản `.harness-core/base/docs/templates/`. Đây có thể là bản chiếu của harness, chưa đủ cơ sở để xóa.

## 9. Danh sách đầy đủ 502 Markdown ngoài sổ tay

Số dòng là kích thước tại snapshot. Nhãn là hướng xử lý sơ bộ, không phải lệnh thực thi. Link mở file hiện hành trong worktree.

### 01. Thư mục gốc — 11 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [AGENTS.md](../../AGENTS.md) | 99 | GIỮ/CHUYỂN AUTHORITY | Cập nhật đường dẫn sau khi tài liệu đích hoàn tất |
| 2 | [ARCHITECTURE.md](../../ARCHITECTURE.md) | 585 | VIẾT LẠI | ARCHITECTURE.md |
| 3 | [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md) | 38 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 4 | [CONTRIBUTING.md](../../CONTRIBUTING.md) | 55 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 5 | [GUIDE.md](../../GUIDE.md) | 118 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 6 | [JOURNAL.md](../../JOURNAL.md) | 381 | GIỮ HỒ SƠ | Không tính vào 12 tài liệu chính |
| 7 | [README.md](../../README.md) | 146 | GIỮ/CẬP NHẬT | README.md |
| 8 | [SECURITY.md](../../SECURITY.md) | 39 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 9 | [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) | 158 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 10 | [WORKLOG.md](../../WORKLOG.md) | 885 | GIỮ HỒ SƠ | Không tính vào 12 tài liệu chính |
| 11 | [plain-prose.md](../../plain-prose.md) | 62 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |

### 02. Tài liệu trong docs/ ngoài sổ tay — 28 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [docs/AI_LOG_SETUP.md](../../docs/AI_LOG_SETUP.md) | 92 | ĐỐI CHIẾU/GỘP | CONTRIBUTING.md; yêu cầu nộp bài |
| 2 | [docs/BRAINSTORM.md](../../docs/BRAINSTORM.md) | 323 | GIỮ NGUYÊN | docs/BRAINSTORM.md |
| 3 | [docs/BRIEF.md](../../docs/BRIEF.md) | 434 | GỘP RỒI XÉT BỎ | docs/PRD.md; docs/MASTER_PITCH.md |
| 4 | [docs/CONTEXT.md](../../docs/CONTEXT.md) | 1666 | GỘP RỒI XÉT BỎ | README.md; ARCHITECTURE.md; docs/STATUS.md |
| 5 | [docs/DATASET_PLAYBOOK.md](../../docs/DATASET_PLAYBOOK.md) | 1888 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md; input contracts → docs/CONTRACTS.md |
| 6 | [docs/DEMO_SCENES.md](../../docs/DEMO_SCENES.md) | 56 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 7 | [docs/MASTER_PITCH.md](../../docs/MASTER_PITCH.md) | 1772 | GIỮ NGUYÊN | docs/MASTER_PITCH.md |
| 8 | [docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md](../../docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md) | 322 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md |
| 9 | [docs/PRD.md](../../docs/PRD.md) | 1344 | VIẾT LẠI | docs/PRD.md |
| 10 | [docs/RAV01_MO_TA_DE_TAI.md](../../docs/RAV01_MO_TA_DE_TAI.md) | 237 | ĐỐI CHIẾU/LỊCH SỬ | docs/PRD.md |
| 11 | [docs/README.md](../../docs/README.md) | 66 | VIẾT LẠI | docs/README.md |
| 12 | [docs/RUNPOD_GUIDE.md](../../docs/RUNPOD_GUIDE.md) | 389 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 13 | [docs/STUDIO_UX_SPEC.md](../../docs/STUDIO_UX_SPEC.md) | 870 | ĐỐI CHIẾU/GỘP | docs/UX.md |
| 14 | [docs/TRACKS.md](../../docs/TRACKS.md) | 205 | ĐỐI CHIẾU/GỘP | ARCHITECTURE.md; docs/STATUS.md |
| 15 | [docs/WIREFRAME_AND_UI_FLOW.md](../../docs/WIREFRAME_AND_UI_FLOW.md) | 314 | GỘP RỒI XÉT BỎ | docs/UX.md |
| 16 | [docs/WORKFLOW.md](../../docs/WORKFLOW.md) | 178 | ĐỐI CHIẾU/GỘP | CONTRIBUTING.md; AGENTS.md |
| 17 | [docs/architecture_diagram.md](../../docs/architecture_diagram.md) | 63 | GỘP RỒI XÉT BỎ | ARCHITECTURE.md |
| 18 | [docs/archived/RAV01_Real2Sim_Problem_Deep_Dive_Report.md](../../docs/archived/RAV01_Real2Sim_Problem_Deep_Dive_Report.md) | 1003 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 19 | [docs/archived/RAV01_Real2Sim_Problem_Deep_Dive_Report_v2.md](../../docs/archived/RAV01_Real2Sim_Problem_Deep_Dive_Report_v2.md) | 351 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 20 | [docs/archived/README.md](../../docs/archived/README.md) | 3 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 21 | [docs/mentor-duty-report/buoi-2/script/script-buoi-2.md](../../docs/mentor-duty-report/buoi-2/script/script-buoi-2.md) | 355 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 22 | [docs/mentor-duty-report/buoi-2/script/video_demo_script.md](../../docs/mentor-duty-report/buoi-2/script/video_demo_script.md) | 66 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 23 | [docs/patterns/encoding-invariants.md](../../docs/patterns/encoding-invariants.md) | 77 | RÀ TỪNG FILE | Chưa quyết định xóa |
| 24 | [docs/runpod/README-runpod.md](../../docs/runpod/README-runpod.md) | 39 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 25 | [docs/runpod/README-team.md](../../docs/runpod/README-team.md) | 88 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 26 | [docs/templates/TASK_TEMPLATE.md](../../docs/templates/TASK_TEMPLATE.md) | 47 | RÀ TEMPLATE | Chỉ giữ template còn consumer |
| 27 | [docs/templates/decision.md](../../docs/templates/decision.md) | 34 | RÀ TEMPLATE | Chỉ giữ template còn consumer |
| 28 | [docs/templates/exec-plan.md](../../docs/templates/exec-plan.md) | 56 | RÀ TEMPLATE | Chỉ giữ template còn consumer |

### 03. Quyết định — docs/decisions/ — 29 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [docs/decisions/0001-metric-scale-strategy-and-roadmap.md](../../docs/decisions/0001-metric-scale-strategy-and-roadmap.md) | 156 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 2 | [docs/decisions/0002-studio-mvp-video-to-3dgs.md](../../docs/decisions/0002-studio-mvp-video-to-3dgs.md) | 64 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 3 | [docs/decisions/0003-cloud-architecture-roles-and-browser-budget.md](../../docs/decisions/0003-cloud-architecture-roles-and-browser-budget.md) | 192 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 4 | [docs/decisions/0004-input-kinds-and-routing.md](../../docs/decisions/0004-input-kinds-and-routing.md) | 121 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 5 | [docs/decisions/0005-stage-results-viewer.md](../../docs/decisions/0005-stage-results-viewer.md) | 72 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 6 | [docs/decisions/0006-scene-object-extraction.md](../../docs/decisions/0006-scene-object-extraction.md) | 84 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 7 | [docs/decisions/0007-object-centric-hybrid-usd-pipeline.md](../../docs/decisions/0007-object-centric-hybrid-usd-pipeline.md) | 180 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 8 | [docs/decisions/0008-research-code-license-policy.md](../../docs/decisions/0008-research-code-license-policy.md) | 44 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 9 | [docs/decisions/0009-user-lidar-input-and-routing.md](../../docs/decisions/0009-user-lidar-input-and-routing.md) | 180 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 10 | [docs/decisions/0010-interactive-character-and-browser-physics.md](../../docs/decisions/0010-interactive-character-and-browser-physics.md) | 77 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 11 | [docs/decisions/0011-first-person-navigation-and-initial-camera-pose.md](../../docs/decisions/0011-first-person-navigation-and-initial-camera-pose.md) | 77 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 12 | [docs/decisions/0012-editable-collision-and-usd-capabilities.md](../../docs/decisions/0012-editable-collision-and-usd-capabilities.md) | 192 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 13 | [docs/decisions/0013-validation-evidence-and-release-identity.md](../../docs/decisions/0013-validation-evidence-and-release-identity.md) | 92 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 14 | [docs/decisions/0014-durable-heavy-operations.md](../../docs/decisions/0014-durable-heavy-operations.md) | 62 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 15 | [docs/decisions/0015-scene-revision-head.md](../../docs/decisions/0015-scene-revision-head.md) | 55 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 16 | [docs/decisions/0016-collision-quality-and-lidar-selection.md](../../docs/decisions/0016-collision-quality-and-lidar-selection.md) | 228 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 17 | [docs/decisions/0017-fast-preview-and-final-artifacts.md](../../docs/decisions/0017-fast-preview-and-final-artifacts.md) | 59 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 18 | [docs/decisions/0018-opt-in-lidar-odometry.md](../../docs/decisions/0018-opt-in-lidar-odometry.md) | 74 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 19 | [docs/decisions/0019-anonymized-input-preparation.md](../../docs/decisions/0019-anonymized-input-preparation.md) | 66 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 20 | [docs/decisions/0020-automatic-rgb-lidar-map-registration.md](../../docs/decisions/0020-automatic-rgb-lidar-map-registration.md) | 99 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 21 | [docs/decisions/0021-guest-identity-and-ownership.md](../../docs/decisions/0021-guest-identity-and-ownership.md) | 72 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 22 | [docs/decisions/0022-guest-daily-job-quota.md](../../docs/decisions/0022-guest-daily-job-quota.md) | 111 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 23 | [docs/decisions/0023-client-video-normalization.md](../../docs/decisions/0023-client-video-normalization.md) | 155 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 24 | [docs/decisions/0024-unified-upload-and-input-resolution.md](../../docs/decisions/0024-unified-upload-and-input-resolution.md) | 151 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 25 | [docs/decisions/0025-imported-3dgs-continuation.md](../../docs/decisions/0025-imported-3dgs-continuation.md) | 98 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 26 | [docs/decisions/0026-decoupled-resource-tuning-and-observed-budget.md](../../docs/decisions/0026-decoupled-resource-tuning-and-observed-budget.md) | 123 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 27 | [docs/decisions/0027-structured-error-diagnostics-and-redacted-excerpts.md](../../docs/decisions/0027-structured-error-diagnostics-and-redacted-excerpts.md) | 68 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 28 | [docs/decisions/0028-benchmark-derived-verdicts-and-rule-based-insights.md](../../docs/decisions/0028-benchmark-derived-verdicts-and-rule-based-insights.md) | 68 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |
| 29 | [docs/decisions/README.md](../../docs/decisions/README.md) | 38 | RÀ QUYẾT ĐỊNH | Chắt lọc quyết định còn hiệu lực vào docs chính; giữ lịch sử có lý do |

### 04. Thực thi và track — docs/execution/ — 75 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [docs/execution/CONFIG_CATALOG.md](../../docs/execution/CONFIG_CATALOG.md) | 265 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; link configs/ |
| 2 | [docs/execution/INTEGRATION_PLAYBOOK.md](../../docs/execution/INTEGRATION_PLAYBOOK.md) | 1539 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 3 | [docs/execution/README.md](../../docs/execution/README.md) | 60 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 4 | [docs/execution/REC05_EXTERNAL_FILL.md](../../docs/execution/REC05_EXTERNAL_FILL.md) | 76 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 5 | [docs/execution/RUNTIME_POLICY.md](../../docs/execution/RUNTIME_POLICY.md) | 61 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 6 | [docs/execution/TEAM_EXECUTION_CONTRACT.md](../../docs/execution/TEAM_EXECUTION_CONTRACT.md) | 1197 | CHUYỂN SAU KIỂM CHECK | docs/CONTRACTS.md |
| 7 | [docs/execution/TEAM_EXECUTION_PLAN.md](../../docs/execution/TEAM_EXECUTION_PLAN.md) | 664 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 8 | [docs/execution/TRACK_IMPLEMENTATION_GUIDE.md](../../docs/execution/TRACK_IMPLEMENTATION_GUIDE.md) | 1300 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 9 | [docs/execution/audits/00_cross_repo_reuse_matrix.md](../../docs/execution/audits/00_cross_repo_reuse_matrix.md) | 416 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 10 | [docs/execution/audits/01_openreal2sim.md](../../docs/execution/audits/01_openreal2sim.md) | 702 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 11 | [docs/execution/audits/02_r2g.md](../../docs/execution/audits/02_r2g.md) | 541 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 12 | [docs/execution/audits/03_vr_robo.md](../../docs/execution/audits/03_vr_robo.md) | 344 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 13 | [docs/execution/audits/04_supersplat.md](../../docs/execution/audits/04_supersplat.md) | 273 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 14 | [docs/execution/audits/04a_splat_transform.md](../../docs/execution/audits/04a_splat_transform.md) | 204 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 15 | [docs/execution/audits/05_discoverse.md](../../docs/execution/audits/05_discoverse.md) | 2100 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 16 | [docs/execution/audits/06_gaussian_grouping.md](../../docs/execution/audits/06_gaussian_grouping.md) | 1290 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 17 | [docs/execution/audits/07_re3sim.md](../../docs/execution/audits/07_re3sim.md) | 491 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 18 | [docs/execution/audits/08_playcanvas_engine.md](../../docs/execution/audits/08_playcanvas_engine.md) | 107 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 19 | [docs/execution/audits/09_supersplat_viewer.md](../../docs/execution/audits/09_supersplat_viewer.md) | 108 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 20 | [docs/execution/audits/10_pipeline_v2_methods.md](../../docs/execution/audits/10_pipeline_v2_methods.md) | 65 | RÀ LỊCH SỬ | Giữ quyết định/nguồn độc nhất; xét bỏ phần trùng |
| 21 | [docs/execution/templates/TASK_TEMPLATE.md](../../docs/execution/templates/TASK_TEMPLATE.md) | 83 | ĐỐI CHIẾU/GỘP | docs/PIPELINE.md; docs/CONTRACTS.md; docs/STATUS.md |
| 22 | [docs/execution/tracks/README.md](../../docs/execution/tracks/README.md) | 50 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 23 | [docs/execution/tracks/ex_product/HANDOFF-2026-09-29-cloud-ops.md](../../docs/execution/tracks/ex_product/HANDOFF-2026-09-29-cloud-ops.md) | 125 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 24 | [docs/execution/tracks/ex_product/METRIC_BASELINE.md](../../docs/execution/tracks/ex_product/METRIC_BASELINE.md) | 220 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 25 | [docs/execution/tracks/ex_product/PLAN.md](../../docs/execution/tracks/ex_product/PLAN.md) | 215 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 26 | [docs/execution/tracks/ex_product/TRACK.md](../../docs/execution/tracks/ex_product/TRACK.md) | 149 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 27 | [docs/execution/tracks/ex_product/tasks/PRODUCT-01.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-01.md) | 187 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 28 | [docs/execution/tracks/ex_product/tasks/PRODUCT-02.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-02.md) | 198 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 29 | [docs/execution/tracks/ex_product/tasks/PRODUCT-03.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-03.md) | 89 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 30 | [docs/execution/tracks/ex_product/tasks/PRODUCT-04.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-04.md) | 100 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 31 | [docs/execution/tracks/ex_product/tasks/PRODUCT-05.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-05.md) | 261 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 32 | [docs/execution/tracks/ex_product/tasks/PRODUCT-06.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-06.md) | 241 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 33 | [docs/execution/tracks/ex_product/tasks/PRODUCT-07.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-07.md) | 146 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 34 | [docs/execution/tracks/ex_product/tasks/PRODUCT-07A.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-07A.md) | 133 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 35 | [docs/execution/tracks/ex_product/tasks/PRODUCT-08.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-08.md) | 94 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 36 | [docs/execution/tracks/ex_product/tasks/PRODUCT-09.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-09.md) | 123 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 37 | [docs/execution/tracks/ex_product/tasks/PRODUCT-10.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-10.md) | 170 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 38 | [docs/execution/tracks/ex_product/tasks/PRODUCT-11.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-11.md) | 150 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 39 | [docs/execution/tracks/ex_product/tasks/PRODUCT-12.md](../../docs/execution/tracks/ex_product/tasks/PRODUCT-12.md) | 92 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 40 | [docs/execution/tracks/ex_rec/TRACK.md](../../docs/execution/tracks/ex_rec/TRACK.md) | 154 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 41 | [docs/execution/tracks/ex_rec/tasks/REC-01.md](../../docs/execution/tracks/ex_rec/tasks/REC-01.md) | 380 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 42 | [docs/execution/tracks/ex_rec/tasks/REC-02.md](../../docs/execution/tracks/ex_rec/tasks/REC-02.md) | 331 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 43 | [docs/execution/tracks/ex_rec/tasks/REC-02A.md](../../docs/execution/tracks/ex_rec/tasks/REC-02A.md) | 148 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 44 | [docs/execution/tracks/ex_rec/tasks/REC-03.md](../../docs/execution/tracks/ex_rec/tasks/REC-03.md) | 195 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 45 | [docs/execution/tracks/ex_rec/tasks/REC-04.md](../../docs/execution/tracks/ex_rec/tasks/REC-04.md) | 194 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 46 | [docs/execution/tracks/ex_rec/tasks/REC-05.md](../../docs/execution/tracks/ex_rec/tasks/REC-05.md) | 605 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 47 | [docs/execution/tracks/ex_rec/tasks/REC-06.md](../../docs/execution/tracks/ex_rec/tasks/REC-06.md) | 666 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 48 | [docs/execution/tracks/ex_rec/tasks/REC-07.md](../../docs/execution/tracks/ex_rec/tasks/REC-07.md) | 302 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 49 | [docs/execution/tracks/ex_rec/tasks/REC-08.md](../../docs/execution/tracks/ex_rec/tasks/REC-08.md) | 156 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 50 | [docs/execution/tracks/ex_rec/tasks/REC-09.md](../../docs/execution/tracks/ex_rec/tasks/REC-09.md) | 268 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 51 | [docs/execution/tracks/ex_rec/tasks/REC-10.md](../../docs/execution/tracks/ex_rec/tasks/REC-10.md) | 169 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 52 | [docs/execution/tracks/ex_rec/tasks/REC-11.md](../../docs/execution/tracks/ex_rec/tasks/REC-11.md) | 201 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 53 | [docs/execution/tracks/ex_scene/TRACK.md](../../docs/execution/tracks/ex_scene/TRACK.md) | 97 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 54 | [docs/execution/tracks/ex_scene/tasks/SCENE-01.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-01.md) | 96 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 55 | [docs/execution/tracks/ex_scene/tasks/SCENE-02.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-02.md) | 85 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 56 | [docs/execution/tracks/ex_scene/tasks/SCENE-03.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-03.md) | 104 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 57 | [docs/execution/tracks/ex_scene/tasks/SCENE-04.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-04.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 58 | [docs/execution/tracks/ex_scene/tasks/SCENE-05.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-05.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 59 | [docs/execution/tracks/ex_scene/tasks/SCENE-06.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-06.md) | 106 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 60 | [docs/execution/tracks/ex_scene/tasks/SCENE-07.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-07.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 61 | [docs/execution/tracks/ex_scene/tasks/SCENE-08.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-08.md) | 84 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 62 | [docs/execution/tracks/ex_scene/tasks/SCENE-08A.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-08A.md) | 85 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 63 | [docs/execution/tracks/ex_scene/tasks/SCENE-09.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-09.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 64 | [docs/execution/tracks/ex_scene/tasks/SCENE-10.md](../../docs/execution/tracks/ex_scene/tasks/SCENE-10.md) | 84 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 65 | [docs/execution/tracks/ex_sim/TRACK.md](../../docs/execution/tracks/ex_sim/TRACK.md) | 108 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 66 | [docs/execution/tracks/ex_sim/tasks/SIM-01.md](../../docs/execution/tracks/ex_sim/tasks/SIM-01.md) | 105 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 67 | [docs/execution/tracks/ex_sim/tasks/SIM-02.md](../../docs/execution/tracks/ex_sim/tasks/SIM-02.md) | 114 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 68 | [docs/execution/tracks/ex_sim/tasks/SIM-02A.md](../../docs/execution/tracks/ex_sim/tasks/SIM-02A.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 69 | [docs/execution/tracks/ex_sim/tasks/SIM-03.md](../../docs/execution/tracks/ex_sim/tasks/SIM-03.md) | 98 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 70 | [docs/execution/tracks/ex_sim/tasks/SIM-04.md](../../docs/execution/tracks/ex_sim/tasks/SIM-04.md) | 95 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 71 | [docs/execution/tracks/ex_sim/tasks/SIM-05.md](../../docs/execution/tracks/ex_sim/tasks/SIM-05.md) | 130 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 72 | [docs/execution/tracks/ex_sim/tasks/SIM-06.md](../../docs/execution/tracks/ex_sim/tasks/SIM-06.md) | 119 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 73 | [docs/execution/tracks/ex_sim/tasks/SIM-07.md](../../docs/execution/tracks/ex_sim/tasks/SIM-07.md) | 94 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 74 | [docs/execution/tracks/ex_sim/tasks/SIM-08.md](../../docs/execution/tracks/ex_sim/tasks/SIM-08.md) | 89 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 75 | [docs/execution/tracks/ex_sim/tasks/SIM-09.md](../../docs/execution/tracks/ex_sim/tasks/SIM-09.md) | 91 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |

### 05. Kế hoạch và handoff — docs/plans/ — 73 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [docs/plans/README.md](../../docs/plans/README.md) | 12 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 2 | [docs/plans/active/2026-09-23-integration-foundation.md](../../docs/plans/active/2026-09-23-integration-foundation.md) | 163 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 3 | [docs/plans/active/2026-09-24-ex-rec-track.md](../../docs/plans/active/2026-09-24-ex-rec-track.md) | 729 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 4 | [docs/plans/active/2026-09-29-cloud-studio.md](../../docs/plans/active/2026-09-29-cloud-studio.md) | 248 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 5 | [docs/plans/active/2026-09-29-ex-scene-rush.md](../../docs/plans/active/2026-09-29-ex-scene-rush.md) | 110 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 6 | [docs/plans/active/2026-09-29-mvp-studio-demo.md](../../docs/plans/active/2026-09-29-mvp-studio-demo.md) | 397 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 7 | [docs/plans/active/2026-09-29-studio-completion.md](../../docs/plans/active/2026-09-29-studio-completion.md) | 256 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 8 | [docs/plans/active/2026-09-30-pipeline-v2.md](../../docs/plans/active/2026-09-30-pipeline-v2.md) | 172 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 9 | [docs/plans/active/2026-10-01-studio-ux-restructure.md](../../docs/plans/active/2026-10-01-studio-ux-restructure.md) | 847 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 10 | [docs/plans/active/2026-10-02-evaluation-system.md](../../docs/plans/active/2026-10-02-evaluation-system.md) | 102 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 11 | [docs/plans/active/2026-10-02-interactive-scene-and-metric-scale.md](../../docs/plans/active/2026-10-02-interactive-scene-and-metric-scale.md) | 282 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 12 | [docs/plans/active/2026-10-02-lidar-video-flow.md](../../docs/plans/active/2026-10-02-lidar-video-flow.md) | 126 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 13 | [docs/plans/active/2026-10-02-resource-management-cleanup.md](../../docs/plans/active/2026-10-02-resource-management-cleanup.md) | 481 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 14 | [docs/plans/active/2026-10-03-studio-packaging.md](../../docs/plans/active/2026-10-03-studio-packaging.md) | 195 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 15 | [docs/plans/active/2026-10-07-codegraph-audit/AGENT_GUIDE.md](../../docs/plans/active/2026-10-07-codegraph-audit/AGENT_GUIDE.md) | 161 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 16 | [docs/plans/active/2026-10-07-codegraph-audit/GEMINI_FINDINGS.md](../../docs/plans/active/2026-10-07-codegraph-audit/GEMINI_FINDINGS.md) | 69 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 17 | [docs/plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md](../../docs/plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md) | 139 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 18 | [docs/plans/active/2026-10-07-codegraph-audit/README.md](../../docs/plans/active/2026-10-07-codegraph-audit/README.md) | 714 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 19 | [docs/plans/active/2026-10-07-codegraph-audit/TECHNOLOGY_LIMITS.md](../../docs/plans/active/2026-10-07-codegraph-audit/TECHNOLOGY_LIMITS.md) | 120 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 20 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-01-collision-background.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-01-collision-background.md) | 281 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 21 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-02-usd-capabilities.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-02-usd-capabilities.md) | 285 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 22 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-03-validation-gate.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-03-validation-gate.md) | 259 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 23 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-04-release-sealing.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-04-release-sealing.md) | 250 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 24 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-05-isaac-validation.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-05-isaac-validation.md) | 334 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 25 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-06-durable-import.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-06-durable-import.md) | 200 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 26 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-07-heavy-operation-admission.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-07-heavy-operation-admission.md) | 278 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 27 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-08-object-correction.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-08-object-correction.md) | 362 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 28 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-09-collider-editor.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-09-collider-editor.md) | 233 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 29 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-10-revision-head.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-10-revision-head.md) | 271 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 30 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-11-test-baseline.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-11-test-baseline.md) | 144 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 31 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-12-collision-quality.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-12-collision-quality.md) | 726 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 32 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-13-lidar-calibration-qa.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-13-lidar-calibration-qa.md) | 258 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 33 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-14-adaptive-floor.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-14-adaptive-floor.md) | 264 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 34 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-15-worker-latency.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-15-worker-latency.md) | 270 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 35 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-16-fast-preview.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-16-fast-preview.md) | 124 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 36 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-17-lidar-odometry.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-17-lidar-odometry.md) | 568 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 37 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-18-privacy-anonymizer.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-18-privacy-anonymizer.md) | 239 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 38 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-19-automatic-rgb-lidar-registration.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-19-automatic-rgb-lidar-registration.md) | 1509 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 39 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-20-user-display-name-and-creator.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-20-user-display-name-and-creator.md) | 182 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 40 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-21-guest-signup-and-ownership.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-21-guest-signup-and-ownership.md) | 343 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 41 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-22-guest-daily-job-quota.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-22-guest-daily-job-quota.md) | 257 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 42 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-23-client-video-normalization.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-23-client-video-normalization.md) | 769 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 43 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-24-unified-upload-and-input-resolution.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-24-unified-upload-and-input-resolution.md) | 573 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 44 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-25-imported-3dgs-continuation.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-25-imported-3dgs-continuation.md) | 360 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 45 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-26-decoupled-resource-tuning-and-observed-budget.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-26-decoupled-resource-tuning-and-observed-budget.md) | 740 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 46 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-27-structured-error-diagnostics-and-redacted-excerpts.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-27-structured-error-diagnostics-and-redacted-excerpts.md) | 370 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 47 | [docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-28-benchmark-derived-verdicts-and-rule-based-insights.md](../../docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-28-benchmark-derived-verdicts-and-rule-based-insights.md) | 387 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 48 | [docs/plans/active/2026-10-13-pipeline-config-and-vocab-tree/VERIFICATION_REPORT.md](../../docs/plans/active/2026-10-13-pipeline-config-and-vocab-tree/VERIFICATION_REPORT.md) | 47 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 49 | [docs/plans/active/2026-10-14-pr02-representation-lifecycle/FIX-EDITOR-GAUSSIAN-COUPLING.md](../../docs/plans/active/2026-10-14-pr02-representation-lifecycle/FIX-EDITOR-GAUSSIAN-COUPLING.md) | 71 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 50 | [docs/plans/active/2026-10-14-pr02-representation-lifecycle/FOLLOWUP-OBJECT-RESTORE.md](../../docs/plans/active/2026-10-14-pr02-representation-lifecycle/FOLLOWUP-OBJECT-RESTORE.md) | 91 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 51 | [docs/plans/active/2026-10-14-pr02-representation-lifecycle/HANDOFF.md](../../docs/plans/active/2026-10-14-pr02-representation-lifecycle/HANDOFF.md) | 133 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 52 | [docs/plans/active/2026-10-14-pr03-effective-collision/HANDOFF.md](../../docs/plans/active/2026-10-14-pr03-effective-collision/HANDOFF.md) | 163 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 53 | [docs/plans/active/2026-10-14-pr04-browser-physics/COLLISION_DISPLAY_HANDOFF.md](../../docs/plans/active/2026-10-14-pr04-browser-physics/COLLISION_DISPLAY_HANDOFF.md) | 62 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 54 | [docs/plans/active/2026-10-14-pr04-browser-physics/HANDOFF.md](../../docs/plans/active/2026-10-14-pr04-browser-physics/HANDOFF.md) | 206 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 55 | [docs/plans/active/2026-10-14-pr04-browser-physics/PLANAR_CUT_REPAIR_HANDOFF.md](../../docs/plans/active/2026-10-14-pr04-browser-physics/PLANAR_CUT_REPAIR_HANDOFF.md) | 68 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 56 | [docs/plans/active/2026-10-14-pr04-browser-physics/STUDIO_PREVIEW_HANDOFF.md](../../docs/plans/active/2026-10-14-pr04-browser-physics/STUDIO_PREVIEW_HANDOFF.md) | 67 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 57 | [docs/plans/active/2026-10-15-membership-correction/HANDOFF.md](../../docs/plans/active/2026-10-15-membership-correction/HANDOFF.md) | 79 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 58 | [docs/plans/active/2026-10-15-object-pipeline-evidence/HANDOFF.md](../../docs/plans/active/2026-10-15-object-pipeline-evidence/HANDOFF.md) | 130 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 59 | [docs/plans/active/2026-10-15-objectgs-surface-quality/HANDOFF.md](../../docs/plans/active/2026-10-15-objectgs-surface-quality/HANDOFF.md) | 195 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 60 | [docs/plans/active/2026-10-15-pr05-object-aware-geometry/HANDOFF.md](../../docs/plans/active/2026-10-15-pr05-object-aware-geometry/HANDOFF.md) | 432 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 61 | [docs/plans/active/2026-10-15-pr05-object-aware-geometry/RUNTIME.md](../../docs/plans/active/2026-10-15-pr05-object-aware-geometry/RUNTIME.md) | 138 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 62 | [docs/plans/active/2026-10-15-pr05-object-aware-geometry/TASK.md](../../docs/plans/active/2026-10-15-pr05-object-aware-geometry/TASK.md) | 793 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 63 | [docs/plans/active/2026-10-15-segmentation-refinement/HANDOFF.md](../../docs/plans/active/2026-10-15-segmentation-refinement/HANDOFF.md) | 171 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 64 | [docs/plans/active/2026-10-16-geometry-review/HANDOFF.md](../../docs/plans/active/2026-10-16-geometry-review/HANDOFF.md) | 111 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 65 | [docs/plans/active/2026-10-16-production-web-performance/REPORT.md](../../docs/plans/active/2026-10-16-production-web-performance/REPORT.md) | 87 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 66 | [docs/plans/active/2026-10-16-value-metrics/HANDOFF.md](../../docs/plans/active/2026-10-16-value-metrics/HANDOFF.md) | 77 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 67 | [docs/plans/active/2026-10-20-pipeline-stability/HANDOFF.md](../../docs/plans/active/2026-10-20-pipeline-stability/HANDOFF.md) | 88 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 68 | [docs/plans/active/README.md](../../docs/plans/active/README.md) | 13 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 69 | [docs/plans/completed/2026-09-23-complete-coding-agent-harness.md](../../docs/plans/completed/2026-09-23-complete-coding-agent-harness.md) | 102 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 70 | [docs/plans/completed/2026-09-23-materialize-execution-tracks.md](../../docs/plans/completed/2026-09-23-materialize-execution-tracks.md) | 96 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 71 | [docs/plans/completed/2026-09-25-sync-viewer-geometry-baseline.md](../../docs/plans/completed/2026-09-25-sync-viewer-geometry-baseline.md) | 83 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 72 | [docs/plans/completed/2026-10-02-repo-structure-cleanup.md](../../docs/plans/completed/2026-10-02-repo-structure-cleanup.md) | 276 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 73 | [docs/plans/completed/README.md](../../docs/plans/completed/README.md) | 5 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |

### 06. Điều phối và báo cáo — .ai/ — 28 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [.ai/README.md](../../.ai/README.md) | 22 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |
| 2 | [.ai/TOM_TAT_BRAINSTORM_MASTER_PITCH.md](../../.ai/TOM_TAT_BRAINSTORM_MASTER_PITCH.md) | 542 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |
| 3 | [.ai/architecture.md](../../.ai/architecture.md) | 292 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |
| 4 | [.ai/plans/2026-10-19-runpod-auto-provisioning.md](../../.ai/plans/2026-10-19-runpod-auto-provisioning.md) | 647 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |
| 5 | [.ai/plans/2026-10-20-pipeline-stability-and-progress.md](../../.ai/plans/2026-10-20-pipeline-stability-and-progress.md) | 170 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |
| 6 | [.ai/reports/2026-10-17-benchmark-button-placement.md](../../.ai/reports/2026-10-17-benchmark-button-placement.md) | 15 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 7 | [.ai/reports/2026-10-17-bulk-fixed-background.md](../../.ai/reports/2026-10-17-bulk-fixed-background.md) | 34 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 8 | [.ai/reports/2026-10-17-direct-mesh-selection.md](../../.ai/reports/2026-10-17-direct-mesh-selection.md) | 26 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 9 | [.ai/reports/2026-10-17-remove-object-review-frame.md](../../.ai/reports/2026-10-17-remove-object-review-frame.md) | 31 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 10 | [.ai/reports/2026-10-17-walk-object-review.md](../../.ai/reports/2026-10-17-walk-object-review.md) | 119 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 11 | [.ai/reports/2026-10-18-demo-orientation-fix.md](../../.ai/reports/2026-10-18-demo-orientation-fix.md) | 63 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 12 | [.ai/reports/2026-10-18-landing-positioning.md](../../.ai/reports/2026-10-18-landing-positioning.md) | 153 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 13 | [.ai/reports/2026-10-18-restore-root-stale-region-notice.md](../../.ai/reports/2026-10-18-restore-root-stale-region-notice.md) | 64 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 14 | [.ai/reports/2026-10-19-benchmark-multi-gaussian-picker.md](../../.ai/reports/2026-10-19-benchmark-multi-gaussian-picker.md) | 36 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 15 | [.ai/reports/2026-10-19-drag-freeze-fix.md](../../.ai/reports/2026-10-19-drag-freeze-fix.md) | 85 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 16 | [.ai/reports/2026-10-19-interactive-demo-sessions.md](../../.ai/reports/2026-10-19-interactive-demo-sessions.md) | 130 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 17 | [.ai/reports/2026-10-19-production-demo-implementation.md](../../.ai/reports/2026-10-19-production-demo-implementation.md) | 74 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 18 | [.ai/reports/2026-10-19-production-demo-readiness.md](../../.ai/reports/2026-10-19-production-demo-readiness.md) | 239 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 19 | [.ai/reports/benchmark-audit-20261018/report.md](../../.ai/reports/benchmark-audit-20261018/report.md) | 97 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 20 | [.ai/reports/benchmark-provenance-fix-20261018/report.md](../../.ai/reports/benchmark-provenance-fix-20261018/report.md) | 56 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 21 | [.ai/reports/deployment-20261019/checkpoint.md](../../.ai/reports/deployment-20261019/checkpoint.md) | 57 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 22 | [.ai/reports/lpips-jpeg-20261018/drjohnson/continuation.md](../../.ai/reports/lpips-jpeg-20261018/drjohnson/continuation.md) | 33 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 23 | [.ai/reports/lpips-jpeg-20261018/report.md](../../.ai/reports/lpips-jpeg-20261018/report.md) | 38 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 24 | [.ai/reports/production-packaging-20261019/report.md](../../.ai/reports/production-packaging-20261019/report.md) | 109 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 25 | [.ai/reports/runpod-auto-provisioning-20261019/report.md](../../.ai/reports/runpod-auto-provisioning-20261019/report.md) | 159 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 26 | [.ai/reports/telemetry-coverage-20261019/report.md](../../.ai/reports/telemetry-coverage-20261019/report.md) | 159 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 27 | [.ai/roadmap.md](../../.ai/roadmap.md) | 131 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |
| 28 | [.ai/status.md](../../.ai/status.md) | 70 | RÀ ĐIỀU PHỐI | Giữ task đang làm; gộp mô tả hệ thống vào docs chính |

### 07. Hồ sơ task — .ai/tasks/ — 204 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [.ai/tasks/CFG/CFG-01-TOOL-INSPECT.md](../../.ai/tasks/CFG/CFG-01-TOOL-INSPECT.md) | 60 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 2 | [.ai/tasks/CFG/CFG-02-VOCAB-TREE-ASSET.md](../../.ai/tasks/CFG/CFG-02-VOCAB-TREE-ASSET.md) | 95 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 3 | [.ai/tasks/CFG/CFG-03-COLMAP-MATCHING-MODES.md](../../.ai/tasks/CFG/CFG-03-COLMAP-MATCHING-MODES.md) | 99 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 4 | [.ai/tasks/CFG/CFG-04-VOXEL-GEOMETRY-CONFIG.md](../../.ai/tasks/CFG/CFG-04-VOXEL-GEOMETRY-CONFIG.md) | 94 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 5 | [.ai/tasks/CFG/CFG-05-SCENE-OBJECTIFY-CONFIG.md](../../.ai/tasks/CFG/CFG-05-SCENE-OBJECTIFY-CONFIG.md) | 93 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 6 | [.ai/tasks/CFG/CFG-06-SIMULATION-PHYSICS-CONFIG.md](../../.ai/tasks/CFG/CFG-06-SIMULATION-PHYSICS-CONFIG.md) | 88 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 7 | [.ai/tasks/CFG/CFG-07-AUDIT-CORE-RUNNERS.md](../../.ai/tasks/CFG/CFG-07-AUDIT-CORE-RUNNERS.md) | 80 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 8 | [.ai/tasks/CFG/CFG-08-SCENARIO-PRESETS-CATALOG.md](../../.ai/tasks/CFG/CFG-08-SCENARIO-PRESETS-CATALOG.md) | 95 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 9 | [.ai/tasks/CFG/CFG-09-PRESETS-SCHEMA-BACKEND.md](../../.ai/tasks/CFG/CFG-09-PRESETS-SCHEMA-BACKEND.md) | 132 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 10 | [.ai/tasks/CFG/CFG-10-API-OPTIONS-EVALUATION.md](../../.ai/tasks/CFG/CFG-10-API-OPTIONS-EVALUATION.md) | 96 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 11 | [.ai/tasks/CFG/CFG-11-AUDIT-BACKEND-API.md](../../.ai/tasks/CFG/CFG-11-AUDIT-BACKEND-API.md) | 89 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 12 | [.ai/tasks/CFG/CFG-12-FRONTEND-CONTRACTS.md](../../.ai/tasks/CFG/CFG-12-FRONTEND-CONTRACTS.md) | 101 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 13 | [.ai/tasks/CFG/CFG-13-SCENARIO-WIZARD-UI.md](../../.ai/tasks/CFG/CFG-13-SCENARIO-WIZARD-UI.md) | 108 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 14 | [.ai/tasks/CFG/CFG-14-AUDIT-UI-UX.md](../../.ai/tasks/CFG/CFG-14-AUDIT-UI-UX.md) | 85 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 15 | [.ai/tasks/CFG/CFG-15-E2E-VERIFICATION.md](../../.ai/tasks/CFG/CFG-15-E2E-VERIFICATION.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 16 | [.ai/tasks/CFG/README.md](../../.ai/tasks/CFG/README.md) | 76 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 17 | [.ai/tasks/CFG/reports/AUDIT_01_CORE_RUNNERS_REPORT.md](../../.ai/tasks/CFG/reports/AUDIT_01_CORE_RUNNERS_REPORT.md) | 53 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 18 | [.ai/tasks/CFG/reports/AUDIT_02_BACKEND_API_REPORT.md](../../.ai/tasks/CFG/reports/AUDIT_02_BACKEND_API_REPORT.md) | 64 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 19 | [.ai/tasks/CFG/reports/AUDIT_03_UI_UX_REPORT.md](../../.ai/tasks/CFG/reports/AUDIT_03_UI_UX_REPORT.md) | 43 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 20 | [.ai/tasks/CFG/reports/BUG-SCENE-TRASH-INPUT-RUN.md](../../.ai/tasks/CFG/reports/BUG-SCENE-TRASH-INPUT-RUN.md) | 31 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 21 | [.ai/tasks/CFG/reports/BUG-VIEWER-RESET-AND-GPU-HELP.md](../../.ai/tasks/CFG/reports/BUG-VIEWER-RESET-AND-GPU-HELP.md) | 28 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 22 | [.ai/tasks/CFG/reports/REGISTRATION-OPTIONAL-INVITE.md](../../.ai/tasks/CFG/reports/REGISTRATION-OPTIONAL-INVITE.md) | 33 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 23 | [.ai/tasks/CFG/reports/SCENE-ORIGINAL-AND-SAVED-STATE.md](../../.ai/tasks/CFG/reports/SCENE-ORIGINAL-AND-SAVED-STATE.md) | 34 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 24 | [.ai/tasks/CFG/reports/UI-SCENE-STATE-TABS.md](../../.ai/tasks/CFG/reports/UI-SCENE-STATE-TABS.md) | 26 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 25 | [.ai/tasks/CFG/reports/UI-STUDIO-FULLSCREEN.md](../../.ai/tasks/CFG/reports/UI-STUDIO-FULLSCREEN.md) | 19 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 26 | [.ai/tasks/T-001/plan.md](../../.ai/tasks/T-001/plan.md) | 58 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 27 | [.ai/tasks/T-001/report.md](../../.ai/tasks/T-001/report.md) | 37 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 28 | [.ai/tasks/T-001/review.md](../../.ai/tasks/T-001/review.md) | 27 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 29 | [.ai/tasks/T-002/plan.md](../../.ai/tasks/T-002/plan.md) | 104 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 30 | [.ai/tasks/T-002/report.md](../../.ai/tasks/T-002/report.md) | 177 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 31 | [.ai/tasks/T-002/review.md](../../.ai/tasks/T-002/review.md) | 132 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 32 | [.ai/tasks/T-003/plan.md](../../.ai/tasks/T-003/plan.md) | 104 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 33 | [.ai/tasks/T-003/report.md](../../.ai/tasks/T-003/report.md) | 125 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 34 | [.ai/tasks/T-003/review.md](../../.ai/tasks/T-003/review.md) | 69 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 35 | [.ai/tasks/T-004/plan.md](../../.ai/tasks/T-004/plan.md) | 116 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 36 | [.ai/tasks/T-004/report.md](../../.ai/tasks/T-004/report.md) | 57 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 37 | [.ai/tasks/T-004/review.md](../../.ai/tasks/T-004/review.md) | 35 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 38 | [.ai/tasks/T-005/plan.md](../../.ai/tasks/T-005/plan.md) | 100 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 39 | [.ai/tasks/T-005/report.md](../../.ai/tasks/T-005/report.md) | 73 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 40 | [.ai/tasks/T-005/review.md](../../.ai/tasks/T-005/review.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 41 | [.ai/tasks/T-006/plan.md](../../.ai/tasks/T-006/plan.md) | 78 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 42 | [.ai/tasks/T-006/report.md](../../.ai/tasks/T-006/report.md) | 82 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 43 | [.ai/tasks/T-006/review.md](../../.ai/tasks/T-006/review.md) | 30 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 44 | [.ai/tasks/T-007/plan.md](../../.ai/tasks/T-007/plan.md) | 104 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 45 | [.ai/tasks/T-007/report.md](../../.ai/tasks/T-007/report.md) | 160 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 46 | [.ai/tasks/T-007/review.md](../../.ai/tasks/T-007/review.md) | 62 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 47 | [.ai/tasks/T-008/plan.md](../../.ai/tasks/T-008/plan.md) | 65 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 48 | [.ai/tasks/T-008/report.md](../../.ai/tasks/T-008/report.md) | 68 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 49 | [.ai/tasks/T-008/review.md](../../.ai/tasks/T-008/review.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 50 | [.ai/tasks/T-009/plan.md](../../.ai/tasks/T-009/plan.md) | 70 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 51 | [.ai/tasks/T-009/report.md](../../.ai/tasks/T-009/report.md) | 194 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 52 | [.ai/tasks/T-009/review.md](../../.ai/tasks/T-009/review.md) | 99 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 53 | [.ai/tasks/T-010/plan.md](../../.ai/tasks/T-010/plan.md) | 91 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 54 | [.ai/tasks/T-010/report.md](../../.ai/tasks/T-010/report.md) | 88 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 55 | [.ai/tasks/T-010/review.md](../../.ai/tasks/T-010/review.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 56 | [.ai/tasks/T-011/plan.md](../../.ai/tasks/T-011/plan.md) | 77 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 57 | [.ai/tasks/T-011/report.md](../../.ai/tasks/T-011/report.md) | 95 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 58 | [.ai/tasks/T-011/review.md](../../.ai/tasks/T-011/review.md) | 28 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 59 | [.ai/tasks/T-012/plan.md](../../.ai/tasks/T-012/plan.md) | 51 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 60 | [.ai/tasks/T-012/report.md](../../.ai/tasks/T-012/report.md) | 139 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 61 | [.ai/tasks/T-012/review.md](../../.ai/tasks/T-012/review.md) | 57 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 62 | [.ai/tasks/T-013/plan.md](../../.ai/tasks/T-013/plan.md) | 88 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 63 | [.ai/tasks/T-013/report.md](../../.ai/tasks/T-013/report.md) | 110 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 64 | [.ai/tasks/T-013/review.md](../../.ai/tasks/T-013/review.md) | 38 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 65 | [.ai/tasks/T-014/plan.md](../../.ai/tasks/T-014/plan.md) | 74 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 66 | [.ai/tasks/T-014/report.md](../../.ai/tasks/T-014/report.md) | 92 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 67 | [.ai/tasks/T-014/review.md](../../.ai/tasks/T-014/review.md) | 46 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 68 | [.ai/tasks/T-015/plan.md](../../.ai/tasks/T-015/plan.md) | 81 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 69 | [.ai/tasks/T-015/report.md](../../.ai/tasks/T-015/report.md) | 110 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 70 | [.ai/tasks/T-015/review.md](../../.ai/tasks/T-015/review.md) | 40 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 71 | [.ai/tasks/T-016/plan.md](../../.ai/tasks/T-016/plan.md) | 84 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 72 | [.ai/tasks/T-016/report.md](../../.ai/tasks/T-016/report.md) | 134 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 73 | [.ai/tasks/T-016/review.md](../../.ai/tasks/T-016/review.md) | 67 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 74 | [.ai/tasks/T-017/plan.md](../../.ai/tasks/T-017/plan.md) | 75 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 75 | [.ai/tasks/T-017/report.md](../../.ai/tasks/T-017/report.md) | 80 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 76 | [.ai/tasks/T-017/review.md](../../.ai/tasks/T-017/review.md) | 30 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 77 | [.ai/tasks/T-018/plan.md](../../.ai/tasks/T-018/plan.md) | 52 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 78 | [.ai/tasks/T-018/report.md](../../.ai/tasks/T-018/report.md) | 97 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 79 | [.ai/tasks/T-018/review.md](../../.ai/tasks/T-018/review.md) | 24 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 80 | [.ai/tasks/T-019/evidence/README.md](../../.ai/tasks/T-019/evidence/README.md) | 28 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 81 | [.ai/tasks/T-019/plan.md](../../.ai/tasks/T-019/plan.md) | 44 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 82 | [.ai/tasks/T-019/report.md](../../.ai/tasks/T-019/report.md) | 201 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 83 | [.ai/tasks/T-019/review-architect.md](../../.ai/tasks/T-019/review-architect.md) | 39 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 84 | [.ai/tasks/T-019/review.md](../../.ai/tasks/T-019/review.md) | 5 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 85 | [.ai/tasks/T-020/plan.md](../../.ai/tasks/T-020/plan.md) | 47 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 86 | [.ai/tasks/T-020/report.md](../../.ai/tasks/T-020/report.md) | 94 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 87 | [.ai/tasks/T-020/review.md](../../.ai/tasks/T-020/review.md) | 39 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 88 | [.ai/tasks/T-021/plan.md](../../.ai/tasks/T-021/plan.md) | 139 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 89 | [.ai/tasks/T-021/report.md](../../.ai/tasks/T-021/report.md) | 93 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 90 | [.ai/tasks/T-021/review.md](../../.ai/tasks/T-021/review.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 91 | [.ai/tasks/T-022/plan.md](../../.ai/tasks/T-022/plan.md) | 47 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 92 | [.ai/tasks/T-022/report.md](../../.ai/tasks/T-022/report.md) | 62 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 93 | [.ai/tasks/T-022/review.md](../../.ai/tasks/T-022/review.md) | 16 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 94 | [.ai/tasks/T-023/plan.md](../../.ai/tasks/T-023/plan.md) | 54 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 95 | [.ai/tasks/T-023/report.md](../../.ai/tasks/T-023/report.md) | 64 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 96 | [.ai/tasks/T-023/review.md](../../.ai/tasks/T-023/review.md) | 17 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 97 | [.ai/tasks/T-024/plan.md](../../.ai/tasks/T-024/plan.md) | 40 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 98 | [.ai/tasks/T-024/report.md](../../.ai/tasks/T-024/report.md) | 56 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 99 | [.ai/tasks/T-024/review.md](../../.ai/tasks/T-024/review.md) | 15 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 100 | [.ai/tasks/T-025/plan.md](../../.ai/tasks/T-025/plan.md) | 36 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 101 | [.ai/tasks/T-025/report.md](../../.ai/tasks/T-025/report.md) | 94 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 102 | [.ai/tasks/T-025/review.md](../../.ai/tasks/T-025/review.md) | 17 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 103 | [.ai/tasks/T-026/report.md](../../.ai/tasks/T-026/report.md) | 15 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 104 | [.ai/tasks/T-027/plan.md](../../.ai/tasks/T-027/plan.md) | 73 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 105 | [.ai/tasks/T-027/report.md](../../.ai/tasks/T-027/report.md) | 65 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 106 | [.ai/tasks/T-027/review.md](../../.ai/tasks/T-027/review.md) | 46 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 107 | [.ai/tasks/T-028/plan.md](../../.ai/tasks/T-028/plan.md) | 119 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 108 | [.ai/tasks/T-028/report.md](../../.ai/tasks/T-028/report.md) | 158 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 109 | [.ai/tasks/T-028/review.md](../../.ai/tasks/T-028/review.md) | 45 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 110 | [.ai/tasks/T-029/plan.md](../../.ai/tasks/T-029/plan.md) | 44 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 111 | [.ai/tasks/T-029/report.md](../../.ai/tasks/T-029/report.md) | 40 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 112 | [.ai/tasks/T-029/review.md](../../.ai/tasks/T-029/review.md) | 24 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 113 | [.ai/tasks/T-030/plan.md](../../.ai/tasks/T-030/plan.md) | 69 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 114 | [.ai/tasks/T-030/report.md](../../.ai/tasks/T-030/report.md) | 68 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 115 | [.ai/tasks/T-030/review.md](../../.ai/tasks/T-030/review.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 116 | [.ai/tasks/T-031/plan.md](../../.ai/tasks/T-031/plan.md) | 53 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 117 | [.ai/tasks/T-031/report.md](../../.ai/tasks/T-031/report.md) | 47 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 118 | [.ai/tasks/T-031/review.md](../../.ai/tasks/T-031/review.md) | 24 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 119 | [.ai/tasks/T-032/plan.md](../../.ai/tasks/T-032/plan.md) | 186 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 120 | [.ai/tasks/T-032/report.md](../../.ai/tasks/T-032/report.md) | 87 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 121 | [.ai/tasks/T-032/review.md](../../.ai/tasks/T-032/review.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 122 | [.ai/tasks/T-033/plan.md](../../.ai/tasks/T-033/plan.md) | 46 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 123 | [.ai/tasks/T-033/report.md](../../.ai/tasks/T-033/report.md) | 137 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 124 | [.ai/tasks/T-033/review.md](../../.ai/tasks/T-033/review.md) | 107 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 125 | [.ai/tasks/T-034/plan.md](../../.ai/tasks/T-034/plan.md) | 43 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 126 | [.ai/tasks/T-034/report.md](../../.ai/tasks/T-034/report.md) | 103 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 127 | [.ai/tasks/T-034/review.md](../../.ai/tasks/T-034/review.md) | 163 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 128 | [.ai/tasks/T-035/plan.md](../../.ai/tasks/T-035/plan.md) | 24 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 129 | [.ai/tasks/T-035/report.md](../../.ai/tasks/T-035/report.md) | 129 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 130 | [.ai/tasks/T-035/review.md](../../.ai/tasks/T-035/review.md) | 18 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 131 | [.ai/tasks/T-036/plan.md](../../.ai/tasks/T-036/plan.md) | 309 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 132 | [.ai/tasks/T-036/report.md](../../.ai/tasks/T-036/report.md) | 233 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 133 | [.ai/tasks/T-036/review.md](../../.ai/tasks/T-036/review.md) | 83 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 134 | [.ai/tasks/T-037/plan.md](../../.ai/tasks/T-037/plan.md) | 115 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 135 | [.ai/tasks/T-037/report.md](../../.ai/tasks/T-037/report.md) | 153 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 136 | [.ai/tasks/T-037/review.md](../../.ai/tasks/T-037/review.md) | 25 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 137 | [.ai/tasks/T-038/plan.md](../../.ai/tasks/T-038/plan.md) | 141 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 138 | [.ai/tasks/T-038/report.md](../../.ai/tasks/T-038/report.md) | 119 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 139 | [.ai/tasks/T-038/review.md](../../.ai/tasks/T-038/review.md) | 30 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 140 | [.ai/tasks/T-039/plan.md](../../.ai/tasks/T-039/plan.md) | 54 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 141 | [.ai/tasks/T-040/design.md](../../.ai/tasks/T-040/design.md) | 157 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 142 | [.ai/tasks/T-040/plan.md](../../.ai/tasks/T-040/plan.md) | 139 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 143 | [.ai/tasks/T-040/report.md](../../.ai/tasks/T-040/report.md) | 155 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 144 | [.ai/tasks/T-040/review.md](../../.ai/tasks/T-040/review.md) | 78 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 145 | [.ai/tasks/T-041/plan.md](../../.ai/tasks/T-041/plan.md) | 73 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 146 | [.ai/tasks/T-042/plan.md](../../.ai/tasks/T-042/plan.md) | 85 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 147 | [.ai/tasks/T-043/plan.md](../../.ai/tasks/T-043/plan.md) | 100 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 148 | [.ai/tasks/T-043/report.md](../../.ai/tasks/T-043/report.md) | 132 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 149 | [.ai/tasks/T-043/review.md](../../.ai/tasks/T-043/review.md) | 39 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 150 | [.ai/tasks/T-044/plan.md](../../.ai/tasks/T-044/plan.md) | 126 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 151 | [.ai/tasks/T-044/report.md](../../.ai/tasks/T-044/report.md) | 228 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 152 | [.ai/tasks/T-044/review.md](../../.ai/tasks/T-044/review.md) | 52 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 153 | [.ai/tasks/T-045/plan.md](../../.ai/tasks/T-045/plan.md) | 71 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 154 | [.ai/tasks/T-045/report.md](../../.ai/tasks/T-045/report.md) | 83 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 155 | [.ai/tasks/T-046/plan.md](../../.ai/tasks/T-046/plan.md) | 79 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 156 | [.ai/tasks/T-046/report.md](../../.ai/tasks/T-046/report.md) | 5 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 157 | [.ai/tasks/T-047/plan.md](../../.ai/tasks/T-047/plan.md) | 76 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 158 | [.ai/tasks/T-047/report.md](../../.ai/tasks/T-047/report.md) | 6 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 159 | [.ai/tasks/T-048/plan.md](../../.ai/tasks/T-048/plan.md) | 78 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 160 | [.ai/tasks/T-048/report.md](../../.ai/tasks/T-048/report.md) | 7 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 161 | [.ai/tasks/T-049/plan.md](../../.ai/tasks/T-049/plan.md) | 86 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 162 | [.ai/tasks/T-049/report.md](../../.ai/tasks/T-049/report.md) | 6 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 163 | [.ai/tasks/T-050/plan.md](../../.ai/tasks/T-050/plan.md) | 80 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 164 | [.ai/tasks/T-050/report.md](../../.ai/tasks/T-050/report.md) | 11 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 165 | [.ai/tasks/T-051/plan.md](../../.ai/tasks/T-051/plan.md) | 84 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 166 | [.ai/tasks/T-051/report.md](../../.ai/tasks/T-051/report.md) | 10 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 167 | [.ai/tasks/T-052/plan.md](../../.ai/tasks/T-052/plan.md) | 72 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 168 | [.ai/tasks/T-052/report.md](../../.ai/tasks/T-052/report.md) | 6 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 169 | [.ai/tasks/T-053/plan.md](../../.ai/tasks/T-053/plan.md) | 74 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 170 | [.ai/tasks/T-053/report.md](../../.ai/tasks/T-053/report.md) | 10 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 171 | [.ai/tasks/T-054/plan.md](../../.ai/tasks/T-054/plan.md) | 59 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 172 | [.ai/tasks/T-054/report.md](../../.ai/tasks/T-054/report.md) | 9 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 173 | [.ai/tasks/T-055/plan.md](../../.ai/tasks/T-055/plan.md) | 55 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 174 | [.ai/tasks/T-055/report.md](../../.ai/tasks/T-055/report.md) | 7 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 175 | [.ai/tasks/T-056/plan.md](../../.ai/tasks/T-056/plan.md) | 104 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 176 | [.ai/tasks/T-056/report.md](../../.ai/tasks/T-056/report.md) | 10 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 177 | [.ai/tasks/T-057/plan.md](../../.ai/tasks/T-057/plan.md) | 61 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 178 | [.ai/tasks/T-057/report.md](../../.ai/tasks/T-057/report.md) | 8 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 179 | [.ai/tasks/T-058/plan.md](../../.ai/tasks/T-058/plan.md) | 82 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 180 | [.ai/tasks/T-058/report.md](../../.ai/tasks/T-058/report.md) | 5 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 181 | [.ai/tasks/T-059/plan.md](../../.ai/tasks/T-059/plan.md) | 139 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 182 | [.ai/tasks/T-059/report.md](../../.ai/tasks/T-059/report.md) | 12 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 183 | [.ai/tasks/T-060/plan.md](../../.ai/tasks/T-060/plan.md) | 73 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 184 | [.ai/tasks/T-060/report.md](../../.ai/tasks/T-060/report.md) | 10 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 185 | [.ai/tasks/T-061/plan.md](../../.ai/tasks/T-061/plan.md) | 73 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 186 | [.ai/tasks/T-061/report.md](../../.ai/tasks/T-061/report.md) | 9 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 187 | [.ai/tasks/T-062/plan.md](../../.ai/tasks/T-062/plan.md) | 76 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 188 | [.ai/tasks/T-062/report.md](../../.ai/tasks/T-062/report.md) | 8 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 189 | [.ai/tasks/T-063/plan.md](../../.ai/tasks/T-063/plan.md) | 62 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 190 | [.ai/tasks/T-063/report.md](../../.ai/tasks/T-063/report.md) | 23 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 191 | [.ai/tasks/T-064/plan.md](../../.ai/tasks/T-064/plan.md) | 72 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 192 | [.ai/tasks/T-064/report.md](../../.ai/tasks/T-064/report.md) | 29 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 193 | [.ai/tasks/T-065/plan.md](../../.ai/tasks/T-065/plan.md) | 65 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 194 | [.ai/tasks/T-065/report.md](../../.ai/tasks/T-065/report.md) | 25 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 195 | [.ai/tasks/T-066/plan.md](../../.ai/tasks/T-066/plan.md) | 46 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 196 | [.ai/tasks/T-066/report.md](../../.ai/tasks/T-066/report.md) | 23 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 197 | [.ai/tasks/T-067/plan.md](../../.ai/tasks/T-067/plan.md) | 57 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 198 | [.ai/tasks/T-067/report.md](../../.ai/tasks/T-067/report.md) | 31 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 199 | [.ai/tasks/T-068/plan.md](../../.ai/tasks/T-068/plan.md) | 60 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 200 | [.ai/tasks/T-068/report.md](../../.ai/tasks/T-068/report.md) | 32 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 201 | [.ai/tasks/T-069/plan.md](../../.ai/tasks/T-069/plan.md) | 34 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 202 | [.ai/tasks/T-069/report.md](../../.ai/tasks/T-069/report.md) | 39 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 203 | [.ai/tasks/T-070/plan.md](../../.ai/tasks/T-070/plan.md) | 19 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |
| 204 | [.ai/tasks/T-070/report.md](../../.ai/tasks/T-070/report.md) | 28 | RÀ TASK/LỊCH SỬ | Đang làm: giữ; đã xong: chỉ lưu bằng chứng/quyết định độc nhất |

### 08. Triển khai — deploy/ — 5 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [deploy/studio/DEMO_RUNBOOK.md](../../deploy/studio/DEMO_RUNBOOK.md) | 117 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 2 | [deploy/studio/OVERVIEW.md](../../deploy/studio/OVERVIEW.md) | 113 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 3 | [deploy/studio/PACKAGING.md](../../deploy/studio/PACKAGING.md) | 90 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 4 | [deploy/studio/README.md](../../deploy/studio/README.md) | 354 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 5 | [deploy/studio/RUNPOD_AUTOPROVISION.md](../../deploy/studio/RUNPOD_AUTOPROVISION.md) | 144 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |

### 09. Đánh giá — eval/ — 14 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [eval/geometry/README.md](../../eval/geometry/README.md) | 3 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 2 | [eval/object/README.md](../../eval/object/README.md) | 26 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 3 | [eval/path/README.md](../../eval/path/README.md) | 3 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 4 | [eval/pose/README.md](../../eval/pose/README.md) | 3 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 5 | [eval/protocols/BENCHMARKS.md](../../eval/protocols/BENCHMARKS.md) | 47 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 6 | [eval/protocols/README.md](../../eval/protocols/README.md) | 3 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 7 | [eval/protocols/collision_path_clearance.md](../../eval/protocols/collision_path_clearance.md) | 129 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 8 | [eval/protocols/lidar_odometry.md](../../eval/protocols/lidar_odometry.md) | 22 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 9 | [eval/protocols/pipeline_runtime.md](../../eval/protocols/pipeline_runtime.md) | 84 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 10 | [eval/protocols/recon_visual_quality.md](../../eval/protocols/recon_visual_quality.md) | 77 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 11 | [eval/protocols/reference_torwic.md](../../eval/protocols/reference_torwic.md) | 84 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |
| 12 | [eval/results/BENCHMARK_REPORT.md](../../eval/results/BENCHMARK_REPORT.md) | 103 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 13 | [eval/results/LIDAR_ODOMETRY_BENCHMARK.md](../../eval/results/LIDAR_ODOMETRY_BENCHMARK.md) | 298 | RÀ BẰNG CHỨNG | docs/STATUS.md hoặc docs/EVALUATION.md trỏ tới bằng chứng gốc |
| 14 | [eval/visual/README.md](../../eval/visual/README.md) | 27 | ĐỐI CHIẾU/GỘP | docs/EVALUATION.md |

### 10. Fixture — fixtures/ — 5 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [fixtures/candidate/README.md](../../fixtures/candidate/README.md) | 6 | GIỮ THEO FIXTURE | Rà consumer/test trước khi đổi |
| 2 | [fixtures/mock_job/README.md](../../fixtures/mock_job/README.md) | 16 | GIỮ THEO FIXTURE | Rà consumer/test trước khi đổi |
| 3 | [fixtures/reconstruction_bundle/README.md](../../fixtures/reconstruction_bundle/README.md) | 18 | GIỮ THEO FIXTURE | Rà consumer/test trước khi đổi |
| 4 | [fixtures/scene_ir/README.md](../../fixtures/scene_ir/README.md) | 9 | GIỮ THEO FIXTURE | Rà consumer/test trước khi đổi |
| 5 | [fixtures/validation_report/README.md](../../fixtures/validation_report/README.md) | 7 | GIỮ THEO FIXTURE | Rà consumer/test trước khi đổi |

### 11. Frontend — 1 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [frontend/README.md](../../frontend/README.md) | 59 | GỘP RỒI XÉT BỎ | README.md; docs/UX.md |

### 12. Runbook trong scripts/ — 2 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [scripts/gpu/README.md](../../scripts/gpu/README.md) | 183 | ĐỐI CHIẾU/GỘP | docs/OPERATIONS.md |
| 2 | [scripts/torwic/migrations/README.md](../../scripts/torwic/migrations/README.md) | 12 | RÀ TỪNG FILE | Chưa quyết định xóa |

### 13. Thuyết trình — 1 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [presentation/README.md](../../presentation/README.md) | 26 | RÀ TỪNG FILE | Chưa quyết định xóa |

### 14. Bên thứ ba — frontend/vendor/ — 2 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [frontend/vendor/supersplat/PROVENANCE.md](../../frontend/vendor/supersplat/PROVENANCE.md) | 9 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 2 | [frontend/vendor/supersplat/README.md](../../frontend/vendor/supersplat/README.md) | 87 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |

### 15. Quy định, template và công cụ — 24 file

| # | File | Dòng | Hướng xử lý | Đích/ghi chú |
| --- | --- | ---: | --- | --- |
| 1 | [.agents/rules/ai-log-hook.md](../../.agents/rules/ai-log-hook.md) | 43 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 2 | [.agents/workflows/log.md](../../.agents/workflows/log.md) | 36 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 3 | [.github/PULL_REQUEST_TEMPLATE.md](../../.github/PULL_REQUEST_TEMPLATE.md) | 22 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 4 | [.harness-core/base/.agents/skills/audit-onboarding-proposal/SKILL.md](../../.harness-core/base/.agents/skills/audit-onboarding-proposal/SKILL.md) | 321 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 5 | [.harness-core/base/.agents/skills/encode-invariant/SKILL.md](../../.harness-core/base/.agents/skills/encode-invariant/SKILL.md) | 67 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 6 | [.harness-core/base/.agents/skills/improve-harness/SKILL.md](../../.harness-core/base/.agents/skills/improve-harness/SKILL.md) | 112 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 7 | [.harness-core/base/.agents/skills/onboard-repository/SKILL.md](../../.harness-core/base/.agents/skills/onboard-repository/SKILL.md) | 506 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 8 | [.harness-core/base/.agents/skills/onboard-repository/references/evidence-capsule-v1.md](../../.harness-core/base/.agents/skills/onboard-repository/references/evidence-capsule-v1.md) | 144 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 9 | [.harness-core/base/.agents/skills/onboard-repository/references/evidence-capsule-v2.md](../../.harness-core/base/.agents/skills/onboard-repository/references/evidence-capsule-v2.md) | 242 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 10 | [.harness-core/base/AGENTS.md](../../.harness-core/base/AGENTS.md) | 31 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 11 | [.harness-core/base/docs/README.md](../../.harness-core/base/docs/README.md) | 40 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 12 | [.harness-core/base/docs/WORKFLOW.md](../../.harness-core/base/docs/WORKFLOW.md) | 128 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 13 | [.harness-core/base/docs/decisions/README.md](../../.harness-core/base/docs/decisions/README.md) | 10 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 14 | [.harness-core/base/docs/patterns/encoding-invariants.md](../../.harness-core/base/docs/patterns/encoding-invariants.md) | 99 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 15 | [.harness-core/base/docs/plans/README.md](../../.harness-core/base/docs/plans/README.md) | 33 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 16 | [.harness-core/base/docs/plans/active/README.md](../../.harness-core/base/docs/plans/active/README.md) | 5 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 17 | [.harness-core/base/docs/plans/completed/README.md](../../.harness-core/base/docs/plans/completed/README.md) | 8 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 18 | [.harness-core/base/docs/product/README.md](../../.harness-core/base/docs/product/README.md) | 28 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 19 | [.harness-core/base/docs/templates/application-runbook.md](../../.harness-core/base/docs/templates/application-runbook.md) | 49 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 20 | [.harness-core/base/docs/templates/decision.md](../../.harness-core/base/docs/templates/decision.md) | 34 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 21 | [.harness-core/base/docs/templates/exec-plan.md](../../.harness-core/base/docs/templates/exec-plan.md) | 56 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 22 | [.harness-core/base/docs/templates/harness-improvement.md](../../.harness-core/base/docs/templates/harness-improvement.md) | 54 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 23 | [landing/AGENTS.md](../../landing/AGENTS.md) | 9 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |
| 24 | [landing/CLAUDE.md](../../landing/CLAUDE.md) | 1 | GIỮ NGOÀI PHẠM VI GỘP | Quy định/công cụ/giấy phép; không tự xóa |

## 10. Kiểm chứng của lượt khảo sát

- Nguồn danh sách: `git ls-files --cached --others --exclude-standard -z`, deduplicate và lọc file còn tồn tại.
- Kiểm kê: 541 tổng − 39 sổ tay = 502; mỗi file xuất hiện đúng một lần trong mục 9.
- Đọc toàn bộ file bằng scanner để thống kê tiêu đề, cấu trúc, link và exact duplicates; nội dung sâu chỉ đối chiếu ở các phần nêu trên.
- CodeGraph/graphify được dùng trước khi định hướng source. Với query quá rộng hoặc đường dẫn không khớp, thu hẹp sang file thực; không dùng các kết quả trùng tên làm bằng chứng cho file khác.
- Không chạy lint/test/build/pipeline trong lượt này vì chỉ tạo báo cáo khảo sát. Những kiểm tra của lần sửa README trước không phải bằng chứng runtime cho audit này.
- Chưa xác nhận live cloud, trình duyệt, GPU, chất lượng collision hay Isaac acceptance; những phát biểu đó sẽ cần bằng chứng riêng khi chuẩn hóa STATUS/EVALUATION.

## 11. Ràng buộc đã chốt và kết quả lượt 1 — PRD

### 11.1 Chỉ dẫn bổ sung của chủ dự án

- **Không được xóa:** sổ tay; quy định agent; giấy phép; WORKLOG/JOURNAL; task đang làm; bằng chứng gốc cần truy vết. Quy tắc này ưu tiên hơn mọi nhãn sơ bộ “rà”, “gộp”, “xét bỏ” trong snapshot inventory ở trên.
- Mỗi tài liệu phải có cấu trúc đề mục rõ, nội dung đủ chi tiết để hiểu và áp dụng. Mỗi mục có trách nhiệm riêng; nội dung đã có nơi trình bày chính thì dẫn liên kết, không chép lại.
- Thực hiện từng tài liệu theo kế hoạch. Lượt này chỉ chuẩn hóa PRD, chưa bắt đầu tài liệu kỹ thuật kế tiếp và chưa dọn file cũ.

### 11.2 Thay đổi PRD

`docs/PRD.md` được chuẩn hóa từ 1.344 xuống 499 dòng. Phạm vi định vị theo BRAINSTORM/MASTER_PITCH là indoor robotics; warehouse là một use case. Giữ đủ 7 mã G, 7 SM, 14 FR, 8 NFR và 12 AC để truy vết. Tài liệu có mục đích/phạm vi, mục tiêu, người dùng/quyền, phạm vi, input, hành trình, FR, NFR, AC, đánh giá, rủi ro, nguồn code và mốc nghiệm thu riêng.

Tách yêu cầu sản phẩm khỏi implementation/evidence. Bổ sung cách diễn giải input recipe, imported 3DGS, Draft/Ready geometry, collision sau move/delete, demo session và capability export theo code/quyết định mới. Giữ gate LiDAR contribution, đúng candidate/report/approval và kiểm định Isaac; không coi Walk, parser USD hoặc test fixture là acceptance thật. Không viết lại BRAINSTORM/MASTER_PITCH.

Đã đọc toàn bộ PRD cũ; đọc các phần định vị/use case/validation/claims liên quan trong tài liệu ý tưởng; dò source qua CodeGraph cho router/auth/ownership, input resolver, geometry state, simulation package, validation gate, release contracts, privacy, video normalization và demo session. Các đoạn kỹ thuật chi tiết được dẫn sang nguồn tương ứng thay vì sao chép vào PRD.

### 11.3 Kiểm tra và giới hạn

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| So mã yêu cầu PRD cũ/mới | PASS: giữ đầy đủ G/SM/FR/NFR/AC; mỗi FR/NFR/AC có một đề mục riêng |
| Cấu trúc đề mục, liên kết và anchor cục bộ | PASS: không trùng đề mục; 34 liên kết/anchor tồn tại |
| Đoạn văn lặp nguyên văn dài hơn 120 ký tự | 0; đây chỉ là kiểm cơ học, cấu trúc nội dung đã được rà riêng |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_foundation` | PASS: 5 kiểm tra contract fixture, artifact SHA-256, synthetic lineage, negative fixtures và document projection |
| Snapshot bảo toàn file ngoài PRD và báo cáo này | PASS: 1.725 file Markdown/source/config/test/script khác không đổi; không có xóa mới |
| Lint/full test/build/browser/GPU/cloud/Isaac | Không chạy: chỉ đổi tài liệu; không dùng kiểm tra tĩnh để nhận nghiệm thu runtime |

PRD ở trạng thái bản chuẩn hóa chờ chủ dự án rà soát, chưa phải chứng nhận hoàn thành MVP. Không commit/push, không đổi branch, không sửa source/test/config, không sửa sổ tay/giấy phép/WORKLOG/JOURNAL/task đang làm hay bằng chứng runtime gốc.

## 12. Kết quả lượt 2 — ARCHITECTURE

### 12.1 Phạm vi và thay đổi

Đối chiếu source trên `develop`, HEAD `ac0be875`. Chỉ chuẩn hóa `ARCHITECTURE.md` và bổ sung kết quả vào báo cáo này. Không bắt đầu PIPELINE, không xóa/di chuyển tài liệu cũ.

Kiến trúc được viết lại từ 585 xuống 343 dòng, với 48 đề mục có trách nhiệm riêng. Nội dung gồm tổng quan hệ thống, ownership/placement, ranh giới HTTP/worker/tool/controller, DB/artifact/cache, input/config/runtime identity, SceneIR/representation/collision, frontend, export/Isaac/release, bảo mật/demo và topology triển khai. Có hai sơ đồ Mermaid: quan hệ thành phần và mô hình Web/API thường trực với worker GPU từ xa.

Các điểm được sửa theo code:

- Backend dùng module Python chung và orchestration có lời gọi trực tiếp qua các miền; tách process của tool không đồng nghĩa đã tách toàn bộ import thành service độc lập.
- Route tạo simulation package hiện gọi builder trực tiếp. Không ghi mọi công việc nặng đều đã ra khỏi HTTP.
- DB có chuỗi migration và committed SceneIR head; không mô tả schema hiện tại chỉ là v1 hoặc state nằm trong browser/cache.
- Phân biệt artifact bất biến, local artifact cache, worker scratch/checkpoint và derived cache; DB và filesystem/S3 không có một transaction chung.
- API có demo sessions; runtime worker heartbeat, input qualification registry và release catalog có vai trò riêng.
- Có controller/provider RunPod và CPU lane tùy chọn. Readiness có thể dựa vào live worker hoặc catalog tương thích; không mặc định ready là GPU pod đang sống.
- Scene có Draft/Ready geometry, source membership/ownership, effective collision và CAS/head commit. Vỏ preview, visual và collider không được gộp thành một loại geometry.
- Viewer/inspection không được mô tả tất cả cùng một canvas/render pass. Bỏ cây thư mục dự kiến và phụ lục chat-agent cũ khỏi mô hình thực thi.
- OpenUSD authoring, Isaac validation và review/release là các boundary khác nhau; image reconstruction mặc định không tự cài Isaac.

### 12.2 Nguồn đã đối chiếu

Đã đọc toàn bộ ARCHITECTURE cũ, PRD chuẩn hóa và phạm vi kế hoạch. Graphify được dùng để định hướng; CodeGraph được dùng trước khi đọc/đối chiếu source. Nguồn chính: `main`, API routers/simulation route, storage/resolver/remote, RuntimeDatabase, ProjectRegistry, worker CLI/runtime profile/registry, SceneEditor/head, representation composition/effective collision, pipeline projection, demo session context/distributed store, GPU controller/provider/CPU worker, container entrypoint, Isaac process và PlayCanvasScene.

Cấu hình được đối chiếu: Next rewrites, native stack script/Makefile, Compose CPU/GPU, Dockerfile API/Web/GPU và production env template. Các source path được liên kết trực tiếp từ tài liệu. Không dùng phần output CodeGraph trùng tên ngoài file cần đọc làm bằng chứng cho file đó.

### 12.3 Kiểm tra

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| Cấu trúc Markdown | PASS: 48 đề mục không trùng, hierarchy không nhảy cấp, code fence cân bằng |
| Local links | PASS: 56 link tới file/thư mục còn tồn tại |
| Đoạn văn lặp nguyên văn dài hơn 120 ký tự | 0; kiểm cơ học bổ sung cho rà nội dung |
| Sơ đồ | Có 2 block Mermaid; chưa render/kiểm bằng mắt, không nhận là renderer-verified |
| Compose config qua file env mẫu trong `/tmp` | PASS: CPU có 4 service, GPU có 6 service đúng thành phần được mô tả; không start container/build image |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_foundation` | PASS: 5 kiểm tra contract fixture, artifact SHA-256, synthetic lineage, negative fixtures và document projection |
| `git diff --check` | PASS |
| Bảo toàn snapshot ngoài ARCHITECTURE và báo cáo | PASS: 1.731 file Markdown/source/config/test/script/build-config khác không đổi; không có xóa mới |

Không sửa PRD đã chuẩn hóa, BRAINSTORM/MASTER_PITCH, sổ tay, quy định agent, giấy phép, WORKLOG/JOURNAL, task đang làm hoặc bằng chứng runtime gốc. Không sửa source/test/config, không commit/push/đổi branch. Chưa chạy lint/full test/build/browser/cloud/GPU/Isaac vì lượt này chỉ thay tài liệu; kết quả Foundation/Compose config không thay acceptance runtime.

ARCHITECTURE là bản chuẩn hóa chờ chủ dự án rà soát. Tài liệu tiếp theo trong kế hoạch là PIPELINE; chưa bắt đầu trong lượt 2.

## 13. Kết quả lượt 3 — PIPELINE

### 13.1 Phạm vi và kết quả

Tạo `docs/PIPELINE.md`, 341 dòng, mô tả source tại `develop`, HEAD `ac0be875`. Không sửa PRD/ARCHITECTURE của hai lượt trước, không đổi code/config, không xóa hoặc chuyển tài liệu cũ. `docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md` được giữ nguyên để truy vết; chuyển liên kết của cả bộ docs và dọn bản dư vẫn thuộc giai đoạn riêng.

Tài liệu có 48 đề mục, một sơ đồ luồng RGB mặc định và các phần tách biệt: chuẩn bị/resolve input, R1–R6 và import/prepared input, prepare/privacy/sensor, COLMAP/Brush preview, confirmation/finalize, grouping/lifting/Draft, review/region/build geometry, layout/package/Isaac/release, progress/LOD và recovery/evidence. Không sao chép lại cây module/deployment từ ARCHITECTURE hoặc bộ yêu cầu/acceptance từ PRD.

### 13.2 Các điểm được đối chiếu từ code

- R1–R6 là nhóm recipe video reconstruction, không phải bước tuần tự hoặc sáu nhánh LiDAR-only. R4 hiện có ràng buộc calibration/RGB frame times; R5/R6 có điều kiện scan PCD, hệ mét và timestamp tương ứng.
- Schema R6 mô tả rộng hơn biến thể mà worker hiện chấp nhận: worker kiểm estimated scan trajectory và runtime R5/R6. Không coi schema/resolver biểu diễn được một biến thể là proof biến thể đó đã chạy hết.
- R2/R3 dùng manifest reconstruction RGB và giữ nguồn cloud cho registration; không tự thay collision source khi upload cloud.
- Import PLY/SOG hiện chỉ đi viewer/packaging. UnifiedInputFlow nói rõ chưa có continuation cho scene import; không chuyển nội dung ADR/kế hoạch thành chức năng đã có.
- Privacy acceptance có thể dừng job trước COLMAP; reviewed-preview path tiếp tục cùng job, không tự chạy lại mọi bước prepare. Zero redactions có bản ghi tự động khác với người đã xem/duyệt.
- Preview thành công còn chờ xác nhận mét. Finalize canonical pose/visual rồi geometry/bundle; confirmation đo tay không tự xác nhận alignment trajectory LiDAR.
- Grouping xác định nhóm quan sát, lifting gán Gaussian nguồn đã có. Draft lưu membership/visual/shell preview, khác collider cuối.
- Full geometry build chặn khi còn candidate chưa duyệt. `auto` vẫn tạo Draft/xếp operation và chịu gate builder; không được mô tả auto chắc chắn vượt mọi bước duyệt.
- Shell là mặc định của preset. ObjectGS có thể giữ shell từng vật khi surface QA không đạt và phải ghi reason; partial rebuild có đường shell với `partial_rebuild_uses_shell`.
- Inpaint phục vụ visual; collision object-aware ghi `inpaint_used_for_physics=False` và phân biệt support inferred. Ready chỉ được publish theo revision/commit guard.
- Reconstruction job có thể SUCCEEDED trong khi extraction lỗi/chưa có scene dùng tiếp; geometry operation, object confirmation và validation/release cần được đọc riêng.
- Mã `ST-ANONYMIZATION-REVIEW`/`ST-VIEW-LOD` hiện dùng cho marks/UI theo registry, không tự coi là StageArtifact mới. LOD có thể được tạo sau reconstruction success; lỗi LOD không tự làm job gốc failed.

### 13.3 Nguồn và kiểm tra

Đã đọc nội dung tài liệu pipeline cũ; dùng graphify định hướng, CodeGraph explore/node để xem call path và source theo symbol/line range. Các nguồn chính: input assembly contract/resolver, runner/preview worker/prepare/finalize, metric, extraction/objectify, region edits, geometry build/steps, Gaussian shell, scene imports, registration/validation worker, next_action, stage registry và processing presets. Link trực tiếp tới source nằm trong PIPELINE mới.

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| Cấu trúc Markdown | PASS: 48 đề mục không trùng, hierarchy đúng, fence cân bằng |
| Liên kết cục bộ | PASS: 38 link còn tồn tại |
| Đoạn văn dài lặp nguyên văn | 0 đoạn trên 120 ký tự; có rà nội dung theo trách nhiệm từng mục |
| Mermaid | Có 1 block luồng RGB; chưa render/kiểm bằng mắt |
| Stage/recipe identifiers | PASS: 13 mã stage được nhắc khớp StageId; R1–R6 khớp RecipeGroup |
| Mặc định processing | PASS: cả 8 preset khớp shell / required / multiview_v1 |
| Runner entrypoints và call order | PASS: hàm được nhắc tồn tại; `run_video_job` gọi prepare → ingest → odometry → preview theo source |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_foundation` | PASS: 5 kiểm tra fixture/identity/lineage/negative/docs projection |
| `git diff --check` và whitespace file mới | PASS |
| Bảo toàn snapshot ngoài báo cáo này | PASS: 1.732 file Markdown/source/config/test/script/build-config đã có giữ nguyên; chỉ thêm PIPELINE.md và append báo cáo |

Các kiểm tra cơ học trên hỗ trợ đối chiếu tài liệu, không thay kiểm từng nhánh runtime. Không chạy full test/lint/build hoặc live pipeline/browser/cloud/GPU/Isaac. Không provision compute, sửa database/artifact runtime hay commit/push/đổi branch. Sổ tay, quy định agent, giấy phép, WORKLOG/JOURNAL, task đang làm và bằng chứng gốc được giữ nguyên.

PIPELINE là bản chuẩn hóa chờ chủ dự án rà soát. Lượt tiếp theo theo kế hoạch là CONTRACTS; chưa bắt đầu trong lượt 3.

## 14. Kết quả lượt 4 — CONTRACTS

### 14.1 Phạm vi và kết quả

Tạo `docs/CONTRACTS.md`, 335 dòng, đối chiếu source tại `develop`, HEAD `ac0be875`, ngày 20/10/2026. Tài liệu có 46 đề mục và 50 liên kết cục bộ. Các phần được chia theo trách nhiệm: artifact/checksum; input và run acceptance; job/stage/runtime; tọa độ/reconstruction; SceneIR/membership/collision ownership; revision/concurrency; preflight/candidate; validation/evaluation; approval/release; API/version/checks.

Không sao chép toàn bộ field/schema hoặc danh sách endpoint vào Markdown. Tài liệu liên kết model, bên đọc và bộ kiểm tra đang có, giải thích ý nghĩa và điều kiện bàn giao. Không viết lại thứ tự pipeline, cấu trúc module, cấu hình triển khai hoặc tiêu chí sản phẩm của ba tài liệu trước.

Giữ nguyên `docs/execution/TEAM_EXECUTION_CONTRACT.md`. Bản này còn được authority map, task và Foundation checker tham chiếu; chuyển authority/consumer và dọn bản cũ thuộc lượt cuối. CONTRACTS mới là bản chuẩn hóa chờ chủ dự án rà soát, không tự thay policy hoặc duyệt schema mới.

### 14.2 Các điểm được đối chiếu từ code

- Phân biệt checksum exact bytes với canonical logical content; serializer riêng có thể bỏ field để giữ checksum dữ liệu cũ. Bundle/SceneIR/report content checksum khác checksum bytes của JSON đã publish.
- `ArtifactRef` không tự cấp quyền và không tự xác minh bytes; `ProductArtifactRef` chỉ nhận `product_input`/`derived`. Provenance ground-truth assistance được giữ riêng với usage class.
- Assembly revision, resolution, recipe và run receipt khóa đúng input/config/người chấp nhận. Input candidate ID khác candidate OpenUSD; import intent không yêu cầu reconstruction.
- Server verification của prepared video xác minh dữ liệu nhận được, không tự xác minh original source còn trên máy người dùng. Frame-map sidecar và audio consent được giữ đúng ý nghĩa.
- JobManifest hiện dùng runtime checksum, không có software/environment version maps như field list của hợp đồng cũ. Job mới ghép worker bằng software runtime checksum; checksum runtime đầy đủ vẫn được giữ và hỗ trợ job cũ.
- Canonical coordinates dùng meter/Z-up/right-handed/world, `parent_from_local`, quaternion `xyzw`. Preview bắt buộc sfm_world/arbitrary/unconfirmed; bundle builder cần metric verification thật từ đường xử lý của ứng dụng.
- Membership command checksum là checksum bytes labels, không phải hash toàn manifest. Gaussian row ownership, triangle ownership và object-local region được mô tả riêng; correction vẫn chịu các gate consumer.
- Tách object state, geometry readiness, job state, workflow state và validation-run state. Scene cũ thiếu `object_geometry` có nhánh tương thích, không phải bằng chứng đã qua geometry build mới.
- Object-aware collision loại trừ legacy collision-source selection trong cùng environment. Candidate inventory hiện tính thêm collision selection/object-aware manifest refs khi có, theo đúng thứ tự helper trong source.
- Scene head chỉ cập nhật sau reservation/publication/CAS và commit guard. Artifact tồn tại hoặc số revision cao hơn không tự trở thành committed head.
- Validation selection chỉ chọn completed worker run, gắn đúng candidate/config/report/revision và runtime evidence. Schema report pass không đủ chứng minh Isaac; physics claim còn có điều kiện reference độc lập, coverage và contact evidence.
- Approval và sealing là hai kết quả riêng; approve có thể đã lưu khi seal lỗi. Retry seal dùng đúng candidate/report/approval đã có. Không kế thừa approval sang revision khác.
- Version hỗ trợ phụ thuộc model: `SchemaVersion` dùng chung nhận 1.0/1.1; GeometryArtifact payload có 1.2. Không mô tả mọi envelope/consumer đều nhận cùng version hoặc tự sửa schema để đồng nhất.

### 14.3 Nguồn và kiểm tra

Đã đọc toàn bộ hợp đồng kỹ thuật cũ. Graphify được dùng định hướng; CodeGraph explore/node được dùng để xem model, callers và source của các consumer liên quan. Nguồn chính: contracts/artifacts, identity, manifests, coordinates, input_assembly, video_preparation, reconstruction, preview, scene, object_membership, object_geometry, collision_quality, registration, validation, validation_run, release; API schemas; artifact resolver/store; input run records; execution profile; metric confirmation/bundle validation; representation composition; membership consumer/correction; geometry state; scene heads; validation repository/gate; review/sealing và mirror checker.

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| Cấu trúc Markdown | PASS: 46 đề mục không trùng, hierarchy đúng, fence cân bằng |
| Liên kết cục bộ | PASS: 50 link tới file/thư mục tồn tại |
| Đoạn văn dài lặp nguyên văn | 0 đoạn trên 120 ký tự; bổ sung cho rà trách nhiệm nội dung từng mục |
| Đối chiếu tên model và enum/field | PASS: 59 tên shared contract class có trong source; các phân biệt state/enum/field được nhắc khớp model import hiện hành |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/pytest tests/test_contracts -q` | PASS: 256 passed in 0.51s |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_foundation` | PASS: 5 kiểm tra fixture/bytes/checksum/lineage/negative/document projection |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_contract_mirror` | PASS: 5 enum, 9 model trong phạm vi checker; không mở rộng kết luận thành toàn bộ frontend API |
| `git diff --check` và whitespace file mới | PASS |
| Bảo toàn snapshot ngoài báo cáo | PASS: 2.107 file Markdown/source/config/test/script/build-config đã có giữ nguyên; chỉ thêm CONTRACTS.md và append báo cáo |

Không tạo/sửa test, source hoặc config. Không sửa ba tài liệu đã chuẩn hóa, BRAINSTORM/MASTER_PITCH, sổ tay, quy định agent, giấy phép, WORKLOG/JOURNAL, task đang làm hoặc bằng chứng gốc. Không xóa tài liệu, không commit/push/đổi branch. Không chạy full suite/lint/build hoặc live browser/GPU/cloud/Isaac; các kiểm tra contract cục bộ không phải nghiệm thu runtime.

Lượt tiếp theo theo kế hoạch là UX; chưa bắt đầu trong lượt 4.

## 15. Kết quả lượt 5 — UX

### 15.1 Phạm vi và kết quả

Tạo `docs/UX.md`, 331 dòng, đối chiếu source tại `develop`, HEAD `ac0be875`, ngày 20/10/2026. Tài liệu có 49 đề mục, 49 liên kết cục bộ và 16 route được kiểm tra tồn tại trong app hiện tại. Các phần tách theo công việc người dùng: điều hướng; phiên/quyền/quota; input; tiến trình; mét; vật thể; viewer/Walk; kiểm tra/duyệt; tải kết quả; import/demo; benchmark/thùng rác; phản hồi và giới hạn khả năng sử dụng.

Không chép schema/checksum protocol từ CONTRACTS, thuật toán từ PIPELINE hoặc tiêu chí nghiệm thu từ PRD. Quyền/quota được trình bày theo tác động tới nút và đường đi UI; chính sách sản phẩm vẫn dẫn về PRD. Các hướng dẫn nói rõ điều kiện mở và kết quả của thao tác, không đổi bố cục hoặc hành vi code để khớp docs.

Giữ nguyên `docs/STUDIO_UX_SPEC.md`, `docs/WIREFRAME_AND_UI_FLOW.md` và frontend README. Chuyển authority map/consumer/liên kết và dọn tài liệu cũ thuộc lượt riêng. UX mới là bản chuẩn hóa chờ chủ dự án rà soát, chưa phải browser-verified specification.

### 15.2 Các điểm được đối chiếu từ frontend và API

- Root WebApp chuyển tới login/overview, landing là app riêng. Navigation hiện có Tổng quan, Tạo scene mới, Scenes từ video, Scenes đã import, Benchmark, Thùng rác và Nhóm theo quyền. `/jobs` chuyển về `/scenes`.
- `/new` và `/new/import-video` dùng UnifiedInputFlow, ba bước Chọn dữ liệu → Cấu hình xử lý → Xác nhận. Một khung nhận video/sensor/metadata/3DGS, tự phân tích, nêu file dùng/bỏ và lý do chưa chạy được. Luồng import riêng vẫn còn tại `/new/import-scene`.
- Guest khác Visitor; capability server quyết định quyền sửa từng resource. Signup dùng rollout flag; UI không cho tự chọn role. Quota Guest là 3 job/create hoặc manual Retry được chấp nhận mỗi ngày Việt Nam, không tính upload/phân tích input.
- Form upload có lifecycle tạm/cleanup, không được mô tả như nơi giữ file lâu dài hoặc bảo đảm resume sau khi rời trang. Job đã được server nhận tiếp tục độc lập với trang theo dõi.
- Scene có bốn vùng Tiến trình/Studio/Kiểm tra & duyệt/Kết quả; mặc định Tiến trình, Studio toàn màn hình, tab khóa có lý do. Mở tab không đủ chứng minh mọi dữ liệu con sẵn sàng.
- Chuông và các hàng bước dùng trạng thái/hành động tiếp theo; có chờ runtime/resources, privacy review, metric, object/geometry và lỗi riêng. Mất kết nối cập nhật không tự biến job thành failed. Retry đợi backend xác nhận attempt mới.
- Metric đo tay dùng A–B/C–D/ba điểm sàn và preview; proposal trajectory LiDAR có panel không chọn điểm. Không biến một proposal ước lượng hoặc upload LiDAR thành xác nhận metric tự động.
- Draft duyệt vật có giữ nền/tách độc lập, Chỉnh vùng và tạo mesh sau khi không còn candidate chưa xử lý. Ready region Apply có thể nhận operation 202 thay vì revision hoàn tất ngay. Các gate correction có giới hạn theo source/runtime.
- Ẩn trên màn hình là state cục bộ, tắt mô phỏng sửa `active`, xóa là mutation khác. Form collider có preview và Lưu collider; các action ghi thành công trả revision. Không có Save Draft tổng quát sau mọi thao tác.
- Main viewer mặc định WebGL. `GAUSSIAN_EDIT_ENABLED=false`; import hiện chỉ xem qua SceneWorkspace/PreviewScene. Không mô tả editor/Export như chức năng đang bật. Walk/browser physics không thay Isaac validation.
- Tạo gói, chạy validation, chọn report và quyết định Reviewer là các thao tác riêng. Candidate cũ được đánh dấu; approval có thể đã lưu khi sealing lỗi và có Thử lại phát hành.
- Kết quả có ba loại download: preview SOG, candidate OpenUSD, release. Lỗi đọc gói khác chưa có gói; revision cũ không được trình bày như kết quả hiện hành.
- Replay mẫu dùng tiến trình đã ghi; mở scene mẫu tạo phiên riêng, hết phiên có đường mở lại và có fallback chỉ xem khi phù hợp. Lưu trạng thái/khôi phục/gỡ thư viện mẫu khác approve/release.
- Benchmark tổng hợp theo project được chọn; thùng rác xử lý theo capability và có kết quả thành công/lỗi từng phần. Không gọi DOM tests là bằng chứng render/browser/mobile/accessibility/GPU.

### 15.3 Nguồn và kiểm tra

Graphify được dùng định hướng và CodeGraph explore/node được dùng trước khi đọc source. Đã đối chiếu các phần current context, flow, screen inventory, interaction và decision trong UX spec/wireframe cũ; không dùng nhãn VERIFIED lịch sử trong đó làm bằng chứng live hiện tại.

Nguồn chính: route page wrappers; AppShell/routes/AuthForms/AccountPage/TeamPage/auth helpers/ownership guard; Overview/Scenes/ImportedScenes; UnifiedInputFlow; ScenePage và bốn tab; privacy/metric/LiDAR metric; ObjectReviewView/RegionEditor/geometry banner; MetricSceneView/SceneWorkspace/renderer setting; inspection page; package/registration/validation/review/results; sample flow/session/DemoControls; benchmark, trash và NavigationGuard. Các path trọng tâm có link trực tiếp trong UX mới.

Bộ test frontend đã chạy tại `frontend/`:

```bash
npm test -- tests/studio-navigation.test.tsx tests/studio-overview.test.tsx tests/unified-input-flow.test.tsx tests/studio-ownership.test.tsx tests/ux-scene-flow.test.tsx tests/object-review.test.tsx tests/region-editor.test.tsx tests/geometry-review-banner.test.tsx tests/review-panel.test.tsx tests/validation-runs-panel.test.tsx tests/studio-results.test.tsx tests/import-scene-page.test.tsx tests/studio-input-flows.test.tsx tests/trash-page.test.tsx tests/ux-account-auth.test.tsx tests/preview-scene-camera.test.tsx
```

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| Component/flow regressions theo 16 file trên | PASS: 16 test files, 306 tests; Vitest duration 30.00s |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_foundation` | PASS: 5 kiểm tra fixture/bytes/lineage/negative/document projection |
| Route/label/flag đối chiếu source | PASS: 16 route, bốn scene tab, ba input step, Jobs redirect, Gaussian edit flag và renderer default |
| Cấu trúc Markdown | PASS: 49 đề mục không trùng, hierarchy đúng, fence cân bằng |
| Liên kết cục bộ | PASS: 49 link tới file/thư mục còn tồn tại |
| Đoạn văn dài lặp nguyên văn | 0 đoạn trên 120 ký tự; bổ sung cho rà trách nhiệm nội dung từng mục |
| `git diff --check` và whitespace file mới | PASS |
| Bảo toàn snapshot ngoài báo cáo | PASS: 2.108 file Markdown/source/config/test/script/build-config đã có giữ nguyên; chỉ thêm UX.md và append báo cáo |

Không tạo/sửa test, source hoặc config. Không sửa các docs đã chuẩn hóa, BRAINSTORM/MASTER_PITCH, sổ tay, quy định agent, giấy phép, WORKLOG/JOURNAL, task đang làm hoặc bằng chứng gốc. Không xóa tài liệu, không commit/push/đổi branch. Không chạy full frontend suite/lint/build hoặc live browser/GPU/cloud/Isaac. Bộ test chọn lọc trên không chứng minh toàn bộ UX, accessibility, responsive hay runtime deployment đã được nghiệm thu.

Lượt tiếp theo theo kế hoạch là OPERATIONS; chưa bắt đầu trong lượt 5.

## 16. Kết quả lượt 6 — OPERATIONS

### 16.1 Phạm vi và kết quả

Tạo `docs/OPERATIONS.md`, 364 dòng, 44 đề mục, 31 liên kết cục bộ. Tài liệu tập trung vào cài/chạy lại, cấu hình, runtime, health/log, bàn giao/khôi phục, production/demo và bảo trì. Ba đường chạy Compose CPU, Compose GPU và native được tách theo điều kiện sử dụng. Các phần giải thích thuật toán, schema, thao tác UI và nghiệm thu dẫn sang tài liệu sở hữu nội dung tương ứng.

Đối chiếu ban đầu trên `develop`, HEAD `ac0be875`. Khi kiểm tra cuối lượt, HEAD đã thành `ae6d0beb`; diff hai commit chỉ bổ sung `.ai/tasks/T-071/plan.md` (213 dòng), không thay source/config đã dùng. Đây là thay đổi từ hoạt động khác trong workspace; lượt docs này không tạo commit và không sửa task đó. Snapshot trong OPERATIONS ghi HEAD kết thúc đã xác minh.

Giữ nguyên các runbook kỹ thuật cũ để chuyển consumer/liên kết và dọn trong lượt riêng; chưa đổi authority map hoặc README. Không sửa những docs đã chuẩn hóa, BRAINSTORM/MASTER_PITCH, sổ tay, quy định agent, giấy phép, WORKLOG/JOURNAL, task hay bằng chứng gốc.

### 16.2 Những điểm đã đối chiếu theo code

- CPU Compose có bốn service và không có reconstruction worker; GPU override có sáu service. File `.env.studio.example` mặc định chọn GPU nên lệnh CPU luôn chỉ rõ `-f docker-compose.yml`. API/Web local mặc định 8010/3010; native Makefile có dò cổng còn chạy trực tiếp stack script mặc định 8000/3000.
- Startup container restore bỏ qua archive khi DB đã tồn tại. Thay ZIP rồi restart không merge/restore dữ liệu mới. Native `run_stack.sh` không có bootstrap tài khoản như container entrypoint.
- `make setup` dùng Python 3.12 và hash lock, không cài hết GPU/USD/Isaac. Native `up` có thể cài LiDAR/sinh registry; `env` giữ file cũ nhưng `up` cập nhật ba khóa cổng/proxy. `down` gửi TERM theo PID giữ cổng, cần kiểm quyền sở hữu process trước.
- `load_runtime_env` chỉ thêm giá trị thiếu/rỗng; R2S env ưu tiên và legacy env còn fallback. Thay runtime cần identity/manifest/registry phù hợp, không giả lập qualification để mở recipe. Registry dev-local không được gọi là kiểm định production.
- `production.env.example` là nguồn để check/render ba service env. Không source toàn bộ file nhiều section hoặc dùng ba generated examples như thể đang đồng bộ; test đã phát hiện mismatch thật. Không cài/build/deploy hoặc tạo env chứa secret trong lượt này.
- `/health` kiểm DB; `/ready` có thể đạt nhờ catalog khi chưa có worker sống. RuntimeDatabase có lifecycle migration nên endpoint/CLI mở DB không nhất thiết hoàn toàn tách khỏi ghi schema. Không lấy readiness làm bằng chứng GPU/job/Isaac đã chạy.
- Data package giữ SQLite + artifacts + các nhóm optional được hỗ trợ; không bao gồm workspace/runtime/env. Mặc định scrub credentials, giữ đúng hai seed user là lựa chọn riêng. Pack có gate trạng thái; force-unpack có thể chuyển cả nhóm optional không có trong gói mới sang backup.
- PostgreSQL/R2 cần backup nhất quán riêng. `package_publish publish` chỉ ghi khi `--apply`, nhưng `provision` có thể ghi optional data không cần flag đó; không mô tả mọi subcommand là dry-run. Import production yêu cầu đích trống, không có giao dịch chung giữa DB và object store.
- Demo archive khác SQLite data package; baseline immutable, phiên schema/output prefix tách riêng. Không xem replay demo là kết quả reconstruction/validation mới.
- Worker `--once` xử lý queue thật; controller reconcile/watchdog có thể điều khiển tài nguyên. Recovery phải dựa trên state/lease/attempt và owner, không reset status DB thủ công hoặc coi chờ người dùng là orphan. Backfill scene head có phạm vi job cụ thể và không chọn revision bằng tên file lớn nhất.

### 16.3 Nguồn và kết quả kiểm tra

Đã dùng Graphify định hướng và CodeGraph explore/node trước khi đọc source. Các nguồn chính: Makefile/Makefile.studio; setup/run_stack/install/doctor/runtime loader; Compose CPU/GPU; Dockerfile API/GPU/Web; pins và env mẫu; Settings/runtime env; container bootstrap; data_package; deploy_env; package_publish; demo release; main health/readiness; RuntimeDatabase migration; worker lifecycle; scene_head và controller. Các runbook packaging/deployment/demo cũ được đối chiếu theo phần liên quan, không dùng claim lịch sử làm chứng cứ triển khai hiện tại.

Lệnh test đã chạy:

```bash
APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/pytest tests/test_packaging tests/test_runtime_env_names.py tests/test_gpu/test_install_scripts.py tests/test_orchestration/test_runtime_migrations.py -q
```

Kết quả: **142 passed, 5 failed, 4 errors in 11.07s**, exit 1; không có skip. Không sửa test/config/source để che lỗi. Chưa phải full suite hoặc kiểm chứng deploy.

| Nhóm chưa đạt | Kết quả và giới hạn |
| --- | --- |
| `test_committed_examples_are_exactly_what_the_source_renders` | FAIL: `api.env.example` khác kết quả render từ nguồn, gồm comment/nhóm cấu hình; chạy lại đúng test vẫn FAIL, 0.11s |
| `test_colmap_binary_bundle_already_extracted_is_recognised_without_download`, `test_extracted_colmap_tree_from_the_image_only_gets_a_wrapper` | 2 FAIL ở bước tải `COLMAP-LICENSE.txt`; không suy lỗi logic nhận diện binary từ lỗi tải này, chưa kiểm lại ngoài sandbox |
| `test_v11_database_adds_scene_head_tables_without_losing_release_rows`, `test_v12_database_adds_nullable_job_owner_without_backfill` | 2 FAIL: assert cứng `LATEST_SCHEMA_VERSION == 23`, source hiện trả 26 |
| PostgreSQL variants của fresh DB/newer schema/upload locks/project-job lifecycle | 4 ERROR trong fixture kết nối `127.0.0.1:5432`, `psycopg.OperationalError`; chưa chạy được assertion các case này |

| Kiểm tra khác | Kết quả thực tế |
| --- | --- |
| `make -f Makefile.studio help` | PASS; chỉ xem danh sách target |
| `bash -n` sáu shell script setup/stack/install/doctor/entrypoint/loader | PASS |
| `docker compose ... config --services` với env mẫu tạm, `-f` tường minh và pin COLMAP | PASS: CPU 4 service, GPU 6 service; không build/start container |
| CLI help của data_package (root/pack/unpack), deploy_env (check/render), demo.release, cloud.package_publish, studio.scene_head, cloud.runpod_controller, jobs.worker_cli | PASS ở đúng module/argument path; không thực thi subcommand tác động dữ liệu |
| `APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m scripts.check_foundation` | PASS: 5 kiểm tra fixture/bytes/checksum/lineage/negative/document projection |
| Cấu trúc Markdown | PASS: 44 đề mục không trùng, hierarchy đúng, 15 cặp fence cân bằng |
| Liên kết và command block | PASS: 31 link tồn tại; 15 block Bash qua `bash -n` |
| Lặp đoạn văn dài nguyên văn | 0 đoạn trên 120 ký tự trong OPERATIONS; 0 đoạn giống hệt trong PRD/ARCHITECTURE/PIPELINE/CONTRACTS/UX; bổ sung cho rà trách nhiệm nội dung |
| `git diff --check` và whitespace file mới | PASS |
| Bảo toàn snapshot ngoài báo cáo | PASS: 2.109 file đã có giữ nguyên; chỉ thêm OPERATIONS và append báo cáo trong phạm vi lượt 6 |

Không chạy cài dependency, build/start/restart service, export/restore data thật, migration DB vận hành, publish object, cấp GPU hoặc Isaac. Không xóa tài liệu, commit/push/đổi branch. Các thay đổi và file đã thiếu từ đầu lượt được giữ nguyên; không nhận là thao tác của lượt này.

Lượt tiếp theo theo kế hoạch là EVALUATION; chưa bắt đầu trong lượt 6.

## 17. Kết quả lượt 7 — EVALUATION

### 17.1 Phạm vi và kết quả

Tạo `docs/EVALUATION.md`, 322 dòng, 30 đề mục, khoảng 60 liên kết cục bộ. Tài liệu tách bốn việc thường bị gọi chung là đánh giá: tự kiểm trong Studio, so với dữ liệu đối chứng (`eval/`), bảng giá trị theo scene (`value/`, trang `/benchmark`) và kiểm định sản phẩm (dẫn sang CONTRACTS). Mỗi phép đo có: đo gì, cần dữ liệu gì, lệnh chạy, đầu ra và giới hạn diễn giải. Mục tiêu, mã SM/AC và danh sách cần khóa trước lần chạy cuối dẫn sang PRD; định nghĩa lớp dữ liệu và model báo cáo dẫn sang CONTRACTS.

Lượt 6 kết thúc ở HEAD `ae6d0beb`; lượt 7 đối chiếu trên `develop`, HEAD `4fb0f8f9` (các commit chen giữa thuộc phần auth, không đổi code đánh giá). Lượt này do Claude Code tiếp nối từ phiên Codex.

### 17.2 Những điểm đã đối chiếu theo code

- Repo chưa có bộ dữ liệu nghiệm thu đã khóa, chưa có code tạo `EvaluationReport`, chưa có `path_validation`/`object_coverage`; SIM-08 còn TODO. `create_benchmark_split.py`, `validate_dataset.py` là file giữ chỗ.
- Ảnh giữ lại đang dùng là 1/8 ảnh của chính video job (`eval_split_every: 8`), không phải split `evaluation_only` của dataset; DATASET_PLAYBOOK mục 19 chưa được thực hiện.
- Không có ngưỡng nào ở trạng thái khóa. `evaluation_reference_v1.json` ghi rõ chỉ là khoảng tham chiếu. `BENCHMARK_REPORT.md` có ngưỡng tự đặt không có trong protocol/code; tài liệu mới ghi rõ không dùng làm tiêu chí.
- Gói LiDAR demo dựng từ `traj_gt.txt`; job dùng gói này mang cờ có hỗ trợ đáp án, số pose/tỉ lệ không độc lập. Quy tắc "runtime không đọc traj_gt" và "không nhận LiDAR thô" trong DATASET_PLAYBOOK/CONTEXT đã lỗi thời theo ADR 0009.
- Bản ghi `ReferenceBenchmark` của từng job lưu lớp `derived` nên Studio đọc được; ghi lại như quyết định cần giữ có chủ ý, không sửa code.
- Lệch giữa protocol và code: `BENCHMARKS.md` hàng `metric_scale` hứa sai số A/B chưa có evaluator; `collision_path_clearance.md` nhắc số bị chặn ở 0.10/0.15 m mà `path_clearance.py` chưa tính; `metric_click_error` không ghi bản ghi theo job; README trong `eval/geometry`, `eval/path`, `eval/pose`, `eval/protocols` còn ghi "placeholder" dù đã có code.
- PRD mục 10.1 yêu cầu cảnh trong nhà thực và case có kiểm soát; mọi kết quả hiện có là TorWIC. Cần chủ dự án chốt bộ cảnh.

### 17.3 Nguồn và kiểm tra

Đã dùng Graphify định hướng, CodeGraph/đọc source cho `eval/`, `eval/protocols/`, `eval/results/`, `src/services/orchestration/value/`, `src/services/orchestration/evaluation/`, `src/api/studio/value.py`, `scripts/torwic/`, `scripts/demo/`, `scripts/benchmark/`, contract `artifacts.py`/`validation.py`/`release.py`/`reconstruction.py`; đối chiếu DATASET_PLAYBOOK, CONTEXT (phần dữ liệu), TEAM_EXECUTION_CONTRACT chương 5 và plan evaluation-system.

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| 14 file pytest của evaluator, bảng giá trị và contract (lệnh ở EVALUATION mục 8) | PASS: 210 passed in 7.52s |
| 5 file vitest benchmark/value/evaluation | PASS: 39 tests |
| `scripts.check_foundation` | PASS 5/5 |
| Cấu trúc Markdown, liên kết cục bộ, fence | PASS: 30 đề mục không trùng, hierarchy đúng, mọi link tồn tại |
| Block Bash qua `bash -n` | PASS 8/8 |
| Đoạn dài giống hệt trong PRD/ARCHITECTURE/PIPELINE/CONTRACTS/UX/OPERATIONS | 0 |
| `git diff --check` | PASS |

Không chạy evaluator trên dữ liệu thật, không cần GPU/dataset trong lượt này. Không sửa code/test/config, không xóa tài liệu, không commit. Các test chỉ kiểm logic trên dữ liệu giả.

Lượt tiếp theo theo kế hoạch là STATUS; chưa bắt đầu trong lượt 7.

## 18. Kết quả lượt 8–10 — STATUS, README, dọn tài liệu cũ

### 18.1 STATUS

Tạo `docs/STATUS.md`: bốn mức bằng chứng (Code / Local / Production / Nghiệm thu), bảng hệ thống đang chạy, bảng năng lực theo luồng sản phẩm, chất lượng code, việc kế tiếp. Chưa năng lực nào ở mức Nghiệm thu. Đã kiểm trực tiếp ngày 20/10: API production `/health`, `/ready` trả 200; Studio production có nút dùng thử trong bundle trang đăng nhập. Isaac validation/release chưa từng chạy (DB local 0 validation, 0 release). Lần chạy job GPU đầy đủ trên RunPod chưa có job id/log trong repo; chỉ có ghi chép vận hành ngoài repo. CI tổ chức không chạy vì khóa thanh toán. WORKLOG/JOURNAL dừng ở 30/09.

### 18.2 README và bản đồ tài liệu

- `README.md` viết lại còn: sản phẩm là gì, dùng thử, Studio làm được gì, công nghệ, chạy nhanh bằng Docker, kiểm tra khi sửa code, bảng tài liệu. Chi tiết native/GPU/khôi phục chuyển hẳn sang OPERATIONS. Repo chưa có danh sách thành viên chính thức nên chưa thêm mục nhóm theo checklist sổ tay.
- `docs/README.md` viết lại: 11 tài liệu chính (cộng sơ đồ kiến trúc cho hồ sơ nộp bài), bảng hồ sơ và quy định giữ riêng, quy tắc cập nhật.
- `docs/architecture_diagram.md` thay sơ đồ mẫu LangGraph bằng sơ đồ triển khai thật; giữ file vì checklist sổ tay yêu cầu đường dẫn này.
- `ARCHITECTURE.md` mục 10.3: API production là máy ảo Google Cloud Seoul từ 20/10, không còn Railway.

### 18.3 Dọn tài liệu cũ

| Xử lý | File | Nội dung độc nhất đã chuyển |
| --- | --- | --- |
| Chuyển vào `docs/archived/` | `STUDIO_UX_SPEC.md`, `DATASET_PLAYBOOK.md` | Code và hồ sơ còn trích mã D-xx/quy tắc theo tên file; tên file giữ nguyên nên vẫn tra được |
| Xóa | `docs/BRIEF.md`, `docs/CONTEXT.md`, `docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md`, `docs/WIREFRAME_AND_UI_FLOW.md`, `docs/TRACKS.md`, `docs/RUNPOD_GUIDE.md` | Đã có trong PRD/ARCHITECTURE/PIPELINE/UX/OPERATIONS/EVALUATION |
| Xóa | `docs/DEMO_SCENES.md` | Gộp vào OPERATIONS mục 9.4 |
| Xóa | `frontend/README.md` | Lệnh `npm run dev`, proxy `REAL2SIM_API_URL`, lưu ý `next typegen` gộp vào OPERATIONS mục 4.3 |
| Xóa | `docs/runpod/README-runpod.md`, `docs/runpod/README-team.md` | Đã có trong sổ tay `studio-distribution.md`; README-runpod chứa mật khẩu seed dạng rõ |
| Xóa | `eval/{geometry,path,pose,protocols}/README.md` | Chỉ ghi "placeholder", sai với code hiện tại |
| Giữ | `docs/WORKFLOW.md` (quy định agent, harness theo dõi), `docs/RAV01_MO_TA_DE_TAI.md` (đề bài gốc), `docs/AI_LOG_SETUP.md`, `docs/mentor-duty-report/` (hồ sơ nộp bài), `docs/decisions/`, `docs/plans/`, `docs/execution/` (bốn file được `check_foundation` kiểm), `docs/runpod/VERIFICATION.json`, `deploy/studio/*` (phần đóng gói do Codex phụ trách) | — |

Cập nhật liên kết sống: AGENTS.md (authority map), PRD mục 0.1, ARCHITECTURE mục 0, PIPELINE mục 0, UX mục 0, EVALUATION mục 9, `docs/execution/README.md`, `eval/protocols/BENCHMARKS.md`, `scripts/gpu/README.md`, `THIRD_PARTY_NOTICES.md`, chú thích trong `showcase/registry.tsx`. Không sửa hồ sơ lịch sử (`.ai/tasks`, `docs/plans`, `docs/execution/*`, `docs/decisions`, WORKLOG, JOURNAL) nên các liên kết cũ trong đó trỏ tới file đã xóa; lịch sử Git vẫn giữ nội dung. Không sửa sổ tay `docs/guide/`.

### 18.4 Kiểm tra

Liên kết cục bộ, đề mục trùng, fence trên 17 file đã sửa: PASS. `scripts.check_foundation`: PASS 5/5. Frontend `tsc --noEmit` và eslint cho `registry.tsx` (chỉ đổi chú thích): sạch. `git diff --check`: PASS. Không chạy lại full suite vì chỉ đổi tài liệu và một dòng chú thích.

### 18.5 Bỏ hẳn hai tài liệu lưu trữ

Theo yêu cầu chủ dự án (20/10/2026, dự án không còn dùng TorWIC), xóa `docs/archived/STUDIO_UX_SPEC.md` và `docs/archived/DATASET_PLAYBOOK.md`. Bỏ phần trích dẫn hai file này trong khoảng 40 chú thích ở `src/`, `frontend/`, `tests/`, `scripts/`, `eval/` và `THIRD_PARTY_NOTICES.md`; nội dung giải thích giữ nguyên. EVALUATION mục 1.1 và 7, STATUS ghi rõ TorWIC chỉ còn là lịch sử. Hồ sơ lịch sử không sửa. Kiểm tra: py_compile, ruff check/format, 24 pytest (thùng rác, đánh giá), typecheck và eslint frontend, 10 vitest, Foundation 5/5 đều đạt.
