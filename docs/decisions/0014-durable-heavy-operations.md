# 0014 Durable heavy operations dùng chung resource admission

Date: 2026-10-07

## Status

Proposed — extension operational record/admission cần review; chưa implement.

## Context

Import packaging dùng BackgroundTasks trong process API. Reobjectify đã có DB
queue/claim/recovery nhưng chạy ngoài ResourceAdmission; recovery dựa hostname
và thời gian có thể ảnh hưởng worker khác trên cùng host. Worker claim không
ngăn kết quả dài hạn ghi đè scene đã được sửa sau khi request bắt đầu.

## Decision đề xuất

1. API chỉ validate/enqueue operation và trả status. Packaging/reobjectify/
   validation chạy qua worker durable. Import vẫn là ImportedScene, không
   fabricate ReconstructionBundle hoặc chuyển thành reconstruction job.
2. Giữ domain queue records riêng; chia sẻ reservation/admission primitives.
   Không dựng một scheduler framework hoặc hợp nhất tất cả lifecycle enums.
3. Operation có ID/attempt, input/config checksum, lease owner, fencing token,
   heartbeat và base revision/candidate nếu relevant. Owner lease hiện tại
   mới được commit terminal record/publication binding.
4. Không đủ/không biết tài nguyên: chờ có cancel, giữ input/config; admission
   chạy lại khi headroom thay đổi. Không âm thầm giảm quality.
5. GPU, RAM và disk được giữ chỗ/touch/release cho toàn bộ thời gian nặng.
   Request claim và reservation phải không để hai worker chạy cùng operation.
6. Retry giữ attempts/diagnostics; chỉ lỗi transient được retry. Cancel phải
   kill/reap process group trước release reservation. Worker cũ mất lease
   không được resume publication sau worker mới.
7. Scene operation commit theo expected base revision từ request. Kiểm tra
   trước compute là chưa đủ; phải CAS tại publish/commit.

## Data contract

AUD-07.S1 định nghĩa minimal admission request độc lập JobManifest với resource
demand/profile và operation identity. Giữ reservation table/persistence hiện
có bằng additive migration. Import/objectify/validation giữ operational record
của domain; status/lease fields có version và backward-compatible projections.
Artifact identity vẫn dùng logical URI/checksum, không worker-local paths.

## Alternatives Considered

1. BackgroundTasks + startup scan: không đủ cross-host lease/ownership.
2. Fake JobManifest cho import: làm sai lifecycle và provenance.
3. Một generic queue framework cho mọi domain: scope lớn; reuse primitives đủ.
4. Hủy mọi running request cùng hostname lúc startup: không an toàn khi nhiều
   worker trên một máy. Dùng lease/fencing + heartbeat thay thế.

## Consequences

Positive: restart recovery, cạnh tranh tài nguyên minh bạch, không mất edits.
Tradeoffs: DB migration và polling projection cần tương thích; live multiworker
GPU smoke vẫn phải chạy ngoài unit fixtures.

## Follow-Up

- [AUD-07](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-07-heavy-operation-admission.md) khóa primitive.
- [AUD-06](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-06-durable-import.md) dùng cho import.
- [AUD-05](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-05-isaac-validation.md) dùng cho validator.
