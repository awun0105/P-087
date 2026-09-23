# Real2Sim Studio Coding Agent Harness

File này là entrypoint bắt buộc cho mọi coding agent làm việc trong repository
AI20K RAV-01 (Real2Sim Studio). Mục tiêu của harness là giữ đúng context, scope,
authority, code quality và evidence qua nhiều agent/session; không thay thế product
documents hoặc task files bằng suy luận từ hội thoại.

## 1. Non-Negotiable Rules

1. Repository là system of record. Chat history, model memory, ví dụ, fixture,
   default config và code hiện tại không tự tạo product policy.
2. Chỉ làm outcome user yêu cầu. Review/diagnose/status là read-only; không tự sửa
   khi user chưa yêu cầu change hoặc implementation.
3. Không tự tạo/đổi task ID, mở rộng scope, đổi acceptance, schema, ownership hoặc
   canonical placement.
4. Không rename, move hoặc delete organizer-provided scaffold. Không sửa/xóa thay
   đổi đang có của user ngoài task boundary.
5. Không claim `DONE`, “pass”, “production-ready” hoặc “E2E complete” nếu chưa có
   executable/observable evidence phù hợp.
6. Nếu source documents mâu thuẫn hoặc thiếu authority cho một quyết định ảnh
   hưởng behavior/contract, dừng tại đúng boundary đó và báo user theo Conflict
   Protocol. Không chọn file thuận tiện hơn và không dùng “file mới nhất thắng”.
7. Không hardcode hoặc in ra secret, API key, credential, private dataset path hay
   dữ liệu nhạy cảm. Configuration phải đi qua environment và `Settings`.
8. Không commit, push, merge, tạo PR, đổi branch, cài hook hoặc thay CI/branch
   protection nếu user chưa yêu cầu rõ.

Đọc [Repository Workflow](docs/WORKFLOW.md) trước khi triển khai. Chỉ đọc thêm
những source sections, code và validation material liên quan trực tiếp tới task.

## 2. Authority Map

Authority được xác định theo **loại quyết định**, không phải theo ngày sửa file:

| Decision | Authoritative source |
| --- | --- |
| Product scope, priority, user behavior, acceptance | `docs/PRD.md` |
| Dataset preparation, leakage, split, evaluation protocol | `docs/DATASET_PLAYBOOK.md` |
| Shared artifacts, schemas, runtime/review/handoff rules | `docs/execution/TEAM_EXECUTION_CONTRACT.md` |
| Canonical repository placement và module ownership | `ARCHITECTURE.md` |
| Technical baseline, integration strategy, reusable tools | `docs/execution/INTEGRATION_PLAYBOOK.md` |
| Locked task IDs và implementation scope | `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md` |
| Milestone, deadline và team ownership | `docs/execution/TEAM_EXECUTION_PLAN.md` |
| Assigned track rules | `docs/execution/tracks/<track>/TRACK.md` |
| Task-local scope, I/O, dependencies, DoD và evidence | assigned `tasks/<TASK-ID>.md` |
| Current executable behavior | code + tests + runtime evidence |

Code/test hiện tại chứng minh implementation đang làm gì; chúng không được override
product policy hoặc contract đã được chấp nhận. Task/track files là projection và
execution record; chúng không được âm thầm sửa source of truth cấp cao hơn.
`CONTEXT.md` và root `README.md` là onboarding/overview, không phải authority cho
P0 acceptance, schema, task scope hay folder placement; nếu chúng khác bảng trên,
kiểm tra source of truth tương ứng và báo drift, không làm theo hướng dẫn cũ.

Trước khi thay đổi Real2Sim module, agent phải đọc ít nhất:

- `ARCHITECTURE.md`;
- `docs/PRD.md`;
- `docs/execution/TEAM_EXECUTION_CONTRACT.md`;
- `docs/execution/INTEGRATION_PLAYBOOK.md`;
- `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md`;
- assigned `TRACK.md` và task file;
- mọi source anchor được task file dẫn tới.

## 3. Mandatory Task Bootstrap

Trước lần edit đầu tiên, agent phải thực hiện và ghi nhận ngắn gọn:

1. Xác nhận repository root, current branch và `git status --short`.
2. Đọc `AGENTS.md`, `docs/WORKFLOW.md`, assigned `TRACK.md` và task file.
3. Đọc authority sources/sections liên quan; không dựa vào mô tả từ chat nếu repo
   đã có tài liệu hiện hành.
4. Inspect code, tests, fixtures, configuration và dependency versions tại boundary
   sẽ sửa. Không giả định path/API/library tồn tại.
5. Kiểm tra dependency task/artifact đã sẵn sàng hay chỉ là mock/fixture.
6. Tạo **Task Capsule** trong commentary hoặc task file:

```text
Task / outcome:
Authority anchors:
Dependencies and current state:
Inputs / outputs:
Owned paths:
Do-not-modify paths:
Proof required:
Unknowns / blockers:
```

7. Nếu task đủ authority và không blocked, cập nhật task `Status` theo lifecycle và
   điền `Implementation Plan` trước khi code. Không thay đổi Goal/I/O/DoD đã khóa.

Không bắt đầu implementation chỉ từ task title hoặc prompt một dòng.

## 4. Context And Recovery

- Với một assigned task, chính task file là durable execution record: plan, progress,
  decisions, tests, result và evidence phải được cập nhật tại đó.
- Chỉ tạo **một** file trong `docs/plans/active/` khi công việc đi qua nhiều task,
  nhiều session/contributor, có dependency đáng kể hoặc cần recovery. Không tạo plan
  song song nếu task file đã đủ.
- Trước context switch, compaction, pause hoặc handoff, cập nhật record đang dùng với:
  completed work, files changed, decisions, failed attempts, blocker, validation đã
  chạy và next step có thể thực thi.
- Khi resume, không suy đoán từ model memory. Re-read `AGENTS.md`, task/plan, relevant
  source anchors, `git status`, diff và test evidence rồi mới tiếp tục.
- Lasting product/architecture decision phải được owner cập nhật vào authoritative
  source hoặc `docs/decisions/`; không chôn quyết định chỉ trong chat/task notes.
- Không tạo task database, hidden state hoặc lifecycle cạnh tranh ngoài repository.

Nếu dùng helper/subagent, parent phải truyền Task Capsule và file boundary rõ ràng,
đợi helper hoàn tất, inspect diff/test output, rồi tự audit. Agent viết code không tự
phê duyệt completion của chính nó chỉ bằng summary.

### Anti-Hallucination Evidence Labels

- **VERIFIED:** đọc trực tiếp từ repository hoặc quan sát từ command/runtime output.
- **INFERENCE:** suy luận từ evidence; phải ghi rõ là inference và basis.
- **PROPOSAL:** lựa chọn đề xuất, chưa phải accepted authority.
- **UNKNOWN:** chưa có source/evidence; không được điền bằng giả định.

Không phát minh file path, API, schema field, task status, dependency version, metric,
command, test result hoặc runtime capability. Nếu source được nhắc tới nhưng không tồn
tại, báo missing source và tìm owner/reference thật; không âm thầm bỏ qua. Trước khi
dùng API/library behavior có thể thay đổi theo version, inspect manifest/lockfile hoặc
official documentation phù hợp với version thực tế.

## 5. Conflict And Missing-Authority Protocol

Một conflict thật xảy ra khi hai accepted sources yêu cầu behavior, schema, scope,
ownership hoặc acceptance không thể đồng thời thỏa mãn. Khác mức chi tiết không tự
động là conflict nếu phần chi tiết không override authority cao hơn.

Khi phát hiện conflict hoặc gap:

1. Dừng trước edit phụ thuộc quyết định đó; giữ nguyên files affected.
2. Kiểm tra đây không phải stale example, projection, fixture hoặc hiểu sai context.
3. Ghi exact paths + headings/fields và mô tả hai yêu cầu xung đột.
4. Nêu impacted task, producer/consumer, tests/artifacts và hậu quả của từng lựa chọn.
5. Nêu phần độc lập nào vẫn có thể tiếp tục an toàn; tiếp tục phần đó nếu không làm
   user khó review hoặc tạo rework.
6. Đánh dấu task/plan `BLOCKED` chỉ khi conflict thực sự ngăn tiến độ; không dùng
   blocker để che công việc khó hoặc test fail thông thường.
7. Hỏi user/authority owner một quyết định nhỏ nhất cần khóa. Chỉ sửa source of truth
   khi user giao quyền sửa docs/contract.

Format báo cáo:

```text
CONFLICT / AUTHORITY GAP
- Source A: path + section + required rule
- Source B: path + section + incompatible rule (hoặc missing decision)
- Impact: task/artifact/consumer nào bị ảnh hưởng
- Safe work completed: phần không phụ thuộc quyết định
- Decision needed: một câu hỏi cụ thể
- Suggested resolution: proposal, không trình bày như fact
```

## 6. Implementation Loop

Thực hiện theo thứ tự:

```text
bootstrap context
→ establish authority and baseline
→ define proof before code
→ make smallest coherent change inside ownership
→ run focused checks
→ run contract/integration/runtime proof as applicable
→ inspect diff and regressions
→ update task/plan evidence
→ hand off outcome, proof and remaining risk
```

Rules trong loop:

- Preserve public contracts, artifact provenance/checksum, revision invalidation,
  producer/consumer boundaries và event ordering trừ khi task explicitly changes them.
- Cross-track handoff chỉ qua shared contracts và published artifacts. Không import
  implementation nội bộ của track khác hoặc sửa JSON/artifact bằng tay để “cho chạy”.
- Shared contract change cần producer + consumer review và versioning/migration phù hợp.
- Dùng fixture đúng schema để phát triển song song, nhưng luôn ghi rõ fixture proof
  khác real producer/runtime acceptance.
- Không dùng evaluation-only data trong product prediction/runtime.
- Không thêm dependency/framework/repository mới trước khi kiểm tra license, version,
  native alternatives và technical baseline.
- Dùng `rg`/`rg --files` để tìm kiếm. Dùng `apply_patch` cho manual file edits.
- Functionality ngoài scope được ghi follow-up; không “tiện tay” refactor rộng.

## 7. Canonical Ownership Boundaries

Repository placement cụ thể do `ARCHITECTURE.md` quyết định. Baseline hiện tại:

- `src/models/contracts/`: shared artifact contracts; không chứa track internals.
- `src/services/reconstruction/`: `EX-REC`.
- `src/services/scene/`: `EX-SCENE`.
- `src/services/simulation/`: `EX-SIM`.
- `src/services/orchestration/`, `src/api/`, root `frontend/`: `EX-PRODUCT`.
- `scripts/torwic/`: offline dataset tooling, không phải runtime API.
- `tests/test_contracts/`, track-focused tests, `tests/integration/`, `tests/e2e/`:
  proof theo boundary tương ứng.
- `eval/`: reproducible evaluation protocols/results, không phải nơi để đặt product
  source code hoặc ghi số liệu chưa đo như fact.

Frontend `EX-PRODUCT` được phép làm full-stack Web Studio. 3D viewer integration nằm
tại `frontend/src/features/viewer/`; backend lifecycle/API vẫn thuộc FastAPI/shared
artifacts. React/Next.js local state không được trở thành competing source of truth.

## 8. Code Quality Standards

### Python

- Type hints và return type bắt buộc cho mọi function/method.
- Public functions/classes/modules cần docstring có ích.
- Mỗi function tối đa 30 dòng; tối đa 3 parameters. Nếu boundary cần nhiều fields,
  dùng typed/Pydantic model thay vì parameter list dài.
- Naming: file/function `snake_case`, class `PascalCase`, constant `UPPER_SNAKE`.
- Import order: standard library → third-party → local modules.
- Bắt exception cụ thể. Không dùng bare `except`; không swallow lỗi. Broad exception
  chỉ được phép tại documented process boundary, phải log context và preserve cause.
- FastAPI I/O dùng Pydantic models; async I/O không được bọc bằng blocking call trên
  event loop.
- Config qua `pydantic-settings`; không đọc secret rải rác hoặc hardcode environment.
- Ruff là formatting/lint authority hiện tại. Mypy chỉ được claim nếu command thật sự
  chạy được trên checkout hiện tại.

Chi tiết: `docs/guide/code-style/python.md` và
`docs/guide/anti-patterns/common-mistakes.md`.

### TypeScript / React / Three.js

- Frontend mới dùng TypeScript. Không dùng `any` để né contract; validate/parse dữ
  liệu tại API/artifact boundary và giữ typed domain models.
- Components có một responsibility; tách render state, API state và domain commands.
- Persisted job/artifact/scene/review/release state thuộc backend; browser state chỉ
  giữ interaction/view state tạm thời.
- Three.js/Gaussian resources, listeners, animation frames, workers và GPU allocations
  phải có lifecycle cleanup để tránh leak khi unmount/reload.
- Renderer path thực sự được triển khai phải có capability/error/degraded state rõ
  ràng. P0 phải render real 3DGS `VisualArtifact` trong browser cùng các view
  mesh/point-cloud/collider; WebGL/WebGL2 là baseline, WebGPU chỉ cần check khi
  backend được chọn thực sự dùng WebGPU. Mesh/point-cloud mock không được báo
  cáo như real Brush/3DGS acceptance; mọi GPU resource phải được cleanup.
- Dùng scripts/linter/test runner thật trong `frontend/package.json` khi scaffold tồn
  tại; không invent command hoặc claim frontend checks trước khi project được tạo.

### General Quality

- File/module phải cohesive; không dồn business logic vào `main.py`, route hoặc UI
  component lớn.
- Ưu tiên pure functions, explicit dependencies và deterministic adapters.
- Error message phải actionable và không lộ secret/path nhạy cảm.
- Comment/docstring giải thích **why/contract**, không lặp lại code.
- Comment, docstring và ghi chú giải thích ưu tiên tiếng Việt để team dễ review;
  identifier, type, schema và public API giữ tên tiếng Anh rõ nghĩa.
- Không copy cả reference repository; chỉ `REUSE`/`ADAPT` phần task cho phép và giữ
  license/provenance.
- Không sửa generated/vendor files thủ công nếu source generator/owner tồn tại.

## 9. Testing And Evidence Standard

Xác định proof trước khi code và chạy mức phù hợp theo risk:

1. **Static:** Ruff/format/type/build checks thật sự có trong repo.
2. **Unit:** local logic, positive/negative/error paths.
3. **Contract:** schema, serialization, checksum/provenance, compatibility.
4. **Integration:** producer → artifact → consumer không qua manual conversion.
5. **E2E/runtime:** user-visible workflow qua real interface.
6. **Evaluation/GPU:** dataset, metric, Isaac/renderer/runtime evidence khi acceptance
   yêu cầu; không thay bằng mock.

Minimum handoff rules:

- Chạy focused tests cho changed behavior; chạy broader suite/build khi change có
  shared hoặc cross-track blast radius.
- Với invariant, cần positive proof và negative proof theo
  `docs/patterns/encoding-invariants.md`.
- Ghi command, exit/result và môi trường liên quan. Không biến “không chạy được” thành
  “pass”; ghi blocker/limitation chính xác.
- Phân biệt rõ: static inspection, mocked test, fixture integration, real runtime,
  browser visual QA, GPU/Isaac acceptance và external CI.
- Test tồn tại không chứng minh test đã chạy. CI file tồn tại không chứng minh current
  revision green hay branch protection đang enforce.
- Không update snapshot/golden/expected result chỉ để làm test xanh nếu chưa chứng minh
  behavior mới là authority-approved.

Python baseline commands phải được xác nhận từ repo trước khi chạy; hiện tại thường là:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
pytest <focused paths> -v
pytest tests/ -v
```

`make check` hiện có thể format/mutate files; không dùng như read-only validation mà
không inspect target trước.

## 10. Task Lifecycle And Completion

Allowed lifecycle:

```text
TODO → PLANNED → IN_PROGRESS → VALIDATING → DONE
                         └────→ BLOCKED
```

- `PLANNED`: authority/dependencies đã inspect, implementation plan cụ thể.
- `IN_PROGRESS`: implementation đang diễn ra.
- `VALIDATING`: code xong nhưng proof/acceptance chưa hoàn tất.
- `DONE`: tất cả applicable DoD và evidence đã quan sát được.
- `BLOCKED`: external decision/dependency thực sự ngăn tiếp tục; phải ghi unblock
  condition. Test fail hoặc việc khó không tự động là blocker.

Trước handoff, inspect `git diff`/`git status`, đảm bảo chỉ sửa intended files, cập
nhật task `Result / Evidence` và plan nếu có. Báo cáo cuối phải tự chứa:

1. **Outcome:** kết quả đã đạt hay blocker.
2. **Changed:** file/behavior/contract đã thay đổi.
3. **Validation:** exact checks và observed result.
4. **Limits/Risks:** phần mock, chưa chạy, external hoặc cần user decision.
5. **Next step:** chỉ khi còn việc rõ ràng.

Không yêu cầu user đọc commentary cũ để hiểu handoff.

## 11. Git Safety

- Feature work bắt đầu từ `develop` và PR vào `develop`; `main` chỉ nhận release theo
  workflow được user/team thực hiện.
- Không push/merge trực tiếp `main`, không force-push, không rewrite history và không
  dùng destructive reset.
- Commit convention: `type(scope): mô tả ngắn gọn` với `feat`, `fix`, `docs`, `test`,
  `refactor`, `chore`.
- Trước commit/push được yêu cầu: kiểm tra intended diff, ignored secrets, tests,
  branch/tracking/remote state và stage đúng files. Không stage unrelated user changes.

Chi tiết: `docs/guide/chapter-02.md` phần Git workflow.

---

<!-- HARNESS:BEGIN -->
## Harness Core Contract

Start with the requested outcome and use the repository as the system of record.
Read `docs/WORKFLOW.md` and only relevant product, design, plan, code, and
validation material.

- Read-only requests do not authorize edits.
- Use one task record or one durable plan; do not create parallel control-plane state.
- Establish authority before encoding product, architecture, reliability, security,
  or quality policy.
- Pause at ambiguity, document conflict, unsafe recovery, weakened validation, or
  insufficient authority.
- Claim completion only with executable or observable evidence.

Harness has no task database or hidden orchestration lifecycle. Repository plans,
task files, code, tests and behavior-level proof are the durable state.
<!-- HARNESS:END -->
