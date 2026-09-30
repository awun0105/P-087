# TEAM EXECUTION CONTRACT

## Real2Sim Studio — Shared Engineering Contract

**Áp dụng cho:** `EX-REC`, `EX-SCENE`, `EX-SIM`, `EX-PRODUCT`
**Document Role:** Normative shared artifact, runtime, review và handoff contract.
**Scope:** Shared schema, producer/consumer boundary, coordinate, testing, review và change-control rules cho bốn execution tracks.
**Upstream Constraints:** Tuân product scope/acceptance trong [PRD](../PRD.md) và dataset/evaluation methodology trong [DATASET_PLAYBOOK](../DATASET_PLAYBOOK.md).
**Status:** Foundation Baseline v1.0 — approved 23/09/2026.
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

Foundation ownership:

| Role | Owner |
|---|---|
| `EX-REC` Owner | `@awun0105` |
| `EX-SCENE` Owner | Đức |
| `EX-SIM` Owner | Đạt |
| `EX-PRODUCT` Owner | Cường |
| Technical Lead / Integration Owner | `@awun0105` |
| Product Owner | Cường |
| QA / Validation Lead | Đạt |
| Release Approver | Đức |

GitHub handles của Đức, Đạt và Cường chưa được cung cấp; CODEOWNERS phải để
`TODO`, không tự suy đoán handle.

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
| Reconstruction + TorWIC product preparation | `EX-REC` — `@awun0105` |
| Object/Scene Core/Scene IR | `EX-SCENE` — Đức |
| Collider/OpenUSD/Isaac/Evaluation | `EX-SIM` — Đạt |
| FastAPI/Web/Jobs/Review/Release | `EX-PRODUCT` — Cường |
| Shared contracts/fixtures | producer + consumer review |

Cross-module change phải có owner review.

Canonical folder placement và module ownership được khóa tại [`ARCHITECTURE.md`](../../ARCHITECTURE.md). Nếu chưa rõ một file thuộc boundary nào, không tự tạo top-level `utils/`, `pipelines/`, `workers/` hoặc folder tương đương; phải hỏi owner/Tech Lead trước. Contract định nghĩa data shape, còn xử lý nghiệp vụ nằm trong service boundary của track sở hữu.

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
data_class: product_input | derived | ground_truth | evaluation_only
job_id / source provenance khi relevant
```

Không dùng filename hoặc local path làm identity.

`data_class` là metadata typed bắt buộc trên `ArtifactRef`, không suy ra từ tên
URI/path. `ProductArtifactRef` và mọi URI-bearing product manifest/inventory chỉ
nhận `product_input | derived`; thiếu class, `ground_truth` hoặc
`evaluation_only` phải bị reject dù URI nằm dưới `input/`. `ArtifactRef` cấp
thấp trong `EvaluationReport` vẫn biểu diễn được GT/evaluation-only. Tên folder
`evaluation_only/` hữu ích cho vận hành nhưng **không phải policy boundary**.
Class mô tả quyền sử dụng artifact; provenance mô tả lineage. Một artifact
`derived` có thể có `ground_truth_assisted: true` để phục vụ debug/oracle
experiment, nhưng không được claim independent GT accuracy. Producer phải
khai báo class trung thực tại publication; chỉ đổi class trong ref không phải
bằng chứng đã declassify một artifact.

Không hard-code:

```text
/home/user/...
C:\Users\...
```

Artifact URI P0 bắt buộc dùng logical form:

```text
artifact://jobs/<job_id>/<artifact-path>
```

`ARTIFACT_ROOT` là deployment-configured filesystem root. Development có thể dùng
`./data/artifacts/`; production/deployment phải cấu hình absolute path. Absolute
local filesystem path không được serialize vào contract.

**Amendment 2026-09-29 (ADR 0003):** deployment cloud được phép dùng backend
S3-compatible (Cloudflare R2) sau `ArtifactResolver`. Logical URI
`artifact://jobs/<job_id>/<artifact-path>` và checksum protocol không đổi; bucket,
endpoint, key hay presigned URL không được serialize vào contract.

### 3.1.1 Checksum identity protocol (Foundation v1.0)

| Field/role | Identity được hash | Verification owner |
|---|---|---|
| `ArtifactRef.artifact_checksum`, `InputFile.checksum`, `StageArtifact.artifact_checksum`, release inventory checksum | SHA-256 của **exact bytes** tại URI; tương tự `VisualArtifact`, `LiDARGeometryArtifact`, `AlignmentRecord` khi field `artifact_uri` chỉ producer payload | `ArtifactResolver.require` / `sha256_file` |
| `InputManifest.input_manifest_checksum`, `JobManifest.job_manifest_checksum`, `RuntimeManifest.runtime_manifest_checksum`, `ReconstructionBundle.artifact_checksum`, `SceneIR.scene_ir_checksum`, `*Report.report_checksum`, `ApprovalRecord.record_checksum`, `ReleaseManifest.release_manifest_checksum` | SHA-256 của canonical JSON **logical content**, loại trừ chính field checksum ở top level | `canonical_content_checksum` / `verify_content_checksum` |
| `CandidatePackage.candidate_checksum` | SHA-256 canonical JSON của toàn `CandidatePackage` (manifest + ordered entrypoint/assets/geometry/colliders refs), loại trừ `candidate_checksum`; bytes của từng member bắt buộc verify riêng bằng ref | `verify_candidate_inventory`, `verify_content_checksum`, resolver |
| `source_input_checksum`, `scene_ir_checksum`/`job_manifest_checksum` trong downstream manifest, `ValidationReport.candidate_checksum`, release candidate/report checksums | Copy **đúng identity upstream** tương ứng; không hash lại field này | producer/consumer lineage check |
| `JobManifest.config_checksum`, `CandidateManifest.build_config_checksum` | SHA-256 exact processing-config bytes; hai field bind cùng config khi build candidate | `sha256_file` + lineage check |

Canonical JSON dùng `model_dump(mode="json")`, giữ fields/defaults/`null`, sort
keys, separators `,` và `:`, UTF-8 không ASCII-escape, không cho phép NaN/Inf;
array order là một phần identity. Chỉ field self-checksum top-level bị loại trừ;
không hash pretty-print, filesystem listing order hoặc Python `repr()`.
`ReconstructionBundle.artifact_checksum` là **logical bundle content identity**,
không phải SHA của bytes file JSON ở `artifact_uri`; nếu publish serialized bundle,
publication envelope `ArtifactRef` riêng mang byte checksum của file đó. Tương tự
`SceneIR`/report content checksum khác byte checksum của published JSON envelope.
Không có self-referential hash.

Candidate inventory list phải bằng đúng checksum sequence của
`entrypoint_usd → assets[] → geometry[] → colliders[]`; `asset_refs[]` và
`collider_refs[]` trong manifest phải khớp package lists. Thứ tự list là explicit,
không lấy từ filesystem traversal. Sau validation, release-facing record phải
giữ đúng `candidate_checksum` và `validation_report_checksum`; mismatch bị reject.
Foundation chỉ chứng minh identity bằng synthetic fixture; release authorization
và sealing runtime vẫn thuộc `PRODUCT-11`.

## 3.2 Contract matrix

| Producer | Artifact | Consumer |
|---|---|---|
| Input layer | `InputManifest` | `EX-REC`, orchestrator |
| `EX-REC` privacy stage | `PrivacyValidationReport` | orchestrator, `EX-PRODUCT`, QA/Validation Lead |
| Orchestrator | `JobManifest` | tất cả stage |
| `EX-REC` | `ReconstructionBundle` | `EX-SCENE` |
| `EX-REC` | `LiDARGeometryArtifact` | mixed composition/evidence |
| `EX-REC` alignment stage | `AlignmentRecord` | `ReconstructionBundle`, QA/evidence |
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
    data_class: product_input | derived
input_configuration
    rgb_present
    depth_present?  # optional RGB+sensor-depth extension; không đổi P0 input scope
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

`lidar_metadata` chỉ optional khi không có Registered LiDAR. Nếu
`input_configuration.registered_lidar_present: true`, ba metadata field trên
phải hiện diện và không rỗng; khi modality vắng mặt thì không khai báo
`lidar_metadata`. `depth_present` chỉ khai báo modality ở input boundary;
sensor-depth dtype/format/scale thuộc `ReconstructionBundle.depth_frame_set`,
không phát minh thêm input metadata contract trong Foundation.

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
    data_class: product_input | derived  # required whenever artifact_uri is present
    started_at
    completed_at?
    error_ref?
job_manifest_checksum
```

Mỗi stage chỉ được đánh dấu `SUCCEEDED` khi toàn bộ artifact bắt buộc của stage đã có checksum và resolver đọc được. Retry phải append execution record hoặc tạo attempt mới; không được ghi đè provenance của attempt trước.

## 3.4 `ReconstructionBundle`

Tối thiểu:

```text
artifact_type = ReconstructionBundle
schema_version
artifact_uri + artifact_checksum
producer_stage = ST-METRIC-CANONICALIZE
job_id + source_input_checksum
input_configuration
coordinate_system
metric_scale
rgb_frame_refs[]?
depth_frame_set?  # producer-declared dtype/format/positive scale_to_meter; sensor depth
camera_pose_refs[]?
visual_artifact_ref?
rgb_geometry_ref?
lidar_geometry_ref?
alignment_record?
canonical_geometry_ref
provenance
```

Modality invariants:

```text
RGB P0
→ frames + poses + visual + RGB geometry + canonical geometry

RGB + Registered LiDAR
→ RGB artifacts + LiDAR artifact + CONFIRMED AlignmentRecord
→ alignment source/target checksums bind đúng hai geometry refs
→ LiDAR reference khai báo typed preprocessing dependencies và
  `ground_truth_assisted` nhất quán với mọi dependency có origin `ground_truth`;
  khi true, bundle provenance cũng ghi `ground_truth_assisted: true`

RGB + Depth (contract-capable; chưa là P0 input profile riêng)
→ RGB artifacts + DepthFrameSet với frame refs, storage dtype/format và
  `scale_to_meter` dương, hữu hạn; metric depth lưu trực tiếp dùng scale `1.0`
→ depth không được mặc định xem là ground truth

future LiDAR-only
→ visual/RGB geometry có thể absent
→ LiDAR + canonical geometry vẫn bắt buộc
```

`DepthFrameSet` dùng `storage_dtype`, `storage_format` do producer khai báo và
`scale_to_meter` dương/hữu hạn. TorWIC `uint16` PNG với scale `0.001` là giá trị
adapter/fixture của dataset hiện tại, **không** phải shared schema invariant.

`EX-SCENE` không được đọc private COLMAP/Brush/OpenMVS temp folders.

Transform trong shared contract được nhận diện bằng `parent_frame` và
`local_frame`: `T_<parent>_from_<local>` áp dụng
`p_parent = T_parent_from_local * p_local`. Raw TorWIC label `T_cam1_os` được
giữ khi parse source, nhưng khi normalize phải gọi tương đương
`T_os_from_cam`; chiều LiDAR→camera là
`T_cam_from_os = inverse(T_os_from_cam)`. `os_sensor` là source-frame hypothesis
từ REC-01B, chưa được SLAM backend xác nhận tuyệt đối. Canonical meter/Z-up/
right-handed/world là quyết định Real2Sim, không phải claim đầy đủ về native
TorWIC axes.

`VisualArtifact` là abstraction bắt buộc. Fixture Foundation dùng declared format
`real2sim.synthetic.visual.v1` để test contract; đó không phải Brush compatibility
proof. Khi Brush chạy thật, output thực tế của Brush là producer output và metadata
phải ghi `format`, `producer`, `producer_version`, checksum và coordinate system;
không tạo proprietary Gaussian binary format.

### Preview trước metric / SceneIR

`ReconstructionPreview` v1.0 (`src/models/contracts/preview.py`) là contract cộng
thêm cho REC→PRODUCT, không thay `VisualArtifact` canonical hoặc
`ReconstructionBundle`. Nó bind job/attempt/InputManifest checksum, raw visual,
camera poses và single-file SOG delivery bằng `ProductArtifactRef` exact bytes.
`metric_status=UNCONFIRMED`, `coordinate_frame=sfm_world`, `unit=arbitrary` là
bắt buộc. Producer REC consumer-verify checkpoint trước khi PRODUCT commit
preview reference vào JobManifest. API chỉ phục vụ ref đã nằm trong journal;
UI không cần SceneIR để inspect preview. Preview ready giữ job RUNNING tại
metric HITL, không báo toàn pipeline SUCCEEDED và không dùng cho SIM.

## 3.5 `LiDARGeometryArtifact`

Tối thiểu:

```text
artifact_uri
artifact_checksum
source_modality = registered_lidar
source_input_checksum
geometry_format
coordinate_system
source_frame
declared_transform_to_canonical?
preprocessing_provenance
```

Declared transform không đồng nghĩa confirmed alignment. Alignment result phải là
immutable `AlignmentRecord` riêng, bind `source_lidar_checksum`,
`target_rgb_geometry_checksum`, `transform_target_from_source`, status, method,
evidence và provenance; không mutate LiDAR artifact đã checksum.
`preprocessing_provenance` là typed record gồm `dependencies[]`,
`ground_truth_assisted` và `details`. Mỗi dependency ghi `role` (ví dụ `pose`),
`origin` (`sensor_input | estimated | external | ground_truth`) và
`source_checksum` của dependency. Direct registered
input có thể có danh sách dependencies rỗng. Flag `ground_truth_assisted` phải
khớp với việc có dependency `ground_truth`; source provenance của LiDAR reference
trong bundle dùng cùng shape. Không bắt buộc bất kỳ dataset nào có trajectory GT.
GT-assisted output không chứng minh trajectory estimation độc lập.

## 3.6 `SceneIR`

Logical structure:

```text
Scene
├── schema_version
├── scene_id
├── scene_revision
├── coordinate_system
├── metric_scale
├── environment
│   ├── visual_ref?
│   ├── geometry_ref
│   └── collider_ref?
└── objects[]
    └── SceneObject
        ├── id
        ├── name
        ├── state
        ├── origin: reconstructed | user_added
        ├── active
        ├── local_frame
        ├── transform
        ├── visual_ref?
        ├── geometry_ref
        ├── asset_ref?
        ├── primitive_dimensions_xyz_m?
        ├── provenance
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
`SceneObject.id` là duy nhất trong một SceneIR revision; duplicate IDs phải
fail validation. `collider.local_transform`, nếu có, chỉ là local offset với
`parent_frame = SceneObject.local_frame`, không tạo world transform truth thứ hai.
`SceneIR` là editable source of truth. Collider generation tạo SceneIR revision
cùng schema; OpenUSD/CandidatePackage là projection xuất từ revision đó để
Isaac validate và không được dùng làm source of truth cạnh tranh.

`SceneIR.agents[]` không thuộc P0 core. `review_state` không thuộc canonical
`SceneIR`; nó nằm trong workflow/revision record. Vì vậy APPROVED/REJECTED không
được làm đổi `scene_ir_checksum` nếu SceneIR content không đổi.

UI và simulator không được tạo transform truth riêng.

`user_added` object phải có `asset_ref` hoặc primitive geometry với
`primitive_dimensions_xyz_m` dương/hữu hạn. P0 không expose generic scale nếu
chưa định nghĩa propagation sang Visual/Geometry/Collider; asset-specific size
parameters do asset/SCENE-08A quản lý, không dùng collider dimensions thay cho
geometry dimensions.

## 3.7 Physics enrichment

`EX-SCENE` có thể handoff SceneIR khi `collider` chưa đầy đủ.

`EX-SIM` tạo collider rồi ghi ra **SceneIR revision cùng schema**, không tạo competing scene format.

### 3.7.0 Thay đổi dự kiến cho pipeline v2 (ADR 0007) — **Proposed, chưa là contract**

[ADR 0007](../decisions/0007-object-centric-hybrid-usd-pipeline.md) cần các bổ sung sau. Mục này
chỉ ghi ý định; schema chính thức chỉ đổi khi producer và consumer cùng review, có version mới
và migration/fixture tương ứng (§3.1). Tới lúc đó, contract hiện hành vẫn là authority.

| Thành phần | Bổ sung dự kiến | Producer → Consumer |
|---|---|---|
| `SceneObject.visual_ref` (đã có) | Trỏ tới Gaussian của riêng vật (artifact mới) | EX-REC/EX-SCENE → EX-PRODUCT, EX-SIM |
| `SceneEnvironment.visual_ref` (đã có) | Trỏ tới Gaussian nền **đã vá**; provenance ghi vùng nào là hình suy đoán | EX-REC → EX-PRODUCT, EX-SIM |
| `SceneObject.collider` (`ColliderSpec`, đã có) | `collider_type` phân rã lồi (hoặc SDF) kèm `geometry_ref` các phần lồi | EX-SIM → EX-SIM (USD), EX-PRODUCT |
| Vật lý của vật | Trường có kiểu: khối lượng (kg), nguồn khối lượng (mật độ × thể tích / người nhập / asset), vật liệu (ma sát tĩnh/động, restitution) | EX-SIM/EX-SCENE → EX-SIM (USD) |
| `SceneObject.semantic_class`, `asset_ref` (đã có) | Nhãn từ danh mục asset Isaac; `asset_ref` khi thay vật bằng asset | EX-SCENE/EX-PRODUCT → EX-SIM |
| `CandidatePackage` | Thêm layer Gaussian (`ParticleField3DGaussianSplat`) cho nền và từng vật; khai báo `kilogramsPerUnit` | EX-SIM → Isaac validation |

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
| `OBJECT_CONFIRMATION_INCOMPLETE` | Preflight | Có |
| `ROBOT_SPAWN_INVALID` | Isaac | Có |
| `PATH_VALIDATION_ERROR` | Isaac | Có |
| `ISAAC_LOAD_ERROR` | Isaac | Có |
| `REQUIRED_ROUTE_BLOCKED` | Isaac/Product config | Có khi ordinary product config đánh dấu route required |

Chỉ được chuyển sang `READY_FOR_REVIEW` khi tất cả blocking rules applicable cho run đều `PASS`. `ERROR` không được quy đổi thành `PASS` hoặc kết quả `CLEAR/BLOCKED`.

`IsaacValidationWorker` chỉ quan sát `CLEAR | BLOCKED | ERROR` và không đọc hidden
expected benchmark labels. `EvaluationRunner` mới so sánh observed result với
locked expected result. `REQUIRED_ROUTE_BLOCKED` chỉ dựa trên ordinary product
configuration, không dựa trên hidden evaluation label.

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
├── scene_ir_checksum
├── job_manifest_checksum
├── coordinate_system  # canonical meter, Z-up, right-handed, world
├── object_transforms[]
├── asset_refs[]
├── collider_refs[]
├── artifact_checksums[]
└── build_config_checksum
```

`CandidateManifest.coordinate_system` dùng cùng `CoordinateSystem` contract với
`SceneIR`; SIM exporter convert sang native OpenUSD/Isaac convention ở adapter
boundary. Không lưu `unit`/`up_axis` string độc lập trong canonical manifest.

`candidate_checksum` là checksum của toàn bộ `CandidatePackage` theo mục 3.1.1,
không chỉ của file USD entrypoint. `entrypoint_usd` là vai trò artifact; tên file
vật lý không phải contract cho tới khi package naming được khóa.

Checksum được tính từ canonical package inventory/content sau khi package hoàn
tất, loại trừ chính field `candidate_checksum`; không tạo checksum tự tham chiếu.
ArtifactRef riêng của package JSON (nếu publish) vẫn mang SHA của exact bytes.

## 3.9 `ValidationReport`

Tối thiểu:

```text
schema_version
candidate_checksum
validator_version
environment_versions
checks[]
    check_id
    result: PASS | FAIL | ERROR
    evidence_refs[]
    message?
path_results[]
    pair_id
    result: CLEAR | BLOCKED | ERROR
    evidence_refs[]
    message?
overall_result
report_checksum
```

Report phải gắn đúng candidate đã test. `path_results[]` không chứa expected label.

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
path_comparisons[]
    pair_id
    observed_result
    expected_result
    agreement
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
run_type: ORDINARY | LOCKED_MVP_ACCEPTANCE | BENCHMARK
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
    data_class: product_input | derived
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

`evaluation_report_checksum` chỉ optional cho `ORDINARY`. Field này bắt buộc khi
`run_type` là `LOCKED_MVP_ACCEPTANCE` hoặc `BENCHMARK`.

---

# Chương 4. Coordinate, metric và revision rules

## 4.1 Canonical coordinate và transform

```yaml
coordinate_system:
  unit: meter
  up_axis: Z
  handedness: right
  world_frame: world

transform:
  semantics: parent_from_local
  quaternion_order: xyzw
  angle_unit: radian
```

Semantic chính thức:

```text
p_parent = T_parent_from_local * p_local
```

Nếu object trực tiếp dưới world:

```text
parent = world
T_parent_from_local = T_world_from_object
```

COLMAP, PlayCanvas, splat-transform, OpenUSD và Isaac phải convert convention tại adapter boundary;
external convention không được leak vào SceneIR.

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

Direct product/runtime prediction không được đọc `traj_gt.txt`. Offline
`DP-LIDAR-PREFUSION` có thể dùng file này khi explicitly declared. Khi dùng,
TorWIC preparation manifest phải ghi chính xác dependency dataset-specific:

```text
trajectory_gt_used_for_lidar_prefusion: true
assistance_class: GT-assisted
```

Khi publish shared LiDAR artifact/bundle, TorWIC adapter map dependency đó thành
`role: pose`, `origin: ground_truth`, `source_checksum` của trajectory,
`ground_truth_assisted: true`; bundle provenance giữ flag này. Tên
`traj_gt.txt`/`trajectory_gt_used_for_lidar_prefusion` không phải required field
của `LiDARGeometryArtifact` hay `ReconstructionBundle`.

Artifact đó không được claim alignment/geometry độc lập với trajectory GT trong
evaluation yêu cầu independent evidence.

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

P0 dùng `FilesystemArtifactStore` sau `ArtifactResolver` với:

```text
ARTIFACT_ROOT=<deployment-configured-absolute-path>
artifact://jobs/<job_id>/<artifact-path>
```

Bắt buộc:

- resolve logical URI mà không path traversal;
- validate existence và schema version;
- producer chỉ publish artifact sau khi hoàn tất;
- SHA-256 sau khi finalize và verify ở consumer;
- atomic publication và immutable destination;
- consumer chỉ dùng published artifact refs;
- critical artifact không chỉ tồn tại trên laptop cá nhân.

**Amendment 2026-09-29 (ADR 0003):** backend S3-compatible (Cloudflare R2) được
dùng thay `FilesystemArtifactStore` cho deployment cloud, sau cùng `ArtifactResolver`,
với các bắt buộc trên giữ nguyên: publish chỉ khi object đã upload xong (multipart
hoàn tất), không ghi đè key đã publish, SHA-256 tính khi ghi và verify ở consumer,
link tải/upload cho trình duyệt là presigned có hạn và không vào contract. Local/test
vẫn dùng filesystem. Cần producer (EX-PRODUCT) + consumer (EX-SCENE/EX-SIM) review
khi triển khai (phase 2 của plan Cloud Studio).

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

Stage status dùng cùng enum trên ở cấp stage. Stage ID registry P0:

```text
ST-INPUT-VALIDATE       ST-PRIVACY-GATE
ST-FRAME-EXTRACT        ST-CAMERA-POSE
ST-VISUAL-RECON         ST-RGB-GEOMETRY
ST-LIDAR-INGEST         ST-RGB-LIDAR-ALIGN
ST-METRIC-CANONICALIZE  ST-OBJECT-EXTRACT
ST-OBJECT-ASSOC         ST-OBJECT-CONFIRM
ST-SCENE-DECOMPOSE      ST-COLLIDER
ST-EDIT                 ST-PREFLIGHT
ST-CANDIDATE-BUILD      ST-ISAAC-VALIDATE
ST-REVIEW               ST-RELEASE
```

Stage failure dùng typed `ExecutionError(error_code, stage_id, human_message,
retryable, details?)`. Track không được tạo status hoặc stage ID cạnh tranh.

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
- [x] 4 track owners
- [x] Technical Lead / Integration Owner
- [x] Product Owner
- [x] QA / Validation Lead
- [x] Release Approver

**Contracts**
- [x] `InputManifest`, `PrivacyValidationReport`, `JobManifest`, `RuntimeManifest`
- [x] `ReconstructionBundle`, `VisualArtifact`, `LiDARGeometryArtifact`, `AlignmentRecord`
- [x] `SceneIR`, `PreflightReport`, `CandidatePackage`
- [x] `ValidationReport`, `EvaluationReport`
- [x] `ApprovalRecord`, `ReleaseManifest`, `SceneRevisionRecord`

**Coordinate**
- [x] meter, Z-up, right-handed, world frame `world`
- [x] `parent_from_local`, quaternion `xyzw`, angle `radian`

**TorWIC / evaluation inputs**
- [x] P0 traversal: `Aisle_CW`; `Aisle_CCW` bổ sung/backup
- [x] data folders và evaluation-only boundary defined
- [x] LiDAR prefusion provenance rule defined
- [ ] extracted structure inspection, Primary Demo frame range và benchmark split — later milestone
- [ ] metric anchor / independent benchmark inputs — human-provided later milestone

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
- [x] runtime manifest hỗ trợ `UNVERIFIED/TBD`
- [x] logical URI + configured artifact root
- [ ] GPU/VRAM, CUDA/driver, Isaac/OpenUSD/tool versions — record sau provisioning

**Testing**
- [x] synthetic positive/negative fixtures
- [x] contract/integration/readiness commands
- [ ] real GPU smoke path — later milestone
- [ ] real E2E evidence — later milestone

---

# Chương 13. PRD → Pipeline → Execution traceability

Bảng này là crosswalk bắt buộc giữa requirement, pipeline ID, task triển khai, artifact và acceptance. Task mới hoặc đổi tên task phải cập nhật bảng này trong cùng change; không được có task P0 không truy được về requirement/acceptance.

| PRD | Pipeline | Execution task | Artifact | Acceptance |
|---|---|---|---|---|
| `FR-01/02` | `ST-INPUT-VALIDATE`, `ST-PRIVACY-GATE` | `REC-01/02`, `PRODUCT-01` | `InputManifest`, `PrivacyValidationReport` | `AC-02` |
| `FR-03` | `INF-JOB-ORCHESTRATION` | `REC-10/11`, `SCENE-10`, `SIM-09`, `PRODUCT-02/03/08/09` | `JobManifest`, stage artifacts/errors | `AC-09` |
| `FR-04` | `ST-FRAME-EXTRACT`, `ST-CAMERA-POSE`, `ST-VISUAL-RECON`, `ST-RGB-GEOMETRY`, `ST-METRIC-CANONICALIZE` | `REC-02A/03/04/05/06/10` | `ReconstructionBundle` | `AC-01` |
| `FR-05/06` | `ST-LIDAR-INGEST`, `ST-RGB-LIDAR-ALIGN`, `ST-METRIC-CANONICALIZE` | `REC-07/08/09/10` | `LiDARGeometryArtifact`, `AlignmentRecord`, mixed `ReconstructionBundle` | `AC-03/04` |
| `FR-07` | `ST-OBJECT-EXTRACT`, `ST-OBJECT-ASSOC`, `ST-OBJECT-CONFIRM` | `SCENE-01/02/03/04/05` | candidate objects + provenance | `AC-05` |
| `FR-00/08` | `ST-SCENE-DECOMPOSE`, `ST-EDIT` | `SCENE-06/07/08/08A/09`, `PRODUCT-05/06/07/07A` | `SceneIR` revision + real `VisualArtifact` + Geometry/Collider refs | `AC-06/11/12` |
| `FR-09` | `ST-COLLIDER` | `SIM-02/02A/03`, `PRODUCT-07A` | `ColliderSpec`, physics-enriched `SceneIR` | `AC-06/08/12` |
| `FR-10` | `ST-REVIEW`, `ST-RELEASE` | `PRODUCT-10/11` | `ApprovalRecord`, `ReleaseManifest` | `AC-07` |
| `FR-11/12` | `ST-PREFLIGHT`, `ST-CANDIDATE-BUILD`, `ST-ISAAC-VALIDATE` | `SIM-01/04/05/06/07` | `PreflightReport`, `CandidatePackage`, `ValidationReport` | `AC-08`, `SM-02/04` |
| `FR-13` | `INF-ARTIFACT-CONTRACT` | tất cả track, `PRODUCT-04/11` | manifests, checksums, artifact inventory | `AC-10`, `SM-07` |
| PRD §10 metrics | `EV-VISUAL`, `EV-POSE`, `EV-GEOMETRY`, `EV-OBJECT`, `EV-PATH` | `SIM-08` + metric owners trong Team Plan | `EvaluationReport` + metric evidence | locked benchmark/acceptance protocol |
| P0 E2E | Product E2E Acceptance | `PRODUCT-12` + tất cả track owners | sealed demo release + evidence bundle | `AC-01`–`AC-12` applicable cho Primary Demo Scene |

`TRACK_IMPLEMENTATION_GUIDE.md` dùng task ID trong cột **Execution task** làm traceability key. Các bước implementation, test và Definition of Done của cùng task ID kế thừa row tương ứng; không lặp mapping riêng trong từng đoạn để tránh drift.
