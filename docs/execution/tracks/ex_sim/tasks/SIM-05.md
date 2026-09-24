# SIM-05 — Candidate OpenUSD Build

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
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

**Code Donor Reference (Audit #1):**
- Candidate code donor: [`PointsCoder/OpenReal2Sim`](https://github.com/PointsCoder/OpenReal2Sim) (xem chi tiết tại [`docs/execution/audits/01_openreal2sim.md`](../../../audits/01_openreal2sim.md)).
- File tham khảo: `openreal2sim/simulation/isaaclab/sim_preprocess/usd_conversion.py` (**`ADAPT-HIGH`**).
- Code/patterns đáng port sang `IsaacUsdAdapter` / `CandidateBuilder`:
  - `convert_obj_to_usd()` sử dụng IsaacLab `MeshConverter`
  - Cấu hình PhysX: `UsdPhysics`, `PhysxSchema`, `RigidBody`, `CollisionAPI`
  - Thiết lập properties: `MassPropertiesCfg`, `RigidBodyPropertiesCfg`, `CollisionPropertiesCfg`
  - Convex decomposition, CCD configuration và USD stage post-processing
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Headless Enforcement**: Script gốc ép `args_isaaclab.headless = False`. Phải xóa bỏ và enforce headless mode cho worker/container.
  - ❌ **No `scene.pkl`**: Tuyệt đối không nhận state model bằng pickle/dictionary; nguồn dữ liệu duy nhất là canonical `SceneIR` JSON.
  - ❌ **No uncalibrated PhysX defaults**: Các thông số PhysX (contact offset, voxel resolution, số hull) phải được calibrate cho warehouse scene, không lấy nguyên mặc định của OpenReal2Sim.

## 9. Implementation Plan

1. Khảo sát `usd_conversion.py` từ OpenReal2Sim, bóc tách logic cấu hình PhysX và `MeshConverter`.
2. Xây dựng `IsaacUsdAdapter` dịch từ `SceneIR` sang USD stage (headless).
3. Đóng gói CandidatePackage kèm inventory và `candidate_checksum`.
4. Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Hierarchy/unit/up-axis/transform/inventory/checksum unit tests.
- Preflight-not-PASS and unresolved asset negative tests.
- Fixture SceneIR→CandidatePackage smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Package preserves units, hierarchy, transforms, geometry, colliders and assets.
- [ ] Checksum covers canonical package inventory/content without self-reference.
- [ ] `artifact_checksums[]` khớp đúng ordered package refs; từng byte ref resolve
  và SHA-256 match trước khi công bố `candidate_checksum` theo Contract 3.1.1.
- [ ] Exact package is consumable by SIM-06 and immutable through review.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- CandidatePackage/checksum.
- USD inspection/load-precheck.
- Blocked-build failure.
