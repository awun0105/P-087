# AUD-07 — Admission, lease và revision fencing cho heavy operations

## Metadata và goal

- PLANNED; P1; EX-PRODUCT; canonical PRODUCT-02/08/09, SCENE-10.
- SELF-CODE thin adapter; REUSE ResourceAdmission/DB/subprocess primitives.
- Goal: reobjectify/import/validation cạnh tranh tài nguyên theo một cơ chế;
  không vượt user edits hoặc terminal state khi stale worker hoàn tất.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0014](../../../../decisions/0014-durable-heavy-operations.md),
  [ADR 0015](../../../../decisions/0015-scene-revision-head.md).

## Baseline và scope

CodeGraph: `ResourceAdmission`, `_reserve`, `process_next`, `_claim`,
`recover_interrupted`, `reobjectify`, `SceneEditor.publish_next`.
Objectify có DB claim/recovery nhưng ngoài admission. reobjectify đọc current
sau compute rồi publish lên revision đó; pre-run base_revision check chưa đủ.

Owned: orchestration/jobs/admission.py và supporting processing demand logic,
orchestration/scene/objectify_queue.py và publication glue objectify.py,
jobs/worker_cli.py, runtime DB migration và status/API projection nếu cần.
Tests: test_resource_admission.py, test_scene_objectify_queue.py, test_scene_editor.py,
test_runtime_migrations.py và worker cancellation tests.
Không viết lại SAM2/geometry algorithms hoặc generic scheduler framework.

## Input / output / data contract

Input: operation identity/input/config + resource profile + live headroom + queue
record lease; existing reconstruction JobManifest admission vẫn chạy tương thích.
Output: reservation hoặc waiting reason, heartbeat/release, fenced terminal outcome.

Proposed minimal OperationAdmissionRequest: operation_kind (reobjectify,
import_package, isaac_validate), operation_id, parent job/import identity,
input_checksum, config_checksum, resource demand/profile, requested GPU affinity.
Không tạo fake JobManifest cho import. Core admission dùng shared demand/reserve
primitive; old job entrypoint là adapter giữ contract/API hiện có.

Reservation thêm optional operation identity/lease binding bằng compatible
serialization/migration. Queue lease gồm owner process identity, generation/
fencing token, heartbeat/expiry, attempt. hostname không là unique live-owner proof.
Base scene revision giữ từ request tới commit; result của stale base/lease không
được publish current head. Waiting giữ selected quality/config checksum; cancelable.
Unknown resource estimate/headroom không được giả đủ; CPU boxes không đòi GPU
nếu profile thực tế chỉ CPU nhưng vẫn kiểm RAM/disk.

## Dependencies

S1 không phụ thuộc import/validator implementation. S2 dùng S1; atomic scene
commit cần AUD-10.S2. S3 phối hợp AUD-06/AUD-05 consumers để test cạnh tranh;
không tạo dependency cycle giữa contract S1 và final runtime proof.

## Sprint AUD-07.S1 — Admission primitive cho operation

**Input:** existing job demand/reservations + non-job operation profiles.
**Output:** minimal typed request/adapter và backward-compatible records.
**Contract:** preserve old admission semantics; same machine resources cannot
be double-reserved; selected config/input unchanged while waiting.

Implement: inspect exported callers và estimator; extract nhỏ nhất reserve/decide
primitive khỏi JobManifest dependence; keep job wrapper. Operational waiting
projection dùng measured reasons, không fabricated percentage/queue ETA.
Tests: old job admission suite, operation vs job reservation, GPU affinity,
unknown/insufficient RAM/VRAM/disk, release idempotency, migration/old record.
**Exit:** [ ] old jobs unchanged in tests; [ ] operation adapter no fake manifests.

## Sprint AUD-07.S2 — Reobjectify lease và commit theo requested revision

**Input:** queued objectify request với base_revision + operation admission S1.
**Output:** admitted/fenced attempt hoặc waiting; new scene revision khi base còn đúng.
**Contract:** reserve + claim không double-execute; heartbeat current owner;
compute input base được giữ đến atomic publication; stale result không overwrite edits.

Implement: integrate admission before heavy execution; handle claim/reserve failure
rollback/release. Pass expected base revision xuyên reobjectify, không đọc latest
để hợp thức hóa result. Commit qua AUD-10 CAS; heartbeat lease/reservation;
recovery dựa token/expiry, không hủy healthy same-host worker do startup.
Tests: user edits during compute; two workers same host; expired lease completes
late; worker restart; insufficient resource waiting; no geometry publish commit
on stale base; diagnostics retained.
**Exit:** [ ] lost-update regression blocked; [ ] one valid current owner commits.

## Sprint AUD-07.S3 — Cancellation và multi-operation resource proof

**Input:** queued/running operation, cancel command, competing job/import/validator.
**Output:** terminal cancellation hoặc completion, resources released đúng lúc.
**Contract:** cancel fences completion; kill/reap trước release; unknown headroom
waits; failed/cancelled scratch preserved; no silent boxes/quality downgrade.

Implement: add minimal objectify cancel API/status fields/typed UI if absent;
propagate cancel to subprocess lifecycle. Use concrete consumers AUD-06/AUD-05,
avoid parallel scheduler abstraction. Test process death/lease recovery and fairness
using persisted order existing policy, không tự thay scheduling policy.
Tests: real child kill/reap, cancel-vs-complete race, all exception paths release,
stale lease cannot release new owner's reservation; two-worker GPU smoke khi có.
**Exit:** [ ] process/resource lifecycle tested; [ ] public wait/cancel truthful;
[ ] GPU contention proof ghi riêng, không lấy mocked headroom làm empirical evidence.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_resource_admission.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_scene_editor.py tests/test_orchestration/test_runtime_migrations.py tests/test_reconstruction/test_preview_cancellation.py -q
```

Frontend focused tests/studio-resource-wait.test.tsx và tests/object-review.test.tsx
nếu status UI đổi. DONE khi operation/job competition, lease/cancel/stale revision
matrix và concrete consumer handoff pass; GPU smoke limitations phải được ghi.

## Result / Evidence

Pending — demand/profile checksums, waiting reasons, lease generations,
reservation lifecycle và publication/cancellation evidence theo từng sprint.
