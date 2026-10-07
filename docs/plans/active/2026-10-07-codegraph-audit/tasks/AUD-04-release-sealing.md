# AUD-04 — Sealing idempotent qua crash, retry và concurrent calls

## Metadata và goal

- ACTIVE; P0; EX-PRODUCT; canonical PRODUCT-11; SELF-CODE minimal seal protocol.
- Goal: manifest ZIP/API giữ cùng bytes/logical identity và checksum qua retry.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0013](../../../../decisions/0013-validation-evidence-and-release-identity.md).

## Baseline và scope

CodeGraph: `seal_release`, `_release_archive`, `_publish_once`, `decide`,
`review_state`, ArtifactStore.publish callers. Timestamp mới mỗi retry; ZIP cũ
được giữ khi manifest publish fail. Fault injection tái hiện APPROVED → retry
RELEASED, embedded/API manifest khác nhau.

Owned: src/services/orchestration/review/workflow.py, minimal seal record/migration
trong orchestration runtime DB, tests/test_orchestration/test_review_workflow.py,
tests/test_api/test_review_routes.py, tests/test_contracts/test_release.py.
Không rebuild candidate, overwrite published bytes, sửa approval timestamp,
hoặc xóa archive thất bại. Auth/release run_type policy giữ boundary AUD-03.

## Input / output / data contract

Input: exact approved candidate/package/report/approval + eligibility AUD-03.
Output: verified ReleaseArchive + ReleaseManifest + committed release state.

Proposed SealIntent operational record keyed theo job/candidate/approval identity:
version, seal_id, candidate/report/approval checksums, release_timestamp,
exact manifest UTF-8 payload, manifest logical checksum, manifest byte checksum,
archive_ref nếu đã publish, status và CAS generation. Persist exact serialized
payload để timezone/format không tạo bytes khác trên retry. Không serialize
credentials/local paths. Timestamp chỉ cấp một lần tại intent creation.

Intent status là PENDING/SEALED; bảng diagnostic riêng chỉ lưu failure code an
toàn, attempt count và timestamp, không lưu provider exception hoặc secret.
Lifecycle API vẫn giữ APPROVED khi chưa commit và RELEASED sau verify cả
archive/manifest. SEALED là commit marker cho intent mới; release cũ không có
intent vẫn đọc được nếu toàn bộ ZIP closure hợp lệ. Reader không suy RELEASED
từ intent/presence ZIP. Existing artifact phải verify checksum và embedded
manifest; mismatches block, không overwrite để chữa lệch.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Sealing identity qua retry/crash.
Cần sửa đồng bộ: DB seal intent, archive/manifest writer, review workflow commit, API download/status và recovery.
Acceptance xuyên consumer: Fault injection publish ZIP/manifest + concurrent seal trả cùng release identity, không đánh lại timestamp khi retry.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 có thể dùng current eligibility để viết identity regression; final S3 tích
hợp shared gate AUD-03. Atomic artifact publication primitive phải được inspect
trước khi chọn protocol, không giả DB+object store chung transaction.

## Sprint AUD-04.S1 — Seal intent và deterministic identity

**Input:** approved fixture, stable exact artifact refs và fault injection.
**Output:** failing ZIP-before-manifest regression; persisted intent contract,
timestamp allocation và migration fixture.
**Contract:** same candidate/report/approval → same seal intent/manifest bytes;
different approval/report không reuse nhầm intent; canonical vs byte checksum rõ.

Implement: create/get intent bằng DB transaction/CAS; serialize manifest một lần;
test clock đổi giữa calls. Chọn deterministic ZIP member order/metadata hoặc
persist exact archive ref/bytes sau build; không generate archive identity tùy retry.
Tests: repeated call, different clock, same/different approval, payload corruption,
backward-compatible read of existing sealed releases.
**Exit:** [x] original partial-publish regression exists; [x] identity frozen before publish.

## Sprint AUD-04.S2 — Resume publication và committed release

**Input:** intent S1 với không/partial/all artifacts đã publish.
**Output:** exact artifact closure và one committed release identity.
**Contract:** verify-before-reuse; no overwrite; failed publish keeps APPROVED;
returned API manifest matches ZIP bytes and content checksum.

Implement: load frozen payload, publish/verify ZIP, publish/verify manifest,
commit marker cuối. Nếu manifest exists nhưng ZIP thiếu/corrupt thì báo recoverable
diagnostic theo invariant, không claim RELEASED. Ghi lỗi thay vì silent swallowing;
automatic sealing vẫn cho explicit retry khi approval đã persist.
Tests: failure trước ZIP, sau ZIP, sau manifest/trước record; remote store transient
error; rerun after crash; wrong existing bytes; resolver closure/ZIP extraction.
**Exit:** [x] failure before ZIP, after ZIP, after manifest/before commit marker,
missing ZIP và pre-intent partial ZIP recover mà không đổi manifest identity;
[x] checksum/closure mismatch giữ APPROVED, không tải xuống và không overwrite.

## Sprint AUD-04.S3 — Concurrent seals và API consumer

**Input:** hai registry/processes cùng DB/artifact store, exact approval.
**Output:** one seal intent và same release returned to all callers.
**Contract:** CAS winner freeze timestamp; loser reuse verified intent; revoked/
stale current eligibility không được seal; history untouched.

Implement: controlled barriers để tái hiện concurrency; test review_state only
exposes committed valid release; integrate AUD-03 gate and error projection.
Tests: two independent SQLite connections; PostgreSQL locking nếu có fixture
runtime thật; concurrent publish; stale candidate; download ZIP vs API equality.
**Exit:** [ ] idempotency/concurrency suite pass; [ ] PG proof ghi riêng nếu chưa chạy.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_review_workflow.py tests/test_api/test_review_routes.py tests/test_orchestration/test_artifact_store.py tests/test_contracts/test_release.py -q
```

Planned tests/test_orchestration/test_release_sealing_recovery.py sau khi tạo.
DONE khi fault matrix/concurrency/ZIP equality pass; old releases giữ checksum.

## Result / Evidence

### AUD-04.S1 — seal intent và deterministic identity

- Base commit: `e77eebb` (`AUD-03.S3`). CodeGraph traced `seal_release` through
  `decide` and `POST /release-seal`, `review_state` release projection,
  `FilesystemArtifactStore.publish`, and RuntimeDatabase migrations. The seal
  path has eight callers after adding the recovery regression. No API or public
  contract fields changed.
- Red reproduction before the fix: inject an `OSError` after `release.zip`
  publication and before `ReleaseManifest`; advance the clock by one hour;
  retry produced different embedded and API manifests. The new test failed at
  the byte-equality assertion on the old implementation.
- Added internal `ReleaseSealIntent` and `ReleaseSealRepository`, keyed by
  `(job_id, candidate_checksum, validation_report_checksum,
  approval_record_checksum)`. It stores a stable seal ID, timestamp, exact UTF-8
  manifest payload, logical and byte checksums, archive ref, status, generation
  and payload checksum. `get_or_create` persists the intent transactionally
  before artifact publication; updates to archive ref and SEALED status use
  checksum-guarded CAS. Same identity reuses one intent; different report or
  approval identity gets a distinct row; malformed/tampered payload fails closed.
- `seal_release` now publishes from the frozen manifest bytes. It persists the
  expected archive reference before publishing ZIP bytes, resumes if publication
  did not complete, checks an existing archive against the recorded checksum,
  verifies the embedded manifest matches the frozen payload, then publishes the
  API manifest and marks the intent SEALED. Older RELEASED records remain
  readable without a seal-intent row. Full archive closure, mixed-version
  recovery and committed-state verification remain S2.
- Schema delta: additive RuntimeDatabase migration v10 creates
  `r2s_release_seals`; v8→latest and v9→v10 SQLite fixtures preserve existing
  project/job rows. Existing migration v1 records remain covered. No artifact is
  overwritten and no prior checksum is rewritten.
- Files changed: `src/services/orchestration/review/release_seals.py`,
  `src/services/orchestration/review/workflow.py`,
  `src/services/orchestration/jobs/database.py`,
  `tests/test_orchestration/test_release_sealing_recovery.py`,
  `tests/test_orchestration/test_runtime_migrations.py`,
  `docs/decisions/0013-validation-evidence-and-release-identity.md`, plus this
  task record and the execution-plan README.
- CodeGraph after implementation: 749 files, 13,385 nodes, 37,945 edges; index
  up to date. `seal_release` callers include the API, decision path, legacy
  workflow tests and new partial-publication recovery test.
- Verification: **44 passed, 4 skipped** across release sealing, review workflow,
  review API, runtime migrations, artifact store and release contracts. All four
  skips require unavailable `R2S_TEST_POSTGRES_URL`; SQLite migration and crash
  recovery paths ran. `ruff check src/ tests/` passed; `ruff format --check src/
  tests/` reported 465 files already formatted; `git diff --check` passed.
- Limits: no live PostgreSQL/cloud artifact store was available. This sprint does
  not yet prove concurrent seal calls or recover every missing/corrupt archive
  boundary; those are S2/S3. No production release data or runtime DB was changed.
- Next: AUD-04.S2 verifies every reused artifact and closes recovery behavior at
  pre-ZIP, post-ZIP, post-manifest and pre-commit failure boundaries.

### AUD-04.S2 — publication recovery và committed release

- Base commit: `6c1335e` (`AUD-04.S1`). CodeGraph re-traced `decide` →
  `seal_release` → `review_state`, the release download route and `ReviewPanel`.
  `review_state` has one API status consumer and feeds the download route; the
  UI contract now carries an explicit safe seal diagnostic and exposes retry to
  Reviewer while status is APPROVED.
- `review_state` now requires a valid, current ReleaseManifest, a committed
  SEALED intent for new releases, exact API/ZIP manifest bytes, intact ZIP CRCs,
  exactly the package members plus the three release records, unchanged package
  member bytes, and validation/approval records matching the selected trusted
  evidence. Pre-intent legacy releases remain readable only after the same ZIP
  closure check. A missing/corrupt/mismatched artifact remains APPROVED, has no
  downloadable release reference, and projects a generic retry diagnostic.
- `seal_release` verifies before reuse and publishes immutable release objects
  idempotently. It adopts byte-identical manifest payloads from valid pre-intent
  partial ZIPs, restores a missing ZIP only when its rebuilt checksum matches
  the frozen ref, publishes/validates the API manifest, then writes SEALED last.
  Existing wrong bytes are retained and fail closed. A migration v11 table stores
  only a fixed safe failure code, attempt count and timestamp; success clears the
  diagnostic. No raw provider error or credential is persisted or returned.
- Updated `ReviewStateView`/`ReviewPanel` together with the backend API projection:
  the retry action remains available to Reviewer for APPROVED releases even if
  release integrity diagnostics are present. The API download route inherits
  the stricter projection and returns 404 for an invalid archive.
- Tests cover failure before ZIP, after ZIP, after manifest but before SEALED,
  recovery of a missing archive, exact adoption of a pre-intent partial archive,
  immutable wrong bytes, API download fail-closed behavior, and v10→v11 migration
  without losing the v10 intent row.
- CodeGraph after implementation: 749 files, 13,412 nodes, 38,084 edges; index
  up to date. `codegraph explore` confirms the read/download flow uses the strict
  `review_state` projection and UI retry reaches `POST /release-seal`.
- Verification: **53 passed, 4 skipped** across release sealing, review workflow,
  review API, artifact store, release contracts and runtime migrations. Four skips
  require unavailable `R2S_TEST_POSTGRES_URL`; SQLite v10→v11 migration and
  recovery cases ran. `.venv/bin/ruff check src/ tests/` passed;
  `.venv/bin/ruff format --check src/ tests/` reported 465 files formatted.
  Frontend: `npm run test` **42 files / 275 tests passed**, `npm run lint`,
  `npm run typecheck` and `npm run build` passed. `git diff --check` passed.
- Browser DevTools MCP was not exercised for this sprint; the earlier
  AUD-03.S3 browser gate remains **UNVERIFIED**. No live PostgreSQL or remote
  object store was available, and no production release/runtime data was changed.
- Next: AUD-04.S3 covers concurrent seals/CAS losers and API equality under
  multiple registry/process consumers.
