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
- Gaussian Grouping, ObjectGS, SegAnyGaussians, R2G và gs-real2sim chỉ là references trừ khi change control chấp nhận khác.
- Team sở hữu candidate lifecycle, deterministic association baseline, HITL operations, decomposition và SceneIR behavior.

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
