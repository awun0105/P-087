# 0023 Client video normalization trước upload và geometry/time provenance

Date: 2026-10-07

## Status

Proposed — owner đã chọn nén trước upload, default720p/options1080p/720p/480p,
portrait/landscape. AUD-23.S1 hiện có versioned Python/TypeScript contracts,
checksum-bound profile và synthetic contract fixtures. S3 đã nối server verification
và frame/camera consumers. ADR vẫn Proposed: browser support, bitrate quality, real
upload saving và paired sensor/reconstruction behavior chưa được qualified; không
đánh dấu Accepted từ local tests.

## Context

Current upload giữ received bytes, chưa compression. Reconstruction sample3/6FPS
khác encoded media FPS. Không có fixed16:9 input gate trong paths đã đọc; quality
probe resize640×360 chỉ là measurement. Portrait/rotation thiếu dedicated proof.
LiDAR camera_priors map original frame_id to trajectory row; FPS reduction cần
mapping. Client encode sẽ mất backend access tới raw original nếu nó không uploaded.

## Decision đề xuất

1. Preset choice trước upload; client compress bằng capability-checked Worker,
   finalized media mới upload. Default720p, options1080p/720p/480p. Profile v1
   là `real2sim_client_video` với checksum
   `sha256:b09fdfdea2c66d347387fcf3a21df107cb12e5a163fcc367a9bd53ec9e5a6ca7`.
   Maximum long/short edge lần lượt là1920/1080,1280/720,854/480; bitrate
   8/4/2Mbps là **candidate khởi đầu**, chưa đo/qualify. Actual digest/bytes là
   resume identity. Server compression không thay requested bandwidth goal.
2. Preserve display aspect và orientation; portrait9:16, landscape16:9, square/4:3
   fit orientation-independent bounds. No crop/stretch/padding/upscale; even
   rounding và actual SAR/rotation/pixel transform recorded. Không bắt buộc
   landscape để simplify UI. Pixel matrix maps source coded pixels to encoded
   output pixels, applying source display rotation and sample-aspect correction
   once. Intrinsics/extrinsics must use that same pixel/camera convention.
3. Candidate maximum30FPS, native low FPS giữ nguyên; không force exact CFR,
   duplicate/interpolate hoặc change playback speed. Use source presentation
   timeline, mapping each output presentation frame to original frame ID/PTS;
   reconstruction sampling independent. Changing FPS requires sensor remap.
   JSONL sidecar is separately checksummed and capped at32MiB in profile v1.
4. Prefer WebCodecs + bounded demux/mux with license/version review. Codecs not
   universally supported; actual isConfigSupported and resource budgets mandatory.
   No whole large video/decoded frame collection in RAM. WASM only qualified
   bounded fallback. Do not silently upload original or select smaller preset.
5. Preparation manifest binds actual upload + profile, timeline/pixel/color/audio
   transforms. Python and TypeScript share profile/capability/manifest fixtures;
   client manifest checksum uses sorted-key canonical JSON with finite-float matrix
   values. Server independently verifies actual received metadata/checksums; client-local
   source hash is declared provenance, cannot become server source-byte proof.
   Store received compressed file immutable; raw original stays user's device.
6. Preserve all compatible audio tracks through mux. Unsupported audio needs remediation or
   explicit user selection to omit; không strip/trim ngầm. v1 preserves SDR color
   metadata and rejects HDR. Camera calibration/projection
   uses updated image/camera frame
   conventions, not just scaled focal values after rotation. Sensor data insufficient
   blocks paired mode with remediation; original uncompressed path remains available.
7. Encode cancellation/backpressure cleanup, content-bound multipart resume và
   stale local cache/re-encode handled explicitly. Different encoding bytes require
   new upload session. Config/profile participates preview/cache/quality identities.
8. Qualify byte savings and reconstruction tradeoff per preset/browser/input.
  720p default is convenience, not universal accuracy/speed claim.480p cannot be
  forced when user chose1080p, and uploaded720p cannot recover lost detail later.

### Supported input and capability envelope

S1 defines a per-input capability result. A preparation is supported only when the
page is a secure context, Worker/decoder/AVC encoder/MP4 muxer are available, video
metadata is understood, storage is known and sufficient, HDR policy is satisfied,
and audio is preservable or explicitly omitted. Landscape and portrait are both
valid; aspect ratios are fit into the selected long/short edge bounds without
upscaling. Source codec support depends on the detected browser decoder, so this ADR
does not claim universal MOV/HEVC support. HDR is not normalized in profile v1.
Unsupported audio or metadata must produce an explicit remediation state. A user
may choose to upload original bytes only through an explicit path; no hidden raw
fallback is allowed.

AUD-23.S2 now implements a Worker-local conversion using `mediabunny@1.61.3`
(MPL-2.0), `@noble/hashes@2.4.0` (MIT), OPFS-backed streams and output re-decode
for PTS/frame-map checks. It caps presentation sampling at 30 FPS without frame
duplication, preserves compatible audio or requires explicit omission, and fails
closed on unsupported browser/media/storage conditions. The dependency versions
are pinned in `frontend/package.json` and `frontend/package-lock.json`. This is
implementation evidence, not browser qualification. Profile/contract and
orchestration tests do not establish real WebCodecs availability, playable output,
measured memory bounds, actual bandwidth savings, calibration projection, LiDAR
pose association or reconstruction quality.

AUD-23.S3 adds separate pending-manifest and server-verification endpoints, checks
received MP4 bytes and decoded output PTS with ffprobe, publishes the bounded map, and
propagates source frame IDs through frame extraction, preview, metric proposal and
finalization. Camera intrinsics/extrinsics now follow supported resize, SAR and
right-angle rotation transforms; unsupported transforms fail closed. Product quality
measurement uses a new aspect-preserving v2 profile while retaining v1 compatibility.
These results are local-code and synthetic/FFmpeg-fixture evidence. The local original
and its source-frame association remain client-declared. S4 upload/resume integration
and S5 browser, bandwidth, held-out quality and paired-sensor acceptance remain open.
Keep this ADR **Proposed** until those gates pass.

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
- [Mediabunny writing files](https://mediabunny.dev/guide/writing-media-files) —
  stream targets and backpressure; target-browser behavior still needs qualification.
- [Mediabunny codec support](https://mediabunny.dev/guide/supported-formats-and-codecs) —
  runtime codec availability varies by browser and platform.
- [W3C WebCodecs](https://www.w3.org/TR/webcodecs/) — codec support/config/resource contracts.
- [Chrome WebCodecs guide](https://developer.chrome.com/docs/web-platform/best-practices/webcodecs) — capability detection, queueing và explicit resource release.
- [FFmpeg rotation](https://ffmpeg.org/ffmpeg.html#Video-Options) và
  [scale/FPS filters](https://ffmpeg.org/ffmpeg-filters.html) — preserve aspect/rotation;
  FPS filter can duplicate/drop, so exact timeline mapping needs separate evidence.
- [ffmpeg.wasm performance](https://ffmpegwasm.netlify.app/docs/performance/) — historical
  comparison, not this project's browser/device benchmark.
