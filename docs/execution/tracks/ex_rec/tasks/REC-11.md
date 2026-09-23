# REC-11 — Reconstruction Worker Entrypoint

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M2` |

## 2. Goal

Cung cấp stable CLI/worker entrypoint cho EX-REC với logging, exit status và artifact publication.

## 3. Why This Task Exists

EX-PRODUCT phải dispatch reconstruction mà không sửa path hoặc gọi implementation nội bộ.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-10 publication path.
- JobManifest/stage artifact lifecycle contract.
- Locked runtime boundaries before worker-specific container changes.

## 5. Input Contract

- InputManifest/JobManifest và versioned config.
- Artifact resolver/root.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Stable worker command/interface.
- Stage status, errors, logs và published REC artifacts.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/`
- `tests/test_reconstruction/`
- container/worker files chỉ khi runtime authority đã khóa

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` wrapper quanh adapters/stages; heavy tools chạy qua process/container boundaries.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- CLI argument/config/error unit tests.
- Failed stage does not publish success negative test.
- Small fixture worker smoke và PRODUCT dispatch contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Command không cần manual path patch.
- [ ] SUCCEEDED chỉ khi required artifacts có checksum và resolve được.
- [ ] Retry/attempt không overwrite provenance trước; PRODUCT gọi qua abstraction.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Example command/status/log.
- Success and controlled failure runs.
- Published JobManifest stage records.

