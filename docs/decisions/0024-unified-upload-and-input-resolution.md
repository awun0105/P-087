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
   - Không hạ ngầm: luồng hạng cao hơn còn `needs_input` thì không chạy luồng thấp hơn (hỏi dữ
     kiện còn thiếu). Luồng hạng cao hơn `pending_verification`/`unsupported` thì cho phép hạ,
     kèm cảnh báo `HIGHER_ROUTE_UNAVAILABLE`. Hai luồng ready cùng hạng thì vẫn hỏi.
   - File mà luồng được chọn không dùng thì tự loại và liệt kê (`UNUSED_INPUTS_EXCLUDED`), không
     còn là điều kiện chặn. Lý do chọn ghi vào `diagnostics` (`ROUTE_AUTO_SELECTED`).
   - Cloud đi kèm LiDAR mà chưa có ý định `video_reconstruction` vẫn không bao giờ rơi về R1.
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
