# AUD-23 — Nén video trước upload, presets và hỗ trợ video dọc/ngang

## Metadata và goal

- IN PROGRESS; P1; EX-PRODUCT browser/upload/config; EX-REC frames/camera consumers.
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

S1 profile expresses dimensions as orientation-independent `max_long_edge_px` /
`max_short_edge_px`; 1080p is1920/1080, 720p1280/720, 480p854/480. Initial
target bitrates8/4/2Mbps are tuning candidates only, not quality or size guarantees.
The pixel transform maps source coded pixels into output encoded pixels, applying
rotation and sample-aspect correction exactly once. The frame-map sidecar is JSONL,
SHA256-bound and limited to32MiB. Client source fingerprint remains untrusted; the
received prepared media checksum is the server-verifiable source identity.

Capability result includes secure-context, Worker, decoder, AVC encoder, MP4 muxer,
metadata, HDR, audio-policy and storage checks. It is input-specific and fails
closed when storage is unknown or required media operations are unavailable. V1
keeps all compatible audio tracks, requires explicit omission for incompatible
audio, preserves SDR color tags and rejects HDR. S1 only defines this envelope;
real browser codec support is qualified in S5.

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

Implement: chốt enum/default/config checksum, candidate bitrate/quality tuning protocol,
HDR/color và audio policy. Giữ tất cả audio track qua compatible mux; audio codec không
hỗ trợ phải báo remediation hoặc cho user chọn bỏ audio, không strip ngầm. Không
trim/change video time để fit audio. Primary candidate WebCodecs in DedicatedWorker
với container demux/mux dependency nhỏ, reviewed license/pinned version. Feature
check actual decoder/encoder config, secure context, rotation/coded/display/SAR và
storage budget. WebCodecs không cung cấp cả container pipeline. WASM fallback chỉ
khi measured safe file/memory budget; không require full huge file in JS/WASM RAM.
Unsupported case cho explicit local compression instructions hoặc user-selected
original upload; không tự đổi sang server compression hay raw upload. Scope keys
và local storage theo account; shared browser không leak output của user trước.
Tests: presets/default, landscape/portrait and4:3 dimension formulas, low-resolution
no-upscale, rotated-source metadata/pixel matrix, non-square output rejection,
untrusted capability fields, legacy InputManifest checksum, unsupported capability,
policy identity, HDR/audio behavior and bounded frame-map cases.
**Exit:** [x] shared Python/TypeScript schema, policy and capability blockers agree
through the same fixture; actual browser support remains S5 qualification.
[x] source-local versus uploaded-source identity, preset reset and quality-loss
semantics are recorded for the S4 UI.

### S1 supported-input matrix

| Input condition | S1 contract outcome |
|---|---|
| Landscape or portrait, SDR, supported decoder/metadata, enough storage | Supported when Worker, AVC encoder, MP4 muxer and the selected preset are available; fit long/short edge, no upscale. |
| 4:3, square, ultrawide, non-square source pixels or rotation metadata | Supported when metadata is understood; display transform records coded-pixel to output-pixel rotation/SAR/scale. Do not force16:9. |
| Native rate at or below30FPS | Preserve source presentation frames/timestamps. |
| Source rate above30FPS | Candidate policy selects source presentation frames without duplication; output→source frame/PTS sidecar is required. |
| HDR transfer function | Block under profile v1; no silent tone-map or SDR relabel. |
| Compatible audio tracks | Preserve every source track. |
| Unsupported audio | Block until explicit user omission; never strip tracks silently. |
| Unsupported decoder/metadata, missing secure context/Worker/muxer, unknown or low storage | Return explicit capability blocker; no implicit raw upload or smaller preset. |

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

Planned real-browser codec fixtures and backend normalization/mapping integration
tests; create before adding their focused commands. Ruff,
frontend lint/typecheck/build and DevTools gate apply implementation. Mock WebCodecs
only proves orchestration; do not label browser encoding or real bandwidth acceptance.

## Result / Evidence

AUD-23.S1–S3 local implementation is recorded below. Upload UI/resume and
real-browser, bandwidth, reconstruction-quality and paired-sensor acceptance
remain for S4–S5. Local tests do not prove that a target browser can encode or
play a real capture.

### S1 changes and verification

- Added the versioned Python/TypeScript profile, media metadata, capability,
  preparation manifest, pixel transform and checksummed frame-map contracts; both
  languages load [the same fixture](../../../../../../fixtures/contracts/video_preparation_v1.json).
- Added `fitVideoDimensions` for orientation-independent, even-dimension bounds,
  without crop or upscale. The supported input contract accepts portrait and
  landscape; actual decode/encode is not implemented in S1.
- Capability blockers now explicitly cover secure context, Worker, decoder,
  encoder, muxer, storage, metadata, HDR and the audio decision. The manifest binds
  to the candidate profile, limits sidecar size, requires square-pixel/orientation-
  baked AVC output, preserves SDR tags and all audio tracks or validates explicit
  user omission.
- Preserved legacy logical checksums when an older `InputManifest` omits optional
  `preparation_provenance`; non-null current provenance is unchanged.
- CodeGraph was run on `VideoNormalizationProfile`,
  `ClientVideoPreparationManifest`, `VideoFrameMapDescriptor`,
  `validate_video_frame_map_rows`, checksum utilities and `InputManifest` callers.
  `InputManifest` has 30 indexed callers (20 listed by the CLI); the source update
  is serializer-only and retains current non-null serialization. Upload, frame
  extraction and camera-pose consumers remain S3 work.
- Tests: shared Python profile/capability/manifest fixture, 60→30 source mapping
  `[0, 2, 4]`, strict PTS/frame-index monotonicity, sidecar bounds, unsupported
  HDR/audio/rotation/upscale cases, Python/TypeScript canonical manifest checksum,
  portrait/landscape/4:3 and low-resolution no-upscale.
- Verification commands and results:
  - `.venv/bin/pytest tests/test_contracts/test_video_preparation.py tests/test_contracts/test_input_manifest.py tests/test_contracts/test_identity.py tests/test_contracts/test_artifacts.py tests/test_api/test_studio_routes.py tests/test_orchestration/test_upload_input_kinds.py tests/test_orchestration/test_direct_upload.py tests/test_orchestration/test_processing_config.py tests/test_reconstruction/test_rec02_quality.py tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_reconstruction/test_rec_prepare_input.py tests/test_reconstruction/test_lidar_world_alignment.py tests/test_reconstruction/test_lidar_overlay.py tests/integration/test_upload_to_prepared_job.py -q` — **148 passed**.
  - `.venv/bin/ruff check src/ tests/` and `.venv/bin/ruff format --check src/ tests/` — pass; **480 files** checked for formatting.
  - `cd frontend && npm run typecheck` — pass; changed-file ESLint — pass; `npm test -- --run tests/video-preparation-contract.test.ts` — **8 passed**; `npm run build -- --webpack` — pass.
- Synthetic contract tests are local evidence only. No browser encoder, actual
  upload savings, GPU reconstruction, LiDAR calibration projection or pose
  association is claimed from this sprint.

### Pre-flight gate report (GUIDE.md Rule 13)

- codegraph: `VideoNormalizationProfile`, `ClientVideoPreparationManifest`,
  `VideoFrameMapDescriptor`, `validate_video_frame_map_rows`, identity helpers,
  `InputManifest` and its indexed callers.
- impact: 30 indexed `InputManifest` callers; omission-only serialization preserves
  historical shape, explicit `null` and non-null provenance retain their identity.
- understand: upload → `InputManifest` → prepare/frame extraction → camera-prior
  consumers; only contract/checksum boundaries changed in S1, frame consumers are
  scheduled for S3.
- minimal-code: reused `ContractModel`, canonical checksum utilities, shared
  contract exports and the current Vitest/Pytest setups; added only the new v1 DTOs,
  dimensions helper, and regression/contract tests.
- checks: backend-related Pytest **148 passed**; full `ruff check src/ tests/` and
  `ruff format --check src/ tests/` pass (480 files); frontend typecheck and changed-
  file ESLint pass; focused Vitest **8 passed**; production Next.js webpack build
  passes and generates all 16 static pages.
- DevTools: n/a — no rendered UI or runtime behavior changed; actual browser media
  capability and encode remain unverified until S5.

### S2 changes and verification

- Added `prepareVideoForUpload` and a dedicated module Worker using pinned
  `mediabunny@1.61.3` (MPL-2.0) plus `@noble/hashes@2.4.0` (MIT) for incremental
  SHA-256. The input is read and hashed incrementally; encoded MP4, temporary
  selection rows and final JSONL frame map are written through OPFS. MP4 output
  uses a backpressure-aware `WritableStream` with a one-chunk high-water mark.
  The original `File` is never modified and this sprint does not call an upload endpoint.
- The conversion callback selects source presentation frames on integer PTS at a
  maximum interval of 30 FPS, drops without duplicating, and records source frame
  index/PTS. It intentionally does not set MediaBunny's `frameRate` option because
  the pinned package's CFR path fills presentation gaps with duplicate frames.
  Output is decoded again in presentation order; its actual PTS is paired with the
  selection sidecar, then written as bounded, checksummed JSONL.
- The Worker verifies one readable AVC video track, output frame count and source
  mapping, monotonic presentation timestamps, source/output duration tolerance,
  baked rotation/SAR and dimensions, SDR color tags, actual output digest/size,
  and every preserved audio track. Unsupported audio requires explicit omission;
  HDR, negative start PTS, multi-video/subtitle/attachment inputs, unsupported
  codec/transform, duration over two hours, decoded area over 12,582,912 pixels,
  unknown/insufficient OPFS quota, and a frame map over 32 MiB fail with typed
  errors. Cancellation terminates the Worker and attempts removal of all temporary
  files. The 64 MiB storage reserve and bitrate estimate are conservative gates,
  not a measured memory or output-size guarantee.
- CodeGraph was run on `prepareVideoForUpload`, the Worker conversion/output
  verification, `PresentationFrameSelector`, and callers. The service has no
  upload or UI consumer yet; only its focused test calls it. `directUpload.ts`,
  server ingest, frame extraction, camera priors and calibration consumers are
  unchanged and remain S3/S4 work.
- Tests cover 24/25/29.97/30 FPS preservation, 60→30 source indices, VFR gaps,
  nonzero PTS, strict order, rotation/SAR/flip pixel matrix, incremental hash,
  safe file name, finalized-file service contract, worker termination and OPFS
  cleanup. They do not exercise a real browser codec or the Worker against a
  playable media fixture.
- Verification commands and results:
  - `cd frontend && npx vitest run tests/video-preparation-contract.test.ts tests/video-normalization-core.test.ts tests/video-normalization-service.test.ts` — **20 passed**.
  - `cd frontend && npm run typecheck` — pass.
  - `cd frontend && npx eslint src/lib/media/video-normalization-core.ts src/lib/media/video-normalization.ts src/lib/media/video-normalization.worker.ts tests/video-normalization-core.test.ts tests/video-normalization-service.test.ts` — pass.
  - `cd frontend && npx esbuild src/lib/media/video-normalization.worker.ts --bundle --format=esm --platform=browser --target=es2022 --alias:@=./src --outfile=/tmp/aud23-s2-video-normalization.worker.js` — pass; generated a **1,251,089-byte** standalone Worker bundle.
  - `cd frontend && npm run build -- --webpack` — **exit 0**, all 16 static pages generated.
  - `cd frontend && npm ci --dry-run --ignore-scripts --no-audit` — **exit 0**;
    npm emitted existing `EBADENGINE` warnings because this checkout runs Node
    24.11.1 while jsdom/css-color dependencies request Node 24.15 or newer.
  - `git diff --check` — pass.
- Browser codec support, real playable bytes, memory bounds, upload savings, paired
  LiDAR projection/pose association, reconstruction quality and full UI lifecycle
  remain **UNVERIFIED** until their later sprint gates. The standalone Worker
  bundle and types pass static checks; the bundle is about 1.2 MiB before
  transfer compression. This is not device qualification or a measured browser
  memory result.

### S2 pre-flight gate report (GUIDE.md Rule 13)

- codegraph: explored `prepareVideoForUpload`, `video-normalization.worker.ts`,
  `Conversion`, `PresentationFrameSelector`, output validation and callers; `codegraph
  sync` reports 775 files, 14,376 nodes and 41,335 edges. The normalizer has no
  product caller; its only indexed caller is the focused service test.
- impact: the normalizer is currently called only by its focused test; upload,
  server and reconstruction consumers are not changed in S2. S3/S4 must bind actual
  uploaded bytes and map identity before using the media output.
- understand: local File → lazy demux/decode → PTS selection → resize/orientation
  and SAR correction → AVC/MP4 → output re-decode and map verification → finalized
  local artifact. Audio is copied only when supported or omitted by explicit choice.
- minimal-code: reused MediaBunny's demux/decode/encode/mux and OPFS streams;
  added a focused PTS selector, bounded temporary map writer, Worker service and
  lifecycle tests. No realtime canvas recorder, whole-file array buffer, or UI
  surface was introduced.
- checks: typecheck, changed-file ESLint, 20 focused Vitest tests, production
  webpack build, standalone Worker bundle and npm lockfile dry-run pass; see exact
  commands above.
- DevTools: n/a — S2 adds no rendered UI or browser upload flow. Real browser media
  behavior and UI acceptance are explicitly pending S5.

### S3 changes and verification

- Added separate upload-manifest and bounded frame-map verification endpoints.
  The client declaration remains pending until the server hashes the received MP4,
  checks its byte count and ffprobe-observed stream metadata, and compares every
  declared output PTS with ffprobe's decoded presentation timestamps. The map is
  capped at 32 MiB, checksum-bound and published as an immutable product artifact.
  Project creation stops while a preparation declaration is pending. Upload API
  responses omit the local-source fingerprint and server verification payload.
- Added server verification provenance to `InputManifest` and
  `NormalizedRGBFrameSet`. Frame extraction rechecks the published map and decoded
  prepared-video PTS, then records each selected prepared frame's original source
  index. Preview, metric proposal and finalization map those indices to the original
  LiDAR trajectory rows; mismatched counts or partial maps fail closed. Legacy RGB
  frame sets without the optional mapping keep their prior serialization and behavior.
- Added `prepared_camera_calibration` for scale, sample-aspect and right-angle
  rotation transforms. It rotates the camera basis with the image, transforms the
  intrinsics and tangential distortion, and rejects reflection, shear, or calibration
  aspect mismatch. Synthetic projection tests cover resize + non-square pixels +
  90-degree rotation; this is not an actual calibrated sensor acceptance run.
- Added `upload_quality_v2.json` with a new profile ID/checksum. Its FFmpeg filter
  fits portrait and landscape into orientation-aware 640/360 long/short-edge bounds,
  preserves aspect and avoids measurement upscaling. The v1 profile and checksum
  remain readable. Existing numeric motion thresholds remain candidate values and
  still require S5 held-out capture qualification.
- Fixed the server's one-tick tolerance in the 30 FPS cap check and added a 60 FPS
  rejection regression. The source map remains client-declared: the server cannot
  prove the original local video bytes or source-frame association without receiving
  that original media.
- CodeGraph was synced after edits and explored `ServerVideoPreparationVerifier`,
  upload routes, `camera_priors`, `prepared_camera_calibration`, frame extraction,
  preview, metric and finalization callers. The pose-prior function has 12 indexed
  callers; legacy callers retain identity mapping while prepared-video consumers pass
  explicit source indices and source frame counts.
- Tests exercise verified map publication, byte/PTS mismatch rejection, the 30 FPS
  cap, public response redaction, selected-frame mapping, 60→30 pose rows and known
  projection under resize/SAR/rotation. Real FFmpeg filter tests cover landscape,
  portrait, 4:3 and below-preset input dimensions.
- Verification commands and results:
  - `.venv/bin/pytest -q tests/test_orchestration/test_video_preparation_verification.py tests/test_contracts/test_video_preparation.py tests/test_contracts/test_input_manifest.py tests/test_orchestration/test_upload_input_kinds.py tests/test_orchestration/test_direct_upload.py tests/test_orchestration/test_project_registry.py tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_reconstruction/test_rec_prepare_input.py tests/test_reconstruction/test_rec03_guided.py tests/test_reconstruction/test_lidar_world_alignment.py tests/integration/test_upload_to_prepared_job.py tests/test_api/test_studio_routes.py tests/test_api/test_guest_ownership.py tests/test_orchestration/test_runtime_migrations.py tests/test_reconstruction/test_rec02_quality.py` — **175 passed, 4 skipped**.
  - `.venv/bin/ruff check src/ tests/` — **All checks passed**.
  - `.venv/bin/ruff format --check src/ tests/` — **482 files already formatted**.
  - `git diff --check` — **pass**.
- No target-browser upload flow, upload-byte savings, hardware media matrix, paired
  RGB/LiDAR capture, COLMAP/Brush reconstruction quality or GPU acceptance was run.
  These remain S4/S5 gates; S3 tests validate local services and synthetic contracts.

### S3 pre-flight gate report (GUIDE.md Rule 13)

- codegraph: synced the changed index; explored the upload verifier/routes, manifest
  and frame-set contracts, `camera_priors`, its callers and product quality profile.
- impact: changed upload API/record, project creation, InputManifest, frame set,
  extraction, preview, metric proposal and finalization. All 12 indexed pose-prior
  callers were reviewed; legacy paths keep default identity mapping.
- understand: upload → server byte/stream verification → InputManifest → privacy and
  quality validation → frame extraction/source map → LiDAR pose/calibration consumers.
- minimal-code: reused existing artifact resolver/publication, canonical checksums,
  ContractModel, ffprobe boundary and frame-set resolver; added the verified report,
  bounded server check and optional source mapping at those boundaries.
- checks: focused Pytest **175 passed, 4 skipped**; full Ruff check passes; format
  check reports **482 files already formatted**; `git diff --check` passes; CodeGraph
  sync reports the index is up to date. Real media/browser/sensor acceptance is not
  established by these local checks.
- DevTools: **UNVERIFIED** — Chrome DevTools MCP could not list pages because the
  existing browser profile is locked; no logged-in page snapshot or console check ran.
