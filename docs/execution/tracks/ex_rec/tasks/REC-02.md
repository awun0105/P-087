# REC-02 — RGB Validation And Privacy Gate

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Validate moving-camera RGB, phát hành PrivacyValidationReport và chặn input không đủ điều kiện trước heavy reconstruction.

## 3. Why This Task Exists

Hiện thực FR-01/02, AC-02 và privacy gate trước public/demo use.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-01 cho TorWIC bring-up; user upload có thể đi trực tiếp qua InputManifest.
- REC-02A tiếp nhận output đã privacy-clear để chạy `ST-FRAME-EXTRACT`; REC-02 không absorb frame extraction.

## 5. Input Contract

- InputManifest, RGB video hoặc normalized frame set.
- Source-rights attestation từ EX-PRODUCT.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Deterministic validation result/error.
- PrivacyValidationReport với PRELIMINARY_SCREENED, VERIFIED_ANONYMIZED hoặc QUARANTINED.
- Validated RGB reference cho REC-02A; REC-03 nhận normalized frame artifact
  do REC-02A publish theo Track Guide §2.5.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`
- `configs/torwic/` cho profile Aisle_CW đã được owner duyệt một phần
- `scripts/torwic/` cho offline quality-report publication của TorWIC
- shared validation contract chỉ khi có producer/consumer review

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` trên FFmpeg decode/probe; không biến sampled screening thành VERIFIED_ANONYMIZED.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

2026-09-24 Codex audit: `docs/PRD.md` FR-01/02, AC-02 yêu cầu decode,
usable frames, motion, blur, registration/coverage estimate, structured
error và stop trước heavy stage. Contract §3.3 yêu cầu `InputManifest` identity
và `PrivacyValidationReport` canonical checksum; `VERIFIED_ANONYMIZED` chỉ
khi toàn bộ selected frames hoặc approved copy được kiểm và QA accept.
`INTEGRATION_PLAYBOOK.md` §2.1/2.2 cùng Track Guide §2.5 đặt extraction ở
REC-02A, nên task-local output handoff được sửa như trên.

External audit: installed FFmpeg/ffprobe `6.1.1-3ubuntu5` (CLI, GPL-enabled
binary); FFmpeg `ffprobe.c` cung cấp stream/frame metadata, `libavfilter/
vf_blurdetect.c::blurdetect_filter_frame` xuất `lavfi.blur` metadata và
`libavfilter/vf_vidstabdetect.c::filter_frame` xuất local motion transforms.
Local CLI xác nhận filters có sẵn. `Nannigalaxy/video-3d-reconstruction-gsplat`
commit `9fae0190345a7080f680d20d1a0c2f45b1354a16`, MIT,
`video_to_gsplat.sh` chỉ làm CLI extraction/cleanup, không phù hợp để
reuse trong REC-02; giữ làm REFERENCE cho REC-02A. Không copy source.
`cv2`, NumPy, Pillow không có trong `.venv`; chọn FFmpeg CLI adapter để tránh
dependency graph mới.

Plan: thêm project-owned `FFmpegProbeAdapter` và `RGBInputValidator` trong
`src/services/reconstruction/rgb/`; nhận resolved refs qua interface rõ,
verify source bytes, full decode và đo motion/blur/coverage; ngưỡng thuộc typed
config bắt buộc, không giả tạo default policy. Privacy gate trả report typed,
chỉ phát `PRELIMINARY_SCREENED` hoặc `QUARANTINED` từ screening; bước QA
approval phải có evidence/authority riêng trước `VERIFIED_ANONYMIZED`.
Tests dùng real tiny video/frame set và negative corrupt/static/privacy;
report canonical checksum phải verify. Product artifact publication và frame
extraction sẽ nối ở REC-02A/REC-11, không import orchestrator internals.

Owner decision 2026-09-24: chỉ khóa Aisle_CW blur score `>8.5` để loại
reconstruction candidate frame **logic**, giữ đủ 1.092 canonical PNG và frozen
REC-01 split. Motion `>1 px`, active ratio `70%`, static run `60` là
diagnostic/warning reference, không hard FAIL. Bỏ minimum 900 generic. Generic
minimum-frame sanity cần calibrate riêng sau bring-up; COLMAP registration và
coverage ở REC-03 là viability gate mạnh hơn. REC-02 quality report phải có
per-frame score/reason, effective reconstruction IDs, sequence diagnostics,
checksums/provenance. Privacy verified vẫn cần QA acceptance thật.

### 9.1. Input-quality proposal, chưa phải config đã khóa

FR-02 phân biệt `camera motion` và `motion blur`. `blurdetect` đo mức blur
của ảnh nói chung; nó không phân loại motion blur. `vidstabdetect` cho vector
chuyển động hình ảnh giữa frame; median `(dx,dy)` là proxy translation, không
chứng minh camera motion, parallax hoặc camera registration. Số frame dùng
được được **đề xuất** tính sau structural/decode validation và quality filtering,
trên tập reconstruction IDs đã khóa; không lấy 109 held-out frame để đạt
minimum. PRD/task chưa định nghĩa rõ thứ tự đếm này, nên cần owner duyệt cùng
threshold trước khi encode policy.

Ngày 2026-09-24, Codex đo toàn bộ 1.092 normalized Aisle_CW PNG theo thứ tự
frame ID (mạnh hơn sample đầu/giữa/cuối), gồm cả đoạn quay nhanh 428–475,
537–545, 1028–1044. Input là `normalized/aisle_cw/rgb_frames/`; không dùng
reconstruction metric hoặc GT. FFmpeg 6.1.1-3ubuntu5, một filter thread:

```bash
ffmpeg -hide_banner -loglevel error -threads 1 -filter_threads 1 -framerate 10 -start_number 0 -i data/torwic_slam/normalized/aisle_cw/rgb_frames/%06d.png -vf 'scale=640:360:flags=bicubic,format=gray,blurdetect,metadata=print:file=/tmp/ex-rec02-blur-all.txt' -f null -
ffmpeg -hide_banner -loglevel error -threads 1 -filter_threads 1 -framerate 10 -start_number 0 -i data/torwic_slam/normalized/aisle_cw/rgb_frames/%06d.png -vf 'scale=640:360:flags=bicubic,format=yuv420p,vidstabdetect=result=/tmp/ex-rec02-motion-all.trf' -f null -
```

`10 fps` chỉ cấp timestamp cho chuỗi PNG khi đo, không ghi đè timestamps.csv.
Per-frame `lavfi.blur` được parse từ metadata; motion score là độ dài Euclid
của median `dx` và median `dy` trên các `LM` vectors mỗi frame. Frame 0
không có transition trước nó. Quantile là linear interpolation trên sorted
observations. Cả hai FFmpeg passes exit 0, cho 1.092 blur records và 1.092
frame records (1.091 frame có prior motion); REC-01 structural checks đã
chấp nhận 1.092 PNG. Đây là frame count **trước** quality filtering.
File phân tích độc lập ở
`eval/results/rec02_aisle_cw_quality_probe.json` lưu đủ 1.092 score, SHA-256
của preparation manifest/split/raw filter outputs, version và preprocessing;
`status=PROPOSAL_NOT_LOCKED`. Chỉ `eval/` giữ analysis output; product runtime
không được auto-load file này.

| Metric | n | min | p5 | p10 | median | p90 | p95 | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Image blur `lavfi.blur`, higher=worse | 1092 | 5.017 | 5.067 | 5.092 | 5.754 | 7.108 | 7.731 | 10.742 |
| Inter-frame visual translation proxy, px at 640×360 | 1091 | 0 | 0 | 0 | 3.162 | 12 | 15.75 | 32.016 |

Train-only blur p95 là 7.762, max 10.742. Held-out blur max 6.770;
đây là check conflict sau khi chọn candidate từ input quality, không phải
lý do sửa split. Với motion proxy `>1 px`, 867/1091 transitions hoạt động
(79.47%). Theo thirds đầu/giữa/cuối, active fractions là
258/363=71.1%, 348/364=95.6%, 261/364=71.7%. Hai đoạn ít chuyển động
liên tục dài 1–53 và 969–1023. Có 47/1091 transitions `>20 px`, trong đó
14 thuộc held-out; chỉ là cảnh báo overlap, không phải rejection rule.
Nếu ghép điều kiện thăm dò `blur > 8.5` và motion proxy `>12 px`, có 21
frame (đều nằm trong 29 blur rejects). Đây chỉ là nhóm **nghi motion blur**,
không phải classifier đã được validate; exposure, vật thể động và rotation
có thể làm hai phép đo khác nhau.

Representative quanh ngưỡng: frame 435 score 8.442 (vẫn thấy blur, sẽ lọt
ngưỡng 8.5), 441 score 9.401, 453 score 10.643 / motion proxy 32.016 px,
454 score 10.742 / 17 px (blur rõ), 470 score 7.725, 541 score 6.592 /
30.504 px, 1030 score 7.242 / 29.517 px, 1078 score 5.100 / 1 px.
Đây là heuristic không hoàn hảo; visual spot check không thay SfM match proof.
Rerun độc lập frame 454 với đúng filter 640×360/grayscale cho 10.741585,
khớp chính xác score trong full pass.

Các candidate chỉ là **đề xuất cho benchmark Aisle_CW**, không phải default
universal core. Mỗi candidate bắt đầu với 1.092 decoded frames, 983 frozen
reconstruction và 109 frozen held-out. `min_usable_reconstruction_frames=900`
được đề xuất như capacity floor trước heavy stage; không khẳng định 900 frame
đủ để COLMAP thành công. Motion gate dùng `>1 px` active fraction và độ dài
maximal low-motion run trong reconstruction sequence; không reject từng frame
vì motion. Số active fraction dưới đây là ước lượng từ pass trên toàn
traversal, bỏ các transition nối từ held-out; production phải đo lại trên
selected reconstruction frames, không feed held-out vào product runtime.

| Candidate | Blur reject (`score >`) | Motion gate proposed | Blur reject train / held-out | Motion reject frame | Usable train / all | Longest added blur gap | Expected overlap risk |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| Lenient | 9.5 | active ≥60%; static run ≤80 | 20 / 0 (1.83% total) | 0 | 963 / 1072 | 14 frames (451–464) | Retains visibly blurred 435–441; registration may suffer. |
| Recommended | 8.5 | active ≥70%; static run ≤60 | 29 / 0 (2.66% total) | 0 | 954 / 1063 | 15 frames (451–465) | Preserves 97.1% train; two ~14–15-frame holes around turn need COLMAP match proof. |
| Strict | 7.75 | active ≥80%; static run ≤40 | 53 / 0 (4.85% total) | 0 | 930 / 1039 | 39 frames (428–466) | Proposed motion gate fails (~77.4% active; max static 53); large turn gap risks loss of overlap. |

Trong candidate recommended, active proxy train ≈741/950=78.0% sau khi
bỏ transition ngay sau held-out; max low-motion run trong train IDs là
53. Cả ba candidate vượt floor 900 nhưng **đây không phải SfM proof**.
Frozen held-out blocks 118–153, 528–564, 937–972 đã tạo gap 36–37 frame;
không được đổi chúng để cải thiện score. Các blur thresholds hiện không loại
held-out nào; nếu gate khác làm held-out invalid, mở conflict riêng theo
Dataset Playbook. Bảng này là lịch sử proposal; quyết định owner ở §9 chỉ
duyệt blur exclusion 8.5 cho Aisle_CW và motion warning thresholds. Floor
900 và motion hard gate **không** được đưa vào implementation.

### 9.2. Implementation checkpoint

`configs/torwic/aisle_cw_rec02_quality_v1.json` lưu profile checksummed đúng
quyết định owner: fixed 640×360, `blur_exclude_gt=8.5`; motion `>1 px`,
active-ratio reference 0.70 và static-run reference 60 chỉ tạo warnings.
Generic core trong `src/services/reconstruction/rgb/` không chứa TorWIC path,
frame count 900 hoặc hard gate cho image-motion proxy. Nó verify source bytes,
size khi InputManifest khai báo, giải mã qua FFmpeg, tạo per-frame quality
decision và effective IDs; selected PNG gốc không bị xóa. Frame-set motion
đo trên effective set và bỏ qua transition bắc qua missing IDs. Video probe
đọc mp4/mov trực tiếp; frame extraction/published frame set vẫn thuộc REC-02A.

`scripts/torwic/rec02_quality.py` là offline dataset adapter: gọi REC-01
canonical validator, chỉ lấy frozen `train_frame_ids`, publish immutable
`derived/aisle_cw/quality_report.json`; quality probe không decode held-out.
Runtime path nhận `InputManifest` qua injected resolver và có publisher qua
`ArtifactRef`/injected artifact store; không import orchestrator internals
trong production EX-REC code. Report bind preparation/InputManifest identity,
selection checksum, profile checksum, FFmpeg version, producer version và
per-frame source checksum. Privacy service phát shared
`PrivacyValidationReport`; `VERIFIED_ANONYMIZED` không thể sinh khi thiếu
QA-verifier được inject, full-frame/approved-copy inspection hoặc có
unresolved findings. Dispatch kiểm tra report, inspection evidence checksum
và QA acceptance cùng input identity; publisher từ chối report `VERIFIED` nếu
không có cùng QA dispatch proof. Production QA verifier/acceptance của
EX-PRODUCT chưa được cung cấp; synthetic verifier trong unit test chỉ chứng
minh logic. TorWIC offline issuance dùng
`scripts/torwic/rec02_privacy_issue.py` để kiểm exact human record và explicit
authorization addendum trước khi publish, không phải EX-PRODUCT dispatcher.

## 10. Tests

- Decode/corrupt/usable-frame/motion feasibility unit tests.
- QUARANTINED và insufficient-motion negative tests.
- Privacy report contract test và small input smoke.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Invalid/corrupt/exact-static input dừng trước unsupported stage với error rõ;
  nonidentical nhưng camera ít di chuyển chỉ cảnh báo theo owner decision.
- [x] REC-02 gate/publisher chặn preliminary, forged và mismatched proof;
  public/demo dispatch thực tế do EX-PRODUCT sở hữu và chưa được receipt bật.
- [x] Report bind đúng input checksum và evidence scope trong code/fixture proof.
- [x] Focused/full tests và local REC-02 boundary handoff proof pass;
  evidence/limitations được ghi.

## 12. Result / Evidence

DONE tại REC-02 boundary sau explicit user review và issuance approval. Real Aisle_CW offline run:

```bash
.venv/bin/python -m scripts.torwic.rec02_quality --dataset-root data/torwic_slam --traversal-id Aisle_CW --profile configs/torwic/aisle_cw_rec02_quality_v1.json
```

Observed output: `selected=983`, `excluded=29`, `effective=954`;
`active_ratio=739/948=0.7795358649789029`, `max_static_run=53`, no motion
warning. Quality report canonical checksum
`sha256:2795ef2ef8afed56e4587f6e7b450a41dd5b0cfc55950266c30d69be592fbf48`;
published JSON byte SHA-256
`sha256:3dd5491c37c5064fa876f05f059d330741f0dde2fc788f207fd423c0260d643a`.
Independent audit matched exact selected IDs to frozen train split, all 29
excluded IDs to prior input-only analysis, no held-out ID in report, 1.092
canonical normalized PNG still physically present; source/split/profile
checksums and report canonical identity validate. The initial draft report
was backed up under `/tmp` and regenerated before acceptance when
`producer_version` was added; no canonical RGB or split was changed.

2026-09-24 correction audit: user selected public noncommercial demo scope and
said a second agent completed privacy review. That statement does not by itself
identify the exact QA approval record or frame scope, so the second agent's
`rec02_review_verified/privacy_report.json` is retained for audit but is not
accepted as REC-02 completion evidence yet. Inspection found its generator
could set `attested=true`, `inspected=983` and issue `VERIFIED_ANONYMIZED` from
arbitrary CLI reference strings, without resolving an independent inspection
or QA approval record. This was a real bypass, regardless of whether the
separate human review occurred. The unsafe issuance path has been removed
from `scripts/torwic/rec02_evidence.py` pending a verifiable QA integration.

The first corrected candidate under `rec02_review_pending/` recorded rights
pending. User then explicitly authorized TorWIC use for public noncommercial
demo on 983 reconstruction frames, keeping 109 held-out for evaluation only.
`data/torwic_slam/derived/aisle_cw/rec02_source_rights_attestation.json` records
that operator attestation (checksum
`sha256:eb6bb75649905773a08b37af71cbb848de21a47ac8ea90604076525c55753586`),
the CC BY-NC 4.0 plus Dataset Terms source and attribution requirement. It is
not a grant of TorWIC ownership or a privacy approval. The new candidate under
`rec02_review_rights_confirmed/` binds this attestation to the frozen split:
InputManifest checksum
`sha256:e3d110936bb6df00ee86ceba9160ec7243be3e9f9ddf070472ea8ce47b17cede`;
983-frame inventory checksum
`sha256:97431a98723188a35d4d2eda005b5db72e2f25cf5d753554997872acb11cf2f0`;
review packet checksum
`sha256:04dd661b9fa870c325f159943e17fe7a54ff4185c3c2753b66f44f45516c62e5`.
The packet still records `inspected_frame_count=0`, `qa_accepted=false`,
findings unknown and `privacy_report_result=NOT_ISSUED`: these are the facts
the generator can verify. Exact train IDs equal the frozen split; no held-out
ID appears. The old agent-generated verified report references a different
InputManifest checksum, so it cannot clear this candidate by identity alone.

Focused tests: `tests/test_reconstruction/test_rec02_quality.py` verifies
mask/reason/checksum immutability, corrupt PNG/video, static/duplicate/tampered
input, motion warning-only behavior, real FFmpeg PNG/video probes,
InputManifest adapter, artifact-store publication/resolution and privacy
fail-closed paths including attempted VERIFIED publication without QA proof.
After rights binding and bypass correction, final
`.venv/bin/pytest tests/test_reconstruction/test_rec02_evidence.py
tests/test_reconstruction/test_rec02_quality.py -q`: 30 passed;
`.venv/bin/pytest tests/ -q`: 188 passed. Ruff check and format on
`src/ tests/ scripts/torwic`, `git diff --check` and AST 30-line/
3-parameter audit pass.
`.venv/bin/ruff check src/ tests/ scripts/torwic`, `.venv/bin/ruff format --check src/ tests/
scripts/torwic`, `git diff --check`, and AST 30-line/3-parameter audit all
pass. `mypy` executable is absent; no type-check pass is claimed. Real quality
report was also published into a temporary configured `FilesystemArtifactStore`
and resolved by `ArtifactResolver` at
`artifact://jobs/torwic-aisle-cw-rec02-smoke/rec02/quality_report.json`
with byte checksum matching the local derived report; this is artifact
boundary proof, not product job dispatch.

2026-09-24 closure: user supplied exact 983-frame QA attestation and then
explicitly approved issuance/completion. Codex verified the review record,
InputManifest, inventory, split, and all 983 source PNG checksums. An
authorization addendum (`qa_report_issuance_authorization.json`, checksum
`sha256:31244cec42402b63d6c66c4228f9778df1aa02db0af77ef4c3967bfd877a4d7a`)
binds the review record checksum and current input identity. The original
review retains `independent_qa_verified=false` and
`report_issuance_authorized=false`; those flags had been edited without
updating its checksum, so the first attempt failed and they were restored.

Real report: `rec02_review_rights_confirmed/privacy_report.json`, result
`VERIFIED_ANONYMIZED`, scope `all_selected_frames`, 983/983, canonical checksum
`sha256:f8de1db01c60c2f72711bdcc04e3692089eaeb402730f37e450c2b4a28f33999`.
It resolves unchanged at
`artifact://jobs/torwic-aisle-cw-rec02-approved/rec02/privacy_report.json`.
Issuance receipt checksum:
`sha256:6cbdf3b2ea658e782e77663316b8374d664f410ba499e40f7b796f3756e58180`;
`public_dispatch_authorized=false`. Local handoff proof resolved 983 manifest
refs through the injected resolver, verified source bytes, and passed
`RGBPrivacyGate.require_dispatch` for matching report/evidence/acceptance.
The quality mask has the same 983 IDs, 29 blur exclusions and 954 effective
IDs; no held-out frame was used. Human inspection is user-attested; Codex did
not repeat visual inspection or claim independent QA. REC-02A owns frame
extraction; EX-PRODUCT owns actual public dispatch.
