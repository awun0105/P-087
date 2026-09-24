# EX-SIM — Physics, OpenUSD, Isaac Sim & Evaluation

## Mission

Biến `SceneIR` thành physics-ready candidate, validate exact CandidatePackage
trong Isaac Sim và chạy evaluator riêng khi protocol yêu cầu.

```text
SceneIR → collider → preflight → CandidatePackage → Isaac → ValidationReport
prediction + locked references → EvaluationRunner → EvaluationReport
```

## Ownership

Track Owner: Đạt. QA / Validation Lead: Đạt.

- `src/services/simulation/`
- evaluation implementations/protocols dưới `eval/`
- `tests/test_simulation/`
- simulation/evaluation contracts với consumer review

Không sở hữu scene editing UI, product review authorization hoặc reconstruction.

## Inputs And Outputs

Inputs:

- `SceneIR` cho product validation;
- evaluation-only references chỉ trong EvaluationRunner và sau prediction freeze.

Outputs:

- physics-enriched SceneIR revision;
- `PreflightReport`, `CandidatePackage`, `ValidationReport`;
- `EvaluationReport` cho locked acceptance/benchmark.

## Technology And Strategy

- Open3D/Trimesh cho collider utilities.
- OpenUSD cho package translation.
- Isaac Sim/IsaacLab cho simulator runtime.
- `PointsCoder/OpenReal2Sim`: Tier-0 Code Donor cho USD conversion, PhysX properties (`SIM-05`), collision optimization (`SIM-02`) và Docker runtime isolation (`SIM-06`) theo [Audit #1](../../audits/01_openreal2sim.md).
- `zst1406217/VR-Robo`: Tier-0 Integration Donor cho IsaacLab scene/robot runtime (`SIM-01`, `SIM-06`), video replay fallback và visual/physics synchronization theo [Audit #3](../../audits/03_vr_robo.md).
- `discoverse-dev/DISCOVERSE`: Tier-0 Integration Reference cho Visual ↔ Physics synchronization (`gs_model_dict`), Secondary Utility Donor cho CoACD collider decomposition (`SIM-02`), và Tier-0 P1 Code Donor cho remote GS rendering & hardware NVENC H.264 streaming theo [Audit #5](../../audits/05_discoverse.md).
- Re3Sim là architecture reference.
- Không tự viết lại USD core, physics engine hoặc Isaac runtime.

## Authority Gates

- Isaac/CUDA/driver/GPU hiện `UNVERIFIED/TBD` và phải được runtime manifest ghi lại sau provisioning; không block synthetic Foundation.
- Robot footprint và final Start–Goal benchmark do human cung cấp ở milestone evaluation, không được invent.
- ValidationReport structured checks/path results đã được normative Contract khóa.
- Isaac worker chỉ ghi observed `CLEAR/BLOCKED/ERROR`; expected-label comparison thuộc EvaluationRunner trừ khi product config công khai quy định route bắt buộc.
- Object-candidate rule dùng `OBJECT_CONFIRMATION_INCOMPLETE`; không dùng final-candidate review làm preflight gate.

## Task Index

| Task | Name | Depends on | Primary output |
|---|---|---|---|
| [SIM-01](./tasks/SIM-01.md) | Minimal Isaac smoke | locked runtime | smoke evidence |
| [SIM-02](./tasks/SIM-02.md) | Collider generation | SceneIR fixture | `ColliderSpec` artifacts |
| [SIM-02A](./tasks/SIM-02A.md) | Collider edit validation | SIM-02 | validated collider edit behavior |
| [SIM-03](./tasks/SIM-03.md) | Physics enrichment | SIM-02/02A | physics SceneIR revision |
| [SIM-04](./tasks/SIM-04.md) | Deterministic preflight | SIM-03 | `PreflightReport` |
| [SIM-05](./tasks/SIM-05.md) | Candidate OpenUSD build | SIM-04 | `CandidatePackage` |
| [SIM-06](./tasks/SIM-06.md) | Isaac validation | SIM-01/05 | observed validation evidence |
| [SIM-07](./tasks/SIM-07.md) | ValidationReport | SIM-06 | candidate-bound report |
| [SIM-08](./tasks/SIM-08.md) | EvaluationRunner | locked protocols; SIM-06 for path | `EvaluationReport` |
| [SIM-09](./tasks/SIM-09.md) | Worker entrypoints | SIM-06/07/08 | separate simulation/evaluation CLIs |

## Track Definition Of Done

- Real SceneIR được consume và collider/preflight/candidate build hoạt động.
- Exact CandidatePackage load/validation trong Isaac có evidence.
- 5/5 path observations tồn tại; agreement với expected labels được tính trong evaluator.
- Locked acceptance tạo EvaluationReport; ordinary upload không bị yêu cầu ground truth độc lập.
- EX-PRODUCT đọc reports trực tiếp, không manual conversion.

## Required Sources

- [`PRD.md`](../../../PRD.md)
- [`DATASET_PLAYBOOK.md`](../../../DATASET_PLAYBOOK.md)
- [`TEAM_EXECUTION_CONTRACT.md`](../../TEAM_EXECUTION_CONTRACT.md)
- [`INTEGRATION_PLAYBOOK.md`](../../INTEGRATION_PLAYBOOK.md)
- [`TRACK_IMPLEMENTATION_GUIDE.md`](../../TRACK_IMPLEMENTATION_GUIDE.md)
- [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md)
- [`ARCHITECTURE.md`](../../../../ARCHITECTURE.md)
