# AUD-08 — Manual merge và reassign object membership

## Metadata và goal

- PLANNED; P1; EX-SCENE domain, EX-PRODUCT commands/UI.
- Canonical SCENE-03/06/07/08, PRODUCT-06/07. REUSE gaussian_split/association;
  SELF-CODE revision-bound commands và ownership update.
- Goal: sửa segmentation/grouping trước confirmation, tạo artifact đồng bộ
  visual/geometry/collision thay vì chỉ đổi tên hoặc ghép mask IDs.
- [Agent guide](../AGENT_GUIDE.md); contract background phối hợp [AUD-01](AUD-01-collision-background.md).

## Baseline và scope

CodeGraph: `merge_candidates` (0 callers), `label_gaussians`, `split`,
`apply_object_action`, `publish_next`, ObjectReviewView. merge_candidates chỉ trả
primary + event; không cập nhật secondary, SceneIR hoặc object artifacts.
Source split dùng source Gaussian row indices và local axes song song world,
giữ spherical harmonics; không thể ghép transformed PLY bằng cách đổi position thôi.

Owned: src/services/scene/{candidates,decomposition,editing}/,
orchestration/scene/ command/publication glue, src/api/product/scene.py hoặc
Studio façade đang dùng, schemas và frontend ObjectReviewView/API/contracts,
tests/test_scene/, tests/test_orchestration/test_scene_editor.py,
tests/test_api/test_scene_v2_routes.py, frontend/tests/object-review.test.tsx.
Không thay segmentation model, thêm arbitrary transform/SH rotation engine,
merge catalog assets hoặc generic mesh sculpting.

## Input / output / data contract

Input: expected_scene_revision, source membership ref/checksum, reconstructed
CANDIDATE IDs và command. Initial scope chỉ candidates chưa có pose edit;
confirmed/moved/asset/legacy-without-membership phải reject rõ, không fake merge.
Output: one new DRAFT SceneIR revision + changed visual/geometry/background
refs + audit event; secondary tombstone; old revisions/artifacts giữ nguyên.

Proposed ObjectMembershipArtifact header: version, source_visual_ref,
source_geometry_ref, extraction_revision, coordinate_system, gaussian_count,
labels_ref và stable label_to_object_id map; background label -1 như split hiện có.
Binary labels/indices không dùng pickle; bind source row count/byte checksum.
Collision source regions dùng contract AUD-01, không suy Gaussian index = mesh face index.

Merge command: expected_scene_revision, primary_object_id, secondary_object_ids,
membership_checksum. Reassign command: same revision/checksum, source region
selection (bounded ROI trong source canonical frame hoặc verified selection ref),
source_object_id/background, target_object_id/background. S1 chốt DTO/routes;
server validate selection ownership, bounds, count, target và identity.

Each Gaussian có tối đa một owner; merge union deduplicate; reassign chuyển
ownership không clone điểm. Không thất thoát/nhân đôi source rows. Primary ID
giữ ổn định; secondary inactive + review MERGED/merged_into audit provenance,
không thêm SceneObjectState mới. Membership IDs của secondary được map primary.
Geometry/local origin thay đổi phải regenerate collider, background source
ownership và refs; confirmation reset CANDIDATE. Không kế thừa validation/approval.

## Dependencies

S1 cần source ownership AUD-01.S1. S2/S3 dùng artifact publication và atomic
revision commit AUD-10.S2. S4 integration AUD-02 export; real simulator ở AUD-05.
S1 phải xác định membership có đang persist hay không; nếu chưa, bổ sung producer
output trước UI. Không dùng private worker temporary file làm product contract.

## Sprint AUD-08.S1 — Persist membership và validate correction commands

**Input:** labels/seeds/source PLY của extraction và current candidates.
**Output:** typed membership artifact, stable ID mapping và validated command DTOs.
**Contract:** immutable source identity, exclusive ownership, finite/bounded ROI;
old scene không có membership vẫn đọc được nhưng correction có blocker.

Implement: persist label output/small-object fallback đúng với rows thực tế đã
split; source provenance consumer; DTO/parser và producer/consumer fixtures.
Guard transformed/confirmed/asset candidates trong initial scope.
Tests: source checksum mismatch, duplicate owners, invalid index/count/labels,
stale revision, missing source refs, NaN ROI, floor/background selection semantics.
**Exit:** [ ] source/membership roundtrip; [ ] unsupported correction rejected.

## Sprint AUD-08.S2 — Merge domain và regenerate artifacts

**Input:** validated merge S1 với unedited candidates.
**Output:** primary merged candidate, secondary audit tombstones, new artifacts/revision.
**Contract:** union không duplicate/loss; keep primary ID; local frame/SH semantics
correct; source collision regions hợp nhất theo ownership, không current OBB mù.

Implement: complete domain result thay vì gọi merge_candidates rồi chỉ đổi JSON;
regenerate local PLY/geometry/delivery/collider-required state qua existing ports.
Primary semantic selection phải explicit khi labels xung đột; mass/physics không
blind sum hoặc kế thừa collider cũ. Publish refs trước CAS revision commit.
Tests: two/three candidates, self/duplicate IDs, overlap, primary choice conflicts,
membership counts, source world witness vs new local transform, publication failure,
stale user edit during worker rebuild; secondary restore behavior ghi rõ.
**Exit:** [ ] visual/geometry/membership đồng bộ; [ ] no half-applied merge revision.

## Sprint AUD-08.S3 — Reassign region ownership

**Input:** validated region selection + existing candidate/background target.
**Output:** updated exclusive membership, affected object/background artifacts,
new DRAFT revision và audit trail.
**Contract:** selected rows chuyển owner đúng một lần; unselected rows unchanged;
empty candidate/degenerate geometry có policy explicit, không auto-delete audit.

Implement: server derive/verify ROI selection từ source frame, không UI world
pose đã sửa; regenerate affected parts và background collision ownership. Handle
empty/tiny part bằng explicit candidate state/blocker; không đổi source row order.
Tests: object→object, object→background, background→existing object, out-of-range,
empty selection, full-object selection, ground-plane preservation, corrupt refs,
cancel/stale publication; conservation of source row ownership.
**Exit:** [ ] reassign count/geometry proof; [ ] old revision recoverable.

## Sprint AUD-08.S4 — UI commands, preview và downstream handoff

**Input:** selected candidate IDs/region, current revision và backend result.
**Output:** merge/reassign UI có pending/error/rollback, new canonical scene loaded.
**Contract:** client state không là scene truth; saving disable concurrent commands;
409 reload canonical scene; stale poll không restore selection/eligibility cũ.

Implement: minimal multi-select/primary choice và bounded region selection;
show unsupported/missing-membership reason. Wire actual domain commands, không
local visual merge only. Candidate confirm → export → validation dùng regenerated refs.
Tests: Vitest interaction/typed payload/failure rollback, browser selection/keyboard/
cancel/error, API permission/stale calls, exported object/collider correspondence.
**Exit:** [ ] user action changes canonical artifact; [ ] downstream preflight/export pass;
[ ] browser/Isaac coverage ghi riêng.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_scene/test_gaussian_split.py tests/test_scene/test_editing_review.py tests/test_scene/test_editing_v2.py tests/test_orchestration/test_scene_editor.py tests/test_api/test_scene_v2_routes.py -q
```

Planned tests/test_scene/test_object_correction.py. Frontend
tests/object-review.test.tsx, tests/ux-scene-flow.test.tsx. DONE cần persisted
membership → command → artifacts → revision → consumer proof, không chỉ unit merge helper.

## Result / Evidence

Pending — source/membership checksums, before/after ownership counts, refs,
stale/corruption negatives và browser proof theo từng sprint.
