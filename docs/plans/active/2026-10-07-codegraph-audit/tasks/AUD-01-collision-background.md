# AUD-01 — Background collision đúng sau object edits

## Metadata và goal

- Status: IN PROGRESS; priority P0; boundary EX-SCENE → EX-SIM, PRODUCT publication.
- Canonical tasks: SCENE-06/07, SIM-02/05. Strategy SELF-CODE composition,
  REUSE trimesh/carve utilities. Không thay reconstruction algorithm.
- Goal: move/delete/deactivate không để lại collision của object ở nguồn;
  ignore/visibility không vô tình xóa collision environment.
- Đọc [AGENT_GUIDE](../AGENT_GUIDE.md), [ADR 0012](../../../../decisions/0012-editable-collision-and-usd-capabilities.md).

## Baseline và scope

CodeGraph: `_carved_environment`, `_hybrid_layers`, `objectify_with_retry`,
`delete_object`, `ignore_object`, `SceneEditor.publish_next`.
Current carve dùng current transform + active confirmed. Repro local có pallet:
confirm còn 12 environment faces; delete trả lại 9.228; move khoét 0.

Files có thể sửa: src/services/orchestration/review/simulation_package.py,
src/services/orchestration/scene/{extraction,objectify}.py,
src/services/scene/decomposition/, src/services/simulation/colliders/,
tests/test_scene/, tests/test_simulation/, test_scene_extraction.py,
test_simulation_package.py trong tests/test_orchestration/.
Shared schema extension chỉ trong S1 cùng producer/consumer fixture. Không đổi
delete tombstone, visual-only visibility, metric convention hoặc artifact cũ.

## Input / output / data contract

Input: immutable source collision geometry ref, extraction scene revision,
current SceneIR và source ownership của reconstructed objects.
Output: background collision ref + active object colliders, provenance/checksum,
được cả legacy và hybrid builder consume.

`SceneObject.source_collision` dùng `SourceCollisionRegion` schema 1.0 với
`object_id`, `source_geometry_ref`, `extraction_revision`, `source_transform`,
`region_kind` và một trong hai representation: `region_ref` tới sidecar
`SourceCollisionMembership` (triangle indices) hoặc `source_obb_dimensions_xyz_m`.
Đây là extraction provenance bất biến, không phải editable world transform thứ
hai. Cả hai `ProductArtifactRef.artifact_checksum` đều là checksum bytes; sidecar
cũng lặp `source_geometry_ref` để ràng buộc indices vào đúng mesh. Reader xác
minh ref bytes, object/revision/source ref, giới hạn indices và overlap trước khi
dùng. OBB chỉ là representation có provenance; không được coi là membership
chính xác, và overlap OBB không chứng minh quyền sở hữu vùng.

`source_collision` là field optional và bị lược khỏi JSON khi vắng mặt; giữ
SceneIR schema 1.0 để payload cũ parse/dump và giữ canonical checksum. Không tự
suy ra ownership cũ từ transform hiện tại: chỉ recover từ artifact/extraction
gốc; nếu không đủ evidence thì đọc/tải artifact cũ được nhưng rebuild cần edit
phải block.

| Object state/action | Collision yêu cầu |
|---|---|
| Confirmed, active | Loại source region khỏi background; collider tại current transform |
| Confirmed, inactive/hide canonical | Loại source region; không compose object collider |
| Reconstructed DELETED, kể cả candidate bị delete | Loại source region; giữ tombstone, không collider |
| Candidate IGNORED | Giữ source geometry trong background; không collider riêng |
| Candidate chưa xử lý | Giữ source geometry; preflight confirmation vẫn áp dụng |
| Client-only visibility false | Physics không đổi |
| User-added | Không carve background; compose collider khi active |
| Restore | Dùng đúng immutable source region; compose theo restored transform |

Legacy thiếu source metadata: recover từ extraction/source artifact gốc; không
lấy current pose đã sửa làm source. Không đủ evidence thì block rebuild cần edit,
giữ khả năng đọc/download artifact cũ. Vùng overlap phải có owner xác định;
không trừ hộp mù khiến mất sàn/tường. Gaussian inpainting không chứng minh mesh vật lý.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Background source-region và object collision sau edit.
Cần sửa đồng bộ: extraction/objectify provenance → SceneIR edits → legacy/hybrid simulation_package → USD/candidate → validation; không carve theo pose đã sửa.
Acceptance xuyên consumer: Move/delete/ignore/restore giữ đúng background + active collider, exported candidate không còn collider gốc hoặc collision kép.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập. S2 dùng contract S1. S3 tích hợp AUD-02 capability path; real Isaac
acceptance đi qua AUD-05, không phải điều kiện cho CPU regression pass.

## Sprint AUD-01.S1 — Regression và source ownership

**Input:** fixture mesh sàn + vật cản, source extraction, SceneIR chưa edit.
**Output:** regression thể hiện lỗi ở current carve; typed ownership fixture và
serialization/version decision, kể cả legacy recovery case.
**Contract:** source transform/geometry checksum không đổi qua move/delete;
membership không chồng ownership trái phép; source data không là workflow state.

Implement:

1. Dùng `_scene_job` fixture hiện có; đo faces/occupancy trong vùng vật nguồn
   và điểm witness trên sàn/tường, không chỉ assert active flag.
2. Repro confirm → move, delete, restore, ignore, user-added và overlap.
3. Chốt `SourceCollisionRegion`/`SourceCollisionMembership` schema 1.0, gắn
   ownership vào reconstructed objects ở extraction producer, và thêm reader
   fixture cho simulation consumer; preserve old JSON checksum.

Tests: unit validation của refs/indices; content vs byte checksum; old payload
roundtrip; negative wrong source checksum/source pose missing.
**Exit:** [x] regression chứng minh lỗi; [x] contract/migration fixture có consumer proof.

## Sprint AUD-01.S2 — Build background từ source, compose current objects

**Input:** ownership S1 + edited SceneIR.
**Output:** verified background artifact và package composition mới.
**Contract:** source region removal theo bảng; current transform chỉ đặt object
collider; stable deterministic build identity khi input/config không đổi.

Implement:

1. Dùng ownership để carve hoặc consume mesh background đã tách; ưu tiên
   membership chính xác. Source OBB là path hạn chế có provenance, reject overlap
   không chứng minh được; không infer ownership từ current dimensions/pose.
2. Dùng cùng function cho `_environment_layer` và `_hybrid_layers`.
3. Publish artifact qua resolver/store, giữ failures/diagnostics; không mutate input.

Tests: source obstacle biến mất sau move/delete; object collider chỉ ở nơi mới;
floor witness còn; ignored candidate giữ collision; user box không đục nền.
**Exit:** [x] matrix pass; [x] cả hai builder consume cùng background identity.

## Sprint AUD-01.S3 — Consumer/export regression và legacy recovery

**Input:** implementation S2; legacy/mixed scenes và package builder.
**Output:** exported candidate regression, recovery/blocker và evidence.
**Contract:** candidate bind current revision/background checksum; edit không
kế thừa validation/approval; corrupted legacy metadata không tạo candidate PASS.

Implement: verify candidate inventory/ZIP; thêm negative recovery và overlap
cases; kiểm transform quay/di chuyển và delete/restore nhiều lần. Ghi USD-stage
proof riêng với Isaac acceptance pending; không thêm workflow mới.
Tests: local real GLB/artifact consumer; pxr nếu runtime có; downstream regression.
**Exit:** [ ] exported environment/object occupancy đúng; [ ] no old artifact rewrite;
[ ] limitations của legacy OBB được ghi rõ.

## Verification và Definition of Done

```bash
.venv/bin/pytest tests/test_simulation/test_carve.py tests/test_orchestration/test_scene_extraction.py tests/test_orchestration/test_simulation_package.py tests/test_scene/test_editing_review.py tests/test_scene/test_editing_v2.py -q
```

Thêm planned `tests/test_simulation/test_collision_edit_composition.py` sau khi
tạo. Chạy Ruff như AGENT_GUIDE. DONE khi matrix/export regressions pass và
refs/checksums/legacy behavior được verify. Real Isaac proof ghi ở AUD-05.

## Result / Evidence

### AUD-01.S1 — Implemented

- Added optional `SceneObject.source_collision` schema 1.0 and triangle-membership
  sidecar contract. Old SceneIR payloads omit the absent field and keep the same
  canonical checksum.
- Extraction binds reconstructed candidates to the exact source environment
  artifact and source transform. Edits keep that ownership immutable; duplicated
  objects do not claim the source region.
- Consumer fixture verifies source/sidecar byte checksums, reference identity,
  bounds, and duplicate triangle claims. Legacy JSON remains readable without
  synthesizing metadata; S2 must recover from the original extraction or block a
  rebuild that needs ownership.
- Before/after boundary: `_carved_environment` still consumes the current SceneIR
  transform/status in S1; extraction now produces immutable source provenance for
  the S2 builder. `extract_scene` and `use_boxes` are the production bind points;
  `duplicate_object` explicitly clears source ownership. SceneIR parsing and the
  triangle-sidecar reader are the S1 consumer proofs. No DB migration or runtime
  config change is needed because the optional field is part of the immutable
  SceneIR artifact; legacy metadata is never backfilled from edited state.
- Reproduced baseline on the local pallet fixture: 9,228 environment triangles
  before confirmation; confirmation removes 9,216 and leaves 12. Moving or
  deleting the confirmed object restores all 9,228 triangles because the current
  carver follows the edited pose/active flag. Restoring at the moved pose still
  removes none. User-added boxes at the source pose and overlapping OBBs are also
  blindly carved by the current builder, each removing the same 9,216 triangles.
- Verification: `pytest tests/ -q` passed with 1,562 passed and 40 skipped
  (329.83s). After adding the final duplicate-owner and nonfinite-dimension
  negative cases, all 50 focused tests across ownership, SceneIR contracts,
  extraction, simulation package, and edit commands passed. Full Ruff check and
  format check passed; the TypeScript/Pydantic mirror, frontend lint, and
  frontend typecheck passed.

### AUD-01.S2 — Implemented

- `_carved_environment` verifies source geometry bytes against the SceneIR ref,
  loads the GLB without face processing, and resolves exact membership sidecars
  before using source OBBs. Exact and OBB claims share one triangle-ownership
  check; ambiguous overlaps fail with object/triangle diagnostics.
- Confirmed objects carve their immutable source region whether active or hidden;
  reconstructed deletions, including deleted candidates, also remove their
  source region. Ignored and pending candidates retain background collision.
  User-added objects do not carve. Duplicated objects remain independently
  collidable without claiming or requiring source ownership.
- Legacy reconstructed objects that need a source carve but have no ownership
  fail closed before publishing a new revision; their source artifact remains
  resolvable. Input SceneIR and mesh arrays are not mutated.
- `_environment_layer` and `_hybrid_layers` now consume one `CarvedBackground`
  value. Its deterministic identity binds the source byte checksum, source face
  count, carve margin, algorithm, and packed removed-triangle mask. The identity
  is recorded in SceneIR provenance, CandidateManifest build-config checksum,
  the hybrid request, and package README.
- Regression coverage checks move/delete/restore/hide/ignore/delete-candidate,
  duplicate and user-added behavior, retained floor triangles, legacy missing
  ownership, exact-membership use, OBB/OBB and exact/OBB overlap rejection, and
  hybrid collider placement at the edited transform. This remains CPU fixture
  evidence; Isaac runtime acceptance stays in AUD-05.
- Verification: `pytest` over carve, collision-edit composition, extraction,
  simulation package, scene editing, and review workflow passed (39 passed).
  `pytest tests/test_api/test_review_routes.py -q` also passed (2 passed).
  `ruff check src/ tests/` passed; `ruff format --check src/ tests/` reported
  455 files already formatted.
