# SIM-05 — Candidate OpenUSD Build

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | Đạt |
| Target milestone | `M2/M3` |

## 2. Goal

Translate exact physics SceneIR revision into immutable CandidatePackage with OpenUSD entrypoint, inventory and package checksum.

## 3. Why This Task Exists

Validation/review/release must bind the exact candidate tested, not a rebuilt file.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-04 PreflightReport PASS.
- Canonical coordinate/runtime package policy locked.

## 5. Input Contract

- Physics SceneIR checksum, PASS preflight report, JobManifest and build config.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Immutable CandidatePackage and candidate manifest/checksum.
- SceneIR→USD transform/asset/collider provenance.
- CandidateManifest mang shared canonical `CoordinateSystem`; exporter convert
  convention native tại adapter boundary, không ghi free-form unit/up-axis.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/usd/`
- `tests/test_simulation/`
- shared candidate contract with PRODUCT review

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` adapter using OpenUSD APIs; do not mutate package after checksum.

**Code Donor Reference (Audit #1 & #7):**
- Candidate code donor: [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim) (xem chi tiết tại [`docs/execution/audits/01_openreal2sim.md`](../../../audits/01_openreal2sim.md)).
- File tham khảo: `openreal2sim/simulation/isaaclab/sim_preprocess/usd_conversion.py` (**`ADAPT-HIGH`**).
- Code/patterns đáng port sang `IsaacUsdAdapter` / `CandidateBuilder`:
  - `convert_obj_to_usd()` sử dụng IsaacLab `MeshConverter`
  - Cấu hình PhysX: `UsdPhysics`, `PhysxSchema`, `RigidBody`, `CollisionAPI`
  - Thiết lập properties: `MassPropertiesCfg`, `RigidBodyPropertiesCfg`, `CollisionPropertiesCfg`
  - Convex decomposition, CCD configuration và USD stage post-processing
- Candidate architecture donor: [`InternRobotics/Re3Sim`](https://github.com/InternRobotics/Re3Sim) (xem chi tiết tại [`docs/execution/audits/07_re3sim.md`](../../../audits/07_re3sim.md)):
  - File tham khảo: `re3sim/utils/usd/obj_to_usd.py` (**`ADAPT-HIGH`**).
  - Chuẩn hóa stage units: `metersPerUnit = 1.0`, `kilogramsPerUnit = 1.0`, `Z-up`.
  - Cấu hình `CollisionPropertiesCfg(collision_enabled=True)`.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Headless Enforcement**: Script gốc ép `args_isaaclab.headless = False`. Phải xóa bỏ và enforce headless mode cho worker/container.
  - ❌ **No `scene.pkl`**: Tuyệt đối không nhận state model bằng pickle/dictionary; nguồn dữ liệu duy nhất là canonical `SceneIR` JSON.
  - ❌ **No uncalibrated PhysX defaults**: Các thông số PhysX (contact offset, voxel resolution, số hull) phải được calibrate cho warehouse scene, không lấy nguyên mặc định của OpenReal2Sim.
  - ❌ **Sửa lỗi CLI flag của Re3Sim**: Chú ý script gốc của Re3Sim dùng sai flag `--collision_approximation` (gạch dưới) thay vì `--collision-approximation` (gạch ngang).

## 9. Implementation Plan

1. Tạo `src/services/simulation/usd/usda.py`:
   - Chuyển đổi SceneIR sang OpenUSD ASCII (`.usda`), định nghĩa metadata `metersPerUnit=1.0`, `upAxis="Z"`.
   - Sinh phân cấp Prim chuẩn: `/World/Environment/GroundPlane` (với `PhysicsCollisionAPI`) và `/World/Objects/<obj_id>`.
   - Sinh chính xác `xformOp:translate`, `xformOp:orient` (quaternion `(qw, qx, qy, qz)`), và Box collider proxy.
2. Tạo `src/services/simulation/usd/builder.py`:
   - Hàm `build_candidate_package(req: CandidateBuildRequest)`:
     - Kiểm tra gate: Từ chối nếu `preflight_report.blocking_result != "PASS"`, hoặc `scene_revision`/`scene_ir_checksum` không khớp.
     - Thu thập tài nguyên: `entrypoint_usd`, `assets`, `geometry`, `colliders`.
     - Tạo `CandidateManifest` với `artifact_checksums` ordered theo đúng quy ước `verify_candidate_inventory`.
     - Tính `candidate_checksum` và niêm phong `CandidatePackage`.
     - Ghi file `scene.usda` và `candidate_manifest.json` vào `output_dir` (nếu có).
3. Kiểm thử với `tests/test_simulation/test_usd.py`:
   - Kiểm tra cú pháp OpenUSD, xác thực inventory và checksum, kiểm tra từ chối khi preflight không đạt.

## 10. Tests

- Hierarchy/unit/up-axis/transform/inventory/checksum unit tests.
- Preflight-not-PASS and unresolved asset negative tests.
- Fixture SceneIR→CandidatePackage smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [x] Package preserves units, hierarchy, transforms, geometry, colliders and assets.
- [x] Checksum covers canonical package inventory/content without self-reference.
- [x] `artifact_checksums[]` khớp đúng ordered package refs; từng byte ref resolve
  và SHA-256 match trước khi công bố `candidate_checksum` theo Contract 3.1.1.
- [x] Exact package is consumable by SIM-06 and immutable through review.
- [x] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

- **Implementation:** `src/services/simulation/usd/usda.py`, `src/services/simulation/usd/builder.py`, `src/services/simulation/usd/__init__.py`.
- **Validation:** `pytest tests/test_simulation/test_usd.py -v` (5 passed in 2.56s).
- **Full Track Suite:** `pytest tests/test_simulation/ -v` (44 passed in 6.26s).
- **Linter & Formatting:** `ruff check .` & `ruff format --check src/ tests/` (100% clean).
- **Proof:**
  - `test_generate_scene_usda_syntax`: OpenUSD metadata (`metersPerUnit=1.0`, `upAxis="Z"`), Prim hierarchy (`/World/Environment`, `/World/Objects`), `PhysicsCollisionAPI` verified.
  - `test_build_candidate_package_success`: `verify_candidate_inventory` & `verify_content_checksum` passed; files `scene.usda` & `candidate_manifest.json` created.
  - `test_build_candidate_package_rejects_non_pass_preflight`: Blocking result FAIL throws ValueError.
  - `test_build_candidate_package_rejects_mismatched_revision`: Throws ValueError when scene revision doesn't match preflight report.
  - `test_build_candidate_package_rejects_mismatched_checksum`: Throws ValueError when scene checksum doesn't match preflight report.

