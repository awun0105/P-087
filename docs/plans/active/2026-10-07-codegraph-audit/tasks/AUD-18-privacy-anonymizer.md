# AUD-18 — Opt-in face/plate anonymizer trước reconstruction

## Metadata và goal

- PLANNED; P2 extension theo yêu cầu owner; EX-REC + EX-PRODUCT.
- Canonical REC-02, PRODUCT-01/02/09; bổ sung task-local scope, không đổi crosswalk.
- ADAPT qualified detection/tracking/redaction; REUSE RGBPrivacyGate,
  PrivacyInspectionEvidence, PrivacyQAAcceptance và approved-copy lineage.
- Goal: hỗ trợ chuẩn bị input ẩn danh, manual correction/QA và dispatch đúng
  approved derived copy. Kỹ thuật khả thi; không bỏ task vì old MVP excluded.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0019](../../../../decisions/0019-anonymized-input-preparation.md).

## Baseline và scope

Current Studio self_attested + PRELIMINARY_SCREENED có thể dispatch khi đủ flags
và không findings. Đây không phải auto detector hoặc qa_verified. Strict
RGBPrivacyGate đã có evidence/acceptance verification; reuse thay competing gate.

CodeGraph: RGBPrivacyGate/SelfAttestedPrivacyGate, PrivacyInspectionEvidence,
PrivacyQAAcceptance, project_block_reason, frame extraction/preflight publication,
input manifests/privacy review routes và product upload/dispatch consumers.
Owned: worker-only sanitized-copy preparation, privacy evidence/QA integration,
PRODUCT operation/API/reviewer UI và focused tests. Không đổi self_attested policy
ngầm, cấp review permission mới, xóa original hoặc redact sau training rồi coi
raw-derived 3DGS/thumbnails an toàn. Không guarantee mọi face/plate đều được detect.

## Input / output / data contract

Input: source-rights attestation, restricted original ref, explicit anonymize
profile và reviewer corrections. Output proposed SanitizationManifest, sanitized
derived input/frame refs, inspection evidence và verified acceptance when approved.

Manifest: schema/version, source input/checksum, detector/tracker/runtime/model
version+weights checksum, config checksum, frame inventory/PTS mapping, processed
coverage, per-frame region/redaction action refs, failures/uncertainty và sanitized
byte checksum. Detection/crop evidence giữ restricted boundary; public logs không
ghi PII images hoặc original download URLs. Unprocessed frames không marked covered.
S1 chốt schema/placement dựa existing contracts; no competing privacy status enum.

Preserve resolution/crop/timing/intrinsics binding theo declared codec contract;
redaction không đổi frame geometry. QA inspect chính decoded sanitized copy/frame
inventory mà downstream dùng, không chỉ detector rectangles trên source. Reuse
existing input-manifest/inspection/approved_copy_checksum acceptance verification,
bind original→derived lineage explicit. Any correction/re-encode đổi bytes phải
invalidate old QA/acceptance. Zero detections không tự VERIFIED_ANONYMIZED.
Opt-in sanitized flow consumes approved copy trước training, thumbnails/public
assets; raw input vẫn trong original access boundary, giữ rights attestation.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Sanitized source identity trước reconstruction.
Cần sửa đồng bộ: privacy contracts/gate, detector/tracker/redaction producer, prepared InputManifest/frame set, cache/preview/train consumers, storage access và review diagnostics.
Acceptance xuyên consumer: Train/cache không reuse raw source khi chọn anonymized; timeline/redaction coverage và approval refs match actual sanitized bytes.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập để qualify model/contracts; S2 dùng AUD-07 durable admission pattern.
S3 uses existing privacy QA roles/gate. Source sanitization identity phải nằm
cache/preparation keys của AUD-15/16, không reuse raw-input trained outputs.

## Sprint AUD-18.S1 — Model envelope và sanitization/QA contracts

**Input:** current privacy contracts/gates + consented face/plate fixtures and model candidates.
**Output:** qualified model profile, SanitizationManifest và source/derived/QA state matrix.
**Contract:** original preserved/restricted; full requested coverage recorded;
automation chưa grant acceptance; existing self_attested behavior unchanged.

Implement: choose detector/tracker theo measured small/occluded/angle/lighting cases,
qualify code/model weights/data license and runtime footprint trước integration.
Define supported coverage, uncertainty/manual correction and failure handling;
reuse evidence/acceptance refs and existing reviewer authorization. Do not assume
YOLOv8-Face/plate variants share một license hoặc confidence là privacy guarantee.
Tests: old reports/checksums, wrong input/copy/acceptance refs, incomplete coverage,
zero detections, model/config invalidation, unauthorized approval và restricted refs.
**Exit:** [ ] model/license/quality envelope recorded; [ ] QA/identity contract agreed.

## Sprint AUD-18.S2 — Detection/tracking/redaction worker

**Input:** admitted source refs/profile + full requested frame inventory.
**Output:** verified sanitized copy/frames + coverage/redaction manifest/diagnostics.
**Contract:** all-frame preparation trước raw-derived public output; no silent skipped
frames; actual decoded copy matches manifest; cancellation/lease protects publication.

Implement: detector + temporal association, conservative redaction over supported
tracks, blur/mosaic with qualified effectiveness; preserve geometry/PTS mapping.
Review uncertainty/missed regions qua restricted artifacts; reject corrupt/incomplete
output. Store original/derived separately, use immutable refs and bounded worker
resource lifecycle. Failed preprocessing không fallback sang training raw source
trong anonymize mode; manual sanitized-input workflow vẫn available separately.
Tests: intermittent detections/tracks, small/occluded face/plate, variable frame rate,
empty frames/codec failure, coverage gaps, artifact corruption, restart/cancel/lease.
**Exit:** [ ] sanitized output/coverage verified; [ ] no raw public-output path leakage.

## Sprint AUD-18.S3 — Manual correction, QA và dispatch integration

**Input:** decoded sanitized output/evidence + authorized reviewer decisions.
**Output:** review/correction UI, exact-copy acceptance và downstream dispatch binding.
**Contract:** manual edits create new immutable copy/evidence; stale approval rejected;
only chosen approved derived copy drives frame/pose/train/publication in opt-in mode.

Implement: preview restricted source/sanitized evidence under existing roles, add
manual regions and rerender before re-review. Persist verified acceptance through
current QA path; expose pending/failed/cancelled actions and full coverage evidence.
Prevent caches/downstream refs from raw source; evaluate reconstruction quality
impact of redacted texture separately from privacy detection/redaction quality.
Tests: known missed detections/manual fixes, wrong/stale approved_copy_checksum,
QA permission, mode-specific dispatch, browser review→correct→approve→train flow,
consented real dataset privacy/coverage and reconstruction quality acceptance.
**Exit:** [ ] reviewer/dispatch lineage verified; [ ] real detection/coverage limits recorded.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_reconstruction/test_rec02_quality.py tests/test_reconstruction/test_rec02_evidence.py tests/test_reconstruction/test_rec02_self_attested_privacy.py tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_orchestration/test_privacy_gate.py -q
```

Planned tests/test_reconstruction/test_privacy_sanitization.py và API/UI review
tests. DONE cần real supported detector/redaction evaluation + reviewer/browser
and consumer proof; synthetic zero findings không chứng minh anonymity.

## Result / Evidence

Pending — licensed qualified models, source/derived/evidence/checksums, frame/PTS
coverage, misses/manual QA, dispatch lineage, resource lifecycle và quality limits.
