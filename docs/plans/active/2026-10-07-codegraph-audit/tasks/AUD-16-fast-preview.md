# AUD-16 — Fast Preview preset, lifecycle và explicit finalization

## Metadata và goal

- PLANNED; P1; EX-PRODUCT + EX-REC; SCENE/SIM consumers.
- Canonical REC-04/05, PRODUCT-02/08/09. REUSE training parameter registry,
  JobProcessingConfig, preview SOG artifacts, admission và upstream stage cache.
- Goal: user chủ động chọn preview nhanh, inspect visual sớm và chạy final
  profile rõ ràng với identity/history riêng.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0017](../../../../decisions/0017-fast-preview-and-final-artifacts.md).

## Baseline và scope

brush.total_train_iters đã cho 1.000–60.000, step 1.000; 7.000 hợp lệ. Current
"preview" còn là artifact trước metric confirmation, không tự là low-quality tier.
Thiếu named fast preset, explicit preview/final lifecycle/lineage và UX promotion.
Không promise 7k ~5 phút; AUD-15 đo time-to-first-usable-preview trên actual input.

CodeGraph: JobProcessingConfig/config parameter registry, PrepareWorker,
BrushRequest/BrushAdapter, JobPreview/preview publication, job_progress,
create_job/retry paths và frontend processing/pipeline/inspection consumers.
Owned: config presets, REC prepare/packaging ports, PRODUCT config/jobs/API,
frontend preset/preview/final controls và contract tests.
Không đổi iterations ngầm theo GPU, overwrite preview bằng final, hoặc coi SOG
visual là proof collision/physics. Existing user-selected final 7k vẫn có thể
qualify theo actual QA; không phát minh minimum 30k như release policy.

## Input / output / data contract

Input: source refs + explicit preset/profile selection. Output: immutable preview
config/artifact + lineage tới final job/run và candidate/validation khi hoàn tất.

Proposed config/operation extension: quality_tier=preview/final, preset_id/version,
effective params/checksum, source identity và preview/final lineage refs. S1 chọn
placement/version/defaults sau inspect existing preview semantics. Legacy jobs
giữ behavior và identity; không suy tier chỉ từ count iterations hoặc tên preview.

State matrix phải ghi rõ: requested/queued/running → visual preview available;
metric confirmation pending hoặc preview-only operation complete tùy flow; explicit
final request → new immutable config/job/run; final candidate qualified → validation/
review. Preview availability không tự mark whole scene pipeline SUCCEEDED hoặc
enable release. Final request thay config tạo identity mới; retry same job giữ
checksum. Upstream reuse chỉ khi source/frames/pose/preparation keys match.

Brush resume là capability phải qualify bằng pinned CLI/runtime và actual optimizer
checkpoint. PLY/SOG visual output không phải checkpoint đủ để resume training.
Nếu chưa qualified, final rerun có lineage rõ; không claim continuation 7k→30k.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Preview/final lifecycle và lineage.
Cần sửa đồng bộ: preset/config schema, worker stage routing, early SOG publication, frame/preparation cache, final create intent/quota, progress/viewer và candidate/review gating.
Acceptance xuyên consumer: Renderable preview không đồng nghĩa final/SUCCEEDED/releasable; promotion creates exact final config/run và giữ preview history khi final fail.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1/S2 reuse existing admission; AUD-15.S1 timing contract trước final benchmark.
S3 uses AUD-03 validation gate và AUD-05 khi nghiệm thu full final flow; UI early
preview có thể nghiệm thu trước real Isaac acceptance, ghi phạm vi tương ứng.

## Sprint AUD-16.S1 — Preset và preview/final contract

**Input:** current parameter registry/JobPreview semantics + explicit product flow.
**Output:** versioned fast preset candidate 7k và compatible tier/lineage/state contract.
**Contract:** effective config equals selected profile; separate immutable identities;
old jobs readable; preview không grant candidate/validation/release capability.

Implement: qualify frame/resolution/splat caps bằng benchmark thay arbitrary
defaults; start from existing params và chỉ đổi những gì preset công khai. Define
final selection/promotion command và conflict/idempotency responses; concurrent
requests không tạo duplicate final run cho cùng intent. Document known resume support.
Tests: preset bounds/versions, old payload/checksum, tier vs iterations, explicit
final config, duplicate promotion intent, incompatible source/preparation profile.
**Exit:** [ ] producer/consumer agree state/config; [ ] no hidden downgrade.

## Sprint AUD-16.S2 — Early visual publication và final execution

**Input:** selected preview profile/source + S1 finalization intent.
**Output:** verified SOG available early; durable final job/run with exact final config.
**Contract:** preview-only path không phải chờ geometry/SAM chỉ để inspect;
publication verified trước readiness; failed final giữ preview/history usable.

Implement: isolate early visual milestone using existing packaging/preview port;
skip downstream work chỉ khi mode contract explicitly preview-only. Final intent
enqueues normal final flow, reuses compatible upstream artifacts and retains
metric confirmation obligations. Qualify checkpoint continuation riêng nếu available;
unsupported resume reruns normal final, không mutate preview config hoặc artifacts.
Tests: worker restart around SOG publish, corrupted delivery, config/cache mismatch,
final failure/cancel preserving preview, promotion idempotency and resource waiting.
**Exit:** [ ] early verified visual path; [ ] final output/lineage correct.

## Sprint AUD-16.S3 — Studio UX và measured acceptance

**Input:** API state/config/lineage + preview/final artifacts and timing evidence.
**Output:** selectable preset, preview inspection, explicit final request và history UI.
**Contract:** user sees quality tier/current stage và selected final configuration;
queued waiting cancellable; final approval không carry từ preview/old candidate.

Implement: show preview availability while pending downstream stages, final action
with selected profile, loading/error/retry and conflict reconciliation. Keep
viewer lifecycle cleanup. Measure time-to-first-usable-preview including artifact
publication/browser load; compare separately with full final timing/quality.
Tests: frontend domain/API command tests, browser preset→preview→final, failed/cancelled
final, stale polling/duplicate clicks, approval invalidation, real GPU paired runs.
**Exit:** [ ] browser flow verified; [ ] actual timings/quality and limits recorded.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_job_progress.py tests/integration/test_studio_processing_job.py tests/test_reconstruction/test_rec04_brush.py -q
```

Planned tests/test_orchestration/test_fast_preview.py và frontend focused preset/
promotion tests. DONE cần early visual + durable final flow + browser/GPU evidence;
final release acceptance còn theo AUD-03/05, không suy từ fast training duration.

## Result / Evidence

Pending — preset/version, effective preview/final checksums, lineage/state matrix,
resume capability, actual hardware/frame count/timings và browser/final evidence.
