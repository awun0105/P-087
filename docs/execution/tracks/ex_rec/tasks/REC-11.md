# REC-11 — Reconstruction Worker Entrypoint

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
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

1. Thiết kế `WorkerConfig` và `WorkerExecutionResult` chuẩn Pydantic ContractModel.
2. Triển khai `ReconstructionWorker`: nhận `WorkerConfig`, `ArtifactWriter`, `ArtifactResolver`.
3. Điều phối stage `METRIC_CANONICALIZE` gọi `ReconstructionBundleService.build_and_publish`.
4. Ghi nhận `StageArtifact` với status `SUCCEEDED` hoặc `FAILED`, ghi nhận `ExecutionError` có cấu trúc khi có ngoại lệ.
5. Triển khai CLI argument parser và `main()` entrypoint trả về exit code cho orchestrator.
6. Viết bộ unit/contract tests trong `tests/test_reconstruction/test_rec11_worker.py`.

## 10. Tests

- CLI argument/config/error unit tests.
- Failed stage does not publish success negative test.
- Small fixture worker smoke và PRODUCT dispatch contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Command không cần manual path patch.
- [x] SUCCEEDED chỉ khi required artifacts có checksum và resolve được.
- [x] Retry/attempt không overwrite provenance trước; PRODUCT gọi qua abstraction.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

### Result / Evidence 2026-09-26 — Refactor REC-11 Hoàn thành (DONE)

- Module: `src/services/reconstruction/worker.py`
  - `WorkerConfig`, `WorkerExecutionResult`, `ReconstructionWorker`, `create_cli_parser`, `main`.
  - Hỗ trợ tham số `--request` nạp file cấu hình JSON (`WorkerConfig` hoặc `BundleBuildRequest`) và `--output` ghi `WorkerExecutionResult` có cấu trúc.
  - Tích hợp trực tiếp với `FilesystemArtifactStore` và `ArtifactResolver` thật, trả về exit code 0 khi `SUCCEEDED` và 1 khi `FAILED`.
- Tests: `tests/test_reconstruction/test_rec11_worker.py` (4/4 passed).
  - `test_worker_run_success`: xác nhận worker hoàn thành stage `METRIC_CANONICALIZE`, xuất bản `StageArtifact` hợp lệ với bundle checksum.
  - `test_worker_run_failure_captures_error`: xác nhận worker bắt lỗi, chuyển job status thành `FAILED`, ghi nhận `ExecutionError` và không xuất bản bundle ref.
  - `test_worker_cli_parser_and_main`: kiểm tra parser command line và returncode 0 khi khởi tạo.
  - `test_worker_cli_full_execution`: kiểm tra thực thi trọn vẹn CLI với `--request` và `--output` sinh `WorkerExecutionResult` hợp lệ trên `FilesystemArtifactStore` thật.
- Tuân thủ AST and Ruff:
  - Max function length: 22 lines (ngưỡng <= 30).
  - Max args: 3 parameters.
  - Type annotations đầy đủ.
  - Ruff check & format: pass 100%.


