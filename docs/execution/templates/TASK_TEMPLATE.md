# TASK-ID — Task Name

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-*` |
| Priority | `P0` / `P1` / `P2` |
| Status | `TODO` |
| Owner | Track owner / assignee |
| Target milestone | `M0`–`M6` |

Allowed lifecycle:

```text
TODO → PLANNED → IN_PROGRESS → VALIDATING → DONE
                         └────→ BLOCKED
```

## 2. Goal

Mô tả một outcome duy nhất, kiểm chứng được.

## 3. Why This Task Exists

Nêu requirement, acceptance hoặc handoff mà task hiện thực.

## 4. Dependencies

- Task/artifact/runtime dependency.
- Authority gate cần khóa trước khi implementation nếu có.

## 5. Input Contract

- Input artifact và schema authority.
- Không dùng private temp folder hoặc hidden local path.

## 6. Output Contract

- Output artifact, checksum/provenance và consumer.

## 7. Code Ownership

Create/modify only inside canonical owner paths. Liệt kê path cụ thể trong
Implementation Plan sau khi inspect repository.

Do not modify:

- implementation nội bộ của track khác;
- shared contract nếu chưa có producer + consumer review;
- organizer scaffold bằng rename/move/delete.

## 8. Tool / Repository Strategy

- Strategy: `REUSE` / `ADAPT` / `SELF-CODE` / `REFERENCE`.
- Primary tool/source:
- Take:
- Do not take:

## 9. Implementation Plan

Điền khi task được assign, sau khi inspect code và test hiện tại. Không đổi scope.

## 10. Tests

- Unit:
- Contract:
- Smoke/integration:
- Negative proof:

## 11. Definition of Done

- [ ] Implementation tồn tại trong owner boundary.
- [ ] Focused tests pass.
- [ ] Output validate contract và refs resolve.
- [ ] Consumer/handoff proof pass khi applicable.
- [ ] Evidence và known limitations được ghi lại.

## 12. Result / Evidence

Điền sau implementation. Không đánh dấu `DONE` chỉ dựa trên code review hoặc
mock nếu task yêu cầu real runtime/GPU acceptance.

