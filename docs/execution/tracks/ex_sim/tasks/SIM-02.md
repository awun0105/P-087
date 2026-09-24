# SIM-02 — Collider Generation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M1/M2` |

## 2. Goal

Generate appropriate ColliderSpec for environment and SceneObjects using simple deterministic proxies.

## 3. Why This Task Exists

Raw reconstruction mesh is unsuitable as default physics collider and AC-08 requires floor/obstacle colliders.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SceneIR fixture or SCENE-09 output.
- Accepted collider baseline policy.

## 5. Input Contract

- SceneIR geometry refs and object/environment semantics.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- ColliderSpec records/artifacts for floor/wall, box-like and complex static objects.
- Generation provenance/config.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/colliders/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` policy using Trimesh/Open3D AABB/OBB/convex/simplification utilities.

**Code Donor Reference (Audit #1, #4a, #5 & #7):**
- [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim) (chi tiết: [`docs/execution/audits/01_openreal2sim.md`](../../../audits/01_openreal2sim.md)):
  - `scenario_collision_optimization.py` (**`ADAPT-MEDIUM`**): SDF query, ground clearance, thuật toán chống lún/xuyên sàn.
  - `scenario_construction.py` (**`ADAPT-MEDIUM`**): Trimesh/Open3D AABB extraction, mesh simplification.
- [`playcanvas/splat-transform`](https://github.com/playcanvas/splat-transform) (chi tiết: [`docs/execution/audits/04a_splat_transform.md`](../../../audits/04a_splat_transform.md)):
  - Voxelization + Marching Cubes / watertight voxel faces tạo `collision.glb` (**`ADAPT-HIGH` làm fallback**).
  - Tiện ích kho bãi: `--voxel-carve` (capsule carve khoảng không di chuyển) và `--voxel-floor-fill` (vá lỗ hổng mặt sàn).
- [`discoverse-dev/DISCOVERSE`](https://github.com/discoverse-dev/DISCOVERSE) (chi tiết: [`docs/execution/audits/05_discoverse.md`](../../../audits/05_discoverse.md)):
  - `scripts/mesh2mjcf.py` portion using `trimesh` + `coacd` (**`ADAPT-HIGH selective`**): CoACD convex decomposition pipeline (`CoACDColliderBackend` candidate) để xử lý các vật thể phức tạp như giá kệ kho bãi thành tập hợp convex parts.
  - Mã hóa rõ ràng nguyên tắc: `Visual mesh` ≠ `Collision mesh` (mesh gốc dùng cho visual, các convex parts từ CoACD dùng cho collision).
- [`InternRobotics/Re3Sim`](https://github.com/InternRobotics/Re3Sim) (chi tiết: [`docs/execution/audits/07_re3sim.md`](../../../audits/07_re3sim.md)):
  - `re3sim/utils/usd/obj_to_usd.py` (**`ADAPT-HIGH`**): Cấu hình IsaacLab `MeshConverterCfg` với các chế độ va chạm (`convexDecomposition`, `convexHull`, `meshSimplification`).
  - Qualification Spike **`SIM-QUAL-RE3-01`**: Đánh giá chuyển đổi OpenMVS mesh sang Isaac USD, so sánh thời gian convert, độ ổn định va chạm và hiện tượng cản trở di chuyển của AMR.
- **Guardrails:**
  - ❌ **Không thay thế OpenMVS**: Collision mesh từ 3DGS chỉ là fallback backend (`SplatVoxelColliderBackend`) hoặc baseline đối chứng khi OpenMVS mesh gặp sự cố.
  - ❌ **Không copy default physics của DISCOVERSE**: Script gốc hardcode `mass = 0.001 kg`, `diaginertia = 2e-5`; tuyệt đối không mang default tùy tiện này vào Real2Sim. Mọi thông số vật lý phải explicit, policy-generated hoặc human-confirmed.
  - ❌ **Không dùng MJCF generation**: DISCOVERSE tạo file XML MuJoCo; dự án chỉ lấy phần phân rã CoACD và xuất ra OpenUSD/PhysX.
  - ❌ **Sửa lỗi CLI trong script Re3Sim**: Chú ý script gốc của Re3Sim có lỗi sai flag CLI (`--collision-approximation` vs `--collision_approximation`); code adapter phải validate CLI arguments cẩn thận.
  - ❌ **Không thay thế Preflight**: Mọi collider phải qua Preflight (`SIM-04`) và Isaac validation (`SIM-06`) mới được coi là hợp lệ.

## 9. Implementation Plan

1. Thiết lập các utility tạo AABB/OBB/convex hull từ mesh/geometry refs (dựa trên Trimesh/Open3D).
2. Tích hợp optional clearance/SDF remediation utility từ `scenario_collision_optimization.py` nếu cần xử lý penetration sàn/vật thể.
3. Sinh và xác thực `ColliderSpec` cho floor, wall và obstacles.
4. Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- AABB/OBB/convex/dimensions unit tests.
- Empty/non-finite/high-poly misuse negative tests.
- Fixture SceneIR collider generation smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Floor/wall and selected obstacles receive allowed collider types.
- [ ] Raw high-poly visual/mesh is not silently used as collider.
- [ ] Every collider binds geometry/object and generation provenance.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Collider overlay/images.
- ColliderSpec samples/checksums.
- Invalid geometry failure.

