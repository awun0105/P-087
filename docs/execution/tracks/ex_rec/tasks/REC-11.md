# REC-11 — Reconstruction Worker Entrypoint

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
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

Integration increment 2026-09-28: REC publish `ReconstructionPreview` shared
contract trong prepared attempt và cung cấp public consumer port qua package
facade. PRODUCT gọi CLI, kiểm result qua port rồi CAS manifest pointer; preview
vẫn UNCONFIRMED/HITL pending. SIGTERM tại CLI được đổi thành interrupt để
VisualProcess cleanup Brush/Node session riêng, tránh orphan trainer khi cancel.
Tests mới chưa chạy theo yêu cầu owner; không nâng thành full video pipeline
hoặc GPU acceptance. Historical evidence phía dưới không chứng minh patch mới.

Owner clarification khi resume 2026-09-27: hoàn thiện EX-REC để nối UI/backend
cho video → frames → camera poses → 3DGS preview và canonical pipeline; chưa nối
EX-SCENE. Cloud GPU training sau integration chạy trên Vast.ai. Không chạy local
30k hoặc thuê/provision cloud trong lượt này.

Task Capsule cho preview dispatch:
- Authority: PRD FR-03/04/06; Contract §3.3.2/§3.4, Architecture isolated workers;
  REC-02A/03/04 published producer boundaries và REC-11 I/O.
- Inputs: checksum-bound published frame set/InputManifest identity, explicit
  COLMAP/Brush configs/runtime settings và immutable attempt/workspace.
- Outputs: stage progress/errors và raw 3DGS preview (arbitrary SfM units,
  metric UNCONFIRMED), không giả thành final ReconstructionBundle.
- Dependencies: REC-02/02A đã có privacy-aware frame producer; confirmation UI
  xảy ra sau visual preview. Không bỏ privacy hoặc lấy raw uploads chưa kiểm làm
  bypass. API/QA authority wiring thuộc EX-PRODUCT, không implement thay ở worker.
- Plan: audit request/config/source binding → compose REC-03→04 qua existing
  adapters từ prepared frame artifact → immutable attempt result + CLI seam
  → positive/negative fixture subprocess tests và native runtime qualification.
  Video ingestion/frame preparation dùng REC-02/02A boundary hiện hữu trước đó;
  chưa gọi partial preview worker là full video dispatcher hoặc entire track DONE.
- Owned: EX-REC worker modules/tests/task/active plan. Không sửa PRODUCT APIs/UI,
  shared stage/status registry hoặc import orchestration internals ngoài public store.

Audit 2026-09-27: trước full JobManifest wiring, sửa false-success boundary:
module main guard, request required, strict CLI/config binding, injected REC-10
validation ports thay import storage implementation vào worker. Stage success
chỉ sau publish + resolver verification; structured redacted error không lộ
private paths, output create-only. Không gọi wrapper publish-bundle là full
reconstruction pipeline; InputManifest/JobManifest dispatch còn cần integration.

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

### Prepared preview implementation — 2026-09-27

- `preview_cli.py` / `preview_worker.py`: compose REC-03→04 từ published
  `NormalizedRGBFrameSet`. CLI nhận versioned `PreparedPreviewRequest` trong
  `preview_models.py`: job/attempt, source InputManifest checksum, frame ref,
  explicit COLMAP/Brush configs. Không có dataset-specific coordinates/default
  scale hoặc hidden LiDAR input.
- Runtime settings dùng các prefix hiện hữu `REC03_COLMAP_`, `REC04_BRUSH_`,
  `REC04_SPLAT_`; command/module paths là deployment config, không serialize vào
  request/result. Không tự cài tools, provision GPU hoặc chọn training quality.
- Chạy: `.venv/bin/python -m src.services.reconstruction.preview_cli --request
  <prepared-request.json> --store-root <artifact-root> --workspace <fresh-workspace>`.
  Exit 0 = preview checkpoint ready, **job vẫn RUNNING và metric UNCONFIRMED**;
  exit 1 = failed stage; exit 2 = request/setup/publication failure.
- Artifacts tại `artifact://jobs/<job>/attempts/<attempt>/rec03|rec04|rec11/`;
  request claim create-only trước tools, immutable stage events và result. Retry
  cần attempt ID/workspace mới, không đổi job và không overwrite lần trước.
  Caller cũ không truyền attempt giữ URI legacy.
- `preview_validation.py` reload checkpoint qua resolver, kiểm request/source,
  configs, poses→visual→delivery lineage, inventory và stage refs. Không đọc temp
  COLMAP/Brush folders và không giả SOG preview thành canonical VisualArtifact.
- Chỉ chạy sau REC-02/02A + privacy/QA dispatch; worker không nhận raw video và
  không tự cấp quyền privacy. Backend queue/JobManifest reducer, metric HITL,
  final pipeline dispatcher và UI viewer vẫn phải nối riêng.
- Focused regression REC-03/04/11: **78 passed (73.28s)** với native SOG codec;
  COLMAP/Brush engines trong integration fixture được stub, không là GPU training
  hoặc real dataset acceptance. Preview suite cuối gồm consumer-tamper checks:
  **16 passed (37.93s)**; Ruff check/format EX-REC source/tests: **100 files pass**.

## 11. Definition of Done

- [x] Command không cần manual path patch.
- [x] SUCCEEDED chỉ khi required artifacts có checksum và resolve được.
- [ ] Retry/attempt không overwrite provenance trước; PRODUCT gọi qua abstraction.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

Audit 2026-09-27: CLI chạy thật nhưng scope chỉ verified_bundle_publication;
không là full InputManifest → reconstruction dispatcher. EX-PRODUCT branch có
UI/backend, chưa có real worker wiring vào abstraction này. Không claim DONE.

### Result / Evidence 2026-09-26 — Refactor REC-11 Hoàn thành (DONE)

**Audit 2026-09-27 supersedes historical DONE:** CLI module từng no-op exit 0
do thiếu main guard; request rỗng được xem success. Hai subprocess red tests
đã tái hiện và sửa. Request bắt buộc, config/CLI job/store/workspace phải khớp,
không fallback broad exception; atomic create-only result, redacted structured
failure, core worker nhận `BundleDependencies` thay storage implementation.
CLI composition root chỉ gọi public storage facade.

Current scope explicit `verified_bundle_publication` trong config/result;
không claim full reconstruction dispatch. SUCCEEDED chỉ sau REC-10 validation,
publication và byte resolver check. CLI không có qualified production verifier
cho REC-06 nên fail closed kể cả caller tự ghi CONFIRMED. Không bật fixture
verifier bằng CLI flag. Injected synthetic fixture worker success là unit/contract
proof, không real product approval. InputManifest/JobManifest dispatch/lifecycle
và retry orchestration vẫn pending; không sửa shared contract để né dependency.

Validation: REC-10/11 **31 passed**, EX-REC **338 passed/11 skipped**, current
SCENE bundle consumer + artifact store **10 passed**, Ruff **185 files pass**.
Contract/integration hai SceneIR fixture checksum failures và full suite thiếu
NumPy ở SIM vẫn hiện diện ngoài ownership (xem REC-10 audit evidence).

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

## 12. Result / Evidence

### 2026-09-30 — worker hoàn tất sau xác nhận tỉ lệ

- `src/services/reconstruction/finalize.py` + `finalize_cli.py`; PRODUCT `run_finalize_job`,
  queue tự nhận job RUNNING đã xác nhận hoặc QUEUED sau retry (chỉ chạy lại bước hoàn tất).
- Chạy thật trên `job-ac2bfd924cc6` (Aisle_CW, Quadro T2000 adapter 1): SUCCEEDED sau ~74 s
  (canonical + voxel/carve + verify + bundle).
- Các lần hỏng trước đó đều là lỗi thật đã sửa: iGPU index 0 (`VK_ERROR_DEVICE_LOST`),
  artifact theo nội dung đã có khi chạy lại, lọc cụm xoá hết Gaussian, tam giác suy biến.
- Tests: `test_finalize_flow.py` (4), `pytest tests` 1003 passed / 40 skipped.
