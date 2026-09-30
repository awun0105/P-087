# EX-SCENE — Object Intelligence & Scene Core

## Mission

Biến reconstruction toàn cục thành `Environment` và các `SceneObject` độc lập,
có thể xác nhận/chỉnh sửa và publish thành `SceneIR`.

```text
ReconstructionBundle → masks → candidate identities → human confirmation
→ scene decomposition → SceneIR
```

## Ownership

Track Owner: Đức.

- `src/services/scene/`
- `tests/test_scene/`
- Scene contracts/fixtures với producer + EX-SIM/EX-PRODUCT review

Không sở hữu collider generation, Isaac/OpenUSD runtime, UI implementation hoặc
reconstruction backend.

## Inputs And Outputs

Inputs: `ReconstructionBundle`, RGB frame refs, camera poses và canonical geometry.

Output: valid, versioned `SceneIR`; collider có thể chưa đầy đủ ở handoff đầu.

## Technology And Strategy

- SAM2 được reuse qua adapter cho mask prediction/propagation.
- Open3D/NumPy cho geometry association utilities.
- `BigCiLeng/R2G` (SAMPro3D): Tier-0 Algorithm Donor cho multi-view association (`SCENE-03`) và per-object decomposition (`SCENE-06`) theo [Audit #2](../../audits/02_r2g.md).
- `lkeab/gaussian-grouping`: Tier-0 Algorithm Reference cho per-Gaussian persistent identity learning và Tier-1 Qualification Candidate (`SCENE-QUAL-GG-01`) theo [Audit #6](../../audits/06_gaussian_grouping.md).
- ObjectGS, SegAnyGaussians, OpenReal2Sim và gs-real2sim là references/donors cho các utilities chuyên biệt.
- Team sở hữu candidate lifecycle, deterministic association baseline, HITL operations, decomposition và SceneIR behavior.

## Hiện trạng trên `develop` (2026-09-29)

- Có `src/services/scene/bundle_consumer.py` (SCENE-01, PR #8) đọc `ReconstructionBundle`
  qua shared contract; các package `association/ candidates/ decomposition/ editing/
  extraction/` còn là placeholder. Code mới của track chưa được push.
- Kiến trúc cloud (ADR 0003) chưa quyết định nơi chạy worker SCENE (SAM2 cần GPU);
  khi nối vào, dùng cùng mô hình worker nhận job qua server và đọc/ghi artifact R2.

## Cập nhật 2026-09-30 (`feat/studio-integration`, PR #16)

- Tách vật thật: SAMPro3D adapt với SAM2 (ADR 0006), stage `ST-OBJECT-EXTRACT`, fallback hình học;
  `job-123dfd4868d8` 30 ứng viên. SceneIR sửa theo vật: xác nhận / loại / ẩn / đổi tên / thêm vật
  cản hộp, mỗi thao tác một revision (`src/services/scene/editing/`,
  `src/services/orchestration/scene/objects.py`).
- **Pipeline v2 ([ADR 0007](../../../decisions/0007-object-centric-hybrid-usd-pipeline.md)):** SCENE-02/03 chuyển sang mask
  vật theo video (SAM2 lan mask, ID ổn định); SCENE-06/07 tách nền/vật với Gaussian + mesh riêng;
  gợi ý nhãn từ danh mục asset Isaac; SCENE-08A thêm asset Isaac. SAMPro3D-trên-hộp là đường tạm
  cho tới khi v2 có bằng chứng.

## Authority Gates

- Final `SceneIR`/`SceneObject` field set phải theo normative Contract; Playbook projection và fixture không tự tạo authority.
- `agents[]` không phải P0 requirement nếu chưa được PRD/Contract chấp nhận.
- `review_state` không thuộc canonical SceneIR; workflow/revision lifecycle do EX-PRODUCT quản lý.
- Manual evaluation annotations không được feed vào prediction.
- Shared schema change cần EX-SCENE cùng EX-SIM/EX-PRODUCT review.

## Task Index

| Task | Name | Depends on | Primary output |
|---|---|---|---|
| [SCENE-01](./tasks/SCENE-01.md) | Fixture-first bundle consumer | — | validated bundle view |
| [SCENE-02](./tasks/SCENE-02.md) | Object extraction | SCENE-01 | mask artifacts + metadata |
| [SCENE-03](./tasks/SCENE-03.md) | Multi-view association | SCENE-01/02 | candidate identities |
| [SCENE-04](./tasks/SCENE-04.md) | Candidate model | SCENE-03 | candidate state/provenance model |
| [SCENE-05](./tasks/SCENE-05.md) | Human Confirmation operations | SCENE-04 | confirmed/corrected candidates |
| [SCENE-06](./tasks/SCENE-06.md) | Scene decomposition | SCENE-05 | Environment + object bindings |
| [SCENE-07](./tasks/SCENE-07.md) | SceneObject model | SCENE-06 | canonical SceneObjects |
| [SCENE-08](./tasks/SCENE-08.md) | Edit semantics | SCENE-07 | revised scene behavior |
| [SCENE-08A](./tasks/SCENE-08A.md) | Add primitive/asset | SCENE-07 | user-added SceneObject |
| [SCENE-09](./tasks/SCENE-09.md) | Publish SceneIR | SCENE-06/07 | versioned `SceneIR` |
| [SCENE-10](./tasks/SCENE-10.md) | Worker entrypoint | SCENE-09 | stable worker/CLI |

## Track Definition Of Done

- Automatic candidates và ít nhất một correction case hoạt động.
- Environment + independent SceneObjects tồn tại.
- SceneIR roundtrip/refs/unique IDs/transform invariants pass.
- Real ReconstructionBundle được consume không sửa tay.
- EX-SIM đọc SceneIR trực tiếp và evidence before/after được lưu.

## Required Sources

- [`PRD.md`](../../../PRD.md)
- [`TEAM_EXECUTION_CONTRACT.md`](../../TEAM_EXECUTION_CONTRACT.md)
- [`INTEGRATION_PLAYBOOK.md`](../../INTEGRATION_PLAYBOOK.md)
- [`TRACK_IMPLEMENTATION_GUIDE.md`](../../TRACK_IMPLEMENTATION_GUIDE.md)
- [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md)
- [`ARCHITECTURE.md`](../../../../ARCHITECTURE.md)
