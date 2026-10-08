# AUD-14 — Adaptive floor/noise model cho object extraction

## Metadata và goal

- IN PROGRESS; P1; EX-SCENE; REC floor prior và SIM quality consumers.
- Canonical SCENE-02/03/06, REC-06, SIM-02. REUSE NumPy/SciPy clustering;
  ADAPT bounded RANSAC plane fitting, optional worker-only Open3D đã qualified.
- Goal: floor separation thích ứng slope/noise, giữ low obstacles và canonical frame.
- [Agent guide](../AGENT_GUIDE.md), [AUD-12](AUD-12-collision-quality.md).

## Baseline và scope

GeometricConfig.floor_clearance_m=0,06; find_candidates filter z rồi voxel connected
components. Không có requirement phải thay connected components bằng DBSCAN nếu
algorithm hiện có đạt clustering contract. Gaussian label growth cũng có floor
clearance; inspect các consumers để dùng cùng floor/noise evidence khi phù hợp.
CodeGraph: GeometricConfig/find_candidates, candidate_objects, label_gaussians,
floor_seed và confirmed metric/floor models.

Owned: services/scene/geometric.py, decomposition Gaussian floor masking,
extraction/association adapters, floor config/provenance và focused tests.
Không rotate lại toàn bộ SceneIR, chọn tường làm floor, xóa mọi point thấp hoặc
thêm heavy dependency vào API process để fit một plane.

## Input / output / data contract

Input: canonical metric geometry/points, confirmed floor/up prior, noise/fit
profile và source refs. Output proposed FloorModel/fit evidence + per-point
floor classification, candidates/background segmentation và provenance.

FloorModel: version, frame=world, unit=meter, plane normal+offset, normal hướng
canonical up, source/config checksum, inlier count/coverage, residual/noise scale,
status supported/uncertain/fallback reason. Plane distance dùng signed n·p+d,
threshold theo measured noise + bounded profile; không dùng raw z cho mọi slope.
Local/multiple floor surfaces hoặc ramp outside single-plane support phải báo
unsupported/uncertain, không force dominant wall thành floor.

Candidate transforms giữ world frame; floor filtering extraction không được
xóa low obstacle collision geometry. Source classification/selection bind AUD-01/
AUD-12 ownership. Small/thin object chưa thành candidate vẫn thuộc environment.
Fallback known confirmed flat plane phải ghi explicit reason/profile; no silent new plane.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Fitted floor thay raw-z/static-clearance classification.
Cần sửa đồng bộ: REC-06 floor prior port, object extraction/geometric clustering, background ownership, collision cleanup/source QA và classification thresholds.
Acceptance xuyên consumer: Sloped/noisy floor, low/thin obstacles và canonical units/frame consistency pass; source ownership không suy từ edited collider.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập runtime; S2 dùng AUD-01 ownership/AUD-12.S1 quality fixtures, không
đợi AUD-12.S2 cleanup. S3 handoff fit evidence để cleanup consumers sử dụng. Floor prior
từ REC-06 dùng qua port/schema, không import internal REC implementation vào scene.

## Sprint AUD-14.S1 — Floor model và fitted-plane classification

**Input:** flat/sloped/noisy point fixtures + confirmed up/floor prior.
**Output:** typed floor fit/config/classification và uncertainty diagnostics.
**Contract:** deterministic seeded RANSAC; finite normalized normal/distance;
support/angle/coverage constraints; no canonical frame mutation.

Implement: constrain RANSAC candidates near known up/floor region; robust residual
scale, bounded thresholds, evaluate fit support. Reuse existing linear algebra/
spatial functions; freeze profile units/seed and serialize measured evidence.
Tests: flat, slope, noisy, vertical-wall-dominant, missing floor, degenerate/NaN
input, ramp/multiple levels, outlier robustness and uncertain fallback.
**Exit:** [x] correct supported fit; [x] degenerate scene not fake floor success.

## Sprint AUD-14.S2 — Extraction/clustering và Gaussian consumers

**Input:** FloorModel S1 + geometry/Gaussian source/profile.
**Output:** candidates/labels using plane-relative floor distance và recorded config.
**Contract:** object/world transforms same frame; floor noise excluded from seeds;
low obstacles/wall/support preserved in environment/physics.

Implement: replace relevant fixed-z masks with plane/noise policy; keep existing
connected-component clustering if adequate. Qualify DBSCAN/cKDTree radius clustering
only for documented failure case, with memory bounds and unit-aware parameters.
Adapt Gaussian growth floor guard without deleting arbitrary raw Gaussian records.
Tests: pallet/shelf legs/low boxes above tilted floor, floor floaters, touching
objects, sparse clouds, varying density, stable labels/source conservation.
**Exit:** [ ] extraction improvement on supported cases; [ ] no low-obstacle erasure.

## Sprint AUD-14.S3 — Product config/provenance và quality handoff

**Input:** fit/extraction outputs + selected profile + actual canonical artifact.
**Output:** versioned provenance/quality report và UI diagnostics khi uncertain.
**Contract:** old profile/revisions read-compatible; override/retry explicit;
new algorithm/version/config creates new artifact identity/revision.

Implement: persist floor evidence/ref and effective thresholds; expose fit failure
as actionable metadata without arbitrary expert knobs on core user flow. Integrate
AUD-12 floor/obstacle retention benchmark; don't infer model accuracy from candidate count.
Tests: source/profile checksum mismatch, old JSON, failed fit/report API,
supported real sloped/noisy sample, candidate/collision consumer parity.
**Exit:** [ ] floor model used consistently; [ ] measured quality/limitations recorded.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_scene/test_geometric_candidates.py tests/test_scene/test_gaussian_split.py tests/test_scene/test_sampro3d_consolidate.py tests/test_orchestration/test_scene_extraction.py tests/test_reconstruction/test_rec06_floor_frame.py -q
```

`tests/test_scene/test_adaptive_floor.py` covers S1 fit/degeneracy. Task DONE khi
fit/extraction/retention/consumer tests và real supported sample proof pass; floor
fitting không được coi là solved multi-level unseen geometry.

## Result / Evidence

### AUD-14.S1 — Floor model và fitted-plane classification

- Base commit: `35eab16` (`AUD-13.S1`).
- Logic delta: trước đây floor evidence chưa có trong EX-SCENE; geometric fallback
  và Gaussian label growth dùng các ngưỡng world-Z riêng. S1 thêm constrained
  deterministic RANSAC trên point cloud mét, ràng buộc bằng up vector và điểm sàn
  đã xác nhận; scene points không bị xoay hoặc dịch.
- Contract v1.0: `FloorPrior`, `FloorFitProfile`, `FloorModel` và compact point
  labels. Model lưu source checksum, embedded profile và checksum, seed, unit/frame,
  plane, support ratio, coverage, residual/noise, effective floor band và reason.
  `uncertain` không được dùng để phân loại floor; mọi point trả `UNKNOWN`.
- Algorithm: seed cố định; sample count có giới hạn; normal hướng theo up; giới hạn
  slope và khoảng cách tới prior; robust residual scale; floor band bị chặn trong
  profile; convex-hull coverage; plane hypotheses cạnh tranh trả `uncertain`.
- Impact: `find_candidates` vẫn lọc fixed world-Z và `label_gaussians` vẫn có
  `floor_clearance_m`. Hai consumer này chưa đổi trong S1 vì AUD-14.S2 thay chúng
  đồng bộ bằng FloorModel. `REC-06 FloorEstimate/floor_frame` tiếp tục là prior,
  không dùng trực tiếp internal REC code trong EX-SCENE. Không có production caller
  cho fitter mới; consumer integration là phần tiếp theo.
- Files: `src/models/contracts/floor_model.py`,
  `src/models/contracts/__init__.py`, `src/services/scene/floor_model.py`,
  `tests/test_scene/test_adaptive_floor.py`, task và plan README.
- Verification: `.venv/bin/ruff check src/ tests/` PASS; `.venv/bin/ruff format
  --check src/ tests/` PASS (515 files); focused suites PASS (30 tests);
  `scripts/check_contract_mirror.py` PASS (5 enums, 5 models); CodeGraph current
  (845 files, 16,518 nodes, 48,329 edges). Focused suites covered sloped/noisy
  planes, outliers, wall dominance, missing prior/floor, nonfinite/degenerate input,
  multiple levels, narrow support, existing extraction and REC-06 floor frame.
- Limits: source checksum hiện do caller cung cấp; S3 phải bind nó vào exact
  canonical geometry artifact trước khi persistence/consumer gate. Chưa nối vào
  object extraction, Gaussian growth, collision cleanup hoặc quality report; chưa có
  supported production sloped/noisy artifact. Multi-level detection chỉ đánh dấu
  ambiguity khi các hypotheses cùng thỏa prior/profile.
  S2/S3 và real floor/obstacle-retention evidence còn pending.
- Pre-flight (GUIDE.md Rule 13): codegraph đọc `GeometricConfig/find_candidates`,
  `candidate_objects/box_candidates`, `SplitConfig/label_gaussians`, REC-06 floor
  prior/frame và callers; fitter mới chỉ có test callers. Understand flow được
  truy vết qua CodeGraph; `understand-anything`/`understand-domain` CLI không có trong
  môi trường (**UNVERIFIED**). Minimal-code rung 2: dùng Pydantic ContractModel,
  canonical JSON checksum, NumPy và SciPy đã có trong scene pipeline. UI không đổi,
  DevTools n/a.
