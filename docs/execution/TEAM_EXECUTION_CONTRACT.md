# TEAM EXECUTION CONTRACT

## Real2Sim Studio — Shared Engineering Contract

**Áp dụng cho:** `EX-REC`, `EX-SCENE`, `EX-SIM`, `EX-PRODUCT`
**Document Role:** Normative shared artifact, runtime, review và handoff contract.
**Scope:** Shared schema, producer/consumer boundary, coordinate, testing, review và change-control rules cho bốn execution tracks.
**Upstream Constraints:** Tuân product scope/acceptance trong [PRD](../PRD.md) và dataset/evaluation methodology trong [DATASET_PLAYBOOK](../DATASET_PLAYBOOK.md).
**Status:** Draft for Review.
**Related Documents:** [BRIEF](../BRIEF.md), [WIREFRAME](../WIREFRAME_AND_UI_FLOW.md), [INTEGRATION_PLAYBOOK](./INTEGRATION_PLAYBOOK.md), [TEAM_EXECUTION_PLAN](./TEAM_EXECUTION_PLAN.md), [TRACK_IMPLEMENTATION_GUIDE](./TRACK_IMPLEMENTATION_GUIDE.md).

---

# Chương 1. Vai trò và các invariant bắt buộc

File này chỉ định nghĩa **luật chung để 4 track ghép được với nhau**.

Đây là **normative source** cho artifact shape, trường bắt buộc/tùy chọn, schema version và producer/consumer. [`INTEGRATION_PLAYBOOK.md`](./INTEGRATION_PLAYBOOK.md) chỉ minh họa hoặc tham chiếu contract; nếu một schema minh họa khác file này thì contract hiện tại được áp dụng và phần minh họa phải được sửa lại.

Chi tiết từng track nằm ở [`TRACK_IMPLEMENTATION_GUIDE.md`](./TRACK_IMPLEMENTATION_GUIDE.md).
Timeline nằm ở [`TEAM_EXECUTION_PLAN.md`](./TEAM_EXECUTION_PLAN.md).

Thứ tự xử lý khi tài liệu có khác biệt:

1. [PRD](../PRD.md) — product scope, P0/P1/P2, MUST/SHOULD và acceptance;
2. [DATASET_PLAYBOOK](../DATASET_PLAYBOOK.md) — dataset preparation, leakage và evaluation protocol;
3. [TEAM_EXECUTION_CONTRACT](./TEAM_EXECUTION_CONTRACT.md) — shared artifact/schema/runtime contracts;
4. [INTEGRATION_PLAYBOOK](./INTEGRATION_PLAYBOOK.md) — technical baseline và tool choices;
5. [TRACK_IMPLEMENTATION_GUIDE](./TRACK_IMPLEMENTATION_GUIDE.md) — per-track implementation tasks;
6. [TEAM_EXECUTION_PLAN](./TEAM_EXECUTION_PLAN.md) — timeline và ownership;
7. [BRIEF](../BRIEF.md) — high-level communication, không override requirement chi tiết.

Thứ tự trên chỉ dùng để xác định authority theo loại quyết định. Mâu thuẫn thật sự vẫn phải được sửa trong tài liệu liên quan; coding agent không được âm thầm chọn một bên.

Các invariant bắt buộc:

1. **Artifact-first:** track giao tiếp bằng artifact contract, không import implementation nội bộ của nhau.
2. **Visual ≠ Geometry ≠ Physics.**
3. **Global Reconstruction ≠ Editable Scene.**
4. **Một canonical coordinate system + metric scale.**
5. **Human-in-the-loop trước approval/release.**
6. **Candidate phải validation trước review.**
7. **Approved candidate không được regenerate rồi vẫn gọi cùng release.**
8. **Product/runtime data tách khỏi evaluation-only data.**
9. **Heavy stage có process/container boundary.**
10. **RGB-only, RGB+LiDAR và future LiDAR-only dùng reusable branches, không copy-paste ba pipeline.**

---

# Chương 2. Architecture và ownership

## 2.1 Dependency direction

```text
InputManifest
    ↓
EX-REC
    ↓ ReconstructionBundle
EX-SCENE
    ↓ SceneIR
EX-SIM
    ↓ CandidatePackage + ValidationReport + EvaluationReport?
EX-PRODUCT
    ↓ Review / Release
```

`EX-PRODUCT` đồng thời orchestrate các workers.

`EvaluationReport?` chỉ bắt buộc cho locked MVP acceptance hoặc benchmark run theo ma trận tại mục 3.10; ordinary user-upload release không bị chặn khi không có ground truth độc lập.

## 2.2 Module ownership

| Module | Owner |
|---|---|
| Reconstruction + TorWIC product preparation | `EX-REC` |
| Object/Scene Core/Scene IR | `EX-SCENE` |
| Collider/OpenUSD/Isaac/Evaluation | `EX-SIM` |
| FastAPI/Web/Jobs/Review/Release | `EX-PRODUCT` |
| Shared contracts/fixtures | producer + consumer review |

Cross-module change phải có owner review.

---

# Chương 3. Shared artifact contracts

## 3.1 Quy tắc chung

Mọi artifact quan trọng phải truy vết được bằng:

```text
artifact_type
schema_version
artifact_uri
artifact_checksum
producer_stage
job_id / source provenance khi relevant
```

Không dùng filename hoặc local path làm identity.

Không hard-code:

```text
/home/user/...
C:\Users\...
```

## 3.2 Contract matrix

| Producer | Artifact | Consumer |
|---|---|---|
| Input layer | `InputManifest` | `EX-REC`, orchestrator |
| `EX-REC` privacy stage | `PrivacyValidationReport` | orchestrator, `EX-PRODUCT`, QA/Validation Lead |
| Orchestrator | `JobManifest` | tất cả stage |
| `EX-REC` | `ReconstructionBundle` | `EX-SCENE` |
| `EX-REC` | `LiDARGeometryArtifact` | mixed composition/evidence |
| `EX-SCENE` | `SceneIR` | `EX-SIM`, `EX-PRODUCT` |
| `EX-SIM` | physics-enriched `SceneIR` | `EX-PRODUCT` |
| `EX-SIM` preflight | `PreflightReport` | candidate builder, `EX-PRODUCT`, Reviewer |
| `EX-SIM` | `CandidatePackage` | validation/review |
| `EX-SIM` | `ValidationReport` | `EX-PRODUCT` |
| `EX-SIM` evaluator | `EvaluationReport` khi run type yêu cầu | `EX-PRODUCT`/reporting |
| `EX-PRODUCT` Reviewer flow | `ApprovalRecord` | release stage, audit |
| `EX-PRODUCT` | `ReleaseManifest` | final release |

## 3.3 `InputManifest`

Tối thiểu:

```text
schema_version
source_type: dataset | upload
received_at
files[]
    original_name
    media_type
    size_bytes
    checksum
    artifact_uri
input_configuration
    rgb_present
    registered_lidar_present
    declared_same_scene?
lidar_metadata?
    unit
    coordinate_frame
    registration_status
source_rights_attestation
dataset_manifest_checksum?
preparation_provenance?
input_manifest_checksum
```

## 3.3.1 `PrivacyValidationReport`

Tối thiểu:

```text
input_manifest_checksum
inspection_scope: sampled | all_selected_frames | approved_copy
selected_frame_count
inspected_frame_count
unresolved_findings[]
result: PRELIMINARY_SCREENED | VERIFIED_ANONYMIZED | QUARANTINED
report_checksum
```

`PRELIMINARY_SCREENED` chỉ là kết quả sàng lọc mẫu, không đủ để lưu trữ lâu dài, public hoặc demo. `VERIFIED_ANONYMIZED` yêu cầu đã kiểm tra toàn bộ selected frames hoặc dùng approved anonymized copy. `QUARANTINED` có unresolved PII và phải dừng pipeline.

Ownership:

- `EX-PRODUCT` thu source-rights attestation và hiển thị privacy state;
- `EX-REC` chạy `ST-PRIVACY-GATE` và phát hành `PrivacyValidationReport`;
- QA/Validation Lead chấp nhận trạng thái `VERIFIED_ANONYMIZED` trước public/demo use.

## 3.3.2 `JobManifest`

Tối thiểu:

```text
schema_version
job_id
project_id
scene_revision
input_manifest_checksum
config_checksum
software_versions
environment_versions
seed?
started_at
completed_at?
current_stage
stage_artifacts[]
    stage_id
    status
    artifact_type
    artifact_uri
    artifact_checksum
    started_at
    completed_at?
    error_ref?
job_manifest_checksum
```

Mỗi stage chỉ được đánh dấu `SUCCEEDED` khi toàn bộ artifact bắt buộc của stage đã có checksum và resolver đọc được. Retry phải append execution record hoặc tạo attempt mới; không được ghi đè provenance của attempt trước.

## 3.4 `ReconstructionBundle`

Tối thiểu:

```text
source/input identity
coordinate metadata
RGB frame refs
camera pose refs
visual artifact ref
RGB geometry ref
metric/scale status
provenance
```

`EX-SCENE` không được đọc private COLMAP/Brush/OpenMVS temp folders.

## 3.5 `LiDARGeometryArtifact`

Tối thiểu:

```text
artifact_uri
artifact_checksum
source_modality = registered_lidar
source_input_checksum
geometry_format
unit
coordinate_frame
preprocessing_provenance
```

Alignment result/transform phải được lưu riêng; không mutate artifact đã checksum.

## 3.6 `SceneIR`

Logical structure:

```text
Scene
├── coordinate_system
├── metric_scale
├── environment
└── objects[]
    └── SceneObject
        ├── id
        ├── state
        ├── origin: reconstructed | user_added
        ├── active
        ├── transform
        ├── visual_ref?
        ├── geometry_ref
        ├── asset_ref?
        └── collider?
            └── ColliderSpec
                ├── collider_id
                ├── collider_type: AABB | OBB | CONVEX_HULL | SIMPLIFIED_MESH
                ├── local_transform
                ├── dimensions?
                ├── geometry_ref?
                ├── parameters
                └── provenance
```

Một `SceneObject` chỉ có **một canonical transform**.

UI và simulator không được tạo transform truth riêng.

`user_added` object phải có `asset_ref` hoặc primitive geometry có kích thước rõ ràng. P0 không expose generic scale nếu chưa định nghĩa propagation sang Visual/Geometry/Collider; dùng primitive dimensions hoặc asset-specific size parameters.

## 3.7 Physics enrichment

`EX-SCENE` có thể handoff SceneIR khi `collider` chưa đầy đủ.

`EX-SIM` tạo collider rồi ghi ra **SceneIR revision cùng schema**, không tạo competing scene format.

## 3.7.1 `PreflightReport`

Tối thiểu:

```text
schema_version
scene_revision
scene_ir_checksum
ruleset_version
rules[]
    rule_id
    severity
    result: PASS | FAIL | ERROR
    affected_object_ids[]
    evidence_refs[]
    remediation
blocking_result: PASS | FAIL | ERROR
report_checksum
```

Ruleset P0 phải bao phủ metric scale, collider presence, transform validity, object bounds, robot spawn prerequisites, required artifacts, unresolved candidates và path-configuration completeness. Candidate build/review bị chặn khi `blocking_result` khác `PASS`.

Rule matrix tối thiểu:

| Rule ID | Stage | Blocking |
|---|---|---:|
| `METRIC_SCALE_MISSING` | Preflight | Có |
| `COLLIDER_MISSING` | Preflight | Có |
| `TRANSFORM_INVALID` | Preflight | Có |
| `OBJECT_OUT_OF_BOUNDS` | Preflight | Có |
| `REQUIRED_ARTIFACT_MISSING` | Preflight | Có |
| `CANDIDATE_UNREVIEWED` | Preflight | Có |
| `ROBOT_SPAWN_INVALID` | Isaac | Có |
| `PATH_BLOCKED_UNEXPECTED` | Isaac | Có |
| `PATH_VALIDATION_ERROR` | Isaac | Có |
| `ISAAC_LOAD_ERROR` | Isaac | Có |

Chỉ được chuyển sang `READY_FOR_REVIEW` khi tất cả blocking rules applicable cho run đều `PASS`. `ERROR` không được quy đổi thành `PASS` hoặc kết quả `CLEAR/BLOCKED`.

## 3.8 `CandidatePackage`

Candidate được build trước review và phải immutable trong validation/review cycle.

Bao gồm tối thiểu:

```text
CandidatePackage
├── candidate_manifest.json
├── entrypoint_usd
├── assets[]
├── geometry[]
├── colliders[]
└── candidate_checksum

candidate_manifest.json
├── schema_version
├── candidate_id
├── scene_revision
├── job_manifest_checksum
├── unit
├── up_axis
├── object_transforms[]
├── asset_refs[]
├── collider_refs[]
├── artifact_checksums[]
└── build_config_checksum
```

`candidate_checksum` là checksum của toàn bộ `CandidatePackage`, không chỉ của file USD entrypoint. `entrypoint_usd` là vai trò artifact; tên file vật lý không phải contract cho tới khi package naming được khóa.

Checksum được tính từ canonical package inventory/content sau khi package hoàn tất và được lưu ở artifact registry hoặc envelope bên ngoài payload được hash; không tạo checksum tự tham chiếu bên trong chính byte range dùng để tính hash.

## 3.9 `ValidationReport`

Tối thiểu:

```text
candidate_checksum
validator_version
result
report_checksum
```

Report phải gắn đúng candidate đã test.

## 3.10 `EvaluationReport`

Tối thiểu:

```text
subject_type: reconstruction | scene_revision | candidate_package
subject_id
subject_checksum
evaluation_protocol_id
split_manifest_checksum?
references_used[]
preprocessing_dependencies[]
metrics[]
report_checksum
```

Binding theo protocol:

- `EV-VISUAL`, `EV-POSE`, `EV-GEOMETRY` bind vào `reconstruction`;
- `EV-OBJECT` bind vào `scene_revision`;
- `EV-PATH` bind vào `candidate_package` đã validation, theo protocol đã khóa.

Ma trận bắt buộc:

| Run type | `ValidationReport` | `EvaluationReport` |
|---|---|---|
| Ordinary user upload/release | Bắt buộc | Optional/N/A nếu không có independent ground truth |
| Locked MVP acceptance | Bắt buộc | Bắt buộc |
| Reconstruction backend benchmark | Không bắt buộc nếu không tạo candidate | Bắt buộc |
| LiDAR Contribution Evidence | Theo downstream consumer đã chọn | Full benchmark optional; provenance evidence bắt buộc |

## 3.10.1 `ApprovalRecord`

Tối thiểu:

```text
schema_version
candidate_checksum
validation_report_checksum
reviewer_id
decision: APPROVE | REJECT
reason?
decided_at
accepted_warning_ids[]
record_checksum
```

`reason` bắt buộc khi `decision = REJECT`. Mỗi `accepted_warning_ids[]` phải trỏ tới warning cụ thể trong evidence/report, không được thay bằng một boolean tổng quát.

## 3.11 `ReleaseManifest`

Tối thiểu:

```text
schema_version
project_id
scene_version
input_manifest_checksum
job_manifest_checksum
candidate_checksum
preflight_report_checksum
validation_report_checksum
evaluation_report_checksum?
processing_config_checksum
software_versions
artifact_inventory[]
    artifact_type
    artifact_uri
    artifact_checksum
review_state: APPROVED
approval_record
    reviewer_id
    approved_at
    accepted_warning_ids[]
    record_checksum
release_timestamp
release_manifest_checksum
```

`candidate_checksum` tiếp tục mang nghĩa checksum của toàn bộ Candidate Package. `ReleaseManifest` chỉ được phát hành khi ApprovalRecord bind cùng candidate/validation checksum và mọi accepted warning đều truy được về evidence cụ thể.

---

# Chương 4. Coordinate, metric và revision rules

## 4.1 Canonical coordinate

Trước implementation chính thức phải khóa:

```text
CANONICAL_UNIT
CANONICAL_UP_AXIS
CANONICAL_HANDEDNESS
CANONICAL_WORLD_FRAME
```

Mọi conversion nằm ở adapter/boundary rõ ràng.

## 4.2 RGB metric scale

Dùng một locked real-world anchor.

Không dùng cùng anchor làm evaluation distance.

## 4.3 RGB+LiDAR

Chỉ gọi scene unified/metric-ready sau khi alignment/transform đã được xác nhận.

## 4.4 Revision invalidation

Nếu scene đã validation rồi bị sửa:

```text
old validation → invalid
new revision → DRAFT
→ new candidate
→ new validation
→ new review
```

Approval không được kế thừa.

---

# Chương 5. TorWIC data contract

## 5.1 Directory boundary

```text
data/torwic_slam/
├── raw/              # immutable
├── normalized/       # product-friendly
├── derived/          # regenerable
└── evaluation_only/  # evaluator only
```

Không sửa source gốc.

## 5.2 Raw LiDAR

Product MVP không nhận raw scan sequence.

TorWIC raw LiDAR phải qua offline:

```text
lidar/*.pcd
+ declared poses
→ DP-LIDAR-PREFUSION
→ registered_lidar.ply
```

Nếu dùng `traj_gt.txt`, provenance phải ghi rõ.

## 5.3 Product/runtime được đọc

- normalized RGB;
- derived demo video;
- registered/fused LiDAR;
- calibration metadata khi contract cho phép.

## 5.4 Evaluation-only

Không được feed vào prediction:

- `groundtruth_map.ply`;
- `traj_gt.txt` reference;
- manual object annotations;
- locked path references.

Evaluator chỉ đọc chúng sau khi prediction đã được xác định theo protocol.

---

# Chương 6. External repositories và runtime boundary

## 6.1 Integration rule

Pattern bắt buộc:

```text
project interface
→ project adapter
→ external CLI/library/runtime
```

Không để business code rải subprocess/import external repo khắp nơi.

## 6.2 Heavy environments

Recommended tách:

```text
reconstruction runtime
scene-intelligence runtime
simulation runtime
platform runtime
```

Không cần Kubernetes.

Docker/process isolation + shared artifact storage là đủ cho MVP.

## 6.3 Backend substitution

Có thể thay backend nếu vẫn giữ contract.

Ví dụ đổi visual backend không được buộc `EX-SCENE` hoặc Web sửa code nếu artifact contract không đổi.

## 6.4 License

External repository phải tuân license. Không copy source tùy tiện khi process boundary phù hợp hơn.

---

# Chương 7. Local, GPU và artifact storage

## 7.1 Local laptop

Dùng cho:

- code;
- unit test;
- schema/serialization;
- fixture;
- manifest/checksum;
- transform math;
- FastAPI/Next.js;
- mock workers;
- lightweight geometry.

## 7.2 GPU/cloud

Dùng cho:

- 3DGS;
- SAM2 heavy inference;
- heavy reconstruction;
- Isaac Sim;
- E2E/acceptance.

Owner của worker chịu trách nhiệm runtime/container của worker đó.

## 7.3 GPU priority

1. P0 blocker
2. cross-track integration blocker
3. E2E
4. acceptance
5. optimization
6. experiment

## 7.4 Artifact store

MVP có thể dùng shared persistent filesystem.

Bắt buộc:

- producer chỉ publish artifact sau khi hoàn tất;
- checksum sau khi finalize;
- consumer chỉ dùng published artifact refs;
- critical artifact không chỉ tồn tại trên laptop cá nhân.

---

# Chương 8. Testing contract

Tất cả track dùng cùng taxonomy:

| Level | Mục đích |
|---|---|
| L1 | Unit test |
| L2 | Contract test |
| L3 | Adapter/worker smoke test |
| L4 | Track integration |
| L5 | Cross-track integration |
| L6 | Full E2E |
| L7 | Acceptance / benchmark |

Một handoff chỉ hợp lệ khi:

1. producer output validate schema;
2. checksum tồn tại;
3. refs resolve;
4. consumer đọc trực tiếp;
5. không manual conversion;
6. coordinate/metric metadata đủ;
7. provenance đủ.

Fixtures phải dùng **cùng schema** với real artifact.

Sau Integration #1 nên khóa:

- golden `ReconstructionBundle`;
- golden `SceneIR`;
- golden `ValidationReport`.

---

# Chương 9. Job, error và review contract

## 9.1 Job states

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

## 9.2 Scene review states

```text
DRAFT
PROCESSING
CANDIDATE_READY
VALIDATING
READY_FOR_REVIEW
APPROVED
REJECTED
RELEASED
```

Không trộn hai state machine.

Các transition hợp lệ ở nhánh review:

```text
READY_FOR_REVIEW → APPROVED → RELEASED
READY_FOR_REVIEW → REJECTED → new DRAFT revision
```

`REJECTED` không được chuyển thẳng sang `RELEASED` và phải có rejection reason. Mọi edit sau validation, kể cả edit từ một revision bị reject, tạo revision `DRAFT` mới và làm mất hiệu lực Candidate/Validation/Evaluation reports cũ.

## 9.3 Error

Stage failure tối thiểu có:

```text
error_code
stage_id
human_message
retryable
```

Raw logs có thể lưu riêng.

## 9.4 Review

Automation không được tự `APPROVED`.

Release chỉ dùng exact candidate đã validation.

Permission matrix:

| Action | Editor | Reviewer |
|---|---:|---:|
| Create job | Có | Có |
| Edit scene | Có | Có, nhưng tạo revision mới |
| Submit review | Có | Có |
| Approve/reject | Không | Có |
| Release | Không trực tiếp | Chỉ sau approval hợp lệ |

Rules:

- Editor không được gọi approve/reject endpoint;
- rejection reason bắt buộc;
- review decision phải bind đúng `candidate_checksum` và `validation_report_checksum`;
- Reviewer edit scene phải tạo revision `DRAFT` mới và invalidates validation/approval cũ;
- edit event và review event là hai audit entries riêng, kể cả khi cùng một người giữ cả hai vai trò trong demo nội bộ.

---

# Chương 10. Git và change control

Recommended:

```text
main
develop
feature/ex-rec-*
feature/ex-scene-*
feature/ex-sim-*
feature/ex-product-*
```

- feature branch tạo từ `develop`;
- pull request của feature merge vào `develop`;
- `main` chỉ nhận merge từ `develop` khi chuẩn bị release;
- không push hoặc merge trực tiếp vào `main`.

Shared contract change phải có producer + consumer review.

Contract version:

- compatible optional addition → minor;
- breaking shape/meaning change → major.

Sau Integration #1 chỉ breaking-change khi có blocker.

Sau Feature Freeze không breaking-change.

Không giữ branch riêng nhiều ngày rồi merge một lần nếu có thể chia PR nhỏ.

---

# Chương 11. Handoff protocol

Mọi handoff:

```text
producer run
→ finalize artifact
→ checksum
→ manifest
→ schema validation
→ publish
→ consumer validation
→ consume
```

Không chấp nhận:

- rename file bằng tay;
- sửa JSON bằng tay;
- script ngoài repo;
- hidden local path.

Nếu deterministic conversion cần thiết, nó phải thành adapter/stage versioned trong repo.

---

# Chương 12. Foundation Lock checklist

Trước khi 4 track tách ra:

**People**
- [ ] 4 track owners
- [ ] Technical Lead
- [ ] Product Owner
- [ ] Release Approver

**Contracts**
- [ ] `InputManifest`
- [ ] `PrivacyValidationReport`
- [ ] `JobManifest`
- [ ] `ReconstructionBundle`
- [ ] `LiDARGeometryArtifact`
- [ ] `SceneIR`
- [ ] `PreflightReport`
- [ ] `CandidatePackage`
- [ ] `ValidationReport`
- [ ] `EvaluationReport`
- [ ] `ApprovalRecord`
- [ ] `ReleaseManifest`

**Coordinate**
- [ ] unit
- [ ] up axis
- [ ] handedness
- [ ] world frame

**TorWIC**
- [ ] bring-up traversal
- [ ] data folders
- [ ] benchmark split
- [ ] LiDAR prefusion rule
- [ ] metric anchor rule

**Locked Evaluation Set — phải hoàn tất trước Exit gate M1**
- [ ] input/traversal IDs + checksums
- [ ] train/held-out split checksum
- [ ] target obstacle list
- [ ] metric anchor + independent test distances
- [ ] robot footprint
- [ ] đúng 5 Start–Goal pairs
- [ ] expected `CLEAR/BLOCKED` label cho 5/5 pairs
- [ ] independent geometry reference
- [ ] Isaac Sim version + driver/CUDA/GPU
- [ ] evaluation protocol ID
- [ ] metric status: `MEASURE` / `BASELINE` / `PROPOSED_TARGET` / `LOCKED_ACCEPTANCE_THRESHOLD`

**Runtime**
- [ ] GPU machine
- [ ] CUDA/driver
- [ ] Isaac version
- [ ] artifact root

**Testing**
- [ ] fixtures
- [ ] contract test command
- [ ] GPU smoke path
- [ ] E2E evidence location

---

# Chương 13. PRD → Pipeline → Execution traceability

Bảng này là crosswalk bắt buộc giữa requirement, pipeline ID, task triển khai, artifact và acceptance. Task mới hoặc đổi tên task phải cập nhật bảng này trong cùng change; không được có task P0 không truy được về requirement/acceptance.

| PRD | Pipeline | Execution task | Artifact | Acceptance |
|---|---|---|---|---|
| `FR-01/02` | `ST-INPUT-VALIDATE`, `ST-PRIVACY-GATE` | `REC-01/02`, `PRODUCT-01` | `InputManifest`, `PrivacyValidationReport` | `AC-02` |
| `FR-03` | `INF-JOB-ORCHESTRATION` | `REC-10/11`, `SCENE-10`, `SIM-09`, `PRODUCT-02/03/08/09` | `JobManifest`, stage artifacts/errors | `AC-09` |
| `FR-04` | `ST-FRAME-EXTRACT`, `ST-CAMERA-POSE`, `ST-VISUAL-RECON`, `ST-RGB-GEOMETRY`, `ST-METRIC-CANONICALIZE` | `REC-03/04/05/06/07` | `ReconstructionBundle` | `AC-01` |
| `FR-05/06` | `ST-LIDAR-INGEST`, `ST-RGB-LIDAR-ALIGN`, `ST-METRIC-CANONICALIZE` | `REC-08/09` | `LiDARGeometryArtifact`, alignment/provenance evidence | `AC-03/04` |
| `FR-07` | `ST-OBJECT-EXTRACT`, `ST-OBJECT-ASSOC`, `ST-OBJECT-CONFIRM` | `SCENE-01/02/03/04/05` | candidate objects + provenance | `AC-05` |
| `FR-08` | `ST-SCENE-DECOMPOSE`, `ST-EDIT` | `SCENE-06/07/08/08A/09`, `PRODUCT-05/06/07/07A` | `SceneIR` revision | `AC-06/11/12` |
| `FR-09` | `ST-COLLIDER` | `SIM-02/02A/03`, `PRODUCT-07A` | `ColliderSpec`, physics-enriched `SceneIR` | `AC-06/08/12` |
| `FR-10` | `ST-REVIEW`, `ST-RELEASE` | `PRODUCT-10/11` | `ApprovalRecord`, `ReleaseManifest` | `AC-07` |
| `FR-11/12` | `ST-PREFLIGHT`, `ST-CANDIDATE-BUILD`, `ST-ISAAC-VALIDATE` | `SIM-01/04/05/06/07` | `PreflightReport`, `CandidatePackage`, `ValidationReport` | `AC-08`, `SM-02/04` |
| `FR-13` | `INF-ARTIFACT-CONTRACT` | tất cả track, `PRODUCT-04/11` | manifests, checksums, artifact inventory | `AC-10`, `SM-07` |
| PRD §10 metrics | `EV-VISUAL`, `EV-POSE`, `EV-GEOMETRY`, `EV-OBJECT`, `EV-PATH` | `SIM-08` + metric owners trong Team Plan | `EvaluationReport` + metric evidence | locked benchmark/acceptance protocol |
| P0 E2E | Product E2E Acceptance | `PRODUCT-12` + tất cả track owners | sealed demo release + evidence bundle | `AC-01`–`AC-12` applicable cho Primary Demo Scene |

`TRACK_IMPLEMENTATION_GUIDE.md` dùng task ID trong cột **Execution task** làm traceability key. Các bước implementation, test và Definition of Done của cùng task ID kế thừa row tương ứng; không lặp mapping riêng trong từng đoạn để tránh drift.
