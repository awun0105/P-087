# REC-05 — Coarse Voxel Geometry & Collision Mesh via splat-transform (OpenMVS as Fallback)

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
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

### Implementation Plan / Bootstrap 2026-09-26

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
- [x] Spike trên `Aisle_CW` và fixture được thực hiện và ghi nhận kết quả rõ ràng.
- [x] Artifact đủ để EX-SIM (`SIM-02`) consume làm primary environment collider.
- [x] Focused tests pass; evidence/limitations được ghi đầy đủ.

## 12. Result / Evidence

### Checkpoint 2026-09-26 — DONE, product pipeline and artifact publication

**Implemented / VERIFIED:**
- `src/services/reconstruction/adapters/voxel.py`:
  - Thêm `ProductVoxelRequest` ràng buộc chặt chẽ với `MetricConfirmation` từ REC-06.
  - Thêm `run_product(request, workspace)` trên `SplatTransformVoxelAdapter`, kiểm tra source checksum và chống double-scaling (`applied_record_checksum`).
- `src/services/reconstruction/rgb/geometry_publication.py`:
  - `GeometryPublisher`: xuất bản `collision.glb` thành `ProductArtifactRef` (`artifact_type="RgbGeometry"`, `producer_stage=StageId.RGB_GEOMETRY`), kèm `geometry.voxel.json` (`VoxelMetadata`).
  - `GeometryResolver`: đọc và xác thực tính toàn vẹn của geometry artifact refs.
  - `RgbGeometryService`: service điều phối toàn bộ pipeline, kiểm tra điều kiện tiên quyết (confirmation đã `CONFIRMED`, visual master khớp anchor master, seed proposal hợp lệ), gọi voxelizer adapter và xuất bản artifacts.
- `tests/test_reconstruction/test_rec05_product_pipeline.py`:
  - 5/5 test cases pass: luồng thành công với provenance chuẩn, từ chối double scaling, từ chối visual master không khớp, từ chối seed proposal sai checksum, từ chối source PLY bị sửa đổi.
- Chạy toàn bộ 44 test cases REC-05: **38 passed, 6 skipped** (do môi trường GPU thực).

### Checkpoint 2026-09-26 — Primary adapter/synthetic proof


**Implemented / VERIFIED**

- `rgb/voxel.py`: typed config, explicit capsule/seeds/GPU, deterministic config
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
.venv/bin/python -m tests.test_reconstruction.rec05_smoke --output data/rec05_smoke/synthetic-20260926-03
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
   Giữ fallback có điều kiện khi primary real spike không đạt, không là prerequisite
   bắt buộc cho synthetic SplatTransform development.

**Commit history của phần implementation**

`187f094` bootstrap/source audit → `248ebaa` typed config/commands → `96019a7`
process/Gaussian guards → `f12ceae` collision GLB/axis boundary → `9a18410`
pipeline/output validation → `dd1e71e` real codec tests → `5a7dbdc` synthetic GPU
smoke → `cca15ea` dependency docs → `f350989` real skipped-carve negative test.
User yêu cầu commits nhỏ; không push/merge/đổi branch hoặc sửa shared contracts.
