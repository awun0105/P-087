# REC-02 — RGB Validation And Privacy Gate

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Validate moving-camera RGB, phát hành PrivacyValidationReport và chặn input không đủ điều kiện trước heavy reconstruction.

## 3. Why This Task Exists

Hiện thực FR-01/02, AC-02 và privacy gate trước public/demo use.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-01 cho TorWIC bring-up; user upload có thể đi trực tiếp qua InputManifest.
- REC-02A tiếp nhận output đã privacy-clear để chạy `ST-FRAME-EXTRACT`; REC-02 không absorb frame extraction.

## 5. Input Contract

- InputManifest, RGB video hoặc normalized frame set.
- Source-rights attestation từ EX-PRODUCT.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Deterministic validation result/error.
- PrivacyValidationReport với PRELIMINARY_SCREENED, VERIFIED_ANONYMIZED hoặc QUARANTINED.
- Validated RGB reference cho REC-03.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`
- shared validation contract chỉ khi có producer/consumer review

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` trên FFmpeg decode/probe; không biến sampled screening thành VERIFIED_ANONYMIZED.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Decode/corrupt/usable-frame/motion feasibility unit tests.
- QUARANTINED và insufficient-motion negative tests.
- Privacy report contract test và small input smoke.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Invalid/corrupt/static input dừng trước unsupported stage với error rõ.
- [ ] Public/demo dispatch chỉ khi privacy state đủ điều kiện.
- [ ] Report bind đúng input checksum và evidence scope.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Validation/report artifact.
- Insufficient-motion và privacy failure cases.
- QA acceptance reference cho anonymized demo input.
