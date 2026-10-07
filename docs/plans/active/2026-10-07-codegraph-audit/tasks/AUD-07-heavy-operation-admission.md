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

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Shared resource admission và operation fencing.
Cần sửa đồng bộ: ResourceAdmission, job runner/worker_cli, objectify/import/validator commands, telemetry/status UI và cancellation.
Acceptance xuyên consumer: Cạnh tranh job/operation không double reserve/overcommit; waiting giữ chosen config, stale worker không commit/release reservation của worker mới.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

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
**Exit:** [x] old jobs unchanged in tests; [x] operation adapter no fake manifests.

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

### AUD-07.S1 — Admission primitive cho operation

- Base commit: `0a0f11a` (`AUD-10.S3`). CodeGraph trước khi sửa đã index 753
  files, 13,594 nodes, 38,967 edges; trace `ResourceAdmission`, `_reserve`,
  `job_reservation`, `touch_job_reservation`, `_reclaim_disk` và callers trong
  runner/worker. Direct consumers cần đồng bộ là job lookup, heartbeat và bảo vệ
  scratch khi reclaim.
- Thay đổi: thêm `OperationResourceProfile`, `OperationAdmissionRequest` và
  `OperationAdmissionResult`; `admit_operation()` dùng chung `_assess()` với job,
  giữ identity/input/config checksum trong request/result và reservation. Không
  tạo `JobManifest` giả. Job và operation dùng cùng transaction/advisory lock;
  duplicate operation không được nhận lần hai. Operation release compare-delete
  theo identity và lặp lại an toàn.
- Logic before/after: job dùng phép tính headroom cũ qua shared primitive và giữ
  contract legacy (resource chưa có model vẫn chạy độc quyền GPU để đo); operation
  fail-closed khi estimate/headroom không biết, kiểm GPU affinity và RAM/đĩa. CPU
  operation bỏ qua VRAM nhưng vẫn reserve RAM/đĩa. Job disk reclaim bảo vệ parent
  job của operation reservation. Wait result giữ nguyên checksums/profile, không
  bịa ETA hoặc phần trăm.
- Reservation serialization: không đổi DB schema hay migration; payload job mới
  tiếp tục ghi shape cũ, reader mới đọc payload cũ với `gpu_required=True`; payload
  operation thêm operation/parent/checksum identity. Không có artifact sinh ra.
- Changed files: `src/services/orchestration/jobs/admission.py`,
  `tests/test_orchestration/test_resource_admission.py`, task record và plan index.
- Consumer proof: job admission và operation adapter cạnh tranh trong cùng SQLite
  reservation table; operation chặn job dùng cùng GPU; job không ghi đè operation
  reservation của cùng worker; CPU reservation không chiếm GPU nhưng giữ RAM/đĩa;
  reclaim giữ scratch của parent job; old JSON payload đọc được. Non-job wait chưa
  được persist/project vào queue hoặc UI — thuộc tích hợp AUD-07.S2/S3.
- Focused checks: **101 passed, 4 skipped** trên ResourceAdmission, objectify
  queue, SceneEditor, runtime migrations và preview cancellation. Bốn skip đều là
  PostgreSQL migration/locking tests cần `R2S_TEST_POSTGRES_URL`, biến này không
  được cấu hình. `.venv/bin/ruff check src/ tests/` passed;
  `.venv/bin/ruff format --check src/ tests/` báo 468 files formatted;
  `git diff --check` passed. Các cạnh tranh DB đã chạy trên SQLite; chưa có
  PostgreSQL contention proof hoặc worker/GPU runtime smoke.
- CodeGraph: trước sửa đã xác nhận callers và source hiện hành. Sau sửa MCP báo
  auto-sync disabled do OS watch/file limit; `codegraph sync` bị lock bởi daemon
  CodeGraph đang chạy. Không xóa lock; phần source thay đổi được đọc trực tiếp
  sau cảnh báo stale. Post-edit reindex chưa được xác nhận.
- Pre-flight (GUIDE.md Rule 13): CodeGraph/source caller map trước sửa; impact
  gồm ResourceAdmission, job wrapper, reservation readers và scratch reclaim;
  hiểu rõ transaction/advisory lock và old payload defaults; minimal-code dùng
  bảng JSON/DB primitives sẵn có, không thêm migration/API/UI; checks nêu trên;
  DevTools: n/a — không đổi UI.
- Next: AUD-07.S2 nối reobjectify queue với admission lease và CAS của AUD-10.S2;
  waiting phải giữ base revision/input/config, stale worker không được publish.
