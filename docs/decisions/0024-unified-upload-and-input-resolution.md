# 0024 Unified upload và input assembly resolution

Date: 2026-10-07

## Status

Proposed — owner yêu cầu một khung upload và hệ thống tự nhận diện/chọn luồng từ
tập file. Assembly schema, recipe precedence và runtime qualification chốt trong
AUD-24; requirement mới không nghĩa implementation/geometry đã được verified.

## Context

UploadDropzone chỉ lấy file đầu, yêu cầu kind; video setup chọn optional LiDAR
package riêng. Detector hiện reject raw cloud/loose metadata và chỉ nhận complete
LiDAR ZIP. Việc biết loại từng file chưa đủ để chứng minh tập file thuộc cùng
capture, có units/frame/clock đúng hoặc executable theo một recipe.

Calibration không quyết định cloud registered. Một cloud không cung cấp multi-scan
odometry; TUM timestamps không tự là RGB clock mapping. Map alignment không là
sensor extrinsic calibration. Current source rules không loại các input modes
khả thi khi có qualified adapters và updated producer/consumer contracts.

## Decision đề xuất

1. One multi-file upload surface cho video/cloud/calibration/trajectory/timestamps
   và supported safe ZIP. Server content classification + grouped binding/resolver
   làm authority; user không phải chọn technical mode trước upload.
2. Six supported recipe groups: RGB-only; RGB+registered map; RGB+single static
   cloud; RGB+raw scans+supplied trajectory; RGB+raw scans+estimated trajectory;
   sensor-guided RGB+LiDAR with calibration/trajectory/time binding. Reuse shared
   RGB/fusion/odometry/registration/QA modules; không clone sáu pipelines.
3. Persist revisioned staging assembly và immutable resolution/committed recipe
   bound tới verified file hashes, declarations, normalization, config/tool versions.
   Existing InputManifest adapters giữ old checksums và correct modality semantics.
4. Recommend compatible route dựa dữ liệu/capability; ambiguity/missing facts hỏi
   ngay trong cùng UI. Invalid metadata không bị bỏ ngầm để chọn RGB-only/map route.
   Alternatives chỉ chạy sau user thấy và chọn các exclusions/changed assumptions.
   *(Sửa 2026-10-10 — chọn luồng tự động.)* Người dùng chỉ upload rồi bấm xử lý; resolver tự
   chọn luồng, không bắt chọn thẻ. Quy tắc:
   - Chỉ xếp hạng giữa ứng viên đã `ready`, theo bảng ưu tiên công bố (`_ROUTE_PRECEDENCE`):
     R6 quỹ đạo cấp > R6 ước lượng > R4 > R5 > R2 > R3 > R1. Hạng theo **nguồn gốc ràng buộc
     hình học người dùng đã cấp**, không bao giờ theo khối lượng metadata.
   - Bảng là **chính sách, không phải số đo**: repo chưa có phép đo so sánh các luồng
     (`eval/protocols/lidar_odometry.md` chưa định ngưỡng). Sửa bảng khi có số đo held-out.
   - Không hạ ngầm bỏ bằng chứng: luồng hạng cao hơn còn `needs_input` mà luồng được chọn sẽ
     **loại file** của nó thì không chạy luồng thấp hơn (hỏi dữ kiện còn thiếu). Ngoại lệ: luồng
     được chọn đã dùng đủ file của luồng cao hơn (ví dụ R4 so với R6 chỉ còn thiếu quan hệ đồng
     hồ) thì vẫn chạy kèm `HIGHER_ROUTE_NEEDS_MORE_FACTS`, nói rõ bổ sung gì sẽ nâng cấp được.
     Luồng hạng cao hơn `pending_verification`/`unsupported` (runtime không chạy được, người dùng
     không mở khoá được) thì cho phép hạ, kèm cảnh báo `HIGHER_ROUTE_UNAVAILABLE`. Hai luồng
     ready cùng hạng thì vẫn hỏi.
   - File mà luồng được chọn không dùng thì tự loại và liệt kê (`UNUSED_INPUTS_EXCLUDED`), không
     còn là điều kiện chặn. Lý do chọn ghi vào `diagnostics` (`ROUTE_AUTO_SELECTED`).
   - Cloud đi kèm LiDAR mà chưa có ý định `video_reconstruction` vẫn không bao giờ rơi về R1.

   *(Sửa 2026-10-10 — R4 nhận file rời.)* R4 không còn đòi người dùng đóng ZIP. Khi các file đã
   bind không cùng nằm trong một ZIP do người dùng nộp, server **tự đóng một gói chuẩn** từ chính
   các byte đó (scan đánh số `000000.pcd…` theo thứ tự người dùng đã xác nhận, cộng quỹ đạo,
   calibration, thời điểm frame) rồi cho nó đi qua đúng bộ nhận diện của gói tự nộp, nên toàn bộ
   đường ingest/worker/QA của R4 giữ nguyên. Gói không biến đổi byte nào; mỗi thành viên ghi
   `file_id` và checksum nguồn vào provenance của InputManifest (`package_members`); registry và
   runner kiểm danh sách đó khớp assembly đã niêm phong (checksum nguồn, vai trò, thứ tự scan, tên
   thành viên khớp bộ nhận diện) và runner đối chiếu thêm tên thành viên thật của gói (tải từ kho từ
   xa nếu cần và kiểm checksum; không tìm thấy gói thì lỗi, không bỏ qua). Byte của gói do worker kiểm
   checksum khi đọc. Gói được gắn vào project cùng lúc job được nhận (xoá project xoá luôn gói); nếu
   lần chạy không thành hoặc là replay thì gói bị gỡ ngay cả bản cục bộ lẫn bản trên kho từ xa
   (`discard_unlinked`). Lỗi dọn dẹp chỉ được ghi log, không che lỗi gốc; nếu dọn thất bại thì gói còn
   lại chưa gắn project. Trước khi ghi: kiểm lời khai và tổng dung lượng so với giới hạn một gói. Trong
   lúc ghi: chặn thành viên giải nén vượt kích thước đã niêm phong.
   ZIP người dùng nộp mà bộ nhận diện gói cũ từ chối (bố cục khác, thừa file) nhưng các thành viên
   đã bind đủ thì được đóng lại như file rời thay vì bị từ chối. Điều kiện sớm ở resolver: scan phải là `.pcd` (`SCAN_FORMAT_PCD_REQUIRED`)
   và thời điểm frame phải một dòng mỗi pose (`RGB_FRAME_TIMES_COUNT_MISMATCH`).
   Chưa làm: R5/R6 vẫn đọc scan từ nguồn đã stage (chưa kiểm xem chúng có buộc ZIP hay không).
5. Allow loose/raw files trong assembly staging có validation phù hợp; complete
   legacy input detectors vẫn validate như cũ. Không fake calibration/frame_times
   hoặc identity poses để thỏa schema. Single PCD không tự chứng minh registered map.
6. Source PTS may derive RGB frame times khi clock relation đúng; unknown clock
   offset/units/capture association không tự generate verified values. Sensors QA
   khác map registration QA; geometry qualification remains required after routing.
7. Nén video local theo AUD-23 trước upload; LiDAR/metadata immutable. Resolved
   sensor recipe phải dùng source-time/pixel mapping của actual compressed video.
8. One accepted Run creates one quota intent. Assembly probes/uploads không tính
   lượt; child odometry/fusion/registration reuse admission/lease và same intent.
   Guest ownership/resource checks apply grouped refs và worker commit.
9. Qualified-runtime recipes enable incrementally. Retry uses immutable accepted
   recipe; resources insufficient wait giữ config. Module/runtime unsupported có
   explicit diagnostics, không tự đổi route/provider/quality để làm như success.
10. Gaussian PLY/SOG view import reuse AUD-06 qua same upload UI hoặc existing
    separate import flow. AUD-25 Deferred; không thêm continuation/source adapter.
    SOG content detection distinguishes bundled meta/textures from generic ZIP;
    multiple Gaussian masters require exact source choice, not auto merge. R1–R6
    remain video groups; imported G1–G3 không thuộc active recipes. Demo stays replay.
    Multi-video stitching/multicam và standalone LiDAR-only product không thuộc
    request video reconstruction này.

## Alternatives Considered

- Chỉ thêm multiple vào input: backend còn reject raw/sidecars và create-job binding lệch.
- Một mandatory ZIP sensor package: không đáp ứng loose files/map-without-rig mode.
- Six duplicated pipelines: shared stages/contracts sẽ lệch nhau qua retry/QA.
- Guess units/registration/clock từ filename: không đủ evidence, có thể double-transform cloud.
- Silent RGB-only fallback: user supplied LiDAR/metadata nhưng recipe bỏ chúng không báo.

## Consequences

Need grouped staging, classification/resolution DTO và durable accepted recipe;
cross-cutting changes upload/project/manifest/worker/frontend/auth/quota. Automatic
routing giảm manual mode selection, không phục hồi metadata bất khả xác định.
File formats/input envelopes qualified theo task, không hứa every file usable.

## Follow-Up

- [AUD-24](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-24-unified-upload-and-input-resolution.md).
- [Integration map](../plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md).
- Related proposals: [0023 media preparation](0023-client-video-normalization.md),
  [0018 odometry](0018-opt-in-lidar-odometry.md), [0020 map registration](0020-automatic-rgb-lidar-map-registration.md).
- [0025 imported PLY/SOG continuation — Deferred](0025-imported-3dgs-continuation.md),
  không là active dependency.
