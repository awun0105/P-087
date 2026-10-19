# AUD-18 — Opt-in face/plate anonymizer trước reconstruction

## Metadata và goal

- IMPLEMENTED (code, phạm vi thu gọn theo owner 2026-10-09: người upload tự xem và chấp nhận bản đã che, không có reviewer riêng hay sửa tay; đánh giá trên dữ liệu thật và chạy trên pod còn mở); P2 extension theo yêu cầu owner; EX-REC + EX-PRODUCT.
- Canonical REC-02, PRODUCT-01/02/09; bổ sung task-local scope, không đổi crosswalk.
- ADAPT qualified detection/tracking/redaction; REUSE RGBPrivacyGate,
  PrivacyInspectionEvidence, PrivacyQAAcceptance và approved-copy lineage.
- Goal: hỗ trợ chuẩn bị input ẩn danh, manual correction/QA và dispatch đúng
  approved derived copy. Kỹ thuật khả thi; không bỏ task vì old MVP excluded.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0019](../../../../decisions/0019-anonymized-input-preparation.md).

## Baseline và scope

Current Studio self_attested + PRELIMINARY_SCREENED có thể dispatch khi đủ flags
và không findings. Đây không phải auto detector hoặc qa_verified. Strict
RGBPrivacyGate đã có evidence/acceptance verification; reuse thay competing gate.

CodeGraph: RGBPrivacyGate/SelfAttestedPrivacyGate, PrivacyInspectionEvidence,
PrivacyQAAcceptance, project_block_reason, frame extraction/preflight publication,
input manifests/privacy review routes và product upload/dispatch consumers.
Owned: worker-only sanitized-copy preparation, privacy evidence/QA integration,
PRODUCT operation/API/reviewer UI và focused tests. Không đổi self_attested policy
ngầm, cấp review permission mới, xóa original hoặc redact sau training rồi coi
raw-derived 3DGS/thumbnails an toàn. Không guarantee mọi face/plate đều được detect.

## Input / output / data contract

Input: source-rights attestation, restricted original ref, explicit anonymize
profile và reviewer corrections. Output proposed SanitizationManifest, sanitized
derived input/frame refs, inspection evidence và verified acceptance when approved.

Manifest: schema/version, source input/checksum, detector/tracker/runtime/model
version+weights checksum, config checksum, frame inventory/PTS mapping, processed
coverage, per-frame region/redaction action refs, failures/uncertainty và sanitized
byte checksum. Detection/crop evidence giữ restricted boundary; public logs không
ghi PII images hoặc original download URLs. Unprocessed frames không marked covered.
S1 chốt schema/placement dựa existing contracts; no competing privacy status enum.

Preserve resolution/crop/timing/intrinsics binding theo declared codec contract;
redaction không đổi frame geometry. QA inspect chính decoded sanitized copy/frame
inventory mà downstream dùng, không chỉ detector rectangles trên source. Reuse
existing input-manifest/inspection/approved_copy_checksum acceptance verification,
bind original→derived lineage explicit. Any correction/re-encode đổi bytes phải
invalidate old QA/acceptance. Zero detections không tự VERIFIED_ANONYMIZED.
Opt-in sanitized flow consumes approved copy trước training, thumbnails/public
assets; raw input vẫn trong original access boundary, giữ rights attestation.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Sanitized source identity trước reconstruction.
Cần sửa đồng bộ: privacy contracts/gate, detector/tracker/redaction producer, prepared InputManifest/frame set, cache/preview/train consumers, storage access và review diagnostics.
Acceptance xuyên consumer: Train/cache không reuse raw source khi chọn anonymized; timeline/redaction coverage và approval refs match actual sanitized bytes.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập để qualify model/contracts; S2 dùng AUD-07 durable admission pattern.
S3 uses existing privacy QA roles/gate. Source sanitization identity phải nằm
cache/preparation keys của AUD-15/16, không reuse raw-input trained outputs.

## Sprint AUD-18.S1 — Model envelope và sanitization/QA contracts

**Input:** current privacy contracts/gates + consented face/plate fixtures and model candidates.
**Output:** qualified model profile, SanitizationManifest và source/derived/QA state matrix.
**Contract:** original preserved/restricted; full requested coverage recorded;
automation chưa grant acceptance; existing self_attested behavior unchanged.

Implement: choose detector/tracker theo measured small/occluded/angle/lighting cases,
qualify code/model weights/data license and runtime footprint trước integration.
Define supported coverage, uncertainty/manual correction and failure handling;
reuse evidence/acceptance refs and existing reviewer authorization. Do not assume
YOLOv8-Face/plate variants share một license hoặc confidence là privacy guarantee.
Tests: old reports/checksums, wrong input/copy/acceptance refs, incomplete coverage,
zero detections, model/config invalidation, unauthorized approval và restricted refs.
**Exit:** [ ] model/license/quality envelope recorded; [ ] QA/identity contract agreed.

## Sprint AUD-18.S2 — Detection/tracking/redaction worker

**Input:** admitted source refs/profile + full requested frame inventory.
**Output:** verified sanitized copy/frames + coverage/redaction manifest/diagnostics.
**Contract:** all-frame preparation trước raw-derived public output; no silent skipped
frames; actual decoded copy matches manifest; cancellation/lease protects publication.

Implement: detector + temporal association, conservative redaction over supported
tracks, blur/mosaic with qualified effectiveness; preserve geometry/PTS mapping.
Review uncertainty/missed regions qua restricted artifacts; reject corrupt/incomplete
output. Store original/derived separately, use immutable refs and bounded worker
resource lifecycle. Failed preprocessing không fallback sang training raw source
trong anonymize mode; manual sanitized-input workflow vẫn available separately.
Tests: intermittent detections/tracks, small/occluded face/plate, variable frame rate,
empty frames/codec failure, coverage gaps, artifact corruption, restart/cancel/lease.
**Exit:** [ ] sanitized output/coverage verified; [ ] no raw public-output path leakage.

## Sprint AUD-18.S3 — Manual correction, QA và dispatch integration

**Trạng thái: THAY BẰNG uploader-acceptance (owner 2026-10-09).** Không làm reviewer riêng,
sửa tay vùng che hay dispatch theo `approved_copy_checksum` như mô tả dưới. Thay vào đó,
người upload xem bản đã che và chấp nhận đúng bộ frame đã xem; job dừng ở
`ST-FRAME-EXTRACT` đến khi có chấp nhận (chi tiết ở Result, mục "Quyết định hiện hành").
Phần còn lại của mục này giữ làm lịch sử thiết kế gốc, không còn là yêu cầu hoàn thành.
Các exit dưới đây được đánh dấu N/A, không tick.

**Input:** decoded sanitized output/evidence + authorized reviewer decisions.
**Output:** review/correction UI, exact-copy acceptance và downstream dispatch binding.
**Contract:** manual edits create new immutable copy/evidence; stale approval rejected;
only chosen approved derived copy drives frame/pose/train/publication in opt-in mode.

Implement: preview restricted source/sanitized evidence under existing roles, add
manual regions and rerender before re-review. Persist verified acceptance through
current QA path; expose pending/failed/cancelled actions and full coverage evidence.
Prevent caches/downstream refs from raw source; evaluate reconstruction quality
impact of redacted texture separately from privacy detection/redaction quality.
Tests: known missed detections/manual fixes, wrong/stale approved_copy_checksum,
QA permission, mode-specific dispatch, browser review→correct→approve→train flow,
consented real dataset privacy/coverage and reconstruction quality acceptance.
**Exit (N/A — thay bằng uploader-acceptance):** ~~[ ] reviewer/dispatch lineage verified~~;
[ ] real detection/coverage limits recorded — phần này vẫn mở, thuộc đánh giá trên dữ liệu thật.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_reconstruction/test_rec02_quality.py tests/test_reconstruction/test_rec02_evidence.py tests/test_reconstruction/test_rec02_self_attested_privacy.py tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_orchestration/test_privacy_gate.py -q
```

Planned tests/test_reconstruction/test_privacy_sanitization.py và API/UI review
tests. DONE cần real supported detector/redaction evaluation + reviewer/browser
and consumer proof; synthetic zero findings không chứng minh anonymity.

## Result / Evidence

### Tiến độ 2026-10-09 (S1 và phần lõi của S2; S3 chưa bắt đầu)

- **Model đã chọn:** EgoBlur Gen2 của Meta cho cả khuôn mặt và biển số. Code và trọng số Apache-2.0; Meta ghi
  cho phép dùng thương mại. Trọng số chỉ tải được sau khi nhập email và đồng ý giấy phép trên trang của Meta.
  Loại YuNet (train trên WIDER FACE với nhãn của SCRFD, cả hai phi thương mại), SCRFD/InsightFace (trọng số phi
  thương mại), các bản YOLO của Ultralytics (AGPL), open-image-models (giấy phép trọng số chưa được trả lời).
- **Runtime:** chạy trong `scene_runtime` hiện có (torch 2.7.1). Gói `egoblur` 2.0.1 ghim torch 2.9.1 nên cài
  `--no-deps`. Đã so trên 13 frame: 41 lượt phát hiện giống hệt giữa torch 2.7.1 và 2.9.1 (lệch hộp và điểm
  bằng 0). Trên Quadro T2000: khoảng 0,63 giây mỗi frame mỗi model, peak VRAM 0,89 GB.
- **Đã có trong code:** `adapters/anonymize_runner.py` (phát hiện, lan theo thời gian ±2 frame, tô đặc vùng nới
  15%), `adapters/sanitization_regions.py`, hợp đồng `contracts/sanitization.py` (`SanitizationManifest`),
  `rgb/frames/frame_sanitization.py` (`FrameSanitizer`), cờ `anonymize` của `PrepareInputRequest`, setting
  `PRODUCT_ANONYMIZE_INPUT` và `PRODUCT_EGOBLUR_WEIGHTS`. Khi bật, stage `ST-FRAME-EXTRACT` của job trỏ tới frame
  set ở `rec02a/sanitized/`, nên COLMAP, Brush, thumbnail và các view chỉ dùng frame đã che. Lỗi ở bất kỳ frame
  nào làm bước tách frame thất bại (`FRAME_ANONYMIZATION_FAILED`, `FRAME_ANONYMIZER_UNAVAILABLE`), không lùi về
  frame gốc.
- **Đã kiểm:** `tests/test_reconstruction/test_privacy_sanitization.py` (8 test) và
  `tests/test_reconstruction/test_frame_sanitization.py` (4 test, FFmpeg thật, detector giả). Một lượt chạy
  thật qua `VideoInputPreparer` với runner EgoBlur thật trên video dựng từ ảnh `astronaut` của scikit-image
  (phạm vi công cộng): 12/12 frame có mặt được phát hiện với điểm 1,0 và bị tô đặc.
- **Chưa làm / chưa kiểm:**
  - Không có dữ liệu thật nên chưa đo recall trên video điện thoại và biển số Việt Nam. Ngưỡng đang là mặc định
    của Meta cho camera RGB (mặt 0,67416; biển số 0,74475), chưa hiệu chỉnh. Nhánh biển số mới được chạy, chưa
    từng thấy bắt đúng một biển số thật.
  - Privacy report của job không đổi: vẫn `self_attested` / `PRELIMINARY_SCREENED`. Bước này là lớp bảo vệ thêm,
    không cấp `VERIFIED_ANONYMIZED`. Luồng reviewer xem, sửa tay và duyệt (S3) chưa có.
  - Frame gốc vẫn được publish ở `rec02a/frames/` (không nằm trong allow-list tải của job khi bật che); chưa có
    cơ chế hạn chế truy cập riêng hay xóa.

### Lựa chọn theo từng job (2026-10-09)

- `JobProcessingConfig.anonymize` (chỉ ghi vào bytes cấu hình khi bật, nên checksum của job không chọn che giữ
  nguyên), `ResolvedProcessing.anonymize`, trường `anonymize` của `UploadProjectInput` và `AssemblyRunRequest`.
  Worker che khi job chọn hoặc khi deployment đặt `PRODUCT_ANONYMIZE_INPUT=true`.
- `GET /processing/options` trả `anonymize_available` (deployment đã cấu hình scene runtime và trọng số) và
  `anonymize_enforced`. Yêu cầu che trên deployment chưa cấu hình bị từ chối 409, không âm thầm bỏ qua.
- Form tạo scene (`UnifiedInputFlow.tsx`) hiện ô "Tự động che khuôn mặt và biển số trước khi dựng 3D" khi
  server báo có; lời khai "video không có khuôn mặt/biển số" vẫn bắt buộc. Chưa có test frontend riêng cho ô này.
- **Admission:** `run_video_job` chạy `prepare` rồi `preview` trong cùng một lần nhận job, sau khi admission đã
  giữ chỗ cho pha preview. Bước che (peak khoảng 0,9 GB) chạy bên trong phần giữ chỗ đó, trước khi Brush bắt đầu,
  nên không cần giữ chỗ riêng.
- Tests: `test_anonymize_is_recorded_only_when_chosen`,
  `test_anonymize_option_is_offered_and_recorded_only_with_a_configured_anonymizer`; `tests/test_api` và
  `tests/test_orchestration` (978 test) pass.

### Quyết định trước đó của owner (2026-10-09, ĐÃ THAY — xem mục cuối): không có bước duyệt

Owner cân nhắc hai phương án (chờ reviewer / không chờ) rồi chốt: **không có bước duyệt của reviewer**. Job chọn
che chạy thẳng từ frame đã che sang dựng 3D.

- S3 của plan gốc (màn hình reviewer, sửa tay, chấp nhận theo checksum, chặn dispatch) **không làm**. Đây là
  thay đổi phạm vi so với ADR 0019 mục 3; ADR đã ghi lại.
- Hệ quả giữ nguyên trong code: privacy report của job vẫn là tự cam kết / `PRELIMINARY_SCREENED`. Không có
  đường nào cấp `VERIFIED_ANONYMIZED`, vì không ai kiểm bản đã che. Bước che là lớp bảo vệ thêm, không phải
  bảo đảm; lời khai của người upload vẫn bắt buộc.
- Tối ưu thời gian đã làm: frame không có vùng bị che không bị ghi, băm và publish lại, mà dùng tiếp artifact
  gốc (thường là phần lớn frame). Suy luận theo lô đã đo trên T2000 và không nhanh hơn rõ (0,64 so với 0,57 giây
  mỗi frame, kết quả giống hệt), nên không thêm.
- Lan theo thời gian tắt mặc định (`propagate_radius = 0`); lý do ghi ở `DEFAULT_CONFIG`.
- Đã thấy một phát hiện nhầm trên frame thật: nhãn trắng trên thùng nhựa xanh bị coi là biển số (điểm 0,839).
  Phát hiện nhầm làm xuất hiện mảng đen trong ảnh train; chưa có dữ liệu để chỉnh ngưỡng.

### Xóa bản gốc của frame đã bị che (2026-10-09)

- Sau khi frame set đã che publish xong, `FrameSanitizer` xóa khỏi kho cục bộ của worker bản gốc của mọi frame
  đã bị thay, cùng `rec02a/frame_set.json` gốc (inventory trỏ tới các file đó). Frame không bị che giữ nguyên vì
  frame set đã che đang dùng chính artifact đó. Không frame nào bị che thì không xóa gì.
- Việc xóa diễn ra trong tool `prepare`, trước `sync_up` của runner (`runner.py:770`), nên các file này không
  bao giờ lên kho từ xa. Retry tách lại frame, che lại, cho ra đúng frame set cũ rồi xóa lại.
- Lỗi khi xóa chỉ ghi log và không làm hỏng job: không còn ref nào của job trỏ tới các file đó.
- **Không xóa video nguồn.** Video vẫn chứa khuôn mặt/biển số và vẫn nằm trong kho theo chính sách lưu giữ của
  input; retry và chạy lại job cần nó. Xóa frame gốc vì vậy chỉ bỏ các bản sao chưa che, không làm dữ liệu
  nhạy cảm biến mất khỏi hệ thống.
- Tests: `test_originals_of_redacted_frames_are_deleted_and_retry_still_works`,
  `test_nothing_is_deleted_when_no_frame_was_redacted_or_the_step_fails`.

### Quyết định hiện hành (2026-10-09): người upload xem và chấp nhận bản đã che trước khi dựng 3D

Thay cho mục "không có bước duyệt" ở trên. Owner chọn phương án "kiểm trước khi xử lý".

- **Worker.** Sau bước che, `run_video_job` trả về ngay khi `awaiting_anonymization_review(job)`: job giữ
  `RUNNING` ở `ST-FRAME-EXTRACT`, không giữ GPU. `_dispatch` bỏ qua job đang chờ; `recover_interrupted_jobs`
  không coi nó là tiến trình chết. Khi đã có chấp nhận, `waiting_jobs` đưa job vào hàng đợi (phase `preview`)
  và `run_reviewed_preview_job` chạy LiDAR ingest (nếu có) rồi preview; CAS chuyển stage sang `ST-CAMERA-POSE`
  là claim nên hai worker không cùng chạy.
- **Bản ghi.** `SanitizationAcceptance` (job, checksum bộ frame đã che, checksum manifest, số frame bị che,
  người chấp nhận, thời điểm) publish ở `rec02a/sanitized/acceptance-<checksum>.json`, ghi vào job như stage
  artifact `ST-PRIVACY-GATE` (`record_anonymization_acceptance`, CAS).
- **API** (`src/api/studio/anonymization.py`): `GET /jobs/{id}/anonymization` (frame có vùng bị che),
  `GET /jobs/{id}/anonymization/frames/{name}` (ảnh; chỉ frame thuộc bộ frame đã che của job),
  `POST /jobs/{id}/anonymization/accept` (kèm checksum bộ frame đã xem; lệch thì 409). Quyền theo chủ job như
  bước xác nhận tỉ lệ mét. Từ chối = hủy job bằng route hủy sẵn có.
- **Toàn vẹn.** Manifest che không nằm trong stage artifact nên API tính lại checksum nội dung của nó và so với
  giá trị ghi trong frame set của job trước khi hiển thị hay chấp nhận.
- **UI.** Tab Tiến trình hiện `AnonymizationReviewPanel` khi `waiting_for = anonymization_review`; nhãn scene
  "Cần xem bản đã che"; job đang chờ không bị coi là mất kết nối.
- **Chế độ `qa_verified` (chốt cùng ngày).** Không còn trả 409: API bắt buộc `anonymize` cho mọi video
  (`deps.anonymize_enforced`, form hiện ô chọn đã bật và khóa), worker tự áp theo `project.privacy_mode`, cổng
  dispatch cho video upload đi qua (`projects/privacy.py`). Thiếu bộ che thì API trả 409 kèm lý do và
  `deploy_env check` báo lỗi.
- **Không frame nào bị che thì không dừng.** `accept_when_nothing_redacted` ghi chấp nhận tự động và chuyển
  stage sang `ST-CAMERA-POSE` trong cùng một lần ghi, nên worker khác không nhận trùng job.
- **Giới hạn.** Privacy report của input không đổi thành `VERIFIED_ANONYMIZED`; bằng chứng là bản ghi
  `SanitizationAcceptance`. Người dùng không sửa tay được vùng che: bỏ sót thì phải hủy job.
- **Tests.** `tests/test_orchestration/test_anonymization_review.py` (10), `test_privacy_gate.py`, `test_studio_routes.py`, `frontend/tests/anonymization-review.test.tsx` (5).
  Chưa chạy trên worker thật với GPU; chưa xem giao diện bằng mắt.
