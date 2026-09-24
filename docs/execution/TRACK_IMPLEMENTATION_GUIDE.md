# TRACK IMPLEMENTATION GUIDE

## Real2Sim Studio — Detailed Work Guide for 4 Execution Tracks

**Document Role:** Per-track implementation task guide.
**Scope:** Thứ tự thực hiện, tool strategy, task ID, test và Definition of Done cho `EX-REC`, `EX-SCENE`, `EX-SIM`, `EX-PRODUCT`.
**Upstream Constraints:** Tuân [PRD](../PRD.md), [DATASET_PLAYBOOK](../DATASET_PLAYBOOK.md) và normative [TEAM_EXECUTION_CONTRACT](./TEAM_EXECUTION_CONTRACT.md).
**Status:** Foundation Baseline v1.0 — task IDs/scopes locked.
**Related Documents:** [BRIEF](../BRIEF.md), [WIREFRAME](../WIREFRAME_AND_UI_FLOW.md), [INTEGRATION_PLAYBOOK](./INTEGRATION_PLAYBOOK.md), [TEAM_EXECUTION_PLAN](./TEAM_EXECUTION_PLAN.md).

---

# Chương 1. Cách sử dụng tài liệu

File này chỉ trả lời:

> **Mỗi track phải làm cụ thể những gì và làm theo thứ tự nào?**

Timeline xem [`TEAM_EXECUTION_PLAN.md`](./TEAM_EXECUTION_PLAN.md).
Shared architecture/schema/testing rules xem [`TEAM_EXECUTION_CONTRACT.md`](./TEAM_EXECUTION_CONTRACT.md).

**Traceability:** Mỗi task ID trong tài liệu này phải xuất hiện trong crosswalk tại [`TEAM_EXECUTION_CONTRACT.md` Chương 13](./TEAM_EXECUTION_CONTRACT.md). Implementation steps, tests và Definition of Done kế thừa traceability của task ID; thêm hoặc đổi tên task phải cập nhật crosswalk trong cùng change.

Mỗi track đều theo cùng workflow:

```text
Read required docs
→ Validate input fixture
→ Implement thin path
→ Local test
→ Heavy/GPU smoke test nếu cần
→ Contract test
→ Produce real artifact
→ Handoff test
→ Save evidence
```

---

## 1.1 Implementation strategy taxonomy

Mỗi stage phải được gắn một strategy chính trước khi code:

| Strategy | Nghĩa |
|---|---|
| `REUSE` | Dùng tool/model gần như nguyên bản qua CLI/API/library; không viết lại thuật toán lõi |
| `ADAPT` | Lấy một phần logic/script/pattern rồi chỉnh để phù hợp contract nội bộ; phải kiểm tra license |
| `SELF-CODE` | Team tự viết phần domain, glue, orchestration và product logic của Real2Sim Studio |
| `REFERENCE` | Chỉ đọc kiến trúc/ý tưởng; không tạo runtime dependency |

Nguyên tắc chung:

> Không tự viết lại thuật toán lõi mà một Core repo đã giải quyết tốt. Team chủ yếu sở hữu adapter, artifact normalization, Scene IR, orchestration, HITL, validation và product workflow.

## 1.2 Project-wide Implementation Source Map

| Component | Strategy | Primary source | Dùng phần nào | Team tự viết |
|---|---|---|---|---|
| Video/frame | `REUSE` | FFmpeg | decode/encode CLI | adapter, validation, manifest |
| Camera pose/SfM | `REUSE` | `colmap/colmap` | feature extraction, matching, mapper/SfM | `ColmapAdapter`, input prep, pose/output normalization |
| 3DGS Visual | `REUSE` | `ArthurBrussee/brush` | reconstruction/training CLI, Gaussian output | `BrushAdapter`, COLMAP bridge, config, provenance |
| RGB geometry | `REUSE` | `cdcseacave/openMVS` | COLMAP import, densification, mesh reconstruction | `OpenMVSAdapter`, normalized geometry artifact |
| LiDAR processing | `SELF-CODE` + library | `isl-org/Open3D` | IO, transform, filtering, voxel utilities | prefusion/ingest/alignment workflow + provenance |
| Object masks | `REUSE` | `facebookresearch/sam2` | predictor, video mask propagation | `SAM2Adapter`, mask artifact/metadata |
| Multi-view association | `SELF-CODE` + `REFERENCE` | Gaussian Grouping, ObjectGS, SegAnyGaussians, R2G | identity/grouping ideas | masks + poses + geometry association baseline |
| Scene decomposition | `SELF-CODE` + `REFERENCE` | R2G, `gs-real2sim`, DISCOVERSE | object/environment decomposition patterns | `SceneDecomposer`, Environment/SceneObject mapping |
| Scene IR | `SELF-CODE` | project contract | — | schema, refs, transforms, revisions |
| Collider | `SELF-CODE` + library | Trimesh, Open3D | OBB/AABB/convex/simplification utilities | collider policy + generator |
| OpenUSD export | `SELF-CODE` + library | OpenUSD | USD APIs | SceneIR→USD adapter, package/checksum |
| Isaac validation | `SELF-CODE` + platform | Isaac Sim, IsaacLab | simulator/runtime APIs | load/spawn/collision/path validator + report |
| Simulator patterns | `REFERENCE` | Re3Sim, VR-Robo, DISCOVERSE, OpenReal2Sim | reconstruction→simulator patterns | không tạo dependency nếu không cần |
| Evaluation | `SELF-CODE` | [DATASET_PLAYBOOK](../DATASET_PLAYBOOK.md) | protocol/metric definitions | evaluator orchestration + reports |
| API/jobs | `SELF-CODE` | FastAPI + basic worker/queue | framework primitives | job/artifact/orchestration lifecycle |
| Web Studio | `SELF-CODE` domain + selective `ADAPT` UI | Next.js, Three.js, WebGL/WebGL2; Kiranism dashboard starter; Spark qualification candidate | generic shell/table/form patterns, 3D primitives and browser Gaussian renderer | real 3DGS Visual/Geometry/Point Cloud/Collider views, SceneIR mapping/editing, validation/review UX |
| Review/release | `SELF-CODE` | PRD lifecycle | — | approval gate, revision invalidation, release sealing |

Nếu muốn đổi backend hoặc strategy, output contract phải giữ nguyên và phải tuân [`TEAM_EXECUTION_CONTRACT.md`](./TEAM_EXECUTION_CONTRACT.md).

---

# Chương 2. EX-REC — Dataset & Reconstruction

## 2.1 Mission

Biến RGB/Registered LiDAR thành reconstruction artifacts chuẩn để `EX-SCENE` consume.

```text
RGB
→ Pose
→ Visual
→ RGB Geometry
→ Metric/Canonical
→ ReconstructionBundle

Registered LiDAR
→ LiDARGeometryArtifact
```

## 2.2 Input / Output

**Input**
- moving-camera RGB video hoặc normalized image sequence;
- registered/fused LiDAR cho product LiDAR path;
- TorWIC raw LiDAR chỉ dùng trong offline prefusion.

**Output**
- `ReconstructionBundle`;
- `LiDARGeometryArtifact`;
- alignment/metric provenance khi mixed.

## 2.3 Tools / repositories

Primary:

- FFmpeg
- COLMAP
- Brush
- OpenMVS
- Open3D
- `playcanvas/splat-transform`: Core utility cho 3DGS artifact validation (`readFileInfo`), stats (`fillRatio`), Morton reorder và SOG packaging. Xem [`docs/execution/audits/04a_splat_transform.md`](./audits/04a_splat_transform.md).
- `InternRobotics/Re3Sim`: **Tier-0 System Architecture Reference & Code Donor** cho PyCOLMAP orchestration (`REC-03`), OpenMVS command pipeline (`REC-05`) và FrameTools / similarity transform (`REC-06`). Xem [`docs/execution/audits/07_re3sim.md`](./audits/07_re3sim.md).

Run-first/reference theo Integration Playbook:

- OpenReal2Sim
- VR-Robo
- R2G
- video-3d-reconstruction-gsplat

Mục tiêu audit repo là quyết định nhanh:

```text
REUSE / ADAPT / REFERENCE / REJECT
```

Không nghiên cứu vô hạn.

## 2.4 Implementation Source Map

| Stage | Strategy | Source | Lấy từ repo/tool | Team tự code |
|---|---|---|---|---|
| `REC-01` TorWIC preparation | `SELF-CODE` | Dataset Playbook + Open3D/FFmpeg | IO/transform/encode primitives | normalizer, split/preparation scripts, manifests |
| `REC-02` Input validation + privacy gate | `SELF-CODE` | FFmpeg + PRD rules | decode/probe | input rules, privacy gate, errors, report |
| `REC-02A` Frame extraction | `REUSE` + adapter | FFmpeg | deterministic frame decode/extraction | command builder, normalized frame artifact, provenance |
| `REC-03` Camera pose | `REUSE` + `ADAPT` | `colmap/colmap` + `Re3Sim` | feature extraction, matching, mapper/SfM, sequential vocab tree | `ColmapAdapter`, model selection, pose normalization |
| `REC-04` Visual reconstruction | `REUSE` + utility | `ArthurBrussee/brush` + `playcanvas/splat-transform` | 3DGS reconstruction/training, artifact validation, SOG packaging | `BrushAdapter`, `SplatArtifactProcessor`, config, provenance |
| `REC-05` RGB geometry | `REUSE` + `ADAPT` | `cdcseacave/openMVS` + `Re3Sim` | COLMAP import, densify, mesh, refine command orchestration | `OpenMVSAdapter`, output normalization, timeout/checksum |
| `REC-06` Metric scale | `SELF-CODE` + `ADAPT` | PRD + `Re3Sim` FrameTools concept | frame graph, similarity transform estimation | anchor workflow, scale propagation, confirmation record |
| `REC-07` LiDAR prefusion | `SELF-CODE` + library | Open3D | transform/filter/voxel primitives | TorWIC prefusion + GT-dependency provenance |
| `REC-08` LiDAR ingest | `SELF-CODE` + library | Open3D | point-cloud validation/filtering | `LiDARGeometryArtifact` producer |
| `REC-09` RGB–LiDAR alignment | `SELF-CODE` + library | Open3D + calibration/known transform | transform/registration primitives | alignment flow + transform provenance |
| `REC-10` Publish bundle | `SELF-CODE` | shared contract | — | `ReconstructionBundle` builder/validator |
| `REC-11` Worker entrypoint | `SELF-CODE` | project runtime | — | CLI/worker wrapper, logging, exit status |

**Không tự viết lại trong P0:** SfM/bundle adjustment, 3DGS trainer, dense MVS/mesh reconstruction hoặc generic point-cloud primitives.

System repos như OpenReal2Sim, Re3Sim, VR-Robo, R2G và `video-3d-reconstruction-gsplat` được audit để học/reuse/adapt phần nhỏ phù hợp; chúng không mặc định trở thành production dependency.

## 2.5 Implementation steps

### REC-01 — TorWIC preparation

- chọn locked bring-up traversal;
- giữ `raw/` immutable;
- tạo `normalized/`;
- tạo benchmark split;
- tạo calibration/timestamp metadata.

### REC-02 — RGB validation

Kiểm tra:

- decode/read;
- corrupt frame;
- usable frame count;
- motion/registration feasibility;
- chạy `ST-PRIVACY-GATE` và phát hành `PrivacyValidationReport`;
- chỉ cho pipeline tiếp tục khi trạng thái là `VERIFIED_ANONYMIZED`; `PRELIMINARY_SCREENED` không đủ cho public/demo và `QUARANTINED` phải dừng pipeline.

`EX-PRODUCT` thu source-rights attestation; `EX-REC` sở hữu privacy check/report; QA/Validation Lead chấp nhận `VERIFIED_ANONYMIZED` trước public/demo use.

### REC-02A — Frame extraction

```text
validated + privacy-cleared RGB input
→ ST-FRAME-EXTRACT
→ normalized immutable frame set + timestamps + provenance
```

Frame extraction không nằm trong `REC-07`; `REC-07` chỉ là TorWIC LiDAR
prefusion. Output phải dùng artifact URI/checksum và là input trực tiếp cho
`REC-03`.

### REC-03 — Camera pose

```text
RGB
→ COLMAP
→ intrinsics + poses + sparse model
```

Normalize output thành internal artifact.

### REC-04 — Visual reconstruction

```text
COLMAP
→ Brush
→ 3DGS visual artifact
```

Visual không được dùng như collider.

### REC-05 — RGB geometry

```text
COLMAP
→ OpenMVS
→ mesh / dense geometry
```

Geometry phải đủ cho downstream scale/object/collider.

### REC-06 — RGB metric scale

Dùng locked real-world anchor theo PRD.

### REC-07 — TorWIC LiDAR prefusion

Offline only:

```text
lidar/*.pcd
+ declared poses
→ merge/filter/downsample
→ registered_lidar.ply
```

Direct runtime không đọc `traj_gt`. Nếu offline prefusion explicitly dùng file
này, ghi `trajectory_gt_used_for_lidar_prefusion: true`, `assistance_class: GT-assisted` và không claim resulting
alignment độc lập với trajectory GT.
Đây là field của TorWIC preparation manifest, không phải required field trong
shared `LiDARGeometryArtifact`/`ReconstructionBundle`. REC-08 map nó thành
preprocessing dependency `role: pose`, `origin: ground_truth`, trajectory
checksum và `ground_truth_assisted: true`; estimated/external poses dùng origin
phù hợp thay vì giả làm GT.

### REC-08 — LiDAR ingest

```text
registered_lidar
→ validate unit/frame
→ LiDARGeometryArtifact
```

### REC-09 — Mixed alignment

```text
same-scene RGB artifacts
+
LiDARGeometryArtifact
→ confirmed alignment
```

Không mutate checksummed LiDAR artifact.

### REC-10 — Publish bundle

Tạo `ReconstructionBundle` đúng shared contract.

### REC-11 — Worker entrypoint

Có stable CLI/worker command; không yêu cầu sửa path bằng tay.

## 2.6 Local vs GPU

**Local**
- parsers;
- manifests;
- calibration/timestamp;
- command builders;
- checksum;
- coordinate/scale utilities;
- contract tests.

**GPU/heavy**
- Brush;
- heavy reconstruction;
- large OpenMVS;
- system-reference smoke runs.

## 2.7 Tests

**Unit**
- parser;
- frame selection;
- scale;
- checksum;
- coordinate metadata.

**Smoke**
- small RGB → COLMAP;
- small COLMAP scene → Brush;
- small COLMAP scene → OpenMVS;
- small registered LiDAR → LiDAR artifact.

**Contract**
- `ReconstructionBundle` validates;
- refs resolve;
- coordinate/metric metadata present.

## 2.8 TorWIC rules

Product prediction không được đọc evaluation GT.

Bring-up: 1 traversal.
Development: 2–3 nếu đủ compute.
Final benchmark: 3–5 locked nếu đủ compute.

## 2.9 Definition of Done

- real RGB reconstruction chạy;
- visual + geometry artifacts tồn tại;
- metric path tồn tại;
- LiDAR artifact tồn tại;
- mixed LiDAR evidence path tồn tại;
- bundle validate;
- `EX-SCENE` đọc real bundle không sửa tay.

## 2.10 Evidence

Lưu:

- traversal ID;
- screenshots visual/geometry;
- pose stats;
- runtime/GPU;
- LiDAR evidence;
- manifest/checksum;
- representative failure.

---

# Chương 3. EX-SCENE — Object Intelligence & Scene Core

## 3.1 Mission

Biến reconstruction toàn cục thành scene có cấu trúc và object có thể chỉnh sửa.

```text
ReconstructionBundle
→ Masks
→ Multi-view Association
→ Candidate Objects
→ Human Confirmation
→ Scene Decomposition
→ SceneIR
```

## 3.2 Input / Output

**Input**
- `ReconstructionBundle`;
- RGB frame refs;
- camera poses;
- canonical geometry.

**Output**
- `SceneIR`.

`collider` có thể chưa đầy đủ ở handoff đầu sang `EX-SIM`.

## 3.3 Tools / repositories

Primary:

- SAM2
- Open3D

Reference / Code Donors (Deep Audit):

- `BigCiLeng/R2G` (SAMPro3D): **Tier-0 Algorithm Donor** cho `SCENE-03` (multi-view voting, DBSCAN cleanup, prompt consolidation) và `SCENE-06` (per-object point cloud & OBB extraction). Xem [`docs/execution/audits/02_r2g.md`](./audits/02_r2g.md).
- `PointsCoder/OpenReal2Sim`: **Code Donor** cho alignment utilities (`scenario_construction.py`) và P1 `BackgroundCompletionBackend`. Xem [`docs/execution/audits/01_openreal2sim.md`](./audits/01_openreal2sim.md).
- `lkeab/gaussian-grouping`: **Tier-0 Algorithm Reference** (per-Gaussian persistent identity learning, 3D spatial consistency) & **Tier-1 Qualification Candidate** (`SCENE-QUAL-GG-01`). Xem [`docs/execution/audits/06_gaussian_grouping.md`](./audits/06_gaussian_grouping.md).
- ObjectGS, SegAnyGaussians, gs-real2sim, DISCOVERSE.

Chỉ reuse concept/module cần thiết; không kéo toàn bộ research dependency graph vào core.

## 3.4 Implementation Source Map

| Stage | Strategy | Source | Lấy từ repo/tool | Team tự code |
|---|---|---|---|---|
| `SCENE-01` Bundle consumer | `SELF-CODE` | shared contract | — | loader/validator |
| `SCENE-02` Object extraction | `REUSE` | `facebookresearch/sam2` | predictor + mask/video propagation | `SAM2Adapter`, mask artifact/metadata |
| `SCENE-03` Multi-view association | `SELF-CODE` + `ADAPT` | `BigCiLeng/R2G` (SAMPro3D) + `lkeab/gaussian-grouping` (qualification) | 3D projection, multi-view score voting, DBSCAN, prompt consolidation, identity lifting spike | projection adapter + association service theo canonical coordinate |
| `SCENE-04` Candidate model | `SELF-CODE` | PRD | — | ID/state/provenance model |
| `SCENE-05` Human Confirmation | `SELF-CODE` | PRD | — | confirm/ignore/merge/create/reassign domain operations |
| `SCENE-06` Scene decomposition | `SELF-CODE` + `ADAPT` | R2G, OpenReal2Sim, `gaussian-grouping`, `gs-real2sim`, DISCOVERSE | per-object point cloud, OBB extraction, GaussianObjectMembership alignment patterns | `SceneDecomposer`, object↔geometry binding |
| `SCENE-07` SceneObject model | `SELF-CODE` | Scene IR contract | — | transform/ref/state model |
| `SCENE-08` Edit semantics | `SELF-CODE` | PRD | — | move/rotate/hide/delete behavior |
| `SCENE-08A` Add primitive/asset | `SELF-CODE` | PRD | — | user-added object + primitive dimensions/asset parameters |
| `SCENE-09` Publish SceneIR | `SELF-CODE` | shared contract | — | schema builder, revisions, serializer/validator |
| `SCENE-10` Worker entrypoint | `SELF-CODE` | project runtime | — | CLI/worker wrapper |

**Không tự viết lại:** segmentation foundation model hoặc SAM-like propagation. Phần team cần sở hữu là association, HITL semantics, decomposition và Scene IR.

## 3.5 Implementation steps

### SCENE-01 — Fixture-first consumer

Đọc golden/fixture `ReconstructionBundle` trước khi real reconstruction xong.

### SCENE-02 — Object extraction

```text
RGB frames
→ SAM2
→ mask artifacts
```

Mask phải có metadata, không chỉ file ảnh rời.

### SCENE-03 — Multi-view association

Kết hợp:

```text
masks + camera poses + canonical geometry
→ candidate identities
```

Baseline đơn giản nhưng deterministic được ưu tiên hơn research phức tạp không ổn định.

### SCENE-04 — Candidate model

States:

```text
UNREVIEWED
CONFIRMED
IGNORED
NEEDS_CORRECTION
```

### SCENE-05 — Human Confirmation operations

Support domain operations:

- rename;
- confirm;
- ignore;
- merge;
- create missing object;
- reassign.

UI do `EX-PRODUCT`.

### SCENE-06 — Scene decomposition

```text
confirmed candidates
→ Environment + SceneObjects
```

### SCENE-07 — SceneObject model

Mỗi object có:

```text
id
state
origin: reconstructed | user_added
active
transform
visual_ref?
geometry_ref
asset_ref?
collider: ColliderSpec?
```

Chỉ một canonical transform.
Object IDs phải unique theo SceneIR revision; collider local offset (nếu có)
được parent vào `SceneObject.local_frame`.

### SCENE-08 — Edit semantics

Support domain behavior:

- move;
- rotate;
- hide/show;
- rename;
- delete/disable.

Delete phải loại geometry/physics khỏi active scene; photorealistic background restoration không bắt buộc P0.

### SCENE-08A — Add primitive/asset

Tạo `SceneObject(origin = user_added)` với primitive geometry có
`primitive_dimensions_xyz_m` dương/hữu hạn hoặc `asset_ref` có size parameters
theo asset. Không expose generic scale cho tới khi propagation sang
Visual/Geometry/Collider được định nghĩa và kiểm thử.

### SCENE-09 — Publish SceneIR

Serialize/deserialize/version/validate.

### SCENE-10 — Worker entrypoint

Stable CLI/worker:

```text
ReconstructionBundle
→ SceneIR
```

## 3.6 Local vs GPU

**Local**
- SceneIR;
- association trên fixture;
- transforms;
- state transitions;
- decomposition;
- edit semantics.

**GPU**
- SAM2 inference;
- optional research-reference tests.

## 3.7 Tests

**Unit**
- candidate states;
- merge/reassign/create;
- transform;
- SceneIR roundtrip;
- delete semantics;
- user-added primitive/asset dimensions và provenance.

**Smoke**
- few RGB frames → masks;
- fixture masks/poses/geometry → candidate;
- candidate → SceneIR.

**Contract**
- consume `ReconstructionBundle`;
- produce valid `SceneIR`;
- object IDs unique;
- refs resolve.

## 3.8 TorWIC rules

Được dùng:

- RGB frames;
- poses;
- reconstruction geometry.

Không dùng manual evaluation annotations để tạo prediction.

TorWIC segmentation masks chỉ là debug/reference khi methodology cho phép, không phải perfect GT.

## 3.9 Definition of Done

- automatic candidate được tạo;
- ít nhất một correction case xử lý được;
- Environment + SceneObjects tồn tại;
- SceneIR validate;
- transform consistency đúng;
- real `ReconstructionBundle` consume được;
- `EX-SIM` đọc SceneIR trực tiếp.

## 3.10 Evidence

Lưu:

- masks;
- candidate grouping;
- correction before/after;
- scene decomposition;
- SceneIR sample;
- transform edit evidence.

---

# Chương 4. EX-SIM — Physics, Isaac & Evaluation

## 4.1 Mission

Biến SceneIR thành physics-ready candidate, chạy Isaac validation và tạo report/metrics.

```text
SceneIR
→ Collider
→ Preflight
→ Candidate OpenUSD
→ Isaac
→ ValidationReport
+
EvaluationReport? (theo run type)
```

## 4.2 Input / Output

**Input**
- `SceneIR`;
- evaluation-only references chỉ trong evaluator.

**Output**
- physics-enriched `SceneIR`;
- `CandidatePackage`;
- `ValidationReport`;
- `EvaluationReport` khi locked acceptance/benchmark protocol yêu cầu.

## 4.3 Tools / repositories

Primary:

- Open3D
- Trimesh
- OpenUSD
- Isaac Sim
- IsaacLab

Reference / Code Donors (Deep Audit):

- `PointsCoder/OpenReal2Sim`: **Tier-0 Code Donor** cho `SIM-05` (USD conversion, MeshConverter, PhysX/RigidBody/Collision properties), `SIM-02` (collision remediation) và `SIM-06` (Docker IsaacLab isolation). Xem [`docs/execution/audits/01_openreal2sim.md`](./audits/01_openreal2sim.md).
- `zst1406217/VR-Robo`: **Tier-0 Integration Donor** cho `SIM-01` (IsaacLab startup, USD loading), `SIM-06` (robot runtime, stepping loop, video replay fallback) và `SIM-09` (worker process isolation); Architecture reference cho Visual/Physics separation. Xem [`docs/execution/audits/03_vr_robo.md`](./audits/03_vr_robo.md).
- `discoverse-dev/DISCOVERSE`: **Tier-0 Integration Reference** cho Visual ↔ Physics synchronization (`gs_model_dict`), **Secondary Utility Donor** cho CoACD convex decomposition (`SIM-02`), và **Tier-0 P1 Code Donor** cho remote GS rendering & hardware NVENC H.264 streaming. Xem [`docs/execution/audits/05_discoverse.md`](./audits/05_discoverse.md).
- `InternRobotics/Re3Sim`: **Tier-0 System Architecture Reference & Code Donor** cho IsaacLab `MeshConverterCfg`, stage units normalization (`metersPerUnit=1.0`), collision approximation selection (`SIM-02`, `SIM-05`), và P1 hybrid rendering. Xem [`docs/execution/audits/07_re3sim.md`](./audits/07_re3sim.md).

## 4.4 Implementation Source Map

| Stage | Strategy | Source | Lấy từ repo/tool | Team tự code |
|---|---|---|---|---|
| `SIM-01` Isaac smoke | `REUSE` platform + `ADAPT` | OpenUSD, Isaac Sim, IsaacLab + VR-Robo | USD/simulator APIs, `UsdFileCfg` scene load, environment setup | minimal USD builder + smoke script |
| `SIM-02` Collider | `SELF-CODE` + `ADAPT` | Trimesh, Open3D + OpenReal2Sim + DISCOVERSE (CoACD) + Re3Sim + `splat-transform` (fallback) | OBB/AABB/convex utilities, CoACD decomposition, MeshConverterCfg, ground clearance, voxel collision fallback | collider policy + `ColliderGenerator` |
| `SIM-02A` Collider edit validation | `SELF-CODE` | `ColliderSpec` contract | — | validate type/dimensions/local transform after edit |
| `SIM-03` Physics enrichment | `SELF-CODE` | Scene IR contract | — | `ColliderSpec`/physics metadata on same SceneIR schema |
| `SIM-04` Preflight | `SELF-CODE` | PRD/Integration Playbook | — | deterministic rules + report |
| `SIM-05` Candidate build | `SELF-CODE` + `ADAPT` | OpenUSD + OpenReal2Sim `usd_conversion.py` + Re3Sim `obj_to_usd.py` | USD scene APIs, MeshConverter, PhysX configs, stage units | SceneIR→USD translation, packaging, checksum |
| `SIM-06` Isaac validation | `SELF-CODE` + `ADAPT` | Isaac Sim, IsaacLab + OpenReal2Sim + VR-Robo | load/physics/runtime APIs, robot stepping, `RecordVideo` fallback | spawn/collision/path validation worker |
| `SIM-07` ValidationReport | `SELF-CODE` | shared contract | — | candidate-bound structured report |
| `SIM-08` Evaluation | `SELF-CODE` | Dataset Playbook | protocols/metric definitions | evaluator orchestration + reports |
| `SIM-09` Worker entrypoints | `SELF-CODE` + `ADAPT` | project runtime + VR-Robo patterns | worker/process boundary, separate containers | simulation/evaluation CLI wrappers |

Re3Sim, VR-Robo, DISCOVERSE và OpenReal2Sim là **architecture references & code donors** cho simulator boundary/transform/USD patterns. Không clone cả system để thay project architecture.

**Không tự viết lại:** USD core, physics engine, Isaac runtime, generic geometry primitives.

## 4.5 Implementation steps

### SIM-01 — Minimal Isaac smoke

Làm trước scene thật:

```text
floor + wall + box + robot
→ USD
→ Isaac load
```

Trên minimal USD trong locked runtime, smoke ngắn native MP4 capture, kiểm tra
file đọc được và ghi version của capture/videoencoding extension. Đây là
feasibility probe, chưa phải hệ thống replay đầy đủ. Nếu native thất bại, ghi
nguyên nhân và thử frame capture → FFmpeg chỉ như fallback được kiểm chứng.

### SIM-02 — Collider generation

Baseline:

- floor/wall → plane hoặc simplified static mesh;
- pallet/box → box/OBB;
- complex static object → convex/simplified mesh.

Không mặc định dùng raw high-poly mesh làm collider.

### SIM-02A — Collider edit/resize validation

Mọi thay đổi collider type, `dimensions`, `local_transform` hoặc parameters phải validate theo `ColliderSpec`, tạo SceneIR revision mới và invalidates candidate/validation cũ.

### SIM-03 — Physics enrichment

Gắn `ColliderSpec` vào **SceneIR revision cùng schema**.

Không tạo `PhysicsScene.json` cạnh tranh với SceneIR.

### SIM-04 — Preflight

Check tối thiểu:

- metric scale;
- coordinate sanity;
- required geometry;
- collider presence;
- spawn/floor;
- object bounds.

Output là `PreflightReport` conform normative schema trong [`TEAM_EXECUTION_CONTRACT.md`](./TEAM_EXECUTION_CONTRACT.md); không build candidate khi `blocking_result` khác `PASS`.

Implement đúng các rule IDs: `METRIC_SCALE_MISSING`, `COLLIDER_MISSING`, `TRANSFORM_INVALID`, `OBJECT_OUT_OF_BOUNDS`, `REQUIRED_ARTIFACT_MISSING`, `OBJECT_CONFIRMATION_INCOMPLETE`. Các rule Isaac `ROBOT_SPAWN_INVALID`, `PATH_VALIDATION_ERROR`, `ISAAC_LOAD_ERROR` phải được ghi vào validation evidence; `REQUIRED_ROUTE_BLOCKED` chỉ dùng cho route được ordinary product config đánh dấu required. Không đổi `ERROR` thành pass.

### SIM-05 — Candidate build

```text
physics SceneIR
→ OpenUSD
→ CandidatePackage + checksum
```

### SIM-06 — Isaac validation

**Smoke:**

- tối thiểu 1 `CLEAR` và 1 `BLOCKED` case.

**Acceptance:**

- load;
- robot spawn;
- floor/object collision;
- penetration;
- chạy đúng 5 locked Start–Goal pairs bằng robot footprint đã khóa;
- trả kết quả cho 5/5 pairs;
- chỉ emit observed `CLEAR | BLOCKED | ERROR`, không đọc expected labels;
- `ERROR` không được tính là `CLEAR`, `BLOCKED` hoặc pass.
- ưu tiên native Omniverse MP4 capture trong locked runtime; chỉ dùng frame
  capture → FFmpeg nếu native thất bại ở runtime đó;
- publish replay MP4, screenshots và logs của đúng validation run như review
  evidence riêng, tham chiếu bằng artifact refs/checksums; không sửa candidate
  package sau khi checksum được chốt;
- capture failure được báo riêng, không đổi observed validation PASS thành FAIL;
  Primary Demo vẫn cần replay/screenshots thật để đạt E2E acceptance.

### SIM-07 — ValidationReport

Report phải bind đúng `candidate_checksum`; `checks[]` và `path_results[]`
trỏ tới evidence liên quan qua `evidence_refs[]` theo shared contract. Report là
kết quả máy đọc được; media/logs không thay kết quả check/path.

### SIM-08 — Evaluation

Tách khỏi runtime validation.

**Visual**
- held-out RGB → PSNR/SSIM/LPIPS.

**Pose**
- estimated poses vs `traj_gt` → ATE/RPE.

**Geometry**
- prediction vs `groundtruth_map.ply` → Chamfer/P/R/F1.

**Object**
- locked manual subset → Recall/IoU/AP nếu protocol đủ.

**Path**
- locked start-goal reference → agreement/F1/unsafe false-clear.
- `EvaluationRunner` so sánh observed result từ `ValidationReport` với locked
  expected label sau khi prediction đã cố định.

### SIM-09 — Worker entrypoints

Tách:

```text
simulation-worker validate <scene-ir>
evaluation-runner run <prediction> <protocol>
```

## 4.6 Local vs GPU

**Local**
- collider math;
- preflight;
- report schemas;
- evaluation math;
- small USD tests khi possible.

**GPU/heavy**
- Isaac;
- real scene validation;
- E2E/acceptance.

## 4.7 Tests

**Unit**
- collider;
- collider edit/resize validation;
- transform;
- missing metric/collider preflight;
- object out-of-bounds preflight;
- candidate/report checksum;
- path logic;
- `test_locked_start_goal_results_5_of_5`;
- `test_path_validation_error_is_not_pass`.

**Smoke**
- Minimal USD → Isaac;
- CLEAR case;
- BLOCKED case;
- report generation.

**Contract**
- consume SceneIR;
- luôn produce valid Candidate/Validation report cho release flow;
- produce valid `EvaluationReport` cho locked acceptance/benchmark; ordinary user-upload release có thể không có report nếu không có independent ground truth.

## 4.8 TorWIC rules

Evaluator được đọc:

- held-out RGB;
- `traj_gt.txt`;
- `groundtruth_map.ply`;
- manual annotations;
- locked path references.

Các reference này không được feed ngược vào product prediction.

## 4.9 Definition of Done

- real SceneIR consume được;
- collider tạo được;
- candidate USD build được;
- Isaac load/validation chạy;
- 5/5 locked Start–Goal pairs có kết quả và khớp expected labels;
- locked acceptance/benchmark chạy evaluation protocol và tạo `EvaluationReport` hợp lệ;
- ordinary user-upload release không bị block nếu không có independent ground truth;
- report bind đúng `subject_type`, `subject_id` và `subject_checksum` của protocol;
- `EX-PRODUCT` đọc report trực tiếp.

## 4.10 Evidence

Lưu:

- collider overlay;
- candidate USD;
- Isaac video/screenshots;
- CLEAR/BLOCKED;
- ValidationReport;
- metric tables;
- failure case.

---

# Chương 5. EX-PRODUCT — Product Platform & Orchestration

## 5.1 Mission

Ghép các workers thành một Web product Human-in-the-Loop.

```text
User
→ Web/API
→ Job orchestration
→ EX-REC
→ EX-SCENE
→ EX-SIM
→ Review
→ Release
```

## 5.2 Input / Output

**Input**
- user actions và source-rights attestation;
- manifests/artifact refs;
- SceneIR;
- `ValidationReport` và `EvaluationReport?` theo run type.

**Output**
- project/job lifecycle;
- scene revisions;
- review history và `ApprovalRecord`;
- `ReleaseManifest`;
- final demo workflow.

## 5.3 Stack

Baseline:

- FastAPI
- basic worker/queue
- SSE/WebSocket/polling cho status
- Next.js
- `playcanvas/supersplat` (WebGPU): **Tier-0 Code Donor Candidate** cho 3DGS Visual Editor (chờ qualification spike `PRODUCT-06Q`). Xem [`docs/execution/audits/04_supersplat.md`](./audits/04_supersplat.md).
- Three.js / WebGL/WebGL2: technical views (geometry/point-cloud/collider/transforms) và baseline rendering.
- `playcanvas/splat-transform`: Core utility cho Gaussian artifact validation, SOG conversion và LOD streaming.

Không cần advanced scheduler/multi-tenant infra trong P0.

## 5.4 Implementation Source Map

| Stage | Strategy | Source | Lấy từ framework/library | Team tự code |
|---|---|---|---|---|
| `PRODUCT-01` API | `SELF-CODE` + framework | FastAPI | routing/dependency primitives | project/job/artifact APIs |
| `PRODUCT-02` Job states | `SELF-CODE` | PRD | — | job state machine/persistence |
| `PRODUCT-03` Worker abstraction | `SELF-CODE` | worker contract | — | dispatch interface + queue/CLI integration |
| `PRODUCT-04` Artifact access | `SELF-CODE` | shared contract | — | registry/resolver |
| `PRODUCT-05` Web shell | `SELF-CODE` domain + selective `ADAPT` UI | Next.js + Kiranism dashboard starter; arhamkhnz/shadcndashboard as secondary references | sidebar, layout, table, form, loading/error, upload UI patterns | typed FastAPI client, project/job/artifact workflow and state ownership |
| `PRODUCT-06` 3D Viewer | `SELF-CODE` + `ADAPT` | `playcanvas/supersplat` (Visual 3DGS editor donor) + Three.js/Spark (technical views) | WebGPU splat renderer, camera orbit/fly, selection, layer transform gizmos | SceneIR bridge, Geometry/Collider technical views, artifact resolver |
| `PRODUCT-07` Object actions | `SELF-CODE` + `ADAPT` | `playcanvas/supersplat` interaction machinery + Scene Core | `EntityTransformHandler`, Move/Rotate gizmos, selection, `EditHistory` | domain commands, backend revision persistence, authorization |
| `PRODUCT-07A` Added asset/collider UI | `SELF-CODE` | SceneIR/ColliderSpec contracts | Three.js controls | add/delete obstacle, dimensions, collider adjustment |
| `PRODUCT-08` Orchestration | `SELF-CODE` | shared worker contracts | — | REC→SCENE→SIM control flow |
| `PRODUCT-09` Progress/error/retry | `SELF-CODE` | PRD | — | monitoring + user-facing errors |
| `PRODUCT-10` Review lifecycle | `SELF-CODE` | PRD | — | review state machine + approval gate + `ApprovalRecord` |
| `PRODUCT-11` Release | `SELF-CODE` | release contract | — | exact-candidate sealing + `ReleaseManifest` |
| `PRODUCT-12` Demo route | `SELF-CODE` | locked demo scenario | — | stable presentation path |

Track này tự code **domain workflow riêng của Real2Sim Studio**, nhưng có thể
adapt generic Web UI để không viết lại sidebar, tables hoặc forms. Source links,
take/do-not-take boundaries và license checks nằm trong
[`INTEGRATION_PLAYBOOK.md` §7.1](./INTEGRATION_PLAYBOOK.md). Starter không được
thay product architecture, FastAPI backend hoặc shared contracts.

## 5.5 Implementation steps

### PRODUCT-01 — Mock-first API

Tạo project/job/artifact endpoints bằng fixtures. Input API phải thu source-rights attestation, expose privacy state và không dispatch downstream khi `PrivacyValidationReport` là `QUARANTINED` hoặc chưa đạt trạng thái cần thiết cho public/demo.

### PRODUCT-02 — Job states

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

### PRODUCT-03 — Worker abstraction

Ban đầu mock worker; sau thay real `EX-REC/SCENE/SIM`.

### PRODUCT-04 — Artifact access

API dùng artifact refs/checksums, không local path cá nhân.
Smoke sớm với MP4 fixture qua `artifact://` → resolver → FastAPI `video/mp4`
→ browser playback. Kiểm tra missing/mismatched checksum; chỉ bổ sung HTTP
Range khi playback thực tế cần.

### PRODUCT-05 — Web shell

EX-PRODUCT sở hữu full-stack web: FastAPI/orchestration nằm tại `src/api/` và
`src/services/orchestration/`; Next.js/TypeScript frontend nằm tại root
`frontend/`. Viewer feature canonical placement là
`frontend/src/features/viewer/`.

Tham khảo [`Kiranism/next-shadcn-dashboard-starter`](https://github.com/Kiranism/next-shadcn-dashboard-starter)
để adapt có chọn lọc shell, navigation, table/form và loading/error states;
[`arhamkhnz/next-shadcn-admin-dashboard`](https://github.com/arhamkhnz/next-shadcn-admin-dashboard)
và [`shadcndashboard/next-shadcn-dashboard`](https://github.com/shadcndashboard/next-shadcn-dashboard)
chỉ là nguồn pattern phụ (đặc biệt file-dropzone UI). Không kéo Clerk,
organization/billing, SaaS domain hoặc Next.js business API vào Real2Sim.

Tối thiểu:

- project;
- job;
- scene viewer;
- validation;
- review.

### PRODUCT-06 — Viewer

Load fixture SceneIR.

Dùng [Three.js docs/examples](https://threejs.org/docs/) cho controls, picking,
loaders và layers. [React Three Fiber](https://github.com/pmndrs/react-three-fiber)
là library candidate sau khi kiểm tra version/scaffold, không bắt buộc.
[Spark](https://github.com/sparkjsdev/spark) là P0 qualification candidate cho
Gaussian view; [Spark + Next.js example](https://github.com/sparkjsdev/spark-react-nextjs)
chỉ là reference về client-only setup. [Potree](https://github.com/potree/potree)
chỉ là reference cho point-cloud LOD khi cần. Chưa repo nào được coi là đã
chứng minh tương thích với output Brush thực tế.

Hỗ trợ:

- render real 3DGS từ Brush `VisualArtifact` trên Primary RGB Scene; mock hoặc PLY point cloud không thay thế;
- render geometry mesh, point cloud, collider và canonical SceneObject transforms;
- click chuyển giữa 3DGS Visual, Geometry mesh, Point Cloud và Collider trên cùng SceneIR revision;
- orbit/pan/zoom;
- select;
- hide/show;
- Visual/Geometry/Collider toggles;
- transform editing.

P0 dùng Next.js + Three.js + WebGL/WebGL2 baseline. Chọn Gaussian renderer sau
qualification bằng output Brush thực, kiểm tra artifact checksum, format,
coordinate conversion và browser capability; nếu renderer dùng WebGPU mới cần
WebGPU capability check. Nếu Visual không có/không tương thích, hiển thị lỗi và
cho phép inspect các view khác nhưng không claim AC-11 pass. Cleanup GPU
resources/listeners/workers khi đổi view hoặc unmount. Mesh/point-cloud fixture
không phải Brush compatibility proof.

### PRODUCT-07 — Object actions

Expose UI cho operations P0 do Scene Core cung cấp.
Đây là HITL #1 cùng các thao tác collider của PRODUCT-07A: `Save Draft` persist
SceneIR revision ở backend, còn `Submit for Validation` gửi revision hiện tại
để preflight, candidate build và Isaac validation. Hai hành động không approve.

### PRODUCT-07A — Added asset và collider controls

UI phải hỗ trợ add/delete obstacle, primitive dimensions hoặc asset-specific size parameters, collider type/dimensions/local transform và hiển thị validation error. Mọi edit persist qua backend SceneIR revision, không chỉ giữ trong React state.

### PRODUCT-08 — Real worker orchestration

```text
REC success
→ SCENE

SCENE success
→ SIM
```

Không chạy downstream nếu required artifact thiếu.

### PRODUCT-09 — Progress/error/retry

Hiển thị stage/status/error rõ ràng.

Không fake percentage nếu backend không có progress thật.

### PRODUCT-10 — Review lifecycle

```text
DRAFT
→ PROCESSING
→ CANDIDATE_READY
→ VALIDATING
→ READY_FOR_REVIEW
├── APPROVED → RELEASED
└── REJECTED → new DRAFT revision
```

Reject phải lưu reason. `REJECTED` không được release trực tiếp; mọi edit sau validation tạo revision `DRAFT` mới và invalidates Candidate/Validation/Evaluation reports cũ.
Đây là HITL #2: chỉ mở final review tại `READY_FOR_REVIEW` khi blocking checks
applicable đạt. Web hiển thị đúng scene/candidate, ValidationReport, replay,
screenshots, logs và warnings (kể cả media unavailable) qua artifact refs;
Reviewer approve/reject đúng candidate đã validation. `CANDIDATE` không phải
review state mới. Primary Demo E2E evidence nằm tại PRODUCT-12.

### PRODUCT-11 — Release

Approve chỉ seal **exact CandidatePackage đã validation**.

Release chỉ được tạo từ `ApprovalRecord` hợp lệ, bind đúng `candidate_checksum` và `validation_report_checksum`; output phải conform `ReleaseManifest` normative schema.

Edit sau validation → new DRAFT revision.

### PRODUCT-12 — Demo route

Chuẩn bị một route ngắn, ổn định cho pitching.

## 5.6 Local vs GPU

Hầu hết track này chạy local.

GPU chỉ được dùng gián tiếp qua workers.

## 5.7 Tests

**Unit/API**
- job transitions;
- failed stage ≠ success;
- retry;
- edit invalidates validation;
- approval requires validation;
- release candidate checksum;
- `test_editor_cannot_approve`;
- `test_review_decision_binds_candidate_checksum`;
- `test_reviewer_edit_invalidates_validation`;
- `test_rejected_revision_cannot_release`;
- `test_rejection_requires_reason`;
- `test_rejected_revision_returns_to_new_draft`.

**Viewer smoke**
- load fixture;
- load geometry/point-cloud/collider fixture;
- select;
- toggle;
- transform edit;
- add/delete obstacle;
- edit collider dimensions/local transform.

**Contract**
- consume SceneIR/ValidationReport và `EvaluationReport?` theo run type;
- produce lifecycle/release records.

## 5.8 TorWIC rules

Web product chỉ dùng:

- derived demo input;
- product artifacts;
- reports.

Không trực tiếp đọc evaluation GT để tạo scene.

## 5.9 Definition of Done

- project/job chạy;
- real workers được orchestrate;
- status/error/retry có;
- viewer đạt minimum controls;
- browser render được P0 geometry/point-cloud/collider refs và bind đúng checksum;
- edit persist;
- validation hiển thị;
- approve/reject/release đúng lifecycle;
- full demo route chạy được.

## 5.10 Evidence

Lưu:

- job screens;
- viewer interactions;
- edit before/after;
- validation UI;
- review/approve/reject;
- release;
- error/retry;
- final E2E screen recording.

---

# Chương 6. Handoff cuối cùng giữa 4 tracks

Luồng chuẩn duy nhất:

```text
InputManifest
    ↓
EX-REC
    ↓
ReconstructionBundle
    ↓
EX-SCENE
    ↓
SceneIR
    ↓
EX-SIM
    ↓
Physics-enriched SceneIR
CandidatePackage
ValidationReport
EvaluationReport? (required cho locked acceptance/benchmark)
    ↓
EX-PRODUCT
    ↓
Human Review
    ↓
ApprovalRecord
    ↓
Approved Release
```

Một track chỉ được coi hoàn thành handoff khi:

- output validate contract;
- artifact được publish;
- checksum/provenance có;
- consumer đọc trực tiếp;
- không cần sửa file bằng tay.

---

# Chương 7. Quy tắc khi gặp blocker

Nếu muốn đổi từ `REUSE` sang `SELF-CODE`, đổi backend, hoặc đưa một repo `REFERENCE` thành runtime dependency:

1. phải chứng minh backend hiện tại là blocker P0;
2. kiểm tra license/runtime;
3. giữ nguyên output contract;
4. thông báo downstream consumer;
5. không đổi chỉ vì repo mới “có vẻ tốt hơn”.


## 7.1 Reconstruction geometry yếu

Ưu tiên:

1. fix input/pose;
2. simplified geometry;
3. fallback backend đã cho phép;
4. dùng LiDAR geometry trong scoped evidence khi phù hợp.

## 7.2 SAM2/object association chưa tốt

Giữ:

```text
automatic candidate
+
Human Correction
```

Không research perfect segmentation.

## 7.3 3DGS trong Isaac quá khó

Dùng:

```text
Web → real 3DGS VisualArtifact + các view kỹ thuật
Isaac → mesh + collider
```

## 7.4 GPU thiếu

Tiếp tục local code/tests/fixtures; chỉ xếp hàng heavy smoke/E2E lên GPU.

## 7.5 Trễ tiến độ

Cắt theo thứ tự:

```text
P2
→ P1
→ polish
→ documented fallback
```

Không âm thầm bỏ P0.

---

# Chương 8. Track completion checklist

Một track chỉ được coi “done” khi có đủ:

```text
implementation
+
tests
+
valid output artifact
+
downstream handoff
+
evidence
```

“Code xong trên máy tôi” không được tính là hoàn thành.
