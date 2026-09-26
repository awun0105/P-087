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
- REC-03 COLMAP model cho OpenMVS fallback.
- `splat-transform` (v3.6.6) Node.js/GPU environment.
- Locked OpenMVS Docker environment (làm fallback nếu spike không đạt).

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
3. Nghiệm thu: Hành vi va chạm đúng trong Isaac Sim ➔ **PASS**.

## 10. Tests

- Command/config builder unit tests cho `splat-transform`.
- Missing/invalid PLY negative tests.
- Missing/unconfirmed anchor phải chặn metric voxelization; test scale propagation
  và double-scaling với REC-06.
- Synthetic/small PLY to `collision.glb` smoke test và topology verification.
- Fallback OpenMVS adapter smoke test.

## 11. Definition of Done

- [ ] Geometry/Collision artifact `collision.glb` được tạo bằng `splat-transform` adapter.
- [ ] Format/coordinate metadata/checksum/provenance đầy đủ theo `GeometryArtifact`.
- [ ] Spike trên `Aisle_CW` được thực hiện và ghi nhận kết quả rõ ràng.
- [ ] Artifact đủ để EX-SIM (`SIM-02`) consume làm primary environment collider.
- [ ] Focused tests pass; evidence/limitations được ghi đầy đủ.

## 12. Result / Evidence

Pending implementation.
