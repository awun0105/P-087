# Worklog — Team P-087 (Real2Sim Studio)

> Ghi lại tất cả công việc đã làm theo ngày. Ai làm gì, kết quả gì.

---

## 2026-09-17

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | Nâng cấp backend scaffold sang cấu hình LLM đa provider, tách factory và bổ sung kiểm thử cấu hình. | ✅ Done | [Cấu hình](src/config.py), [LLM factory](src/llm/factory.py), [tests](tests/test_llm_factory.py); commit `18418c5`. Đây là scaffold, chưa phải pipeline Real2Sim. | Chưa ghi nhận |

**Tổng kết ngày:** Hoàn thiện phần nền backend hiện có mà không nhận là đã triển khai workflow Real2Sim.

---

## 2026-09-20

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | Khóa hướng sản phẩm Warehouse/Indoor AMR và đồng bộ bộ tài liệu mô tả, PRD, wireframe cho Real2Sim Studio. | ✅ Done | [BRIEF](docs/BRIEF.md), [PRD](docs/PRD.md), [wireframe/UI flow](docs/WIREFRAME_AND_UI_FLOW.md); commit `615f629`. | Chưa ghi nhận |
| Lâm Quang Anh Quân | Sửa Codex AI-log hook để xử lý đúng định dạng output và cải thiện khả năng lưu vết phiên làm việc. | ✅ Done | [Log hook](scripts/log_hook.py); commit `7562766`. Không đánh đồng hook chạy được với xác nhận server đã nhận mọi log. | Chưa ghi nhận |

**Tổng kết ngày:** Có baseline tài liệu sản phẩm và cải thiện khả năng lưu vết hoạt động của coding agent.

---

## 2026-09-21

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | Nghiên cứu TorWIC-SLAM để chọn và mô tả dữ liệu bring-up cho warehouse/indoor AMR. | ✅ Done | Phân tích dataset được đưa vào [Dataset Playbook](docs/DATASET_PLAYBOOK.md); commit nghiên cứu ban đầu `de496b5`. | Chưa ghi nhận |

**Tổng kết ngày:** Tạo cơ sở dữ liệu cho quyết định traversal và quy trình chuẩn bị/evaluation; chưa phải kết quả reconstruction.

---

## 2026-09-22

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | Đồng bộ tài liệu product, dataset và execution cho bốn track; tách source of truth, handoff, task ID và milestone. | ✅ Done | [Dataset Playbook](docs/DATASET_PLAYBOOK.md), [Contract](docs/execution/TEAM_EXECUTION_CONTRACT.md), [Plan](docs/execution/TEAM_EXECUTION_PLAN.md), [Track Guide](docs/execution/TRACK_IMPLEMENTATION_GUIDE.md); commits `fc6b3b7`, `d0300f2`, `92475ff`. | Chưa ghi nhận |
| Lâm Quang Anh Quân | Củng cố context và luồng ghi AI-log giữa các phiên/agent. | ✅ Done | [CONTEXT.md](CONTEXT.md) và scripts ghi log; commits `bc0dc87`, `c2e3f65`, `dbb284d`. | Chưa ghi nhận |

**Tổng kết ngày:** Các tài liệu quy định scope, ownership và dữ liệu trao đổi giữa track được đưa về cùng hệ thống tham chiếu; implementation thật vẫn thuộc các milestone sau.

---

## 2026-09-23

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | Xây dựng Foundation M0 để bốn track có thể phát triển từ shared contracts: models, artifact store, fixtures, contract/integration tests, checker và agent harness/task files. | ✅ Done | [Shared contracts](src/models/contracts/), [fixtures](fixtures/), [Foundation checker](scripts/check_foundation.py), [execution tracks](docs/execution/tracks/); commit `49f2456`. Đây là synthetic handoff proof, không phải GPU/Isaac/3DGS acceptance. | Chưa ghi nhận |
| Lâm Quang Anh Quân | Chuẩn hóa Python/runtime dependency và cách setup phát triển. | ✅ Done | [Runtime policy](docs/execution/RUNTIME_POLICY.md), [setup script](scripts/setup.sh), lockfiles; commits `ea753bb`, `4080d5d`. | Chưa ghi nhận |
| Lâm Quang Anh Quân | Đồng bộ kiến trúc và yêu cầu Web Studio: 3DGS thật là view P0, các view geometry/point cloud/collider có thể chuyển riêng; bổ sung graphics references cho EX-PRODUCT và tài liệu báo cáo mentor. | ✅ Done | [ARCHITECTURE](ARCHITECTURE.md), [PRODUCT-06](docs/execution/tracks/ex_product/tasks/PRODUCT-06.md), [PRD](docs/PRD.md), [mentor report](docs/mentor-duty-report/buoi-2/script/script-buoi-2.md); commit `a16425d`. | Chưa ghi nhận |
| Lâm Quang Anh Quân | Rà lại entrypoints onboarding để không drift với Foundation và các authority docs. | 🔄 WIP | [README](README.md), [AGENTS](AGENTS.md), [CONTEXT](CONTEXT.md) đã sửa và kiểm tra cục bộ; thay đổi hiện ở working tree, chưa commit. | Chưa ghi nhận |

**Tổng kết ngày:** Foundation có contract/fixture proof cho phát triển song song. Chưa có bằng chứng chạy thật reconstruction, browser 3DGS hay Isaac; nhóm onboarding còn chờ commit/review.

---

<!-- Khung trống 24/09–20/10/2026. Chỉ thay placeholder khi có công việc và evidence thực tế; không tự nâng fixture proof thành runtime acceptance. -->

## 2026-09-24

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
Lê Mạnh Cường	Rà soát toàn bộ tài liệu EX-PRODUCT và hiện trạng code, lập checklist công việc theo milestone M1–M6.	✅ Done	Kế hoạch EX-PRODUCT M1–M6, Track EX-PRODUCT, 13 task PRODUCT-01..12/07A. Hiện trạng ghi nhận: 13/13 task còn Status: TODO, chưa có frontend/.	Chưa ghi nhận
Lê Mạnh Cường	PRODUCT-01 — API mock-first cho project/job/artifact, kèm source-rights attestation và privacy gate: 8 endpoint dưới /api/v1, registry nạp từ fixture, lọc artifact theo data_class.	✅ Done	routes_product.py, schemas.py, registry.py, privacy.py, models.py, errors.py, routes.py, 3 file test. check_foundation → READY. Evidence PRODUCT-01 §12.	Chưa ghi nhận
Lê Mạnh Cường	PRODUCT-02 — Job state machine và persistence: bảng chuyển QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED là hàm thuần, mỗi lần chuyển publish một JobManifest revision bất biến, retry là cạnh duy nhất ra khỏi FAILED, SUCCEEDED bị chặn khi artifact chưa resolve được. Thêm endpoint transitions/retry/attempts.	✅ Done	transitions.py, service.py, store.py, models.py, errors.py, test_job_transitions.py, test_job_lifecycle.py. Evidence PRODUCT-02 §12.	Chưa ghi nhận
Lê Mạnh Cường	PRODUCT-05 — Web shell: dựng frontend/ từ đầu (Next.js 16 + React 19 + Tailwind 4), 8 route project/job/viewer/validation/review, typed API client, mirror TypeScript của shared contract. Proxy /api/v1/* bằng rewrites thay vì bật CORS, vì main.py và config.py ngoài ownership.	🔄 WIP	frontend/, shell.tsx, states.tsx, client.ts, endpoints.ts, api.ts, next.config.ts. npm run build → exit 0 (8 route); npm test → 54 passed; typecheck + lint sạch. Evidence PRODUCT-05 §12. Chưa chạy browser smoke nên chưa đóng task.	Chưa ghi nhận
Lê Mạnh Cường	PRODUCT-06 — Scene viewer: backend seed revision từ fixture, áp transform edit thành revision mới có optimistic concurrency (409 khi revision đã cũ), endpoint đọc bytes artifact chỉ với URI nằm trong allow-list của job; frontend viewer 3 view Geometry/Point Cloud/Collider, ẩn/hiện layer, sửa transform.	🔄 WIP	scene/, editor.py, layers.ts, ply.ts, SceneCanvas.tsx, ViewerPanel.tsx, test_scene_editor.py, test_scene_routes.py. Evidence PRODUCT-06 §12. Cờ brush_compatibility_proof=false đi kèm payload để fixture không bị đọc thành AC-11; render 3DGS thật là mốc M3, chờ REC-04.	Chưa ghi nhận
Tổng kết ngày: Chốt thứ tự thực hiện EX-PRODUCT theo milestone và đưa track từ 13/13 task TODO lên 2 task Done + 3 task In progress: PRODUCT-01 (API mock-first + privacy gate), PRODUCT-02 (state machine + persistence), PRODUCT-05/06 (web shell + scene viewer). Kiểm chứng trong ngày: pytest tests/ → 288 passed, ruff check/format sạch, npm test → 54 passed, npm run build → exit 0 (8 route). Đây là fixture/API/unit proof: API trả đúng shared contract, privacy gate chặn dispatch khi chưa VERIFIED_ANONYMIZED, evaluation_only không lọt ra product endpoint, job không ghi được SUCCEEDED khi artifact chưa resolve. Chưa có bằng chứng browser, chưa có worker thật, chưa có 3DGS thật — nên M1 (28/09) vẫn chưa xong dù code đã có; việc còn lại là browser smoke, metric baseline tuần 1 và evidence bundle, kế hoạch từng ngày ghi ở PLAN.md §3. Blocker cũ vẫn còn: cần worker command interface và artifact paths từ EX-REC/SCENE/SIM trước PRODUCT-03/08; REC-04 chưa publish real Brush VisualArtifact nên AC-11 chưa thể chứng minh. Blocker môi trường: checkout Windows với core.autocrlf=true phá checksum fixture — đã sửa cục bộ, repo vẫn chưa có .gitattributes.

---

## 2026-09-25

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | REC-01, REC-02 & REC-02A — Chuẩn hóa dataset TorWIC, kiểm định chất lượng RGB, privacy gate và trích xuất khung hình tự động qua FFmpeg. | ✅ Done | [Canonical dataset](scripts/torwic/canonical_dataset.py), [RGB quality & privacy](src/services/reconstruction/rgb/privacy.py), [Frame extraction](src/services/reconstruction/rgb/frame_extraction.py), [tests](tests/test_reconstruction/test_rec02_quality.py); commits `adb3c81`, `65c2ad6`, `8a768bc`, `646c4e1`. | Chưa ghi nhận |
| Lâm Quang Anh Quân | REC-03 — Triển khai adapter COLMAP SfM, trích xuất camera poses, model reconstruction và chạy kiểm định GPU/CPU smoke thực tế. | ✅ Done | [COLMAP adapter](src/services/reconstruction/adapters/colmap.py), [Camera pose model](src/services/reconstruction/rgb/camera_pose.py), [Smoke runner](tests/test_reconstruction/rec03_smoke.py), [Task doc](docs/execution/tracks/ex_rec/tasks/REC-03.md); commits `72a0ae4`, `e11f653`. Evidence: 65/65 frames registered, 6.202 điểm thưa, 199/199 tests pass. | Chưa ghi nhận |
| Lâm Quang Anh Quân | Đồng bộ toàn diện kiến trúc Web 3D (PlayCanvas Engine + supersplat-viewer), 10 tài liệu audit tái sử dụng và thứ tự xác nhận metric scale lên develop. | ✅ Done | 10 tài liệu trong [audits](docs/execution/audits/), [PRD](docs/PRD.md), [ARCHITECTURE](ARCHITECTURE.md), [INTEGRATION_PLAYBOOK](docs/execution/INTEGRATION_PLAYBOOK.md), [Pitch deck](presentation/pitch_deck.pptx); commits `dc2b8c1`, `dffcde7`, `e9874ba`, `1002305`. | Chưa ghi nhận |

**Tổng kết ngày:** Hoàn thành toàn bộ luồng tiền xử lý dữ liệu và SfM camera poses (REC-01 đến REC-03), kiểm chứng smoke chạy thật trên 65 frame của TorWIC Aisle_CW (6.202 điểm, ratio 1.0). Đồng thời củng cố toàn bộ kiến trúc PlayCanvas và bộ audit 9 repositories lên develop, giải quyết triệt để rủi ro xung đột scale và viewer.

---

## 2026-09-26

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Lâm Quang Anh Quân | REC-04 — Triển khai Brush 3DGS adapter, tích hợp splat-transform SOG packaging, GPU smoke thực tế và render preview kiểm chứng. | ✅ Done | [Brush adapters](src/services/reconstruction/adapters/brush.py), [Splat bridge](src/services/reconstruction/adapters/splat_bridge.mjs), [Visual publication](src/services/reconstruction/rgb/visual_publication.py), [Tests](tests/test_reconstruction/test_rec04_brush.py), [Smoke & Preview runners](tests/test_reconstruction/rec04_smoke.py), [Task doc](docs/execution/tracks/ex_rec/tasks/REC-04.md); commits `d0dc89a`, `2c19b57`, `77c7e4d`. Evidence: GPU smoke Intel UHD 630 (Vulkan) tạo 6.202 Gaussians + SOG trong 23.15s, xuất `preview.webp`, 27/27 tests REC-04 pass, 226/226 toàn bộ suite pass, ruff clean. | Chưa ghi nhận |
| Lâm Quang Anh Quân | REC-05 — Khởi động task Voxel Geometry & Collision Mesh, lập kế hoạch bootstrap 10 bước và khóa điều kiện tiên quyết metric scale. | 🔄 WIP | [Task doc](docs/execution/tracks/ex_rec/tasks/REC-05.md), [Track plan](docs/plans/active/2026-09-24-ex-rec-track.md); commit `2889af8`. Kế hoạch tái sử dụng GPU voxelization của `splat-transform` và OpenMVS fallback; xác định rõ dependency cần anchor mét từ REC-06 trước khi chạy spike thực tế trên Aisle_CW. | Chưa ghi nhận |

**Tổng kết ngày:** Hoàn thành xuất sắc cổng task REC-04 (Visual Reconstruction), có đầy đủ bằng chứng chạy thật trên GPU (Brush 3DGS $\rightarrow$ nén SOG $\rightarrow$ render preview). Kích hoạt REC-05 sang trạng thái IN_PROGRESS với kế hoạch thực thi chi tiết, sẵn sàng viết code voxel collision adapter.

---

## 2026-09-27

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-09-28

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-09-29

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-09-30

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-01

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-02

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-03

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-04

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-05

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-06

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-07

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-08

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-09

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-10

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-11

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-12

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-13

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-14

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-15

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-16

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-17

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-18

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-19

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

## 2026-10-20

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| [Thành viên] | [Nhóm công việc lớn] | [Chưa cập nhật] | [Link/kết quả có bằng chứng] | [Giờ thực tế] |

**Tổng kết ngày:** [Kết quả chính / blocker nếu có]

---

<!-- Sau 20/10, sao chép block ngày + bảng trên khi cần. -->
