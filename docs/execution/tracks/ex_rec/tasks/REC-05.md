# REC-05 — Coarse Voxel Geometry & Collision Mesh via splat-transform (OpenMVS as Fallback)

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |


## 2. Goal

Tạo coarse voxel geometry & collision mesh artifact (`collision.glb`) từ Brush 3DGS thông qua `splat-transform` GPU voxelization và robot capsule carving, phục vụ trực tiếp cho collider downstream trong MVP. OpenMVS giữ vai trò Secondary Fallback.

## 3. Why This Task Exists

Cung cấp hình học va chạm tĩnh và phân tách không gian lưu thông cho robot mà không cần gánh nặng build native C++/CUDA và rủi ro bản quyền AGPLv3 của OpenMVS. Vẫn bảo toàn nguyên tắc bất biến `Visual ≠ Geometry ≠ Physics`.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md), [Audit #4a](../../../audits/04a_splat_transform.md).

## 4. Dependencies

- REC-04 output: Brush `visual.ply`.
- REC-06 pha xác nhận anchor/transform sang canonical meter đã hoàn tất; không
  đợi final verification/DONE của REC-06 (xem Integration §3.3).
- REC-03 COLMAP model chỉ cho OpenMVS fallback, không là direct input của primary voxel pipeline.
- `splat-transform` (v3.6.6) Node.js/GPU environment.
- Locked OpenMVS Docker environment chỉ khi kích hoạt fallback nếu spike không đạt;
  không chặn implementation/qualification của primary SplatTransform adapter.

Tách dependency theo work package, không theo thứ tự số task:

- **Adapter/unit/synthetic GPU:** fixture có kích thước biết trước + pinned runtime;
  thực hiện được ngay, không cần giả lập confirmation record của REC-06.
- **Real metric-aware Aisle_CW spike:** REC-04 source + REC-06 confirmed canonical
  metric transform/anchor + derivative áp transform đúng một lần + locked robot
  capsule + valid walkable seed. Phần này đang chờ prerequisites.
- **Final publication:** geometry được REC-06 cross-check cùng pose/visual trước
  REC-10. Không giữ ordering cũ `REC-05 arbitrary-unit mesh → REC-06 lần đầu scale`
  cho primary voxel/capsule tính theo mét; không tạo dependency vòng đòi REC-06 DONE.

## 5. Input Contract

- REC-04 Brush `visual.ply` (đã qua structural validation).
- Confirmed metric transform/anchor record và checksummed source refs; tạo working
  derivative theo mét, không sửa master PLY và không coi arbitrary SfM unit là mét.
- Robot footprint config: capsule height, capsule radius cho indoor carving.
- Voxel resolution config: mặc định `0.05m` (5cm).

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- `GeometryArtifact` trỏ tới `collision.glb`.
- Voxel metadata: resolution, bounding box, flood fill seed position.
- Provenance của metric derivative và transform đã áp dụng để REC-06 tránh double scaling.
- Geometry/runtime/config provenance và SHA-256 checksum.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/adapters/`
- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

**Primary P0 Strategy (`playcanvas/splat-transform` v3.6.6):**
- Trích xuất GPU Voxelization từ Gaussian density field:
  - `--filter-cluster` & `--seed-pos`: Loại bỏ các cụm voxel trôi nổi (floaters), chỉ giữ cụm liên thông.
  - `--voxel-carve`: Dùng capsule robot kho khoét khoảng không di chuyển (`navigable cavity`).
  - `--collision-mesh smooth`: Marching Cubes kết hợp coplanar face merge tạo `collision.glb` watertight.
- **Hai Safeguards bắt buộc:**
  - ❌ **Không dùng mesh làm sàn robot:** Mặt sàn sẽ do `SIM-01` tạo bằng `USD Analytic Ground Plane` phẳng tuyệt đối.
  - ❌ **Chân kệ / vật thể mỏng:** Hỗ trợ cơ chế thay thế bằng Box Collider (`SIM-02` / Studio HITL).

**Secondary Fallback Strategy (`cdcseacave/openMVS`):**
- Nếu bài test Spike trên `Aisle_CW` không thỏa mãn điều kiện di chuyển của robot, kích hoạt fallback containerized OpenMVS (`InterfaceCOLMAP` $\rightarrow$ `DensifyPointCloud` $\rightarrow$ `ReconstructMesh`).

## 9. Qualification Spike trên `Aisle_CW`

### Implementation Plan — strict occupancy guard / portable publication

- Bootstrap: `feat/ex-rec-pipeline`, clean worktree tại `1cc26db`; ownership chỉ
  EX-REC adapters/rgb/tests và execution records. Authority: ADR 0001 seed đề
  xuất + bắt buộc bounds/clearance; Integration §3.3, Contract và task I/O.
- ADAPT minimal octree reader từ supersplat-viewer
  `c52f5258df424635323f26aaeebe51361dc0f8e6`, MIT; giữ attribution/license.
  Pinned SplatTransform 3.6.6/afbc281 `carve` dùng separable box dilation,
  `ceil(radius/res)` và `ceil(height/(2*res))`, tự relocate blocked seed.
- Trước carve, xuất occupancy không carve từ cùng immutable cluster/config,
  validate binary/tree, kiểm toàn bộ rounded kernel và bounds. Reject invalid
  seed trước collision process, không công nhận relocation là seed validation.
- Hoàn thiện attempt namespace, publish cả voxel JSON/binary và kiểm refs/checksum
  tại consumer. Không sửa shared schema hoặc code của track khác.
- Proof: valid/blocked/out-of-bounds/corrupt-tree unit tests, adapter/publication
  regression, native synthetic GPU khi runtime khả dụng. Real Aisle_CW vẫn cần
  confirmed correspondence + independent measurement/tolerance; không bịa scale.

### Implementation Plan — controlled seed relocation / verifiable clearance

Owner-approved 2026-09-27, supersedes "reject là hành vi duy nhất" của đợt trước.

- Authority: ADR 0001 §"quy chuẩn hạt giống" amendment (seed relocation có kiểm
  soát). Task file này không tự thêm lựa chọn thứ ba ngoài ADR đã duyệt.
- Bổ sung `VoxelConfig.max_seed_relocation_m` (mặc định 1.0m) vào checksum
  config, không sửa shared schema trong `src/models/contracts/`.
- `adapters/voxel_seed_search.py`: seed bị chặn được tìm lại bằng **BFS 6 hướng
  trên tập ô tự do** thay vì quét vỏ cube của `findNearestFreeCell`. Ràng buộc:
  ngưỡng mét, ngưỡng số bước thoát vật cản, tie-break tất định, và reject khi
  không có ứng viên.
- `adapters/voxel_octree.py`: thêm `solid_mask()` để trích occupancy thành
  mảng dense một lần thay vì gọi box query hàng nghìn lần. Layout fixture
  phải theo đúng `flattenDenseLevels` (BFS theo level), không phải DFS.
- Clearance evidence ghi **cả hai** điểm: `requested_seed_world`,
  `accepted_seed_world`, khoảng cách, số bước thoát, ngưỡng đã áp dụng và
  checksum occupancy đã dùng làm căn cứ.
- Publication: `occupancy.voxel.json`, `occupancy.voxel.bin`, `seed-clearance.json`
  được publish qua `GeometryPublisher`; `GeometryResolver.load_seed_clearance()`
  dựng lại kernel từ bytes đã publish và **tự kiểm lại**, không đọc `status`
  của producer.
- `verify_seed` giữ nguyên fail-loud ở product scope. Đợt trước đã đổi thành
  optional veto; đã revert vì callback biểu diễn policy (frame nguồn, capsule
  đã khóa, vùng làm việc) mà adapter không thể biết.
- Không build lại splat-transform từ source. Voxel internals không nằm trong
  public export nên chỉ CLI gọi được; phạm vi audit export chưa dùng nằm ở
  follow-up bên dưới, chưa cấp task ID.

### Evidence — controlled seed relocation + verifiable clearance (2026-09-27)

- `pytest tests/test_reconstruction/ -q`: **443 passed, 22 skipped** (skip là
  GPU opt-in). Trong đó `test_rec05_clearance.py` **22 passed**:
  exact mixed-leaf bits, solid sentinel, 8 chế độ corrupt tree, relocation ghi
  đủ hai điểm, xác định, từ chối khi vượt ngưỡng, từ chối khi vùi trong tường
  dày, confinement theo vùng liên thông, ba seed ngoài bounds, và dừng trước
  carve ở tầng adapter.
- Publication/consumption: `test_rec05_product_pipeline.py` thêm
  `test_published_clearance_is_independently_reverifiable` cùng bốn negative
  case (swap binary, swap metadata, sai artifact type, kernel mâu thuẫn với
  occupancy) và `test_product_scope_still_fails_loud_without_seed_policy`.
- Native GPU, cùng pinned runtime `splat-transform 3.6.6 afbc281`, Quadro T2000:
  `REC05_TEST_GPU=1` + `VK_ICD_FILENAMES=.../nvidia_icd.json` trên
  `test_rec05_similarity_gpu.py` + `test_rec05_real_codec.py`: **7 passed,
  43.55s**. Seed cũ `(3.25,2.5,1.25)` từng làm test fail nay **relocate thành
  công** trên occupancy GPU thật: `relocates=true`, distance trong ngưỡng, và
  receipt giữ cả seed đã yêu cầu lẫn seed được chấp nhận.
- Sửa 2 lỗi thật phát hiện khi làm việc này, đều có proof hồi quy:
  `_overlaps` trong octree reader dùng sai upper bound nên `solid_mask` trả
  rỗng với cây lớn; và `_window_any` bỏ sót ô khi một trục có extent 0.
  Cả hai được kiểm bằng so sánh với box oracle trên nhiều kích thước.
- **Sửa lỗi thông tin trong evidence cũ:** dòng "Callback `verify_seed` chỉ là
  optional policy veto" ở block trên **không còn đúng** sau khi revert.
- Giới hạn: đây vẫn là synthetic technical proof. "Capsule vừa" + "cùng vùng
  liên thông" **không** chứng minh robot đi tới được; `CLEAR/BLOCKED` là của
  `SIM-02`. Real `Aisle_CW` spike và EX-SIM acceptance vẫn chưa đạt.



- Adapter bắt buộc pre-carve occupancy từ cùng cluster/resolution/opacity; strict
  little-endian octree reader kiểm graph/pointers/counts/depth trước box query.
  Không dùng Euclidean radius thay native separable dilation. ~~Callback `verify_seed`
  chỉ là optional policy veto~~ — đã lỗi thời, xem block Evidence kế tiếp.
- `pytest test_rec05_clearance.py test_rec05_adapter.py test_rec05_product_pipeline.py`
  trong `tests/test_reconstruction/`: **32 passed**. Có corruption ngoài query,
  solid sentinel, low/high mixed masks, capsule corner, bounds và callback bypass.
- Native GPU command: `env -u DISPLAY -u WAYLAND_DISPLAY
  VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json REC05_TEST_GPU=1`
  cùng pinned `REC05_TEST_SPLAT_MODULE` / `REC05_VOXEL_CLI` /
  `REC05_VOXEL_MODULE_PATH` ở `data/rec04_runtime/node_modules/@playcanvas/splat-transform`,
  `.venv/bin/pytest tests/test_reconstruction/test_rec05_similarity_gpu.py
  tests/test_reconstruction/test_rec05_real_codec.py -q`: **7 passed, 63.47s**.
  CLI `--list-gpus`: `[0] Quadro T2000`, splat3.6.6 afbc281.
- First run **1 failed / 6 passed**: old synthetic transformed seed `(3.25,2.5,1.25)`
  intersects native floor voxel y=1.1 after rounding. Kept as negative assertion;
  positive uses known synthetic room center `(3.25,2.5,1.375)` with measured free
  kernel. No product robot/seed/threshold changed to make test green.
- Two passes intentionally reuse upstream voxelizer, no patched npm bundle.
  Extra voxelization cost and runtime-pin dependency remain; this is synthetic
  technical proof, not real Aisle_CW or physics acceptance.


### Implementation Plan / Bootstrap 2026-09-26

Audit/rework 2026-09-27: replace `gaussian_scale.py` scalar buffer patch/silent
copy bằng pinned SplatTransform 3.6.6 afbc281 (MIT) streaming reader/writer và
`Transform`/`bakeTransform` semantics. Đã đọc installed `chunk/source.d.ts`,
`ops/bake-transform.d.ts`, `process-source.d.ts` và bundled Transform/mul source.
Full similarity áp xyz + quaternion + log-scales + SH; PLY storage transform
`Rz(180°)` phải conjugate/compose đúng, không thêm flip vào canonical world.
Giữ immutable master, separate derivative/receipt/hash, refuse malformed input
và source/confirmation mismatch. Proof CPU native codec với nonidentity R/t,
unit-scale R/t, SH rotation, invalid input; fixture process không là math proof.

### Audit evidence 2026-09-27 — full similarity + real synthetic GPU

- Implemented `SplatTransformSimilarityAdapter` và Node public `ChunkSource`
  wrapper. Writer delta `PLY^-1 * PLY * metric` áp đúng `sRp+t` trên raw storage;
  upstream xử lý quaternion, covariance log-scales và SH, không tự viết codec.
  Separate derivative/receipt/source/output SHA-256; input master giữ nguyên.
  Voxel product path dùng toàn transform kể cả scale=1, kiểm master checksum bind
  confirmation, report và geometry provenance giữ full transform/evidence kind.
- `GeometryExecutionRequest` default product gọi `require_real` và injected
  seed/capsule verifier. Synthetic fixture phải chọn scope riêng; không dùng flag
  fixture để bypass real scene gate. Actual clearance implementation còn pending.
- CPU native: `REC05_TEST_SPLAT_MODULE=data/rec04_runtime/node_modules/@playcanvas/splat-transform
  .venv/bin/pytest tests/test_reconstruction/test_rec05_scale.py -q`:
  **9 passed** (6.39s), gồm scale 1/2/0.5 với Rx90 + translation, all256 points,
  log-scales/quaternions, SH l=1 basis rotation, malformed/plain/nonfinite/truncated
  input rejects; immutable source hash verified.
- GPU native: `REC05_TEST_GPU=1` cùng `REC05_VOXEL_CLI` và
  `REC05_VOXEL_MODULE_PATH` trỏ pinned runtime; chạy
  `pytest tests/test_reconstruction/test_rec05_similarity_gpu.py -q`:
  **1 passed** (4.45s), Intel UHD630 index0, Node24.11.1, splat3.6.6 afbc281.
  Fixture `s=0.5, Rz90, t=(4,2,1)` → voxel/carve .05m: 2703→2702 splats,
  48vertices/88triangles, boundary/nonmanifold/degenerate counts đều0.
  Collision checksum `sha256:bd47727983e6df9ca1917c5191ba1d293dd099e0d6d872a63e997b5c28cef1a4`.
  Local generated evidence snapshot: `data/rec05_similarity_audit_20260927/` (ignored).
- All quantities/capsule settings trên chỉ cho synthetic fixture; chưa có real
  Aisle_CW metric confirmation, canonical visual publication/independent-distance
  acceptance hay Isaac qualification. Không đổi toàn REC-05 thành DONE/BLOCKED.
- Final regression run: bật cả `REC05_TEST_GPU=1`, `REC05_TEST_SPLAT_MODULE`
  và pinned `REC05_VOXEL_*` rồi `pytest tests/test_reconstruction/ -q`:
  **353 passed, 5 skipped** (82.71s). Five skips là opt-in ngoài REC-05 đang chạy,
  không claim đã thực hiện. Ruff check/format **186 files pass**; Node `--check`
  hai bridge mới pass; AST <=30 lines/<=3 args và `git diff --check` pass.

### Historical bootstrap 2026-09-26 — không phải current audit status

- Task capsule: REC-05 owns voxel/collision adapter and geometry provenance;
  authority Integration §3.3, Contract §4, Track Guide REC-05/06, this task and
  audits #4a/#7. Branch `feat/ex-rec`; REC-04 source/tests/task evidence are
  existing intended work. No EX-SIM/SCENE/PRODUCT or shared schema edits.
- REC-04 real GPU producer verified (65 frames, 6,202 splats). REC-06 remains
  TODO; no confirmed real anchor/transform or robot capsule config found.
  Contract lists anchor as human-provided later milestone. Do not infer meters
  from arbitrary SfM or use evaluation-only trajectory/reference geometry.
- Read actual splat-transform 3.6.6 source maps/types + OpenMVS app source and
  licenses before code. Reuse GPU voxelizer, connected cluster, capsule carve,
  Marching Cubes and GLB writer; keep OpenMVS process boundary fallback.
- First independent work: explicit typed voxel config/command builder, source
  checksum and metric-input guard, process/output validation and synthetic GPU
  smoke. Record native Y-up versus canonical Z-up conversion explicitly.
- Do not invent REC-06 confirmation artifact schema: integrate via producer
  boundary once its confirmed record exists. Shared contracts currently have
  `ProductArtifactRef` for RGB geometry, no standalone `GeometryArtifact` model.
  Consumer-facing canonical publication waits for this metric producer boundary.
- Proof: missing/unconfirmed/mismatched metric input rejected before process,
  explicit capsule/seed/resolution, upstream CLI qualification, nonempty mesh
  and topology on synthetic smoke; real three-resolution Aisle_CW and Isaac
  CLEAR/BLOCKED remain separate required acceptance, not fixture claims.

### Resume / source audit 2026-09-26

- VERIFIED: bootstrap tại `feat/ex-rec`, HEAD `f73665d`, working tree sạch.
  User yêu cầu tiếp tục REC-05 và commit từng thay đổi nhỏ có ý nghĩa.
- Installed `@playcanvas/splat-transform` 3.6.6 (`afbc281`), MIT, Node >=22;
  actual CLI help và `--list-gpus` xác nhận Intel UHD 630 (index 0). Audit
  source maps của package pin: `writers/write-voxel.ts`, `collision-glb.ts`,
  `voxel/carve.ts`, `filter-cluster.ts`, `data-table/transform.ts`.
  CLI phải xuất `.voxel.json`; `.collision.glb` là output đi kèm. Ghi thẳng
  `.glb` không gọi pipeline voxel collision. Upstream carve có thể warning rồi
  skip khi seed nằm ngoài grid hoặc không tìm được free cell: adapter phải reject
  trường hợp này dù process exit 0.
- OpenMVS source `e23d25f0a9bd93ec056d4ee7fae2b2aaee80e566`, AGPL-3.0;
  inspect CLI tại `apps/{InterfaceCOLMAP,DensifyPointCloud,ReconstructMesh}`.
  InterfaceCOLMAP cần undistorted camera/images. Re3Sim audit §4/19 là reference
  orchestration; không copy upstream source. Fallback runtime chưa qualified.
- Plan cụ thể: typed config và command builder; subprocess có timeout/log;
  strict input checksum + injected metric verifier (chưa triển khai producer
  REC-06); isolated workspace; Gaussian validation bằng pinned upstream;
  kiểm metadata/binary/GLB topology và source immutability. Native voxel/GLB là
  Y-up: record rõ phép đổi từ canonical Z-up và ngược lại, không tự gọi output
  native là shared canonical geometry.
- Thêm tests positive/negative cho config, missing/unconfirmed metric gate,
  tampered input, process failure/timeout, skipped carve và malformed output.
  Synthetic scene có kích thước biết trước dùng để qualification GPU và topology;
  không cấp confirmation giả cho Aisle_CW. Publication/REC-06 record schema và
  consumer acceptance chờ producer thật. Mỗi nhóm thay đổi được validate rồi commit.

### User clarification / implementation boundary 2026-09-26

- REC-06 chưa có record chính thức; user xác nhận không tự bịa scale. Giữ toàn
  task `IN_PROGRESS`, chỉ real spike ghi trạng thái chờ dependency.
- Hoàn thiện tool pipeline bằng `run_synthetic(SyntheticVoxelRequest, workspace)`:
  entrypoint explicit synthetic, không nhận `metric_confirmed` mode, không có
  product publication hoặc tự tạo confirmation schema. Đây là refinement của
  ý định injected metric verifier ở bootstrap: chưa triển khai verifier giả khi
  producer/record REC-06 chưa tồn tại.
- Sau REC-06: implement checksum-bound confirmed-record resolver, tạo metric
  derivative từ immutable master và kiểm applied-transform provenance/double
  scaling rồi mới expose product entrypoint. Synthetic rotation/unit preservation
  tests hiện tại không thay cho handoff test REC-06 thật.

Trước khi chấp nhận primary geometry; giữ OpenMVS fallback nếu spike không đạt:
1. Chạy 3 cấu hình voxel resolution trên file Brush PLY của `Aisle_CW`:
   - Config A: `0.10m`
   - Config B: `0.05m` (Baseline)
   - Config C: `0.025m`
2. Kiểm tra 4 tiêu chí cốt lõi:
   - Aisle không bị ghost-block.
   - Chiều rộng lối đi không bị phình/hẹp quá sai số an toàn robot ($10-20\text{cm}$).
   - Kệ hàng và pallet chính tồn tại đúng vị trí.
   - Chạy test động trong Isaac Sim với sàn USD Plane: kiểm tra các path `CLEAR / BLOCKED`.
3. **Quy chuẩn thông số Voxel Carving (theo ADR 0001):**
   - `navigation_seed_world`: đề xuất từ camera đầu **đã registered**, không bắt
     buộc Frame 0, sau confirmed metric/world transform. Camera center chỉ là
     candidate; phải giữ source ref/checksum/frame ID và kiểm bounds + capsule
     clearance. Seed không hợp lệ phải reject hoặc yêu cầu chọn lại; không auto-pass,
     tự suy camera-to-ground offset hoặc coi upstream relocate/skip là valid seed.
   - Hình trụ ảo đại diện cho robot AMR: Bán kính $r = 0.35\text{ m}$, chiều cao $h = 1.20\text{ m}$.
4. Nghiệm thu: Hành vi va chạm đúng trong Isaac Sim ➔ **PASS**.

## 10. Tests

- Command/config builder unit tests cho `splat-transform`.
- Missing/invalid PLY negative tests.
- Missing/unconfirmed anchor phải chặn metric voxelization; test scale propagation
  và double-scaling với REC-06.
- Synthetic/small PLY to `collision.glb` smoke test và topology verification.
- Fallback OpenMVS adapter smoke test.

## 11. Definition of Done
 
- [x] Geometry/Collision artifact `collision.glb` được tạo bằng `splat-transform` adapter.
- [x] Format/coordinate metadata/checksum/provenance đầy đủ theo `RgbGeometry` / `GeometryArtifact`.
- [ ] Spike trên `Aisle_CW` và fixture được thực hiện và ghi nhận kết quả rõ ràng.
- [x] Artifact đủ cho EX-SIM (`SIM-02`) consume làm primary environment collider.
- [x] Focused tests pass; evidence/limitations được ghi đầy đủ.

### Phân rã DoD — phần contract vs phần physics (2026-09-27)

Mục "Artifact đủ cho EX-SIM consume" trước đây bị gộp chung với nghiệm thu physics,
nên không biết chỗ nào thật sự còn thiếu. Tách rõ:

- **Phần contract (đóng ở đây):** `GeometryArtifact` là shared contract, có validator
  ép `metric_scale=CONFIRMED`, cấm dependency `GROUND_TRUTH`, buộc `relocates` khớp
  hai điểm seed và giữ relocation trong contract. Trước đó REC-05 publish
  `artifact_type="RgbGeometry"` tự do, không có schema, nên EX-SIM không consume được.
- **Phần spike (còn thiếu, chờ REC-06):** voxelize/carve `Aisle_CW` thật ở 3 resolution
  và đo 4 tiêu chí hình học ở §9. Cần `MetricConfirmation` có
  `evidence_kind="real_measurement"`.
- **Phần physics (không thể đóng trên máy này):** `CLEAR/BLOCKED` trong Isaac Sim thuộc
  `SIM-06`, và máy này **không có Isaac Sim** (`import isaacsim` fail, không có
  `/opt/isaac*`). Không được coi DoD của REC-05 là đóng khi phần này chưa qualified ở
  nơi có Isaac; cần tách acceptance sang `SIM-06` hoặc chấp nhận ground-plane analytic
  check thay Isaac, và đó là quyết định của owner chứ không phải task tự quyết.

## 12. Result / Evidence

### 2026-09-30 — REC-05 chạy trong worker Studio trên Aisle_CW thật

Chạy thật 2026-09-30 trên `job-ac2bfd924cc6` (video Aisle_CW, GPU Quadro T2000, adapter index 1),
branch `feat/studio-integration`. Xác nhận tỉ lệ bằng 7 điểm tự chọn trên sàn LiDAR (ADR 0004 §6).
- Profile `configs/product/geometry_v1.json`: voxel 0,05 m, capsule OTTO 0,461/0,308 m.
- **Hiệu chỉnh (không còn dùng số smoke):** 3DGS preview thưa (98.611 Gaussian) làm
  `--filter-cluster` xoá gần hết ở mọi mức (0,1 m: 2.040 khối; 1,0 m upstream: 29 khối, còn ~1k);
  Brush còn sinh Gaussian rác cách hàng trăm mét (lưới 896×529×282 m). Thay bằng
  (1) `--filter-box` = khung camera ± 6 m ngang, −0,5…4 m cao, (2) `--filter-floaters`
  0,05/0,1/0,004 (mặc định upstream) → giữ 75.385/98.611 Gaussian.
- Seed = camera đầu hạ xuống sàn: chấp nhận tại chỗ (−1,515; 0,012; 0,204), không dời.
- Collision GLB: 224.745 tam giác, 112.733 đỉnh; bỏ 397 tam giác diện tích 0 của upstream
  (derivative; tool output giữ nguyên). Sau khi bỏ còn 1.183 cạnh biên dọc chỗ tam giác
  suy biến (khe rộng 0) và 3 cạnh non-manifold — chưa kiểm ảnh hưởng trong Isaac.
- Artifact: `rec05/81a7b1b1…/collision.glb` (`sha256:d616e6f8e84a…`).
- Tests: `test_rec05_collision.py` (10), REC-05 cũ 103 passed.
- Còn thiếu: 3 mức resolution, kiểm lối đi/ghost-block, Isaac CLEAR/BLOCKED (EX-SIM).


### Follow-up chưa cấp task ID — audit splat-transform public export chưa dùng (2026-09-27)

Đây là **proposal**, chưa phải authority. Không tự cấp task ID theo quy tắc harness;
cần track owner cấp ID và xếp milestone.

Sau khi kiểm `dist/index.mjs` của pinned `@playcanvas/splat-transform` 3.6.6, package
chỉ export **61 named export**. Toàn bộ voxel/collision internals — `carve`,
`twoLevelBFS`, `SparseVoxelGrid`, `gpuDilate3` — **không** nằm trong danh sách đó;
`dist/lib/voxel/` chỉ còn `.d.ts` không có implementation `.mjs`, và `exports` map
chỉ mở `.`, `./worker`, `./viewer-settings`, `./lib/*`. Kết luận: muốn gọi trực tiếp
`carve()` thì phải clone repo GitHub và build từ `src/` (MIT cho phép) — chưa đáng
để làm vì CLI đã chạy carve thật và test pass.

Phần **đáng** làm là các public export chưa dùng, cần khảo sát theo từng track:

| Export | Có thể thay gì | Track sở hữu |
|---|---|---|
| `loadCameraTrack` | đọc camera pose COLMAP thay code tự viết | `REC-06` |
| `decimateSourceAdaptive`, `selectLod`, `stackLods`, `sortMortonColumns` | LOD/decimation | `REC-04` |
| `writeSog`, `writeLodSource`, `writeSpz` | đóng gói SOG (P0 web format) | `REC-04` |
| `writeVoxel` | voxel writer, có thể bỏ phụ thuộc output của CLI | `REC-05` |
| `createViewer` | **chưa xác minh** có phải viewer core của supersplat-viewer không; nếu đúng thì liên quan trực tiếp `PRODUCT-06` | `EX-PRODUCT` |

Điều kiện: mỗi mục phải có qualification proof trước khi thay code đang chạy, và
`createViewer` phải verify trước khi đưa vào bất kỳ baseline EX-PRODUCT nào.

### Checkpoint 2026-09-26 — DONE, product pipeline and artifact publication

Historical claim, superseded by audit 2026-09-27: synthetic GPU fixture và
publication tests không thay real Aisle_CW metric-aware spike/EX-SIM acceptance.
Owner robot dimensions đã có (01305c9); còn real confirmation, valid capsule
seed/clearance và downstream runtime proof. Không đánh dấu toàn REC-05 BLOCKED.

**Implemented / VERIFIED:**
- `src/services/reconstruction/adapters/voxel.py`:
  - Thêm `ProductVoxelRequest` ràng buộc chặt chẽ với `MetricConfirmation` từ REC-06.
  - Thêm `run_product(request, workspace)` trên `SplatTransformVoxelAdapter`, kiểm tra source checksum và chống double-scaling (`applied_record_checksum`).
- `src/services/reconstruction/rgb/geometry/geometry_publication.py`:
  - `GeometryPublisher`: xuất bản `collision.glb` thành `ProductArtifactRef` (`artifact_type="RgbGeometry"`, `producer_stage=StageId.RGB_GEOMETRY`), kèm `geometry.voxel.json` (`VoxelMetadata`).
  - `GeometryResolver`: đọc và xác thực tính toàn vẹn của geometry artifact refs.
  - `RgbGeometryService`: service điều phối toàn bộ pipeline, kiểm tra điều kiện tiên quyết (confirmation đã `CONFIRMED`, visual master khớp anchor master, seed proposal hợp lệ), gọi voxelizer adapter và xuất bản artifacts.
- `tests/test_reconstruction/test_rec05_product_pipeline.py`:
  - 5/5 test cases pass: luồng thành công với provenance chuẩn, từ chối double scaling, từ chối visual master không khớp, từ chối seed proposal sai checksum, từ chối source PLY bị sửa đổi.
- Chạy toàn bộ 44 test cases REC-05: **38 passed, 6 skipped** (do môi trường GPU thực).

### Checkpoint 2026-09-26 — Primary adapter/synthetic proof


**Implemented / VERIFIED**

- `rgb/geometry/voxel.py`: typed config, explicit capsule/seeds/GPU, deterministic config
  checksum; hai invocation tách cluster seed khỏi navigation seed. Không dùng
  floor-fill và không áp metric scale ngầm.
- `adapters/voxel_runtime.py` + `voxel_inspect.mjs`: pin CLI/API 3.6.6 `afbc281`,
  version/help/Node/GPU logs; subprocess timeout kill process group; Gaussian
  validation qua upstream trước và sau filter. Reject skipped/empty carve dù exit 0.
- `adapters/voxel.py`: isolated non-overwriting synthetic attempts, source/copy
  checksum và immutability checks, filter-cluster → voxel/carve → collision,
  checksummed private `qualification.json`. Không product publication, không
  cấp metric confirmation, không chạy dữ liệu thật qua synthetic entrypoint.
- `voxel_output.py` kiểm native metadata/resolution/binary byte length;
  `collision_glb.py` kiểm pinned GLB shape, finite positions, indices, bounds,
  buffer layout và degenerate triangles. Native Y-up output giữ riêng;
  canonical Z-up derivative chỉ áp `R_x(+90°)`, không đổi scale.
- Unit/fixture tests bao gồm config/footprint thiếu hoặc sai, checksum tamper,
  non-synthetic mode, timeout/process failure, invalid GLB/voxel payload và
  attempt immutability. Real codec tests reject plain point cloud, NaN,
  invalid quaternion, truncated PLY; positive Gaussian input chạy đạt.
- GPU negative test xác nhận seed `(100,100,100)` khiến upstream **exit 0 +
  skipping carve**, nhưng adapter raise và không tạo canonical `collision.glb`
  hoặc qualification receipt. Native partial outputs/logs giữ để diagnose.

**Synthetic GPU proof — không phải Aisle_CW**

- Runtime: Node `v24.11.1`, splat-transform `3.6.6 (afbc281)`, `--gpu 0`;
  `gpus.log` xác nhận index 0 là Intel UHD Graphics 630, index 1 là llvmpipe.
- Fixture Gaussian shell canonical `2 × 3 × 1.5m`, một detached floater;
  `2,703 → 2,702` Gaussians ở cả ba runs. Capsule test height `0.4m`, radius
  `0.1m`, navigation seed `(1,1.5,0.5)`. Không là locked robot config product.
- Source SHA-256:
  `3d9f10111534a227b78537375d9acbb758263c583b0fb3d125941d8cdec7a383`.
- Evidence local/ignored: `data/rec05_smoke/synthetic-20260926-03/voxel-<resolution>/`.
  Mỗi attempt có native voxel JSON/BIN/GLB, canonical `collision.glb`, inspection
  trước/sau filter, config/source/output/log checksums và `qualification.json`.

| Resolution (m) | Vertices | Triangles | Boundary edges | Non-manifold edges | Degenerate triangles |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.10 | 48 | 88 | 0 | 0 | 0 |
| 0.05 | 51 | 94 | 0 | 0 | 0 |
| 0.025 | 48 | 88 | 0 | 0 | 0 |

Asymmetric bounds check bắt sai axis/scale và floater còn sót. Edge-incidence
checks không chứng minh không self-intersection, clearance tolerance hoặc physics.
Ví dụ baseline 0.05m canonical bounds x `[-0.025,1.975]`, y `[0.025,3.025]`,
z `[-0.025,1.575]`: đây là measured fixture output, không metric Aisle_CW.

**Commands / observed results**

Từ repository root, dùng package đã provision; không auto-install:

```bash
export REC05_VOXEL_CLI="$PWD/data/rec04_runtime/node_modules/@playcanvas/splat-transform/bin/cli.mjs"
export REC05_VOXEL_MODULE_PATH="$PWD/data/rec04_runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs"
export REC05_TEST_SPLAT_MODULE="$REC05_VOXEL_MODULE_PATH"
export REC04_TEST_SPLAT_MODULE="$REC05_VOXEL_MODULE_PATH"
export REC05_TEST_GPU=1
.venv/bin/python -m tests.test_reconstruction.smoke.rec05_smoke --output data/rec05_smoke/synthetic-20260926-03
.venv/bin/pytest tests/test_reconstruction/test_rec05_*.py -q
.venv/bin/pytest tests/ -q
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
git diff --check
```

- Smoke command exit 0, cả ba resolutions đạt fixture assertions. Khi rerun phải
  chọn output directory mới; adapter cố ý không overwrite attempt đã có.
- Full suite với real codec + negative GPU enabled: **286 passed** (17.59s),
  không skip. Focused REC-05 cuối: **39 passed** (6.24s); riêng 5 real codec +
  negative GPU tests: 6 passed (6.05s).
- Ruff check pass; format check 121 files unchanged. AST audit 10 Python files
  mới: không function >30 lines, >3 non-self parameters hoặc thiếu return annotation.
- Failed attempt `synthetic-20260926-01`: cấu hình nhầm `dist/cli.mjs` (module
  export, exit 0 nhưng không chạy main). Version gate reject đúng; sửa runtime
  setting sang package executable **`bin/cli.mjs`**, không nới version gate.
- Attempt `-02` chạy thành công trước khi thêm cluster inspection/GPU inventory;
  `-03` là evidence đầy đủ được dùng ở checkpoint này. Giữ history/logs, không xóa.

**Remaining / next executable work**

1. REC-05 tiếp tục `IN_PROGRESS`, **không BLOCKED toàn task**, không DONE.
   Real Aisle_CW metric-aware spike đang chờ **REC-06 confirmed anchor/transform
   record + locked robot capsule + valid walkable seed**. User đã xác nhận các
   input này chưa có; không bịa scale hoặc lấy evaluation-only GT làm anchor.
2. Sau prerequisite: integrate actual confirmed-record schema/resolver, immutable
   metric derivative và applied-transform checksum; test source lineage,
   missing/unconfirmed anchor, scale propagation/double-scaling với REC-06 thật.
   Adapter hiện chỉ expose synthetic technical path, không shared `GeometryArtifact`.
3. Chạy real Aisle_CW ba resolutions, clearance/ghost-block và EX-SIM Isaac
   `CLEAR/BLOCKED` với analytic ground plane. Chưa claim consumer/physics acceptance,
   browser visual QA, external CI hoặc validation toàn bộ binary octree pointers.
   Upstream có thể relocate seed bị blocked; requested seed trong receipt không
   được diễn giải thành verified walkable seed của scene thật.
4. OpenMVS source/license/CLI đã inspect; container/runtime/smoke chưa qualified.
   Giữ fallback có điều kiện khi primary real spike không đạt, không phải prerequisite
   bắt buộc cho synthetic SplatTransform development.

### Owner chốt 2026-09-29 — thông số voxel và seed cho video người dùng

1. Thông số đọc từ file config versioned `configs/product/geometry_v1.json`
   (checksum ghi vào job), không có default trong `src/`.
2. `resolution_m = 0,05` (baseline). `opacity = 0,1`, `cluster_resolution_m = 0,1`,
   `cluster_opacity = 0,1`, `cluster_min_contribution = 0,004` lấy từ smoke tổng
   hợp, **chưa hiệu chỉnh**; hiệu chỉnh trong spike Aisle_CW 3 resolution ở trên.
3. Capsule theo mục dưới (OTTO 0,4610 / 0,308 m).
4. **Seed (PROPOSAL được owner đồng ý):** camera đầu đã registered sau transform mét,
   **hạ xuống `z = capsule_height/2 + 0,05 m`** trên sàn z=0 người dùng đã xác nhận.
   Không còn là "tự suy khoảng camera–sàn" mà ADR 0001 cấm, vì sàn đã đo
   (REC-06 floor frame). Relocation ≤ `max_seed_relocation_m = 1,0` theo ADR 0001.
5. Seed vẫn hỏng → job dừng với lỗi rõ, UI mời người dùng click điểm robot đứng
   trên sàn (UX thuộc PRODUCT-06).

### Owner chốt capsule robot 2026-09-27 — thay số demo

Số demo cũ `radius=0.35 m` / `height=1.20 m` **không còn dùng**. Owner cung cấp
spec **OTTO 100D**: kích thước tổng thể **740 × 550 × 308 mm**
(L × W × H), lối đi tối thiểu 1,099 mm, tải 150 kg, khối lượng 107 kg.

`VoxelConfig` yêu cầu capsule trục tròn (`capsule_radius_m`, `capsule_height_m`)
nên phải ánh xạ hộp chữ nhật → trục:

| Chọn | Công thức | Bán kính | Khi nào dùng |
| --- | --- | --- | --- |
| **Ngoại tiếp** | `hypot(0.370, 0.275)` | **0,4610 m** | **Carve free space** — bảo đảm robot vừa mọi hướng |
| Nội tiếp | `min(0.370, 0.275)` | 0,2750 m | Kiểm tra "chắc chắn vừa" — không đảm bảo an toàn khi quay |

**Owner chốt dùng ngoại tiếp: `capsule_radius_m = 0.4610`, `capsule_height_m = 0.308`.**
Lý do: `--voxel-carve` tạo khoảng không di chuyển; dùng bán kính nhỏ hơn robot thật
sẽ để lọt va chạm. Số này là **cấu hình theo robot đang mô phỏng**, không nhúng
vào `src/` — `VoxelConfig` bắt buộc truyền vào, không có default.

**Cross-check từ point cloud (chỉ sanity, KHÔNG phải nguồn số):** raw scan có cấu
trúc tĩnh gần cảm biến, giống hệt ở mọi frame, phủ **0,96 × 0,88 m** trong band
0,30–0,55 m. Lớn hơn spec 0,740 × 0,550 vì band gần đo **khung giá đỡ cảm biến +
thân robot**, không chỉ thân. Band gần cũng là vùng Ouster có artifact
dual-return/min-range nên **không dùng làm số**. Cùng cỡ → hợp lý.

Lưu ý phạm vi: capsule chỉ liên quan khi mục tiêu là mô phỏng AMR. Video kho của
người dùng upload không có robot thì không cần capsule.

**Commit history của phần implementation**

`187f094` bootstrap/source audit → `248ebaa` typed config/commands → `96019a7`
process/Gaussian guards → `f12ceae` collision GLB/axis boundary → `9a18410`
pipeline/output validation → `dd1e71e` real codec tests → `5a7dbdc` synthetic GPU
smoke → `cca15ea` dependency docs → `f350989` real skipped-carve negative test.
User yêu cầu commits nhỏ; không push/merge/đổi branch hoặc sửa shared contracts.

### Checkpoint 2026-09-26 — Tích hợp Re3Sim Gaussian Scaling & Fix ESM Loader
1. **Gaussian Scale Adapter (Re3Sim):**
   - File: `src/services/reconstruction/adapters/gaussian_scale.py`
   - Phép biến đổi đồng dạng cho 3DGS PLY: Tọa độ xyz được nhân với hệ số co giãn $s$; các thuộc tính log-scale covariance `scale_0, scale_1, scale_2` được cộng thêm $\ln(s)$ theo chuẩn toán học 3DGS ($\sigma_i = \exp(scale\_i)$).
   - Tích hợp vào `SplatTransformVoxelAdapter._execute`: Tự động co giãn `input.ply` thành working derivative hệ mét chuẩn khi xử lý `ProductVoxelRequest` mà không làm biến đổi source master gốc trong artifact store.
2. **ESM Entrypoint Resolution:**
   - File: `src/services/reconstruction/adapters/voxel_inspect.mjs`
   - Khắc phục lỗi `ERR_UNSUPPORTED_DIR_IMPORT` trên Node.js v24 bằng cách phân giải directory path sang entrypoint chuẩn `dist/index.mjs`.
3. **Kiểm thử:**
   - Files: `tests/test_reconstruction/test_rec05_scale.py`, `tests/test_reconstruction/test_rec05_real_codec.py`
   - Kết quả: `pytest tests/test_reconstruction/test_rec05*.py -v` đạt 41 passed; real splat-transform inspection 5 passed.
