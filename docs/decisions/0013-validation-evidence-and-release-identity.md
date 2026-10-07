# 0013 Trusted validation và identity bất biến khi phát hành

Date: 2026-10-07

## Status

Proposed — extension proof record/policy cần producer-consumer review. Candidate,
report và approval checksum binding đã là invariant của implementation hiện có.

## Context

Gate hiện chỉ kiểm overall_result PASS; report UNVERIFIED, không paths/evidence
vẫn có thể dẫn tới ORDINARY release. Production Isaac producer chưa được nối.
Sealing retry sau lỗi publish manifest giữ ZIP cũ nhưng tạo timestamp/manifest mới.

## Decision đề xuất

1. Review eligibility cần report hợp lệ và persisted validation run của worker
   đã được backend tin cậy, bind exact candidate/config/report checksum.
   environment_versions tự khai báo không tạo runtime proof.
2. Required checks/pairs do public validation config quyết định. Không hardcode
   mọi ordinary run có 5 paths; hidden benchmark labels chỉ thuộc evaluator.
3. Required check thiếu/FAIL/ERROR và configured path thiếu/ERROR phải block.
   BLOCKED chỉ block release khi public pair config đánh dấu required.
   Reviewer acknowledgment không được vượt blocking errors.
4. Capture media là diagnostic riêng. Thiếu video không được đổi simulator
   PASS thành FAIL; gate đòi execution/log proof hợp lệ. Nếu acceptance profile
   yêu cầu replay thì profile phải ghi rõ và gate báo thiếu evidence đó.
5. Synthetic/demo reports dùng flow kiểm thử/preview riêng; không seal ORDINARY
   release. Không thêm release run_type mới chỉ để né validation.
6. Persist một seal intent xác định manifest/timestamp/approval identity trước
   publish. Verify ZIP và manifest đã có; publish commit marker/record cuối cùng.
   Retry/concurrent callers trả cùng manifest; không overwrite bytes đã publish.

## Data contract

Giữ ValidationReport/ApprovalRecord/ReleaseManifest normative fields. Proposed
ValidationRunRecord và SealIntent là backend operational records riêng, có
version, exact checksum bindings và CAS/lease. AUD-03/AUD-04 S1 chốt storage,
migration và corruption handling; mọi ref trong record phải kiểm byte checksum.

Result của worker cũ không attach vào current revision mới. Failed/retried runs
có run_id/attempt riêng; immutable report URI phải cho phép lịch sử nhiều run
của cùng candidate và chọn report được tin cậy một cách xác định.

## Alternatives Considered

1. Tin cờ isaac_runtime_proof/version string: tự khai báo, không đủ nguồn tin cậy.
2. Chỉ yêu cầu arrays không rỗng: có thể dùng fixture giả; không đủ.
3. Tạo timestamp mới mỗi seal retry: đã chứng minh ZIP/API lệch identity.
4. Sửa ZIP cũ cho khớp manifest mới: phá immutable publication/checksum.

## Consequences

Positive: ORDINARY release có nguồn validation kiểm chứng được; recovery giữ
cùng identity. Tradeoffs: legacy report thiếu run proof sẽ chưa đủ eligibility;
queue/report history cần operational migration và selection rõ ràng.

## Follow-Up

- [AUD-03](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-03-validation-gate.md).
- [AUD-04](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-04-release-sealing.md).
- [AUD-05](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-05-isaac-validation.md).
- Crash/concurrency tests và exact-candidate Isaac → review → release proof.

## Implementation status

AUD-03.S1 added the operational config/run/selection contracts, append-only
RuntimeDatabase v9 storage, per-attempt artifact identities, and package
handoff validation. AUD-03.S2 applies one eligibility gate in review, approval,
and direct release sealing. It verifies exact current SceneIR, candidate,
selected config/run/report, worker-origin record and structured runtime
manifest; package import refuses completed worker rows until they carry an
authenticated receipt. AUD-03.S3 projects trusted proof, blockers and optional
path warnings through the API/UI. Its automated checks pass; the required
Chrome DevTools MCP screen gate remains unverified, and worker-shaped test
records are not Isaac runtime acceptance.

AUD-04.S1 added RuntimeDatabase v10 `r2s_release_seals` and persisted the exact
approval-bound manifest payload, timestamp, byte/logical checksums, archive ref
and CAS generation before publication. The ZIP-before-manifest regression now
retries with the same embedded and API manifest bytes after the clock advances.
The existing artifact-derived read path remains compatible with sealed releases
that predate the intent table. AUD-04.S2/S3 still own full artifact recovery and
concurrent seal acceptance; AUD-05 still owns worker authentication and real
Isaac acceptance. This ADR remains **Proposed** until its dependent implementation
and acceptance gates have all been reviewed.
