# REC-01 — TorWIC Preparation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M0/M1` |

## 2. Goal

Chuẩn bị một TorWIC traversal reproducible với `raw/` immutable, normalized product input, benchmark split và calibration/timestamp metadata.

## 3. Why This Task Exists

Tạo input nền cho EX-REC bring-up mà không trộn raw, derived và evaluation-only assets.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Foundation Lock selects the bring-up traversal.
- No implementation task dependency.

## 5. Input Contract

- TorWIC source traversal và checksums.
- P0 traversal `Aisle_CW`; `Aisle_CCW` là bổ sung/backup. REC-01B sensor evidence nằm trong `DATASET_PLAYBOOK.md`; không dùng frame `000500` làm Primary Demo range mặc định.
- Dataset preparation policy trong `DATASET_PLAYBOOK.md`.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Normalized RGB/data layout.
- Benchmark split manifest và calibration/timestamp metadata.
- Preparation provenance/checksums.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `scripts/torwic/`
- `tests/test_reconstruction/`
- dataset manifests/fixtures đã được owner chấp nhận

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` dùng FFmpeg/Open3D primitives; không gọi offline scripts từ product runtime.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Dataset layout/parser unit tests.
- Raw immutability và checksum negative test.
- Small traversal preparation smoke; output manifest validates.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Selected traversal chuẩn bị được từ raw source bằng command versioned trong repo.
- [ ] `raw/` không bị mutate; normalized/derived/evaluation-only tách đúng.
- [ ] Split, calibration, timestamp và provenance có checksum.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Traversal ID/checksums.
- Preparation command/log và generated manifest.
- Representative invalid-input failure.
