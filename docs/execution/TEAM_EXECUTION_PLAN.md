# TEAM EXECUTION PLAN

## Real2Sim Studio — 4-Person Delivery Plan

**Document Role:** Timeline, ownership, milestones và acceptance execution plan.
**Scope:** Phân công bốn track, integration gates, feature freeze, acceptance day và pitch readiness trong cửa sổ MVP.
**Upstream Constraints:** Tuân [PRD](../PRD.md), [DATASET_PLAYBOOK](../DATASET_PLAYBOOK.md) và normative [TEAM_EXECUTION_CONTRACT](./TEAM_EXECUTION_CONTRACT.md); không định nghĩa schema cạnh tranh.
**Status:** Foundation Baseline v1.0 — ownership and M0 gate approved.
**Related Documents:** [BRIEF](../BRIEF.md), [WIREFRAME](../WIREFRAME_AND_UI_FLOW.md), [INTEGRATION_PLAYBOOK](./INTEGRATION_PLAYBOOK.md), [TRACK_IMPLEMENTATION_GUIDE](./TRACK_IMPLEMENTATION_GUIDE.md).

**Project window:** 22/09/2026 → 19/10/2026
**Feature freeze:** 12/10/2026
**Integration buffer:** 13–14/10/2026
**Pitch preparation:** 15–19/10/2026
**Hard readiness deadline:** đêm 19/10/2026

---

# Glossary

| Thuật ngữ | Ý nghĩa | Ví dụ |
|---|---|---|
| **ST** | Stage — một bước xử lý trong product/runtime pipeline | `ST-CAMERA-POSE`, `ST-COLLIDER`, `ST-ISAAC-VALIDATE` |
| **DP** | Dataset Preparation — công việc chuẩn bị dataset offline | `DP-LIDAR-PREFUSION` |
| **EV** | Evaluation — bước benchmark/đánh giá | `EV-GEOMETRY`, `EV-POSE` |
| **INF** | Infrastructure — hạ tầng chung | `INF-JOB-ORCHESTRATION`, `INF-ARTIFACT-CONTRACT` |
| **FR** | Functional Requirement — yêu cầu chức năng trong PRD | `FR-04` (RGB Reconstruction) |
| **AC** | Acceptance Criteria — tiêu chí nghiệm thu | `AC-04` (LiDAR Evidence) |
| **P0** | Bắt buộc cho MVP hiện tại | |
| **P1** | Ưu tiên sau P0 | |
| **P2** | Mở rộng tương lai | |
| **EX-REC** | Execution track Reconstruction | |
| **EX-SCENE** | Execution track Scene/Object | |
| **EX-SIM** | Execution track Simulation/Evaluation | |
| **EX-PRODUCT** | Execution track Product/Web/Orchestration | |

---

# Chương 1. Vai trò của tài liệu

File này chỉ trả lời:

- ai phụ trách phần nào;
- phải hoàn thành khi nào;
- mốc integration nào bắt buộc;
- khi nào dừng phát triển feature;
- 5 ngày cuối chuẩn bị demo/pitch như thế nào.

File này **không định nghĩa schema, Git rule, testing rule hay cách code chi tiết**. Các nội dung đó nằm ở:

- [`TEAM_EXECUTION_CONTRACT.md`](./TEAM_EXECUTION_CONTRACT.md)
- [`TRACK_IMPLEMENTATION_GUIDE.md`](./TRACK_IMPLEMENTATION_GUIDE.md)

Scope sản phẩm vẫn lấy từ:

- [`BRIEF.md`](../BRIEF.md)
- [`PRD.md`](../PRD.md)
- [`DATASET_PLAYBOOK.md`](../DATASET_PLAYBOOK.md)
- [`INTEGRATION_PLAYBOOK.md`](./INTEGRATION_PLAYBOOK.md)

---

# Chương 2. Chia 4 execution tracks

| Track | Owner | Trách nhiệm chính |
|---|---|---|
| `EX-REC` | `@awun0105` | TorWIC preparation, RGB/LiDAR reconstruction |
| `EX-SCENE` | Đức | Object extraction, association, SceneObject, Scene IR |
| `EX-SIM` | Đạt | Collider, OpenUSD, Isaac Sim, evaluation |
| `EX-PRODUCT` | Cường | FastAPI, job orchestration, Web Studio, review/release |

Cross-project roles: Technical Lead / Integration Owner `@awun0105`; Product
Owner Cường; QA / Validation Lead Đạt; Release Approver Đức. GitHub handles của
Đức, Đạt và Cường còn `TBD`, không tự đoán trong CODEOWNERS.

Không dùng tên Track A/B/C/D vì [`DATASET_PLAYBOOK.md`](../DATASET_PLAYBOOK.md) đã dùng các tên đó cho protocol đánh giá.

Bốn track cùng làm **một hệ thống**, không phải bốn project độc lập.

---

# Chương 3. Timeline tổng thể

| Thời gian | Mục tiêu |
|---|---|
| 22–23/09 | Foundation Lock |
| 24–28/09 | 4 subsystem chạy độc lập |
| 29/09–05/10 | Hoàn thiện subsystem + Integration #1 |
| 06–09/10 | Real TorWIC E2E Alpha |
| 10–12/10 | Acceptance + stabilization |
| 12/10 | **FEATURE FREEZE** |
| 13–14/10 | Integration buffer + Demo RC |
| 15–19/10 | Slide + pitch + demo + rehearsal |
| Đêm 19/10 | Presentation-ready |

Nguyên tắc:

> Sau 12/10 không thêm feature mới.
> Sau 14/10 không thay architecture/backend.

---

# Chương 4. Foundation Lock — 22–23/09

Hai ngày này cả team làm chung trước khi tách track.

## 4.1 Việc phải khóa

- owner của 4 track;
- Technical Lead / Product Owner / Release Approver;
- repository structure;
- shared artifact contracts v0;
- fixture/mock artifacts;
- TorWIC P0 traversal: `Aisle_CW`; `Aisle_CCW` bổ sung/backup;
- TorWIC `raw / normalized / derived / evaluation_only`;
- runtime manifest cho GPU/tool versions `UNVERIFIED/TBD` tới khi provision;
- artifact storage;
- branch/integration strategy.

## 4.1.1 Locked Evaluation Set — chuẩn bị trong Foundation, khóa trước M1

- input/traversal IDs và checksums;
- train/held-out split checksum;
- target obstacle list;
- metric anchor và independent test distances;
- robot footprint;
- đúng 5 Start–Goal pairs và expected `CLEAR/BLOCKED` labels;
- independent geometry reference;
- Isaac Sim version, driver/CUDA/GPU;
- evaluation protocol ID;
- trạng thái từng metric: `MEASURE`, `BASELINE`, `PROPOSED_TARGET` hoặc `LOCKED_ACCEPTANCE_THRESHOLD`.

Foundation Lock xác định owner và nơi lưu các mục trên. Danh sách phải được khóa hoàn chỉnh chậm nhất tại Exit gate M1; không được thay threshold sau khi xem kết quả cuối.

## 4.2 Việc từng track chuẩn bị

**EX-REC**
- kiểm tra TorWIC;
- chọn bring-up traversal;
- dựng skeleton reconstruction worker.

**EX-SCENE**
- dựng Scene IR skeleton;
- tạo fixture `ReconstructionBundle`.

**EX-SIM**
- tạo runtime manifest với Isaac/GPU fields `UNVERIFIED/TBD`;
- tạo fixture `SceneIR`;
- chuẩn bị Minimal USD smoke test.

**EX-PRODUCT**
- dựng FastAPI/Next.js skeleton;
- mock job + mock artifact loading.

## 4.3 Exit gate M0 — 23/09

Chỉ chuyển sang coding độc lập khi:

- mọi người biết input/output của mình;
- fixture đã tồn tại;
- TorWIC bring-up scene đã chốt;
- canonical coordinate/transform và artifact store contract đã chốt;
- GPU environment có runtime-manifest placeholders, không block synthetic Foundation;
- không còn câu hỏi “track sau lấy dữ liệu của track trước bằng cách nào?”.

M0 dùng synthetic fixture/integration proof. Gate này không đồng nghĩa real
reconstruction, Brush compatibility, Isaac/GPU acceptance hoặc full E2E pass.

---

# Chương 5. Tuần 1 — 24–28/09: Subsystem Bring-up

Mục tiêu:

> Mỗi track chứng minh phần của mình chạy độc lập, chưa cần E2E thật.

## 5.1 EX-REC

Phải có:

```text
TorWIC RGB subset
→ camera pose
→ first visual reconstruction
→ first RGB geometry
```

và:

```text
registered/fused LiDAR
→ LiDARGeometryArtifact
```

Deliverables:

- first real `ReconstructionBundle`;
- visual/geometry evidence;
- LiDAR ingest evidence.

## 5.2 EX-SCENE

Phải có:

```text
fixture ReconstructionBundle
→ masks
→ candidate objects
→ SceneIR
```

Deliverables:

- SAM2/mask smoke;
- candidate object prototype;
- valid SceneIR fixture.

## 5.3 EX-SIM

Phải có:

```text
Minimal USD
→ Isaac Sim load
```

sau đó:

```text
floor + obstacle + robot
→ collision smoke
→ one CLEAR path
→ one BLOCKED path
```

## 5.4 EX-PRODUCT

Phải có:

```text
mock project
→ mock job
→ browser viewer
→ mock review
```

Viewer tối thiểu:

- orbit/pan/zoom;
- select;
- hide/show;
- basic transform edit.

## 5.4.1 Week-1 metric baseline

- chạy manual workflow baseline trên cùng một scene nhỏ;
- chạy tool-assisted baseline trên cùng scene và cùng người thực hiện khi khả thi;
- ghi Human Active Time, Manual Step Count và Time to Simulation-ready Scene;
- đo baseline kỹ thuật có thể chạy trong tuần 1;
- chưa khóa improvement target trước khi baseline tồn tại;
- ghi lại mọi chuyển đổi trạng thái metric.

## 5.5 Exit gate M1 — 28/09

Bốn subsystem đều phải demo độc lập.

Nếu Minimal USD chưa load được Isaac Sim, đây là blocker cấp project.

M1 không đạt nếu Locked Evaluation Set tại mục 4.1.1 chưa đủ và chưa có checksum/protocol ID cần thiết.

---

# Chương 6. Tuần 2 — 29/09–05/10: Build + Integration #1

Mục tiêu:

> Chuyển prototype thành subsystem đủ ổn để giao artifact thật.

## 6.1 EX-REC

Hoàn thiện:

- RGB validation;
- COLMAP;
- visual backend;
- RGB geometry;
- metric/canonical output;
- LiDAR evidence path;
- worker/container;
- contract tests.

Sau khi baseline chạy được, dừng thử thêm reconstruction repo nếu không có blocker.

## 6.2 EX-SCENE

Hoàn thiện:

- object extraction;
- multi-view association baseline;
- candidate states;
- Human Confirmation data operations;
- Scene Decomposition;
- Scene IR;
- worker/container.

## 6.3 EX-SIM

Hoàn thiện:

- collider;
- preflight;
- Candidate OpenUSD;
- Isaac validation;
- Start–Goal test;
- ValidationReport;
- evaluation harness.

## 6.4 EX-PRODUCT

Hoàn thiện:

- project/job API;
- async status;
- worker invocation abstraction;
- artifact access;
- real SceneIR viewer;
- browser renderer cho real 3DGS `VisualArtifact` của Primary RGB Scene;
- Geometry mesh, Point Cloud và Collider là các view kỹ thuật có thể chuyển/bật lớp, không phải fallback của 3DGS;
- layer toggle;
- transform editing;
- review shell.

## 6.5 Integration #1 — 04–05/10

Bắt buộc chứng minh:

```text
EX-REC real ReconstructionBundle
→ EX-SCENE đọc trực tiếp

EX-SCENE real SceneIR
→ EX-SIM đọc trực tiếp

EX-SIM real ValidationReport
→ EX-PRODUCT hiển thị trực tiếp
```

Không được sửa JSON/file bằng tay giữa các track.

## 6.6 Exit gate M2 — 05/10

- real REC→SCENE pass;
- real SCENE→SIM pass;
- real SIM→PRODUCT pass;
- contract tests pass.

---

# Chương 7. Tuần 3 — 06–12/10: E2E + Feature Freeze

Từ 06/10 không đổi backend/model chỉ vì có phương án “hay hơn”.

## 7.1 06–09/10 — E2E Alpha

Tách hai flow, không dùng một flow mơ hồ cho cả product và benchmark.

**Product E2E Acceptance:**

```text
MP4
→ Web/API upload
→ InputManifest
→ async orchestration
→ EX-REC
→ EX-SCENE
→ EX-SIM
→ Web review
→ approval/release
```

**Reconstruction Backend Benchmark:**

```text
locked PNG split
→ EX-REC backend
→ prediction artifacts
→ EvaluationRunner
```

Backend benchmark pass không đồng nghĩa Product E2E pass. Product E2E chỉ pass khi upload/API, async orchestration, artifact handoff, review và release đều chạy trên cùng candidate lineage.

Một **Primary Demo Scene** phải dùng chung xuyên suốt.

M3 — 09/10:

- real reconstruction;
- real SceneIR;
- real CandidatePackage;
- real Isaac validation;
- Web mở đúng scene đó;
- Web render real Brush 3DGS `VisualArtifact` cùng các view Geometry mesh/Point Cloud/Collider và canonical transforms; kỹ sư chuyển view được trong browser;
- review và release dùng đúng candidate lineage của job upload qua Web/API.

M3 browser proof phải dùng output thực tế từ EX-REC, có format/producer/version,
checksum và coordinate metadata của `VisualArtifact`. Synthetic fixture hoặc
point-cloud/mesh không thay proof 3DGS; nếu renderer chưa tương thích output
Brush, ghi blocker AC-11 và qualification gap, không đổi acceptance âm thầm.

## 7.2 10–12/10 — Acceptance & Stabilization

**EX-REC**
- khóa reconstruction artifacts;
- hoàn tất LiDAR Contribution Evidence;
- lưu runtime/metrics.

**EX-SCENE**
- fix object/SceneIR blockers;
- verify transform consistency;
- verify edit/delete behavior.

**EX-SIM**
- finalize collider;
- Isaac validation;
- locked Start–Goal tests;
- evaluation reports.

**EX-PRODUCT**
- error/retry;
- review/approve/reject;
- exact-candidate release;
- clean demo route.

## 7.2.1 Metric ownership

| Metric | Owner |
|---|---|
| PSNR/SSIM/LPIPS | `EX-SIM` evaluator |
| ATE/RPE | `EX-SIM` evaluator |
| Chamfer/P/R/F1 | `EX-SIM` evaluator |
| Training/reconstruction time | `EX-REC` |
| Registered-frame ratio | `EX-REC` |
| GPU-hours/peak VRAM | `EX-REC` + `EX-SIM` |
| Render performance/FPS | `EX-PRODUCT` |
| Candidate confirm/ignore/correct count | `EX-SCENE` + `EX-PRODUCT` |
| End-to-end runtime | `EX-PRODUCT` |
| Human Active Time/Manual Step Count | `EX-PRODUCT` + QA |
| Time to Simulation-ready Scene | `EX-PRODUCT` + QA |

Owner chịu trách nhiệm định nghĩa nguồn dữ liệu đo, ghi environment/config và publish evidence; không tự thay đổi metric semantics hoặc threshold của PRD.

## 7.3 M4 — Feature Freeze 12/10

M4 chỉ đạt khi:

- AC-08 trả kết quả cho đúng 5/5 locked Start–Goal pairs;
- SM-04 expected `CLEAR/BLOCKED` labels khớp 5/5; `ERROR` không được tính pass;
- AC-12 chạy được add obstacle → path thay đổi → delete obstacle → path được tính lại;
- approval/release authorization và audit tests pass;
- các metric Tier A đã được đo và báo cáo theo locked protocol; thiếu protocol/reference là blocker, không được thay bằng product validation hoặc silent omission.

Sau mốc này chỉ được:

- bug fix;
- stability fix;
- acceptance fix;
- evidence completion;
- low-risk performance fix.

Không được:

- thêm model/repo;
- redesign Scene IR;
- thay architecture;
- thêm P1/P2;
- đại refactor.

---

# Chương 8. 13–14/10: Integration Buffer

## 8.1 Ngày 13/10 — Acceptance Day

Chạy lại full P0 acceptance trên locked environment.

Bốn owner cùng tham gia.

Acceptance bắt buộc kiểm tra:

- AC-08: có kết quả cho 5/5 locked Start–Goal pairs;
- SM-04: expected labels khớp 5/5 và không có `ERROR` được tính pass;
- AC-12: add obstacle làm path validation phản ánh layout mới, sau delete path được tính lại trên revision mới;
- authorization: Editor không approve/reject, Reviewer decision bind đúng candidate/validation checksum;
- deterministic audit: mọi blocking rule applicable đều `PASS` trước `READY_FOR_REVIEW`;
- Product E2E và Reconstruction Backend Benchmark được báo cáo riêng.

Kết quả mỗi test:

```text
PASS
FAIL
WAIVED-SHOULD
```

Không waiver requirement MUST rồi vẫn claim MVP hoàn thành.

## 8.2 Ngày 14/10 — Demo Release Candidate

Khóa:

- code commit;
- environment versions;
- Primary Demo Scene;
- Scene IR;
- CandidatePackage;
- ValidationReport;
- evaluation results;
- screenshots;
- backup demo video.

Sau 14/10 không rebuild chỉ để “đẹp hơn” nếu không có blocker.

---

# Chương 9. 15–19/10: Pitch Sprint

## 9.1 15/10 — Story & Claims

Khóa narrative:

```text
Pain point
→ Current workflow bottleneck
→ Real2Sim Studio
→ Real input
→ Editable scene
→ Isaac validation
→ Human review
→ Measured result
→ Value
```

Mọi claim phải có evidence.

## 9.2 16/10 — Slides v1

Suggested deck:

1. Problem
2. Persona & pain point
3. Solution
4. Product workflow
5. Demo
6. Technical architecture
7. Dataset & evaluation
8. Results
9. Value / differentiation
10. Limitations / roadmap

## 9.3 17/10 — Demo choreography

Demo ưu tiên:

```text
open real warehouse scene
→ toggle Visual/Geometry/Collider
→ inspect object
→ edit/move obstacle
→ run validation
→ show CLEAR/BLOCKED result
→ review
→ approve/reject
```

Chuẩn bị:

- live route;
- precomputed route;
- backup video.

## 9.4 18/10 — Full rehearsal

Chạy full pitch ít nhất 3 lần.

## 9.5 19/10 — Final readiness

Chỉ:

- sửa slide nhỏ;
- kiểm tra demo;
- Q&A;
- backup;
- rehearsal.

---

# Chương 10. Pitch ownership

| Track | Pitch/Q&A ownership |
|---|---|
| `EX-REC` | TorWIC, reconstruction, geometry, LiDAR, reconstruction metrics |
| `EX-SCENE` | SAM2, object association, HITL, SceneObject, Scene IR |
| `EX-SIM` | Collider, OpenUSD, Isaac, collision/path, evaluation |
| `EX-PRODUCT` | Product story, Web workflow, review/release |

Speaker chính có thể là người nói tốt nhất, không bắt buộc Member 4.

Demo operator nên tách khỏi speaker nếu có thể.

---

# Chương 11. Milestone Summary

| ID | Deadline | Điều kiện |
|---|---|---|
| M0 | 23/09 | Foundation locked |
| M1 | 28/09 | 4 subsystem chạy độc lập + Locked Evaluation Set hoàn chỉnh |
| M2 | 05/10 | First real cross-track integration |
| M3 | 09/10 | Product E2E Alpha qua Web/API trên cùng candidate lineage |
| M4 | 12/10 | Feature complete + AC-08/SM-04/AC-12/authorization gates đạt |
| M5 | 14/10 | Demo Release Candidate |
| M6 | 19/10 | Pitch-ready |

Nếu trễ:

1. cắt P2;
2. cắt P1;
3. cắt polish;
4. dùng fallback đã được chấp nhận;
5. không âm thầm bỏ P0.

---

# Chương 12. Daily Team Sync

Mỗi người trả lời đúng 4 câu:

1. Artifact/output nào hôm qua đã chạy?
2. Artifact/output nào hôm nay phải tạo?
3. Blocker hiện tại là gì?
4. Có thay đổi interface/contract không?

Update phải gắn với output kiểm chứng được, không dùng báo cáo kiểu “đã code khá nhiều”.
