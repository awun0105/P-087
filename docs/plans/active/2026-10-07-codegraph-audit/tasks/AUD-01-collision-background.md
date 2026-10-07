# AUD-01 — Background collision đúng sau object edits

## Metadata và goal

- Status: PLANNED; priority P0; boundary EX-SCENE → EX-SIM, PRODUCT publication.
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

Proposed SourceCollisionRegion có version, object_id, source_geometry_ref,
extraction_revision, source_transform, region_kind và region_ref hoặc source
OBB dimensions. Đây là extraction provenance bất biến, không phải editable
world transform thứ hai. Membership indices bind đúng geometry checksum;
region_ref phải resolve, indices trong bounds, dimensions dương/hữu hạn.

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

## Dependencies

S1 độc lập. S2 dùng contract S1. S3 tích hợp AUD-02 capability path; real Isaac
acceptance đi qua AUD-05, không phải điều kiện cho CPU regression pass.

## Sprint AUD-01.S1 — Regression và source ownership

**Input:** fixture mesh sàn + vật cản, source extraction, SceneIR chưa edit.
**Output:** regression failing ở current carve; typed ownership fixture và
serialization/version decision, kể cả legacy recovery case.
**Contract:** source transform/geometry checksum không đổi qua move/delete;
membership không chồng ownership trái phép; source data không là workflow state.

Implement:

1. Dùng `_scene_job` fixture hiện có; đo faces/occupancy trong vùng vật nguồn
   và điểm witness trên sàn/tường, không chỉ assert active flag.
2. Repro confirm → move, delete, restore, ignore, user-added và overlap.
3. Chốt minimal metadata/sidecar và producer/consumer reader; preserve old JSON checksum.

Tests: unit validation của refs/indices; content vs byte checksum; old payload
roundtrip; negative wrong source checksum/source pose missing.
**Exit:** [ ] regression chứng minh lỗi; [ ] contract/migration fixture có consumer proof.

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
**Exit:** [ ] matrix pass; [ ] cả hai builder consume cùng background identity.

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

Pending — ghi riêng evidence và exit checklist của S1, S2, S3 sau implementation.
