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
**Exit:** [x] verified legacy head; [x] clear corruption/migration diagnostics.

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
**Exit:** [x] lost update prevented; [x] artifact/DB partial failure recoverable;
[x] all SceneIR writers use the same commit boundary.

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
**Exit:** [x] bounded lookup proven; [x] packaging/deletion consumers pass;
[x] no 1.000 ceiling in supported committed/repaired history.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_scene_editor.py tests/test_orchestration/test_runtime_migrations.py tests/test_orchestration/test_runtime_persistence.py tests/test_orchestration/test_revision_lifecycle.py tests/test_orchestration/test_scene_deletion.py tests/test_packaging/test_data_package.py -q
```

Planned tests/test_orchestration/test_scene_head.py. DONE khi race/crash/legacy/
call-count/packaging matrix pass; PG/remote-provider proof được phân loại đúng.

## Result / Evidence

### AUD-10.S1 — Persist head và legacy backfill

- Base commit: `5eb88b3` (`AUD-04.S3`). CodeGraph traced `SceneEditor.revision` →
  `_load_revision`, `ArtifactResolver` local/remote listing, `RuntimeDatabase`
  migrations, package publisher allowlists, và trash/restore row allowlists.
- Migration v12 thêm `r2s_scene_heads`, `r2s_scene_head_repairs`,
  `r2s_scene_head_backfill_items`, và `r2s_scene_publications`. Typed head/repair/
  item payloads bind canonical record checksums, indexed DB columns, identity,
  immutable artifact URI/checksum, allocation sequence và resumable page cursors.
- `SceneHeadBackfill.inspect` là dry-run chỉ đọc. Apply chạy hai lượt có giới hạn
  trang: verify artifacts/lineage, rồi recheck bytes trước khi atomically lưu head.
  `supersedes_revision` quyết định lineage; thiếu parent, orphan/branch, duplicate
  revision number, corrupt bytes và thay đổi inventory không được promote.
  `scripts.studio.scene_head` dùng `DATABASE_URL`, `ARTIFACT_ROOT`, và optional S3
  settings; mỗi invocation mặc định chỉ apply một page và có thể resume.
- Artifact bytes/checksums cũ được giữ nguyên. Data package và production importer
  giữ/validate stable head, repair và backfill rows; pending publication chặn pack/
  publish. Trash/restore giữ nguyên head/repair rows, chặn active repair/publication.
- CodeGraph after implementation: 752 files, 13,536 nodes, 38,589 edges; index
  up to date. Index hiển thị `SceneHeadBackfill`, CLI, typed records và các package/
  deletion consumers.
- Verification: focused matrix **123 passed, 4 skipped**; skips cần
  `R2S_TEST_POSTGRES_URL`. `.venv/bin/ruff check src/ tests/` và changed scripts
  passed; `.venv/bin/ruff format --check src/ tests/` reported 470 files already
  formatted; `git diff --check` passed.
- Limits: head/backfill verified locally and through `MemoryObjectStore`; no live
  S3 provider or PostgreSQL locking proof. At S1, readers and writers still used
  the artifact-only path; AUD-10.S2 below replaces it for DB-backed jobs. The
  standalone no-database seam retains bounded legacy recovery for tests/tools.
- Next: AUD-10.S2 moves all scene writers to reserve/publish/verify/CAS.

### AUD-10.S2 — Atomic publication protocol

- Base commit: `e04f86c` (`AUD-10.S1`). CodeGraph refreshed after implementation:
  753 files, 13,582 nodes, 38,871 edges; index up to date. Traced `apply`,
  `publish_initial`, `publish_next`, `revision`, restore, extraction,
  `use_boxes`, reobjectify, registry construction, package handoff and deletion.
- No schema migration was needed: AUD-10.S1 already created
  `r2s_scene_publications`. `expected_generation` stores the target generation to
  satisfy the existing positive check. Pending payloads are checksummed and bind
  base revision, target revision, operation, fencing token, expiry, exact byte
  checksum/reference and lifecycle status.
- `SceneHeadRepository` now reserves under a short DB transaction, publishes and
  verifies artifact bytes outside that transaction, then commits the head and
  removes the reservation in one CAS transaction. Active duplicate writers
  conflict; an expired writer is fenced. Failed/cancelled writes leave ABORTED
  records and immutable orphan bytes; edit retry advances the numeric high-water
  instead of reusing the URI. A headless initial retry can reuse `rev-001` only
  when immutable storage confirms exact bytes.
- `SceneEditor` routes `publish_initial`, `apply`, and `publish_next` through this
  protocol when a RuntimeDatabase is configured. Restore, object/collider edits,
  extraction, box selection, reobjectify and physics-enrichment callers reach the
  same shared methods. Heavy compute remains before reserve. DB-backed reads load
  only the committed head; pending and headless legacy artifacts are not served.
  Legacy scenes require the verified `scripts.studio.scene_head --apply` repair.
- Package handoff preserves checksummed ABORTED publication diagnostics, redacts
  their unusable fencing token, and rejects active/corrupt rows. Trash/restore
  preserves ABORTED rows; active or invalid publication payloads still block
  deletion. Existing artifact bytes and checksum contracts are unchanged.
- Changed files: `src/services/orchestration/scene/heads.py`,
  `src/services/orchestration/scene/editor.py`,
  `src/services/orchestration/scene/identifiers.py`,
  `src/services/orchestration/projects/registry.py`,
  `src/services/orchestration/projects/deletion.py`,
  `scripts/studio/data_package.py`, `scripts/cloud/package_publish.py`,
  `tests/test_orchestration/test_scene_head.py`,
  `tests/test_orchestration/test_scene_deletion.py`,
  `tests/test_packaging/test_package_publish.py`, this task record and plan index.
- Schema delta: none; AUD-10.S1 migration v12 already owns the publication table.
  No external artifacts were generated; regression checks verify immutable
  artifact bytes/references and the production package handoff path.
- Consumer proof: CodeGraph found 3 `_publish_reserved` call paths and 15
  `SceneEditor.apply` callers. Extraction, restore, box selection, reobjectify,
  object/collider edits and physics enrichment publish through the shared editor
  boundary. Package create/import and trash/restore tests verify publication-row
  validation, retention and fencing-token redaction.
- Focused checks: **179 passed, 1 skipped** across scene-head/editor/deletion,
  package create/import, extraction, objectify queue, simulation package, project
  registry and scene API tests. The skip is
  `test_postgres_initial_reservation_has_one_winner`; `R2S_TEST_POSTGRES_URL` is
  unset. `.venv/bin/ruff check src/ tests/ scripts/studio/scene_head.py
  scripts/studio/data_package.py scripts/cloud/package_publish.py` passed;
  `.venv/bin/ruff format --check` reported 471 files already formatted;
  `git diff --check` passed.
- CodeGraph after implementation: 753 files, 13,585 nodes, 38,888 edges; index
  up to date. Final exploration verified `_publish_reserved`,
  `commit_publication`, and `_scene_revision_uris` plus their callers.
- Limits: PostgreSQL locking test skips when `R2S_TEST_POSTGRES_URL` is absent.
  No live S3 provider proof. Publication lease is 15 minutes and has no heartbeat;
  long artifact uploads can expire, leaving a safe orphan for a later retry.
- Next: AUD-10.S3 proves bounded current lookup, cross-process freshness,
  remote checksum failure and long-history recovery/packaging behavior.

- Pre-flight (GUIDE.md Rule 13): CodeGraph read publication/head/editor symbols
  and consumer callers; impact covers shared SceneEditor publication plus package
  and deletion boundaries; understood reserve → bind → immutable publish/verify
  → fenced CAS commit and pending-reader isolation; minimal-code reused the
  existing v12 records, ArtifactResolver, RuntimeDatabase and SceneEditor; checks
  are listed above; DevTools: n/a — no UI change.

### AUD-10.S3 — Bounded current reads and recovery consumer proof

- Base commit: `5d717f9` (`AUD-10.S2`). CodeGraph reindexed after the proof tests:
  753 files, 13,594 nodes, 38,967 edges; index up to date. Traced 31 callers of
  `SceneEditor.current`, the backfill CLI, package row validation/import, and
  trash/restore consumers.
- No production-code or schema change was needed: S2 already routes DB-backed
  `current()` through the committed head. Added deterministic call-count proof:
  both a one-revision scene and a repaired 1,005-revision history perform exactly
  one head query, one `ArtifactResolver.locate`, and zero revision-list calls.
  The legacy no-database test seam retains its explicit 1,000-step ceiling;
  persisted, committed/repaired histories do not use that recovery loop.
- Independent editors with separate SQLite connections and artifact caches see
  the newly committed revision via the shared object-store contract. When remote
  bytes are altered but retain the old checksum metadata, the reader raises
  `ArtifactChecksumError` and leaves no partial cache file.
- Package proof now imports a typed head plus its actual validated SceneIR bytes,
  then reads the restored revision through `SceneEditor.current()`. Trash/restore
  proof uses checksummed head, repair and lineage rows and confirms the original
  artifact checksum inventory is restored unchanged.
- Changed files: `tests/test_orchestration/test_scene_head.py`,
  `tests/test_orchestration/test_scene_deletion.py`,
  `tests/test_packaging/test_package_publish.py`, this task record and plan index.
- Schema delta: none. No generated artifact was retained; package/archive files
  were temporary test outputs. The tests verify their contained SceneIR byte
  checksum and the exact reference restored by the package importer.
- Focused checks: **180 passed, 1 skipped** across the AUD-10.S2 integration
  matrix. The skip is `test_postgres_initial_reservation_has_one_winner` because
  `R2S_TEST_POSTGRES_URL` is unset. Ruff check passed; Ruff format reported 471
  files already formatted; `git diff --check` passed.
- Limitations: these checks use SQLite and `MemoryObjectStore`; no PostgreSQL
  locking or live S3 provider acceptance is claimed. A healthy remote current
  read resolves one exact head artifact, while a remote service outage remains a
  visible read failure rather than a fallback to an older revision.
- Next: AUD-07.S1–S2 add shared worker admission and stale-operation fencing.
- Pre-flight (GUIDE.md Rule 13): CodeGraph indexed the changed test flows and
  traced `current`, backfill, package import and deletion consumers; verified
  one-head/one-artifact call behavior, independent-cache freshness and failure
  paths; made no production abstraction or source-code change because S2 already
  implemented the required head lookup; focused matrix and static checks are
  listed above; DevTools: n/a — no UI change.

### Quyết định owner 2026-10-10 — scene cũ tự nhận head khi được đọc lần đầu

- **Thay đổi so với S1:** scene có revision trên kho nhưng chưa có head trong DB không còn trả lỗi "chưa được chuẩn bị" chờ người vận hành chạy `scripts.studio.scene_head --apply`. `SceneEditor.current()` gọi `_adopt_legacy_head`, chạy đúng `SceneHeadBackfill.backfill_page` của script (kiểm từng revision, kiểm lại, commit head bằng CAS) rồi trả revision. Lượt nhận head đang dở (`IN_PROGRESS`) cũng được chạy tiếp.
- **Giữ nguyên:** không bỏ bước kiểm nào. Artifact hỏng hoặc lineage sai vẫn bị chặn (`BLOCKED` + mã chẩn đoán trong bản ghi repair) và API trả 409 kèm câu cho người dùng; lần đọc sau không thử lại. Publication đang ghi dở vẫn trả 409. Script vẫn dùng được để kiểm (dry-run) hoặc chạy theo trang cho scene rất dài.
- **Giới hạn:** một lần đọc chạy tối đa 64 trang × 250 revision; scene dài hơn trả "đang chuẩn bị" và lần đọc sau chạy tiếp. Hai tiến trình cùng nhận head một job: bên thua CAS đọc lại head của bên thắng.
- **Bằng chứng:** `test_legacy_scene_without_head_is_adopted_on_first_read_with_the_same_checks_as_the_script`, `test_legacy_scene_with_invalid_artifacts_stays_blocked_with_a_user_safe_message`, hai nhóm test route trong `tests/test_api/test_scene_routes.py`; `tests/test_api` + `tests/test_orchestration` 1071 passed. Dữ liệu local: `job-6bc02e5de4ed` (1 revision) và `job-ed9cf7739a70` (2 revision) nhận head dưới 0,1 giây; thử trước trên bản sao DB rồi mới chạy thật qua API.
