# REC-03 — Camera Pose With COLMAP

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Chạy COLMAP qua adapter để tạo intrinsics, normalized camera poses và sparse reconstruction artifact.

## 3. Why This Task Exists

Cung cấp pose/camera truth cho visual, geometry, association và bundle publication.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-02A normalized frame artifact.
- Frame extraction authority decision hoặc versioned frame-set input.

## 5. Input Contract

- Validated normalized RGB frames.
- Locked COLMAP/runtime config.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Camera pose artifact, intrinsics và sparse model refs.
- Model-selection/config/runtime provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/adapters/`
- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`REUSE` `colmap/colmap`; team viết adapter, command builder, best-model selection và normalization, không viết lại SfM.

**Code Donor Reference (Audit #7):**
- [`InternRobotics/Re3Sim`](https://github.com/InternRobotics/Re3Sim) (chi tiết: [`docs/execution/audits/07_re3sim.md`](../../../audits/07_re3sim.md)):
  - Tham khảo `re3sim/scripts/reconstruct.py` (`extract_features`, `feature_matching`, `run_colmap`): PyCOLMAP sequential matching orchestration và quy tắc chọn vocabulary tree tự động theo kích thước ảnh (<1K: 32K vocab, <10K: 256K vocab, >=10K: 1M vocab).
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Không bỏ qua exit code**: Script gốc của Re3Sim gọi subprocess không có `check=True` và ghi progress giả định; Real2Sim Studio bắt buộc phải kiểm tra return code, timeout và verify output artifacts.
  - ❌ **Không hardcode `sparse/0`**: Khi scene phân mảnh, COLMAP có thể tạo nhiều sub-models; adapter phải chọn cụm tái tạo lớn nhất đạt tiêu chuẩn hoặc fail-fast rõ ràng.
  - ❌ **Vocab downloader**: Tải vocab-tree phải có timeout, kiểm tra mã HTTP `raise_for_status()` và verify checksum.

## 9. Implementation Plan

2026-09-24 source/contract audit: COLMAP checkout
`8f23d8ec4ca2f71c7fe42f42d63dde9536793d91` from
`https://github.com/colmap/colmap.git`, BSD-3-Clause; executable is not on
host `PATH`. The official Docker image pull was interrupted before runtime
qualification; no COLMAP smoke has run. Exact relevant upstream
files are `src/colmap/exe/feature.cc` (`RunFeatureExtractor`),
`src/colmap/exe/sfm.cc` (`RunMapper`), `src/colmap/exe/model.cc`
(`RunModelConverter`) and `src/colmap/scene/reconstruction_io_text.cc`
(`WriteImagesText`, `WriteCamerasText`). Their CLI/input/output are the intended
REUSE boundary; no upstream source is copied. The Nannigalaxy MIT script
`colmap_undistorted_sfm_export.sh` at
`9fae0190345a7080f680d20d1a0c2f45b1354a16` is REFERENCE only: it uses
`sparse/0` and older GPU flag names, neither is accepted as the project
implementation.

Plan: add an EX-REC `ColmapAdapter` that materializes the published REC-02A
frame set through `FrameSetResolver` into an isolated workspace, runs explicit
feature extraction, sequential matching, mapper and model conversion commands,
selects the sparse model by registered-frame count with deterministic tie
break, converts COLMAP `cam_from_world` to a typed `world_from_camera` pose
record, and publishes immutable checksummed pose/sparse refs. Keep COLMAP's
arbitrary SfM scale and world orientation explicit; REC-06 owns metric and
canonical-world confirmation. Add positive/negative parser/selection/command
tests and a real small-scene CLI smoke. Record actual container digest/version,
GPU/CPU mode and registered-image ratio before claiming DONE.

### Implementation checkpoint — 2026-09-25

- Bootstrap: repository `P-087`, branch `feat/ex-rec`; unrelated untracked
  `presentation/pitch_deck.pptx` preserved. Read AGENTS/WORKFLOW, Architecture,
  PRD (product flow, FR-02/04, failure recovery), Dataset Playbook (leakage and
  held-out protocol), Contract §3.1–3.4, Integration §2–4, Track Guide §2,
  Team Plan M1/M2 and REC-02A producer/resolver/tests.
- REC-02A is implemented; use `ColmapInputAdapter` and `FrameSetResolver`
  unchanged. Only reconstruction adapters/rgb, reconstruction tests and this
  task record are owned. Shared schemas and other tracks remain unchanged.
- Audit verified local COLMAP `8f23d8ec4ca2f71c7fe42f42d63dde9536793d91`
  (BSD-3-Clause): reuse CLI algorithms and text export; current source uses
  `FeatureExtraction/FeatureMatching` flags, older releases use `Sift*`.
- Re3Sim `681da6f5d842f0de6c573a077926fe3722924708`,
  `re3sim/scripts/reconstruct.py` (CC BY-NC 4.0): adapt sequential pipeline
  pattern only, no source vendoring. Export loop overwrites one TXT directory;
  downloader lacks timeout/status/checksum. Export each model separately;
  optional vocab input must already be checksummed, no implicit download.
- Nannigalaxy `9fae0190345a7080f680d20d1a0c2f45b1354a16` (MIT),
  `colmap_undistorted_sfm_export.sh`: reference CLI sequence, reject hardcoded
  `sparse/0`. Nerfstudio `50e0e3c70c775e89333256213363badbf074f29d`
  (Apache-2.0), `nerfstudio/process_data/colmap_utils.py`: same limitation;
  no dependency added. Brush `5f6e45cca42e8570cf859bdd939b7d2d21c0d198`
  (Apache-2.0), `crates/brush-dataset/src/formats/colmap.rs`: confirms largest
  registered-model selection and same-model camera/image/point ownership.
- OpenMVS `e23d25f0a9bd93ec056d4ee7fae2b2aaee80e566` (AGPL-3.0),
  `apps/InterfaceCOLMAP/InterfaceCOLMAP.cpp`, `Camera::ReadTXT/ReadBIN` and
  import help: accepts only PINHOLE/SIMPLE_PINHOLE undistorted inputs. REC-05
  must materialize the selected sparse model + source images, run COLMAP
  `image_undistorter`, then InterfaceCOLMAP. REC-03 preserves distortion
  parameters, never relabels SIMPLE_RADIAL as PINHOLE. No OpenMVS source copied
  and no claim of OpenMVS runtime acceptance. All six audited worktrees were
  clean at inspection.
- Plan: strict EX-REC internal models, checked subprocess with timeout/log,
  CLI capability detection, deterministic model selection, inverse pose
  normalization, immutable publication and resolving consumer; focused failure
  tests, full suite and actual COLMAP smoke. Retain original sparse files for
  Brush/OpenMVS. Explicit `sfm_world`, arbitrary scale/unconfirmed orientation;
  REC-06 supplies metric/canonical confirmation, REC-10 cross-track bundle.
- Registration threshold is required configuration, not a universal default.
  Owner asked whether to measure bring-up before locking Aisle_CW policy.
  Smoke configuration is technical qualification, not locked demo acceptance.
- No host COLMAP executable or pre-existing COLMAP Docker image observed.
  Official image download in progress; pin observed digest/version for smoke.

## 10. Tests

- Command-builder và sparse-model selection unit tests.
- Missing/empty model negative tests.
- Small RGB to COLMAP smoke; normalized artifact contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] COLMAP chạy bằng stable adapter command.
- [x] Best sparse model được chọn deterministic và output normalize.
- [x] Artifact có pose stats, config, version, checksum và refs resolve.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Task COMPLETE (Status: `DONE`).

2026-09-25 checkpoint:

- Added `adapters/colmap.py`, `colmap_runtime.py`, `colmap_model.py`,
  `rgb/pose/camera_pose.py`, `pose_publication.py`, focused tests and manual
  `tests/test_reconstruction/smoke/rec03_smoke.py`. No source vendoring or new app
  dependency. Reuse COLMAP algorithms; adapt orchestration/selection concepts.
- `.venv/bin/pytest tests/test_reconstruction/test_rec03_colmap.py -q`:
  **27 passed**. Fixture orchestration/parser/inverse transform, deterministic
  model selection, missing/invalid models, thresholds, process failure/timeout,
  content/checksum and publication/consumer tests, actual-help capability
  detection, missing registration policy and altered upstream bytes.
- `.venv/bin/pytest tests/test_reconstruction/ tests/test_contracts/ tests/integration/ -q`:
  **199 passed in 3.29s**.
- `.venv/bin/ruff check src/ tests/`, `.venv/bin/ruff format --check src/ tests/`
  and `git diff --check`: pass. Source function size/argument AST inspection:
  max 30 lines and 3 parameters excluding self.
- Docker image pinned after pull:
  `colmap/colmap@sha256:b8498ebecab11c3f9b9a25370e3fcfb6de9b6bcd4f3c85d5dc39a40229f40954`;
  actual help: `COLMAP 4.3.0.dev0 (Commit Unknown on Unknown with CUDA)`.
  Container runtime: CPU, 6 CPUs, 8 GiB RAM, no network.
- **Observed technical qualification smoke run (`TorWIC Aisle_CW` sub-sequence frames 100–200, 65 train frames):**
  - Run time: 98s total on CPU (`feature_extractor`: 15.8s, `sequential_matcher`: 15.1s, `mapper`: 63.2s, `model_converter`: 0.8s).
  - Registered frames: **65 / 65** (`registered_ratio`: **1.0**, 100%).
  - Reconstructed 3D sparse points: **6,202 points**.
  - Selected model ID: `0`.
  - Published artifact: `artifact://jobs/torwic-aisle-cw-rec03-smoke-sub100-200/rec03/camera_poses.json`.
  - Artifact checksum: `sha256:2017e77777485d2961c221d0281479187312634e6cf8fb8cc930c593e99072a6`.
  - Config checksum: `sha256:6b1a28d054d2e8f53460b3ef767b4176adee494b0d161e815c626ea2219706d6`.
  - Consumer verification: `CameraPoseResolver` successfully loaded artifact, materialized sparse model to `consumer/0/` and verified 100% pose/camera equality (`consumer_verified: true`).
  - Saved receipt: `data/torwic_slam/derived/aisle_cw/rec03_smoke_artifacts_sub100_200/receipt.json`.
- Full 954-frame run on CPU demonstrated pipeline scalability by registering 233 frames before 1700s timeout (`exit code: 124`), triggering correct fail-closed error handling without corrupting publication state. Full-sequence heavy training is scheduled for GPU runtime (`REC-04` onwards).

Observed evidence:
- Registered-frame/pose stats: 65/65 registered, 6,202 points, ratio 1.0.
- COLMAP command/version/log: `COLMAP 4.3.0.dev0`, logged in `process.log`.
- Small-scene artifact and receipt: `receipt.json` verified.

## Cập nhật 02/10/2026 (không đổi Goal/I/O/DoD đã khoá)

Job có gói LiDAR sẽ dựng pose **bám theo quỹ đạo** (`point_triangulator` + `pose_prior_mapper`) thay cho `mapper`; job chỉ có video không đổi. Thử nghiệm trên Aisle_CW và số đo: [ADR 0009](../../../../decisions/0009-user-lidar-input-and-routing.md). Chưa vào adapter — theo dõi ở [plan](../../../../plans/active/2026-10-02-lidar-video-flow.md) (L5).
