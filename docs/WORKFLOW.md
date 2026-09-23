# Repository Workflow

Workflow này mô tả cách coding agent đi từ user request tới evidence trong
Real2Sim Studio. `AGENTS.md` là entrypoint; product documents, task files, code,
tests và runtime signals là system of record.

## 1. Select The Work Shape

### Read-only request

Với answer, review, diagnosis, plan hoặc status:

- chỉ inspect dữ liệu cần thiết;
- không sửa code/docs/task status;
- phân biệt verified fact, inference và unknown;
- phát hiện vấn đề không đồng nghĩa được phép sửa.

### Bounded change

Với một thay đổi nhỏ, một session và không cần cross-task coordination:

1. bootstrap theo `AGENTS.md`;
2. xác định authority, baseline và proof;
3. sửa nhỏ nhất trong owner boundary;
4. validate;
5. cập nhật assigned task file nếu đây là execution task;
6. handoff outcome/evidence/limits.

Không cần tạo execution plan riêng.

### Assigned execution task

Khi user giao một task ID:

```text
AGENTS.md
→ track/TRACK.md
→ tasks/TASK-ID.md
→ source anchors
→ existing code/tests/runtime
→ Task Capsule
→ task implementation plan
→ code + proof
→ task result/evidence
```

Task file là durable record. Agent không được thay đổi Goal, Input/Output
Contract hoặc DoD để hợp với implementation đang có.

### Durable planned change

Dùng một file `docs/plans/active/<date>-<slug>.md` khi công việc:

- qua nhiều task/session/contributor;
- có ordering/dependency đáng kể;
- có migration/recovery risk;
- không thể resume an toàn chỉ từ task file và diff.

Dùng `docs/templates/exec-plan.md`. Cập nhật progress, decisions, validation và
result trong cùng file; sau khi proof hoàn tất, chuyển sang `completed/`.

## 2. Authority Gate

Trước edit, trả lời:

1. Ai/source nào có quyền quyết định behavior này?
2. Exact rule/acceptance/schema/ownership là gì?
3. Task có quyền thay đổi rule đó hay chỉ implement nó?
4. Code/tests hiện tại phù hợp hay đang drift?
5. Proof nào chứng minh outcome?

Nếu nhiều lựa chọn materially different còn mở, dừng và hỏi quyết định nhỏ
nhất. Configurable default, fixture, reference repository, repeated code pattern
hoặc model preference không phải authority.

Authority theo decision type nằm trong `AGENTS.md` và
`docs/execution/README.md`.

## 3. Conflict Gate

Khi hai sources có vẻ khác nhau:

1. xác định exact decision type;
2. kiểm tra source nào là authority và source nào chỉ là projection/example;
3. kiểm tra hai yêu cầu có thực sự không thể đồng thời thỏa mãn;
4. nếu conflict thật, dừng phần affected và báo theo Conflict Protocol trong
   `AGENTS.md`;
5. không tự sửa source docs khi task chỉ cho phép implementation.

Phần độc lập có thể tiếp tục nếu không tạo rework hoặc che conflict.

## 4. Define Proof Before Code

Chọn proof theo behavior:

| Behavior | Minimum proof |
| --- | --- |
| Local calculation/adapter | unit tests gồm positive, negative và error path |
| Artifact/schema | serialization + validation + compatibility/checksum proof |
| Producer/consumer boundary | integration test bằng published artifact |
| API behavior | route/service tests, auth/error behavior nếu applicable |
| Browser interaction | component/browser test và real interaction evidence |
| Cross-track workflow | integration/E2E không dùng manual conversion |
| GPU/Isaac/3DGS acceptance | real runtime artifact/environment evidence |
| Invariant | positive + targeted negative proof |

Mock hoặc fixture chỉ chứng minh layer của nó. Không nâng cấp mock success thành
real runtime acceptance.

## 5. Implementation Discipline

- Inspect working tree trước edit và bảo toàn unrelated changes.
- Chỉ sửa canonical owner paths.
- Reuse existing conventions/adapters/validation owners.
- Thay đổi shared contract phải xem producer, consumer, migration/versioning và
  invalidation.
- Không thêm abstraction/dependency chỉ để dự phòng.
- Error phải actionable; không swallow hoặc che nguyên nhân.
- Không sửa expected/golden output chỉ để làm test xanh.
- Khi evidence làm approach sai, cập nhật plan/task rồi mới đổi hướng.

## 6. Validation Ladder

Chạy từ hẹp tới rộng:

1. syntax/format/lint;
2. focused unit tests;
3. contract tests;
4. integration tests;
5. E2E/runtime/evaluation acceptance;
6. broader repository suite/build nếu blast radius yêu cầu.

Trước khi chạy command, inspect project-native owner (`Makefile`,
`pyproject.toml`, `package.json`, CI). Không invent command. Không claim CI hoặc
branch protection từ static workflow file.

Với architecture, reliability, security hoặc quality invariant, làm theo
[Encoding Invariants](patterns/encoding-invariants.md).

## 7. Context Checkpoints

Cập nhật assigned task hoặc active plan:

- sau một coherent implementation group;
- trước khi đổi agent/session;
- trước pause/context compaction;
- khi authority, approach hoặc blocker thay đổi;
- sau validation quan trọng.

Checkpoint tối thiểu:

```text
Current outcome/status:
Completed:
Files changed:
Decisions and authority:
Validation run/results:
Failures/known limits:
Next executable step:
```

Khi resume, re-read record, source anchors, status, diff và evidence. Không dùng
chat summary làm authority.

## 8. Completion Standard

Task chỉ hoàn tất khi:

- requested outcome tồn tại;
- change nằm đúng ownership/scope;
- repository truth và task evidence được cập nhật;
- focused và applicable boundary/runtime proof pass;
- diff được review, không chứa unrelated/destructive/secret changes;
- limitations và external unverified state được nói rõ;
- task status phản ánh evidence thật.

Nếu blocked, handoff phải nêu exact blocker, work an toàn đã làm và condition để
resume. Completion message không thay thế behavior-level proof.
