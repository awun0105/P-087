# 0015 Scene revision head trong runtime DB và optimistic CAS

Date: 2026-10-07

## Status

Proposed — schema/publishing protocol mới cần review; chưa implement.

## Context

SceneEditor phục hồi bằng scan từ revision đầu, tối đa 1.000 bước. Mỗi process
có cache riêng; kiểm expected revision trước publish không tạo atomic CAS giữa
hai API/worker. Object store và runtime DB không có distributed transaction.

## Decision đề xuất

1. DB giữ committed head gồm job_id, scene_id, revision, SceneIR logical checksum,
   published artifact ref/byte checksum và generation. SceneIR/artifacts vẫn bất biến.
2. Mọi publish_initial/publish_next/apply/restore/reobjectify/physics_enrich dùng
   cùng protocol: reserve generation theo expected head → publish/verify → CAS
   commit head. Reader chỉ thấy committed head.
3. Chỉ một writer reserve một next revision cho cùng head. Giữ revision naming
   hiện có; không dùng hai payload khác nhau tại cùng immutable URI.
4. Crash trước commit để pending publication; recovery kiểm lease + exact bytes
   và CAS hoàn tất hoặc giữ diagnostic. Không coi file hiện diện là committed.
5. Legacy head được bootstrap một lần, kiểm checksum/lineage rồi persist.
   Không tin filesystem lexical order hoặc tự nhảy qua revision gap/corruption.
6. Lookup thông thường O(1) metadata calls theo chiều dài lịch sử. Repair scan
   là thao tác explicit, có continuation/bounded work; không chạy lại toàn bộ
   lịch sử trên mỗi HTTP request và không có hard ceiling 1.000.

## Data contract

Proposed SceneHeadRecord và pending publication record là runtime records trong
DB, không thêm workflow state vào SceneIR. AUD-10.S1 chốt table/version/CAS,
liên kết SceneRevision.scene_reference và supersedes lineage. Old artifacts
giữ nguyên bytes/checksums. Migration không reset hoặc drop lịch sử.

## Alternatives Considered

1. Tăng _MAX_RECOVERY_STEPS: giảm một triệu chứng, vẫn O(n) và thiếu CAS.
2. Chọn revision lớn nhất theo tên URI: có thể chọn orphan/corrupt revision.
3. In-memory lock: không bảo vệ API/worker khác process hoặc host.
4. Ghi mutable SceneIR current.json: cạnh tranh với immutable artifact truth.

## Consequences

Positive: bounded reads, chống lost update, commit point rõ ràng. Tradeoffs:
pending publications cần recovery; SQLite/PG concurrency phải được kiểm riêng.
DB head cần được đưa vào data-package export/restore và deletion flows.

## Follow-Up

- [AUD-10](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-10-revision-head.md).
- Integrate vào AUD-07/08/09 và physics_enrich, không tạo publishing path riêng.
