# AUD-23 — Nén video trước upload, presets và hỗ trợ video dọc/ngang

## Metadata và goal

- PLANNED; P1; EX-PRODUCT browser/upload/config; EX-REC frames/camera consumers.
- Canonical REC-02/03/04/08/09, PRODUCT-02/04/08/09; task-local extension.
- Owner yêu cầu 07/10/2026: default 720p, chọn 1080p/720p/480p và **nén trước
  upload để giảm băng thông**. FPS cap 30 và preserve aspect là hướng đề xuất;
  không giả owner đã yêu cầu exact CFR hoặc bắt buộc landscape.
- Goal: local encode → preview actual result → upload compressed bytes → reconstruct;
  có source-time/pixel mapping cho calibration/LiDAR, recovery và measured quality.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0023](../../../../decisions/0023-client-video-normalization.md).

## Baseline và scope

CodeGraph current source: VideoUploadService.finish giữ checksum/bytes đã nhận;
upload_video stream body không resize. Frontend directUpload.ts chia File thành
parts, resume key theo name/size/lastModified; chưa có compression stage hoặc
content-bound resume. VideoSetupStep dùng processing config sau upload.
PrepareInputRequest.sample_fps default3, max_frames default300. Product presets
minimum_quality sample3, maximum6; đây là reconstruction frame sampling, khác
FPS encoded video. FFmpegFrameDecoder.decode chọn source frame IDs, passthrough
PTS; không có resize filter hay aspect-ratio restriction trong đường đã đọc.
FFmpegRGBProbe.video_info chỉ lấy count/width/height, chưa phân biệt coded/display
size, SAR hoặc display rotation. Quality measurement resize640×360 dùng cho probe,
không là input format 16:9 hay normalized reconstruction resolution. Probe này có
thể distort video dọc; cần qualify measurement profile theo orientation.

camera_priors ghép trajectory bằng frame_id gốc, không timestamp interpolation.
Nén giảm FPS rồi reset IDs sẽ gán sai LiDAR poses. FrameSetResolver verify checksum;
không bypass immutable frame identity để đưa bản nén vào COLMAP. Source review
không chứng minh video dọc/rotation/LiDAR đã chạy E2E.

Owned: frontend upload/normalizer worker/typed media models; Studio upload/create
request, server ingest/probe, processing/config identity, REC frame/camera adapters;
focused tests. Không thay reconstruction model hoặc implement generic video editor.
Server giữ **bản đã upload** bất biến. File gốc trước nén vẫn ở máy user; không
claim backend đã lưu source gốc nếu chỉ compressed file được gửi. Re-run higher
quality cần reselect original; upscaling compressed720p không tạo lại1080p detail.

## Input / output / data contract

Input: local File, selected resolution preset, cancellation token; optional sensor
package binding. Config resolve theo versioned profile: default720p, options1080p/
720p/480p; proposed max_fps30. Encoding settings được qualify/freeze S1/S5, không
silently giảm resolution hoặc tăng compression khi máy yếu/network chậm.

Resolution là oriented **bounding box**, không forced ratio. After rotation/SAR:
1080p landscape≤1920×1080, portrait≤1080×1920; 720p≤1280×720 hoặc720×1280;
480p≤854×480 hoặc480×854. 4:3/1:1/ultrawide giữ display aspect khi fit box.
Never upscale; account even-dimension rounding, record exact output dimensions và
actual scale. Không crop/stretch/letterbox để ép16:9. Portrait thường9:16;
landscape16:9. Physical orientation bake một lần, output rotation identity/SAR1
khi supported transform đã được thực hiện; server không autorotate lần hai.

Proposed temporal policy: retain24/25/29.97FPS hoặc thấp hơn, downselect>30 từ
presentation timeline với documented tolerance; không duplicate/interpolate để
force30. Encoder framerate hint không tự sample. Preserve duration/media time,
không speed-up, frame IDs không tính bằng index/30. VFR/B-frame/edit-list và
nonzero start cần exact rational or integer time mapping, không chỉ avg_frame_rate.
Reconstruction sample_fps/max_frames vẫn independent, dùng actual timestamps.

Output: actual compressed File/blob/container + proposed ClientVideoPreparation
manifest; capability/failure/cancel state; verified server media projection.
State: selected → probing → encoding → local_ready → uploading → verifying → ready;
failed/cancelled giữ user input/config, không tự upload raw original.
Manifest binds profile/implementation version, exact uploaded SHA256/size, original
client fingerprint/metadata, output codec/dimensions/SAR/rotation/duration,
source_time_base/start offset, mapping output presentation frame → original frame
ID/source PTS, pixel transform A và color/audio policy. Large mapping dùng bounded
checksummed sidecar, không unlimited JSON body. Server validates schema/counts,
bounds/monotonicity/actual output PTS and transform metadata. Original local hash
là client-declared provenance, không server-verified source byte evidence.

InputManifest/file checksum source-of-record là actual bytes uploaded. Client
metadata không được forge quality/privacy/calibration PASS. Add compatible
preparation ref/version in job/frame artifacts; original client IDs khác uploaded
video indices. REC extraction records preserve both via explicit mapping/schema;
quality masks theo uploaded frames không áp lên original trajectory trực tiếp.
Legacy uncompressed video có identity mapping, optional fields không rewrite old
payload/checksum. Maps missing/inconsistent: RGB-only workflow vẫn có normal
validation; paired sensor path báo blocked/remediation, không silently map byindex.

Projection invariant: p_out ~ A p_source. Provided camera K/distortion/extrinsic
phải đúng declared pixel/camera convention; scaling cập nhật intrinsics, rotation/
mirror cần pixel transform và camera-axis convention consistent. Không chỉ đổi fx/fy
với90° rồi giữ toàn bộ camera pose. Factor into consumer-supported intrinsics/camera
basis hoặc keep explicit projection adapter; unsupported sensor transform báo lỗi
rõ. COLMAP tự estimate K trên normalized images không loại nghĩa vụ transform
provided calibration cho overlay/priors. Preview2D transform không xoay geometry world.

## Logic change và dependent updates

Risk: **Rất cao** khi chỉ sửa một phần. Logic delta: Client video encode thay uploaded input/time/pixels.
Cần sửa đồng bộ: local demux/encoder/mux + cleanup, content-bound direct/proxy resume, UploadRecord/InputManifest/config/frame set, camera_priors/metric/finalize/overlay, cache/privacy/preview và viewer.
Acceptance xuyên consumer: 60→30 mapping source poses đúng; resize/rotation projection đúng; actual uploaded digest/duration match, original local không giả server source proof.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập. S2 dùng S1, S3 dùng S1 media/timeline fixtures và AUD-21.S1 guards;
backend compatibility có thể triển khai trước frontend integration. S4 dùng S2/S3
và current direct/proxy uploads; AUD-21.S3 khi rollout Guest. S5 dùng AUD-15.S1
measurement protocol, current REC/COLMAP/Brush consumers; không đợi full AUD-15.
AUD-13 sensor QA dùng mapping S1/S3, không đợi whole epic để freeze profile.
AUD-15/16 cache/preparation keys và AUD-18 sanitization identity cần include S1
normalization identity; không reuse outputs khác resolution/time/pixel transform.
AUD-24 grouped upload/resolver consumes media preparation contract: nén chỉ RGB,
metadata/LiDAR bytes giữ nguyên; resolution bind exact prepared source PTS/pixel map.
AUD-23 có thể implement/upload độc lập trước one-dropzone rollout, không cycle.

## Sprint AUD-23.S1 — Media policy, capability và preparation contract

**Input:** current upload/job/frame schemas, landscape/portrait/VFR/sensor fixtures.
**Output:** versioned preset/profile, preparation/timeline/pixel DTO và supported-input matrix.
**Contract:** user chọn trước upload; upload compressed bytes, local original khác server source;
proposed30FPS cap không exact CFR, aspect preserve và no upscaling.

Implement: chốt enum/default/config checksum, bitrates/quality tuning protocol,
HDR/color và audio policy. Giữ audio có sẵn qua compatible mux; audio codec không
hỗ trợ phải báo remediation hoặc cho user chọn bỏ audio, không strip ngầm. Không
trim/change video time để fit audio. Primary candidate WebCodecs in DedicatedWorker
với container demux/mux dependency nhỏ, reviewed license/pinned version. Feature
check actual decoder/encoder config, secure context, rotation/coded/display/SAR và
storage budget. WebCodecs không cung cấp cả container pipeline. WASM fallback chỉ
khi measured safe file/memory budget; không require full huge file in JS/WASM RAM.
Unsupported case cho explicit local compression instructions hoặc user-selected
original upload; không tự đổi sang server compression hay raw upload. Scope keys
và local storage theo account; shared browser không leak output của user trước.
Tests: presets/default, low-resolution no upscale, aspect formulas, rotation180/90/
270/mirror, non-square pixels, untrusted fields, legacy checksums, codec unsupported,
policy identities, color/audio and size limits.
**Exit:** [ ] producer/consumer agree schema, policy và browser support envelope;
[ ] source retention/quality/reset semantics rõ trong UI contract.

## Sprint AUD-23.S2 — Bounded local decode, resize, downselect, encode và mux

**Input:** local File + supported S1 capability/profile, cancel signal.
**Output:** complete compressed media, verified local metadata và exact preparation sidecar.
**Contract:** transformation offline theo media timeline; backpressure không drop frame ngẫu nhiên;
source file giữ nguyên, frame/pixel mapping khớp actual encoded output.

Implement: streaming/chunked demux → decode order → presentation timeline → selected
frames → orientation/SAR-aware scale → encode → mux. Validate frame duration,
keyframes/decoder config and B-frame PTS/DTS; preserve duration within declared
one-frame/timebase tolerance. No realtime canvas playback/MediaRecorder shortcut
để giả exact mapping. Throttle decoder/encoder queues, close VideoFrames/bitmaps,
terminate worker/revoke URLs on cancel/unmount, flush/mux trước local_ready. Output
H.264 MP4 là proposed supported target, codec must isConfigSupported, không assume
mọi browser decode HEVC/MOV. Incremental hash + bounded disk/OPFS cache where
supported; cap duration/pixels/file memory with actionable failure. Do not collect
all decoded frames or multi-GB arrayBuffer. Pixel transform/color conversion logged;
HDR cần qualified tone mapping hoặc explicit unsupported, không washed-out silent output.
Tests: real codec fixtures CFR24/25/29.97/60, VFR gaps, B-frame order/nonzero PTS,
rotation-coded1920×1080 display1080×1920, square/4:3, already-small video, input
immutable, bounded queues, cancellation and decode/encode/mux failure.
**Exit:** [ ] playable bytes + exact mapped frames/PTS; [ ] measured memory stays in
supported budget; [ ] errors/cancel never trigger upload automatically.

## Sprint AUD-23.S3 — Server verification và reconstruction/sensor consumers

**Input:** S1 prepared upload fixture/manifest + actual bytes and optional LiDAR package.
**Output:** verified upload metadata, compatible REC frame/camera adapters và config identity.
**Contract:** server independently verifies received file; original local provenance remains
unverified; downsampling không đổi trajectory association hoặc calibration projection.

Implement: integrate typed preparation at upload completion/create-job without
trusted client PASS. Persist verified metadata/report via appropriate worker/deps,
không expensive transcode in API request. Reject metadata/digest/timeline mismatch,
unknown transform on paired path; preserve uncompressed legacy. Map sampled uploaded
frame to original source index/PTS trước camera_priors; synthetic temporal pose
interpolation outside scope. Bind pixel transforms/intrinsics/axis convention through
COLMAP/overlay/adapters; verify geometry/floor/metric code consumes right images.
Aspect-aware quality measurement profile replaces portrait stretch only with new
version/checksum and qualified motion thresholds. Cache/config/retry/preview keys
bind exact uploaded content + profile/maps; source change invalidates old proof.
Tests: compressed60→30 selects original pose rows0/2/4 correctly, VFR mapping,
missing/forged/nonmonotonic map, known3D projection across resize/rotation/SAR,
legacy InputManifest/FrameSetResolver equality, privacy gate/owner checks, cross-job
refs, quality-profile identity, config/source mismatch and restart of prepare stage.
**Exit:** [ ] source→frame→pose/projection consumer consistency proved;
[ ] old RGB/sensor path works; [ ] no claim server verified local-original bytes.

## Sprint AUD-23.S4 — Upload UI, content-bound resume và recovery

**Input:** S2 local encoder + S3 verified backend contract; direct/proxy upload fixtures.
**Output:** resolution picker default720p, compression progress/preview and resumable upload.
**Contract:** resume same compressed bytes only; re-encode may differ on same source/profile;
no hidden raw fallback/config downgrade; user still can cancel.

Implement: put preset choice before first upload; show original/output dimensions,
orientation, proposed≤30FPS, actual size/saving and selected audio policy. Preview object-fit
contain, keyboard/focus/loading/errors; phase labels compression/upload/verification.
Reuse direct/proxy uploader on finalized result; bind saved session to account,
actual output digest/size + preparation identity, replacing filename-only reuse
for this flow. Preserve completed local file for retry; OPFS eviction/reload must
reselect or re-encode then start new session if digest differs. Do not append newly
encoded bytes to existing multipart parts; no assumption deterministic hardware
encoding. Same-source already within preset may use actual unchanged bytes with
identity/noop manifest when normalization unnecessary. If re-encode produces bigger
file, show measured result and explicit choice; no promised universal saving or
silent lower bitrate. Guest encoding/upload không consume job run; accepted job
still goes through AUD-21/22 backend guards/quota.
Tests: full/reloaded/resumed uploads, same filename/size different bytes, account
switch, changed preset, storage denied/eviction, network retry, cap/unsupported codec,
slow mobile encoding, cancel during each phase, output larger and original-upload
explicit fallback. Existing direct/proxy routes and source selection regression.
**Exit:** [ ] browser uploads chosen finalized bytes and preserves consistent resume;
[ ] orientation/preset/progress/errors usable and permission boundaries unchanged.

## Sprint AUD-23.S5 — Measured bandwidth, quality và browser acceptance

**Input:** frozen profiles/browser matrix, varied actual captures and S2–S4 integrated flow.
**Output:** qualified supported envelope, benchmark receipts và complete handoff.
**Contract:** reducing bytes không chứng minh equal reconstruction accuracy; fixture
codecs không thay real browser/GPU/consumer acceptance.

Implement: measure original/output bytes, encode time, actual upload bytes/time,
client memory, server prep time, selected frames/registration counts and reconstruction
quality for1080/720/480 on same captures. Include portrait rotated phone, landscape,
low texture/fast camera, input below preset, high bitrate60FPS and VFR; freeze tuning
then evaluate held-out set. Compare image/pose/coverage where independent reference
exists, report uncertainty/quality loss;480p is user tradeoff, no guaranteed threshold.
Real browser console/network verify original not uploaded on compression path,
exact multipart digest and cleanup. Paired LiDAR projection/time test and actual
COLMAP/Brush consumer run required; feature support missing hardware stays pending.
Tests: independent held-out/frame sampling/projection cases; real browser memory,
restart, unsupported capability remediation and pixel/timing identity across consumers.
**Exit:** [ ] byte saving and latency measured by preset/condition; [ ] supported
portrait/landscape RGB flow evidenced; [ ] paired sensor path mapping verified;
[ ] unsupported cases and retained-source semantics documented without fake PASS.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_contracts/test_input_manifest.py tests/test_orchestration/test_upload_input_kinds.py tests/test_orchestration/test_direct_upload.py tests/test_orchestration/test_processing_config.py tests/test_reconstruction/test_rec02_quality.py tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_reconstruction/test_rec_prepare_input.py tests/test_reconstruction/test_lidar_world_alignment.py tests/test_reconstruction/test_lidar_overlay.py tests/integration/test_upload_to_prepared_job.py -q
```

In frontend/ run existing focused suites:

```bash
npm test -- tests/direct-upload.test.ts tests/upload-route.test.ts tests/studio-input-flows.test.tsx tests/ux-processing-form.test.tsx
```

Planned frontend/tests/video-normalization.test.ts, real-browser codec fixtures and
backend normalization/mapping tests; create first rồi add focused command. Ruff,
frontend lint/typecheck/build and DevTools gate apply implementation. Mock WebCodecs
only proves orchestration; do not label browser encoding or real bandwidth acceptance.

## Result / Evidence

Pending — source/output hashes and byte counts, profile/codec/browser versions,
metadata/PTS/frame-map/pixel transforms, original retained local vs uploaded source,
client peak memory, phase timings, real upload traffic, pose/projection/quality
consumer proof, recovery and support limitations. Task creation is docs-only.
