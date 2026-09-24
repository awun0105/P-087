# SIM-06 — Isaac Validation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M1/M2/M4` |

## 2. Goal

Load exact candidate in Isaac and record observed load, metric, spawn, collision, penetration and path results.

## 3. Why This Task Exists

AC-08 requires runtime evidence before human review.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-01 locked runtime smoke.
- SIM-05 exact CandidatePackage.
- Locked robot footprint and Start–Goal configuration.

## 5. Input Contract

- Immutable CandidatePackage/checksum.
- Product-visible path config; locked expected labels remain evaluator-only for acceptance.
- `REQUIRED_ROUTE_BLOCKED` chỉ áp dụng khi ordinary product config công khai đánh dấu route đó là required; rule này không thuộc static preflight và không được suy ra từ hidden expected label.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Observed check/path evidence bound to candidate checksum.
- Per-pair CLEAR/BLOCKED/ERROR with reason/evidence.
- Replay MP4, screenshots và logs của đúng candidate/run được publish thành
  artifact refs/checksums khi capture thành công; capture error được báo riêng.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/isaac/`
- `src/services/simulation/validation/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` worker on Isaac/IsaacLab APIs; do not read hidden expected labels inside generic validator.
Native Omniverse MP4 capture là đường chính. Frame capture → FFmpeg chỉ là
fallback khi native không chạy trong locked Isaac runtime; ghi rõ lý do đổi
đường capture và version của extension/encoder liên quan.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Path result/error mapping unit tests.
- Candidate checksum mismatch and ERROR-as-pass negative tests.
- Real smoke with one CLEAR/one BLOCKED; acceptance observes 5/5 pairs.
- Real candidate capture/publish/readability check; lỗi capture/publish không
  được đổi observed validation PASS/FAIL hoặc CLEAR/BLOCKED/ERROR.
- Native failure → fallback test nếu cần; missing/corrupt media và checksum
  mismatch phải được báo riêng, không được giả làm valid evidence.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Exact candidate loads and all required runtime checks execute.
- [ ] Every configured pair has observed CLEAR/BLOCKED/ERROR; ERROR is never pass.
- [ ] Required-route blocking chỉ được đánh giá từ product-visible required-route config.
- [ ] Worker output contains no hidden evaluation comparison.
- [ ] Ít nhất một real candidate validation run có replay MP4, screenshots và
  logs đã publish với ref/checksum/provenance đúng candidate/run; ordinary run
  thiếu replay báo warning/error riêng, không sửa kết quả simulator validation.
  Primary Demo E2E acceptance được kiểm tra riêng tại PRODUCT-12.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Isaac logs/screenshots/video.
- Native capture command/config/version, MP4 readability và published refs;
  fallback proof chỉ khi native thất bại.
- Per-check/per-pair observed evidence.
- Load/spawn/path failure samples.
