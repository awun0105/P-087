# REC-03 — Camera Pose With COLMAP

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
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

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Command-builder và sparse-model selection unit tests.
- Missing/empty model negative tests.
- Small RGB to COLMAP smoke; normalized artifact contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] COLMAP chạy bằng stable adapter command.
- [ ] Best sparse model được chọn deterministic và output normalize.
- [ ] Artifact có pose stats, config, version, checksum và refs resolve.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Registered-frame/pose stats.
- COLMAP command/version/log.
- Small-scene artifact và failure sample.
