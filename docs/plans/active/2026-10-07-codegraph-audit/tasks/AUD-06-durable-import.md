# AUD-06 — Import packaging durable và có recovery

## Metadata và goal

- IN PROGRESS (S1 complete; S2/S3 open); P1; EX-PRODUCT; REC package_splat port.
- Canonical PRODUCT-02/08/09. SELF-CODE durable operation, REUSE packaging adapter.
- Goal: PLY/SOG view import durable; API crash không mất request; retry/cancel an
  toàn; READY chỉ khi SOG delivery đã verify.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0014](../../../../decisions/0014-durable-heavy-operations.md).

## Baseline và scope

CodeGraph: `create_import`, `ImportService.create/package/_update`, `ImportedScene`,
`package_splat`, `RuntimeDatabase._initialize`. Current API enqueue BackgroundTasks
sau persist PACKAGING; no durable worker recovery. Publish exception sau packaging
cũng cần terminal/recovery handling, không để PACKAGING vô hạn.
Current detector/import chỉ nhận gaussian_ply/gaussian_ply_colmap; SOG hiện là
output, chưa là accepted input. Owner bổ sung .sog bên cạnh .ply từ SuperSplat.

Owned: src/services/orchestration/uploads/scene_imports.py và minimal import queue,
src/api/studio/imports.py, worker_cli dispatch, DB migrations, frontend import
status/client/contracts, tests/test_orchestration/test_scene_imports.py,
tests/test_api/test_studio_routes.py, frontend/tests/studio-input-flows.test.tsx.
Không tạo ReconstructionBundle, metric/collision/validation eligibility chỉ từ
READY import. [AUD-25 continuation](AUD-25-imported-3dgs-continuation.md) đã Deferred;
task này chỉ import/view, không thêm processing command/source adapter hoặc CTA đó.

## Input / output / data contract

Input: verified UploadRecord gaussian_ply/gaussian_ply_colmap hoặc proposed typed
gaussian_sog, source format/version/member inventory và source checksum,
selected packaging config/GPU requirement, import ID và requester.
Output: ImportedScene READY + immutable delivery_ref hoặc explicit failed/
cancelled/waiting operational status; upload bytes giữ nguyên.
PLY packaging tạo derived SOG; uploaded SOG được bounded validate/read rồi reuse
exact bytes cho delivery khi runtime hỗ trợ. Không bắt SOG→PLY→SOG để xem. Source
ref luôn actual uploaded format, không rename SOG thành PLY hoặc bỏ lossy provenance.
Archive containing SOG khác generic COLMAP/LiDAR ZIP; extension PK/ZIP không đủ.
AUD-24.S1 chốt `InputAssetFormat`/`GaussianViewFormat` và Gaussian view intent;
AUD-06.S1 dùng lại các enum này thay vì tạo format registry cạnh tranh. AUD-06.S1
sở hữu bounded version/model/SH/limits validation thực tế và durable import;
`gaussian_sog` trong contract chưa chứng minh decoder hoặc runtime support.
Geometry continuation/source adapter không thuộc active scope.

Public ImportedScene hiện PACKAGING/READY/FAILED. S1 chốt additive operation
projection cho queued/waiting/running/attempt/error và CANCELLED khi có cancel;
update TypeScript/consumers cùng change. Old records thiếu operation fields có
default/omission semantics; không diễn giải PACKAGING cũ là lease đang sống.

Operational record: version, operation_id/import_id, upload checksum, packaging
config checksum, attempt, status, owner/fencing/lease/heartbeat, timestamps,
delivery_ref/error. Enqueue atomically với import record. READY commit chỉ sau
SOG publish/byte verify; complete bằng expected lease/attempt CAS, không chỉ
compare old status. Retry tạo attempt mới, giữ history/logs và cùng config/input.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Import từ BackgroundTasks sang
durable worker và nhận PLY/SOG làm source.
Cần sửa đồng bộ: input kind/format classifiers/upload allowlists, shared validation
ports, import creation/DB queue, worker/admission, ImportedScene DTO/status/source
refs, card/import workspace/polling/retry/trash/restore và AUD-24 view consumers.
Acceptance xuyên consumer: Old READY imports đọc được; PLY/SOG view verified;
queued/waiting/cancel/fail không bị coi READY; two workers publish một delivery đúng source.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 queue/schema có thể làm trước; S2/S3 dùng AUD-07 admission primitives. Actual
GPU SOG smoke cần installed package_splat runtime; CPU fake-packager không thay proof.

## Sprint AUD-06.S1 — Persist queue cùng import creation

**Status:** Complete on this branch; worker lease recovery/admission and retry/cancel remain S2/S3.

**Input:** upload verified và create-import request.
**Output:** import record + durable queued operation cùng transaction, API status.
**Contract:** no acknowledged import without durable scheduling; no BackgroundTasks
as authoritative scheduler; import lifecycle không trở thành reconstruction job.

Implement: inspect record/storage; add migration/typed queue; API validate+persist,
worker discovers request sau restart. Existing PACKAGING records được bootstrap
vào recovery nếu chưa có delivery/ref/live lease, không duplicate READY work.
Extend typed input kind/UploadRecord/ImportedScene/API/TypeScript format allowlists
for SOG and define shared bounded validation/version registry; legacy PLY payloads
remain readable. Don't overload gaussian_ply or infer source kind from delivery_ref.
Tests: transaction rollback giữa two inserts; restart after API response;
duplicate request/idempotency decision; old PACKAGING/READY records migration;
new SOG kind across direct/proxy/import parsers and unsupported version/model.
**Exit:** [x] new request survives API restart; [x] legacy PACKAGING is queued or failed explicitly, and READY remains unchanged.

## Sprint AUD-06.S2 — Leased worker, admission và publication

**Input:** queued operation + source ref/config + AUD-07 reservation.
**Output:** verified SOG delivery_ref và one committed terminal result.
**Contract:** one live owner; stale worker can't mark READY; publish before CAS;
unknown headroom waits without changing quality; input/config stable.

Implement: claim/touch/fence, resolve source/extract valid member, call REC port
in worker; catch typed packaging/publish failures into retryable diagnostics.
For SOG, verify meta/count/version/model, required texture members/dimensions/
channels/codebooks and runtime readability, then publish exact verified delivery;
no external texture fetch. ZIP/member/decoded size and resource bounds apply.
Reuse immutable content URI; verify artifact tồn tại trước reuse. Release
reservation sau process teardown; retain failed scratch for diagnosis.
Tests: two independent workers, lease expiry, worker crash before/after SOG publish,
bad ZIP member, corrupt/missing SOG textures/meta, duplicate/traversal/truncated
archive, source checksum mismatch, decode bounds, publish failure, stale terminal
CAS; real PLY packaging and uploaded SOG reuse with original byte identity.
**Exit:** [ ] no duplicate commit; [ ] READY refs resolve and byte checksum matches.

## Sprint AUD-06.S3 — Retry/cancel và truthful UI

**Input:** waiting/running/failed operations và user command.
**Output:** persisted attempt/cancel state, readable status/error, recovery evidence.
**Contract:** cancel queued prevents start; running cancel kills/reaps child before
terminal; retry only known transient failures; no automatic scratch deletion.

Implement: minimal role-guarded retry/cancel Studio routes; typed polling status,
waiting reason and stale poll protection. PLY/SOG source badges và view capability
projection; không expose Xử lý tiếp vì AUD-25 Deferred.
Tests: queued/running cancel, failed publish retry, bad input nonretryable;
API permissions, Vitest status/loading/error, browser import/restart journey;
real SOG consumer readability when runtime available.
**Exit:** [ ] no permanent PACKAGING after interrupted operation; [ ] UI mirrors DB;
[ ] local vs GPU packaging acceptance separated.

## Verification và DoD

```bash
./.venv/bin/pytest -q \
  tests/test_api/test_studio_routes.py tests/test_api/test_guest_ownership.py \
  tests/test_orchestration/test_runtime_migrations.py tests/test_orchestration/test_scene_deletion.py \
  tests/test_orchestration/test_scene_imports.py tests/test_orchestration/test_upload_input_kinds.py \
  tests/test_orchestration/test_import_queue.py tests/test_orchestration/test_direct_upload.py \
  tests/test_reconstruction/test_input_detection.py tests/test_reconstruction/test_sog_input.py
```

Added `tests/test_orchestration/test_import_queue.py`. Frontend focused
tests/studio-input-flows.test.tsx và tests/input-kinds.test.ts; gates theo guide.
DONE khi crash/retry/cancel/publication matrix pass và real SOG packaging/consumer
proof available; không suy cloud restart acceptance từ local fixture.

## Result / Evidence

AUD-06.S1 now stores an import operation atomically with its imported-scene row,
removes HTTP `BackgroundTasks` from the authoritative path, and lets the
standalone worker recover legacy `PACKAGING` records and process queued work
after API restart. Requester-scoped `Idempotency-Key` replay returns the same
import only for an identical upload/name fingerprint. Import deletion/trash
stores the operation row too; active queued/running operations block trash, and
restore recreates the exact operation with the import.

SOG input uses the shared `GaussianViewFormat` contract and bounded bundled-v2
metadata checks. PLY/ZIP produce SOG through the REC packaging port; SOG delivery
copies source bytes and verifies the published checksum. Old `READY` rows remain
readable and are not reprocessed. UI copy, accepted suffix/MIME, contracts, and
status copy now include SOG and the queued worker lifecycle.

Local evidence: selected backend integration suites **130 passed, 4 skipped**;
full frontend suite **336 passed across 48 files**; `ruff check src/ tests/`,
`ruff format --check src/ tests/`, and `git diff --check` passed. Frontend ESLint,
TypeScript typecheck, and production Webpack build passed. After the final SOG
copy/test update, the 3 directly affected Vitest files passed again (**26 tests**).
Chrome DevTools on the
production build rendered `/new/import-scene`; visible copy names PLY/SOG/ZIP,
the file input accepts `.ply,.sog,.zip,application/zip,application/x-sog`, and
the page had no console errors or warnings.

Still open by design: a worker crash after claiming `RUNNING` is not reclaimed
in S1; lease heartbeat/recovery, shared GPU admission, retry/cancel, and full
texture decode/dimension/runtime validation are S2/S3 acceptance. No GPU or
cloud-restart claim is inferred from these local checks. Browser verification
proves the rendered upload surface and allowlist only; it does not prove a real
SOG decoder or production upload/worker run.
