# SIM-01 — Minimal Isaac Smoke

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M0/M1` |

## 2. Goal

Build/load minimal floor+wall+box+robot USD in locked Isaac environment and record a reproducible smoke result.

## 3. Why This Task Exists

Isaac runtime incompatibility is a project-level blocker that must surface before real scene integration.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Foundation Lock chốt Isaac Sim/CUDA/driver/GPU.
- Robot asset/reference và run command có owner.

## 5. Input Contract

- Minimal deterministic scene specification.
- Locked runtime/environment versions.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Minimal USD/smoke package.
- Load result, environment manifest, logs/screenshots and failure diagnostics.
- Native MP4 capture feasibility result for a short run: readable output or exact
  extension/encoder/headless failure. Đây là probe, không phải replay pipeline.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/usd/`
- `src/services/simulation/isaac/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`REUSE` OpenUSD/Isaac APIs plus project-owned smoke wrapper; do not build a physics engine.
Ưu tiên native `omni.kit.capture.viewport` + `omni.videoencoding` trong runtime
đã khóa; chỉ thử frame capture → FFmpeg nếu native MP4 không hoạt động.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Minimal USD structure unit test where possible.
- Missing asset/incompatible runtime negative test.
- Real locked-environment Isaac load smoke.
- Short native MP4 capture/readability smoke; record capture/videoencoding
  extension versions and headless setting. Fallback feasibility chỉ thử khi cần.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Minimal scene loads in the locked Isaac environment.
- [ ] Command and environment are reproducible without GUI-only manual fixes.
- [ ] Native MP4 capture feasibility (hoặc exact failure + fallback probe) được
  ghi nhận; không claim replay system đã hoàn thiện từ smoke này.
- [ ] Failure is actionable and blocks M1 rather than being hidden.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Environment/version manifest.
- USD checksum and smoke command/log.
- Screenshot/video or exact failure.
- MP4 readability check hoặc native/fallback failure trace.
