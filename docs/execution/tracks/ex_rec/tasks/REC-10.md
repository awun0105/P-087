# REC-10 — Publish ReconstructionBundle

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |


## 2. Goal

Build, validate và publish ReconstructionBundle mà EX-SCENE đọc trực tiếp.

## 3. Why This Task Exists

Đây là cross-track handoff chính REC→SCENE và không được phụ thuộc temp folders của tools.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03/04/05/06 cho RGB bundle.
- REC-08/09 conditional cho mixed configuration.
- Normative mixed-modality bundle đã khóa: canonical geometry luôn required;
  mixed RGB/LiDAR phải có exact-checksum-bound `CONFIRMED AlignmentRecord`.

## 5. Input Contract

- Published REC-02A frame, pose, visual, geometry and metric artifacts.
- Conditional LiDAR/alignment composition records.
- Optional RGB+sensor-depth refs chỉ khi input_configuration.depth_present;
  dtype/format/positive scale do producer khai báo. `uint16` PNG và scale `0.001`
  là TorWIC adapter metadata, không phải universal invariant hay GT depth.
- Conditional LiDAR ref mang generic preprocessing dependency provenance;
  bundle phải giữ `ground_truth_assisted: true` nếu LiDAR đã dùng GT.
- Input/job/config provenance.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Versioned ReconstructionBundle với checksum và resolvable refs.
- Bundle publication/handoff record.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/`
- `src/models/contracts/reconstruction.py` chỉ với shared review
- `fixtures/reconstruction_bundle/` và `tests/test_contracts/` với consumer review

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` theo shared contract; không serialize ad-hoc format cạnh tranh.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Resume sau 427ab83: nối `BundleDependencies.verify_metric` với REC-06 immutable
final RGB verification record; exact bundle request (trừ proof ref để tránh cycle)
phải match reviewed candidate. Kiểm canonical VisualArtifact SOG thực + poses +
geometry + frame inventory/source checksum, giữ scope product/fixture tách biệt.
Canonical selection khác RGB geometry hoặc sensor depth cần verifier tương ứng,
không default approval. Producer→consumer fixture handoff là proof cho bridge,
không đóng real dataset DoD hoặc tự triển khai PRODUCT decision authority.

Audit 2026-09-27: default metric UNCONFIRMED, không suy canonical geometry từ
RGB ref. Inject resolver + metric/alignment verifier ports; resolve/hash mọi
dependency, job/type/stage binding và confirmed-record reload trước publication.
Không import SCENE consumer vào producer. Proof ref phải immutable và được giữ
trong bundle provenance. Fixture verifier explicit chỉ chứng minh handoff shape,
không thay real REC-06 cross-artifact proof còn phải sửa. Content-addressed
publication, missing/tampered refs phải fail trước bundle write.

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Builder/roundtrip/checksum unit tests.
- Missing required artifact/unresolved ref negative tests.
- EX-SCENE fixture/real consumer contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Bundle validate normative schema và coordinate/metric metadata đủ.
- [x] RGB-only, RGB+Depth và RGB+LiDAR bundle invariants pass; mixed bundle thiếu alignment bị reject.
- [x] Không chứa hidden local path hoặc require private COLMAP/Brush/OpenMVS folders.
- [x] EX-SCENE deserialize trực tiếp không sửa file tay.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

Audit 2026-09-27: checked items là typed/fixture consumer proof. Real metric
derivative verifier chưa nối, nên chưa publish được real qualified bundle và
chưa đủ required handoff proof để DONE.

## 12. Result / Evidence

### Canonical RGB verification bridge — 2026-09-27 sau 427ab83

REC-06 `BundleMetricVerifier.verify_bundle` nay là concrete verifier port cho
`BundleDependencies`, không chỉ test lambda approve. Recheck canonical payloads,
source InputManifest/frame inventory, geometry transform, measurement protocol
review và exact candidate; proof ref immutable được giữ trong bundle provenance.
Fixture chain đi từ published frame producer qua REC-03/04/06/05 đến REC-10 và
`load_reconstruction_bundle` của EX-SCENE, không sửa bundle/manual conversion.

Focused final metric bridge **19 passed**; combined REC-06 bridge/REC-11 preview/
REC-10/worker **64 passed (137.11s)**, native SOG test enabled. Ruff EX-REC 104
files pass. Đây là fixture proof cho wiring; heavy engines/review authority là
stubs ở fixture chain, không real dataset acceptance. Default deployed verifier
không nhận fixture scope, authenticated reviewer PRODUCT chưa nối. Native LiDAR
canonical selection, sensor depth và real mixed alignment qualification vẫn cần
hoàn thiện; REC-10 chưa DONE.

### Audit correction 2026-09-27 — verified publication boundary

- VERIFIED: 3 red regression tests trước sửa: default CONFIRMED scale, implicit
  canonical geometry, publish missing payload. Nay default UNCONFIRMED,
  canonical geometry explicit, `BundleDependencies` inject resolver + metric
  verifier + immutable alignment loader. No default authority.
- Resolve/hash/job/type/stage checks trước publication; exact reviewed request
  và proof ref bind source checksum, derivatives, scale và canonical selection.
  Mixed record phải reload qua REC-09 verifier, không tin embedded flags.
  Bundle giữ proof ref trong provenance và content-addressed publication URI.
- Test fixtures ghi `evidence_kind=synthetic_fixture`; positive verifier chỉ
  kiểm checksum-bound fixture inventory. Đây là consumer/publication proof,
  KHÔNG chứng minh raw Brush visual hoặc poses đã thành metric derivatives.
- `pytest tests/test_reconstruction/test_rec10*.py tests/test_reconstruction/test_rec11*.py -q`:
  **31 passed**; EX-REC **338 passed, 11 skipped** (63.15s); Ruff check/format
  **185 files pass**. Current consumer/storage tests **10 passed**.
- Cross-track checks: contracts/integration **94 passed, 2 failed** ở historical
  SceneIR checksum fixtures (`test_identity.py`); full suite collection vẫn
  thiếu NumPy ở `test_simulation/test_colliders.py`. Không sửa ngoài ownership.
- Pending: real REC-06 canonical derivative/independent-distance verifier;
  real InputManifest → bundle handoff và RGB+depth proof. Chưa DONE.

### Checkpoint 2026-09-26 — DONE, ReconstructionBundle publication service and validation

**Implemented / VERIFIED:**
- `src/services/reconstruction/bundle.py`:
  - `BundleBuildRequest`: ràng buộc modality, bắt buộc `canonical_geometry_ref` (mặc định lấy `rgb_geometry_ref`), fail closed khi mixed RGB+LiDAR thiếu `CONFIRMED AlignmentRecord`.
  - `ReconstructionBundleService`: lắp ráp và tính toán canonical content checksum chuẩn, xuất bản `ReconstructionBundle` (`producer_stage=StageId.METRIC_CANONICALIZE`) qua atomic writer.
- `tests/test_reconstruction/test_rec10_bundle.py`:
  - 3/3 test cases pass:
    - RGB-only bundle xuất bản và được EX-SCENE consumer (`load_reconstruction_bundle` từ `src.services.scene.bundle_consumer`) đọc và deserialize trực tiếp, giải quyết toàn bộ canonical geometry, frames, poses.
    - Mixed RGB+LiDAR bundle có confirmed alignment được xuất bản và EX-SCENE consumer deserialize thành công cả canonical geometry và lidar geometry.
    - Fail-closed khi cấu hình mixed RGB+LiDAR nhưng thiếu alignment.
