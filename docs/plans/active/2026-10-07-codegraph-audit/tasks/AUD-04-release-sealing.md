# AUD-04 — Sealing idempotent qua crash, retry và concurrent calls

## Metadata và goal

- PLANNED; P0; EX-PRODUCT; canonical PRODUCT-11; SELF-CODE minimal seal protocol.
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

Record status có thể pending/sealed/failed diagnostic; lifecycle API vẫn giữ
APPROVED khi chưa commit và RELEASED sau verify cả archive/manifest. Final marker
phải rõ: dùng manifest publication hiện có hoặc committed DB record theo S1;
reader không suy RELEASED từ intent/presence ZIP. Existing artifact phải verify
checksum và embedded manifest; mismatches block, không overwrite để chữa lệch.

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
**Exit:** [ ] original partial-publish regression exists; [ ] identity frozen before publish.

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
**Exit:** [ ] each boundary recovers same bytes; [ ] mismatch fails closed.

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

Pending — ghi exact manifest/archive checksums và output ở từng failure boundary.
