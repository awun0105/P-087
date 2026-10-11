# Encoding Invariants

Pattern này dùng để biến một rule kiến trúc, reliability, security hoặc quality
đã được chấp nhận thành validation native trong repository. Check chỉ enforce
policy; check không tự tạo policy.

## 1. Establish Authority

Ghi source và exact rule phải đúng. Code patterns, defaults, tests, fixtures,
tool conventions và undocumented preferences không đủ để tạo invariant.

Dừng trước edit khi:

- không có accepted authority;
- scope/exception chưa rõ;
- hai accepted sources không tương thích;
- enforcement proposed mạnh hơn rule được phép.

## 2. Define The Boundary

Trước khi chọn tool, ghi:

| Field | Required content |
| --- | --- |
| Authority | path + section + accepted rule |
| Scope | files/modules/config/runtime objects được cover |
| Allowed | ít nhất một conforming example |
| Forbidden | cấu trúc/behavior chính xác cần reject |
| Exceptions | chỉ exception do cùng authority cho phép |
| Diagnostic | violating item + rule + authority + next action |

Không kéo adjacent preferences vào cùng check.

## 3. Reuse Native Validation

Tìm validation owner hiện tại: Ruff rule, test suite, build command, script,
schema validator hoặc policy scanner. Thêm check nhỏ nhất tại layer thấp nhất có
thể quan sát toàn scope.

Không thêm framework/linter/service mới nếu native mechanism diễn đạt được rule.
Failure message phải actionable, ví dụ:

```text
src/services/scene imports reconstruction internals:
cross-track communication must use shared contracts
(ARCHITECTURE.md). Depend on src/models/contracts instead.
```

## 4. Prove Both Directions

- **Positive proof:** conforming case pass.
- **Negative proof:** targeted forbidden fixture/mutation fail vì đúng rule và
  diagnostic.

Negative proof phải isolated/recoverable; không để violating product file trong
working tree. Repository pass mà chưa exercise violation không chứng minh guard
có thể bắt regression.

## 5. Report Enforcement Precisely

| Level | Claim allowed |
| --- | --- |
| Local | command tồn tại; ghi có chạy/pass hay không |
| Hook | optional convenience; không claim required nếu chưa verify/install |
| CI | checked-in workflow có/không invoke command |
| Branch protection | verified externally hoặc unverified |

Không tự cài hook, sửa CI/merge policy hoặc branch protection nếu task/user chưa
authorize. Workflow file tồn tại không chứng minh current revision green.

## Handback

1. authority và encoded scope;
2. validation owner/check được thêm;
3. positive và negative proof;
4. local/hook/CI/branch-protection state tách riêng;
5. exceptions, gaps và external state chưa verify.
