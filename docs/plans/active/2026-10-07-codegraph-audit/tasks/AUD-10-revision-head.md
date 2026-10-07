# AUD-10 — Committed scene head, CAS và bounded recovery

## Metadata và goal

- PLANNED; P1; EX-PRODUCT; canonical PRODUCT-06/08, SCENE-10.
- SELF-CODE minimal persistence protocol; REUSE RuntimeDatabase, resolver/store.
- Goal: current lookup không scan lịch sử; simultaneous writers không lost update;
  recovery hoạt động với lịch sử trên 1.000 revision.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0015](../../../../decisions/0015-scene-revision-head.md).

## Baseline và scope

CodeGraph: SceneEditor.current/_recover/_publish/publish_next/apply,
restore_revision, reobjectify, build_simulation_package, RuntimeDatabase._initialize.
Current recovery scan tuyến tính, ceiling 1.000; cached check-before-publish
không là DB CAS giữa nhiều processes. Artifacts và DB không có joint transaction.

Owned: orchestration/scene/editor.py và supporting runtime record,
jobs/database.py migration, publication callers trong scene/review,
artifact verification glue; packaging/deletion/bootstrap consumers khi schema đổi.
Tests: scene_editor, runtime_migrations/persistence, revision_lifecycle,
scene_deletion và test_packaging. Không rename old revisions hoặc rewrite payloads.

## Input / output / data contract

Input: committed head, expected_scene_revision, validated proposed SceneIR và
writer/operation identity. Output: verified immutable SceneRevision + new committed
head hoặc SceneRevisionConflictError. Reader chỉ thấy committed state.

Proposed SceneHeadRecord: version, job_id, scene_id, scene_revision,
scene_ir_checksum, scene_reference (byte checksum), committed generation,
allocation_sequence/high-water và updated_at. PendingPublishRecord: writer/token,
expected generation/base revision, reserved target revision, exact payload/ref,
lease/expiry, status. S1 khóa table/index/CAS và minimal serialization.

Reserve next numeric revision name duy nhất; orphan revision URI không được reuse
với payload khác. Allocation high-water tách committed generation để recovery
không bắt revision names liên tục. Lineage theo edited_from/supersedes và exact
head refs, không lexical max filename. Giữ naming scheme hiện có và API fields.
Reserve chỉ ở publication phase; không khóa scene suốt GPU compute.

Publish/verify immutable bytes rồi CAS head theo expected generation và writer
fencing; loser/stale operation không commit. Orphan giữ diagnostic, không auto-delete.
Legacy backfill một lần verify lineage/checksums; corruption/gap không bị ignore.
Long repair có paging/continuation, không scan toàn bộ trong HTTP current lookup.
Missing head lúc migration cần truthful recovery status/explicit repair, không
trả nhầm revision cũ hoặc current head từ uncommitted artifact.

## Logic change và dependent updates

Risk: **Rất cao** khi chỉ sửa một phần. Logic delta: Committed head/CAS thay local recovery authority.
Cần sửa đồng bộ: SceneEditor apply/publish_initial/publish_next/current/revision/restore, objectify/extraction, physics_enrich, object/collider mutations, package readers và packaging.
Acceptance xuyên consumer: Mọi reader thấy committed head, mọi writer dùng cùng CAS; crash/concurrent/stale publication không overwrite user edit hoặc tạo orphan thành current.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1/S2 độc lập UI/object features. Consumers AUD-07/08/09 và physics_enrich phải
chuyển sang một publication path. S3 migration/export/restore cần packaging fixtures,
không cần cloud/provider access để kiểm local protocol.

## Sprint AUD-10.S1 — Persist head và legacy backfill

**Input:** DB schema hiện tại + immutable revision chain ngắn/dài.
**Output:** head/pending schemas, migration và verified backfill/repair entrypoint.
**Contract:** old bytes/checksums không đổi; head refs resolve; wrong checksum/
lineage không chọn làm current; numeric revision >= 1.001 hỗ trợ.

Implement: minimal forward migration và typed records; explicit dry-run/apply
repair script trong scripts/studio/ nếu cần. Backfill dùng validated supersedes/
edited_from, không mtime/filename sorting; record incomplete repair và continuation.
Update data-package manifest/export/restore/deletion schema consumers sau inspect.
Tests: old DB migration, empty/new scene, 1.005 revisions, corruption/gap/orphan,
repeat backfill idempotency, missing head, retained old ref/content checksums.
**Exit:** [ ] verified legacy head; [ ] clear corruption/migration diagnostics.

## Sprint AUD-10.S2 — Atomic publication protocol cho mọi writers

**Input:** expected head + proposed content + writer/lease identity.
**Output:** exactly one committed next head hoặc conflict; no overwritten immutable URI.
**Contract:** reserve target/name → publish/verify → CAS commit; same head winner
duy nhất; cancelled/expired writer không commit; readers never see pending revision.

Implement: route publish_initial/apply/publish_next/restore/reobjectify/enrichment
qua shared protocol; pass original expected revision đến commit. Allocate high-water
an toàn; handle lease expiry và uncommitted artifact without URI reuse. Don't hold
DB transaction across long GPU compute/remote upload. Cached editor state chỉ là cache.
Tests: two independent registries/processes, same expected head, fault injection
before/after publish/commit, old writer finishes late, cancelled operation, duplicate
retry; SQLite and available PostgreSQL locking separately.
**Exit:** [ ] lost update prevented; [ ] artifact/DB partial failure recoverable;
[ ] all writers use same commit boundary.

## Sprint AUD-10.S3 — O(1) current reads và recovery consumer proof

**Input:** committed head with short/long history + remote resolver test double.
**Output:** bounded normal lookup và recovery/export/restore evidence.
**Contract:** metadata/resolver calls cho current không tăng theo revision count;
verify exact head bytes; remote unavailable/corrupt head không là success.

Implement: current reads head then ref, not `_recover` on every request. Explicit
repair handles missing/corrupt head/pending publication; package export/restore
preserves head/intents and refuses unsafe active operations per existing policy.
Delete/trash/restore updates head ownership atomically without deleting history.
Tests: compare resolver call counts 2 vs 1.005 revisions, restart/cache freshness,
cross-process new head, remote checksum failure, packaging roundtrip, trash/restore.
Use call-count assertions, không flaky wall-clock thresholds.
**Exit:** [ ] bounded lookup proven; [ ] packaging/deletion consumers pass;
[ ] no 1.000 ceiling in supported committed/repaired history.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_scene_editor.py tests/test_orchestration/test_runtime_migrations.py tests/test_orchestration/test_runtime_persistence.py tests/test_orchestration/test_revision_lifecycle.py tests/test_orchestration/test_scene_deletion.py tests/test_packaging/test_data_package.py -q
```

Planned tests/test_orchestration/test_scene_head.py. DONE khi race/crash/legacy/
call-count/packaging matrix pass; PG/remote-provider proof được phân loại đúng.

## Result / Evidence

Pending — migration version, head/byte checksums, resolver call counts,
concurrency winners/conflicts và repair/restore evidence.
