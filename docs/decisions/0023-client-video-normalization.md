# 0023 Client video normalization trước upload và geometry/time provenance

Date: 2026-10-07

## Status

Proposed — owner chọn nén trước upload, default720p/options1080p/720p/480p.
FPS cap30, codec/runtime/quality settings và schema là đề xuất cần chốt S1/qualifyS5;
chưa implement hoặc chứng minh acceptance.

## Context

Current upload giữ received bytes, chưa compression. Reconstruction sample3/6FPS
khác encoded media FPS. Không có fixed16:9 input gate trong paths đã đọc; quality
probe resize640×360 chỉ là measurement. Portrait/rotation thiếu dedicated proof.
LiDAR camera_priors map original frame_id to trajectory row; FPS reduction cần
mapping. Client encode sẽ mất backend access tới raw original nếu nó không uploaded.

## Decision đề xuất

1. Preset choice trước upload; client compress bằng capability-checked Worker,
   finalized media mới upload. Default720p, options1080p/720p/480p. Actual digest/
   bytes là resume identity. Server compression không thay requested bandwidth goal.
2. Preserve display aspect và orientation; portrait9:16, landscape16:9, square/4:3
   fit oriented bounds. No crop/stretch/padding/upscale; even rounding và actual
   SAR/rotation/pixel transform recorded. Không bắt buộc landscape để simplify UI.
3. Max30FPS, native low FPS giữ nguyên; không force exact CFR, duplicate/interpolate
   hoặc change playback speed. Use source presentation timeline, mapping to source
   IDs/PTS; reconstruction sampling independent. Changing FPS requires sensor remap.
4. Prefer WebCodecs + bounded demux/mux with license/version review. Codecs not
   universally supported; actual isConfigSupported and resource budgets mandatory.
   No whole large video/decoded frame collection in RAM. WASM only qualified
   bounded fallback. Do not silently upload original or select smaller preset.
5. Preparation manifest binds actual upload + profile, timeline/pixel/color/audio
   transforms. Server verifies actual received metadata/checksums; client-local
   source hash is declared provenance, cannot become server source-byte proof.
   Store received compressed file immutable; raw original stays user's device.
6. Preserve compatible audio through mux. Unsupported audio needs remediation or
   explicit user selection to omit; không strip/trim ngầm. Camera calibration/projection
   uses updated image/camera frame
   conventions, not just scaled focal values after rotation. Sensor data insufficient
   blocks paired mode with remediation; original uncompressed path remains available.
7. Encode cancellation/backpressure cleanup, content-bound multipart resume và
   stale local cache/re-encode handled explicitly. Different encoding bytes require
   new upload session. Config/profile participates preview/cache/quality identities.
8. Qualify byte savings and reconstruction tradeoff per preset/browser/input.
  720p default is convenience, not universal accuracy/speed claim.480p cannot be
   forced when user chose1080p, and uploaded720p cannot recover lost detail later.

## Alternatives Considered

- Server-only normalization: reduces downstream cost, no first-upload bandwidth saving.
- Force all videos1280×720: distorts/crops portrait and calibration image coordinates.
- Always60FPS: more candidate frames/encoding work without demonstrated product benefit.
- Force30CFR without mapping: creates duplicate/drop semantics and wrong pose indices.
- Raw-video auto fallback: contradicts selected local compression and hides costs.
- Universal ffmpeg.wasm default: runtime/memory overhead needs device qualification.

## Consequences

Need bounded local storage/codec lifecycle, metadata/sidecar verification and sensor
adapter migration. Low-capability browsers get explicit remediation or selected raw
upload path. Higher-quality reruns may require original file re-selection. No claim
all phones/browsers support every codec or bandwidth always falls by a fixed factor.

## Follow-Up

- [AUD-23](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-23-client-video-normalization.md).
- [W3C WebCodecs](https://www.w3.org/TR/webcodecs/) — codec support/config/resource contracts.
- [Chrome WebCodecs guide](https://developer.chrome.com/docs/web-platform/best-practices/webcodecs) — capability detection, queueing và explicit resource release.
- [FFmpeg rotation](https://ffmpeg.org/ffmpeg.html#Video-Options) và
  [scale/FPS filters](https://ffmpeg.org/ffmpeg-filters.html) — preserve aspect/rotation;
  FPS filter can duplicate/drop, so exact timeline mapping needs separate evidence.
- [ffmpeg.wasm performance](https://ffmpegwasm.netlify.app/docs/performance/) — historical
  comparison, not this project's browser/device benchmark.
