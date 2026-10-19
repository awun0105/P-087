# 0017 Fast Preview và final artifacts có identity riêng

Date: 2026-10-07

## Status

REJECTED / DEFERRED theo quyết định của owner ngày 2026-10-08. Không triển khai trong kế hoạch hiện tại.

## Lý do bác bỏ / Defer (Owner Rationale 2026-10-08)

1. **Chất lượng hình ảnh 7.000 iterations không có giá trị đánh giá thực tế:**
   Trong 3D Gaussian Splatting (3DGS), 7.000 vòng lặp chỉ mới bắt đầu chu trình densification/pruning thô. Kết quả tái tạo ở mốc này chỉ là các đám điểm mờ (blobs/floaters) không có biên dạng hình học rõ ràng, không đủ độ nét để người dùng đánh giá chất lượng scene hoặc quyết định quay lại video.
2. **Nguy cơ làm chậm toàn bộ pipeline thay vì tăng tốc:**
   Bộ huấn luyện Brush chưa nghiệm thu năng lực checkpoint resume (continuation 7k → 30k). Nếu dừng ở 7k rồi chạy tiếp bản Final mà không resume được, hệ thống buộc phải huấn luyện lại từ đầu 30k. Tổng số vòng lặp bị đội lên 7k + 30k = 37k iterations, làm lãng phí GPU và kéo dài thời gian chờ đợi.
3. **Lệch mục tiêu cốt lõi của Real2Sim:**
   Real2Sim Studio cần cảnh có mesh, collider và vật lý chính xác cho robot mô phỏng (Isaac Sim). Bản 7k hoàn toàn không có mesh/collider và không thể dùng để trích xuất vật thể. Việc tối ưu thời gian xử lý thực sự sẽ được giải quyết trực tiếp qua AUD-15 (loại bỏ thao tác thừa trong worker pipeline) thay vì cắt giảm số vòng lặp huấn luyện.

## Context

30k Brush có local stage timing ~42,6–45 phút ở hai attempts chưa finalize.
Config đã cho 1k–60k iterations; chỉ đổi 30k thành 7k không tạo complete Preview
Mode hoặc guarantee 5 phút. Preview visual không chứng minh collider/release quality.

## Decision đề xuất

1. User chọn explicit Fast Preview preset hoặc final processing profile. Preview
   và final giữ effective config/quality tier/checksum riêng, không silent downgrade.
2. Preview publish SOG/visual sớm để inspect; chưa đủ final scene/candidate/
   validation/release. Không gọi toàn bộ job SUCCEEDED vì SOG preview xuất hiện.
3. Promote/finalize là command explicit: dùng final config đã chọn, admission
   giữ quality; cache/checkpoint chỉ reuse khi upstream/runtime/config identities
   tương thích và Brush runtime thực sự hỗ trợ resume.
4. Không claim continuation từ 7k→30k nếu checkpoint capability chưa qualified;
   rerun final có identity/history rõ là valid fallback.
5. Preview timing đo time-to-first-usable-preview, queue/compute/publish/browser
   riêng; final quality và collider QA đánh giá riêng.

## Data contract

AUD-16.S1 chốt quality_tier/preset version và preview/final lineage record dựa
JobProcessingConfig/preview artifacts hiện có. Không dùng field “preview” cũ
để suy quality tier mà không inspect semantics; old flows giữ behavior tương thích.
Preview/final refs không share mutable URI hoặc overwrite input/config/artifacts.

## Alternatives Considered

1. Hạ iterations tự động khi máy chậm: vi phạm selected config; không chọn.
2. Thêm training knob khác: knob hiện có, reuse preset thay duplication.
3. Mark preview như final candidate: không có collision/runtime evidence.

## Consequences

Positive: inspect sớm, timing trung thực, final identity không lẫn preview.
Tradeoffs: checkpoint/cache qualification và API/UI status/lineage integration.

## Follow-Up

- [AUD-15](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-15-worker-latency.md).
- [AUD-16](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-16-fast-preview.md).
