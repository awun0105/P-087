# AUD-14 — Adaptive floor/noise model cho object extraction

## Metadata và goal

- PLANNED; P1; EX-SCENE; REC floor prior và SIM quality consumers.
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
**Exit:** [ ] correct supported fit; [ ] degenerate scene not fake floor success.

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

Planned tests/test_scene/test_adaptive_floor.py. DONE khi fit/degeneracy/extraction/
retention/consumer tests và real supported sample proof pass; floor fitting không
được coi là solved multi-level unseen geometry.

## Result / Evidence

Pending — source/fit/profile identity, plane/noise metrics, candidate/obstacle
witnesses và supported/uncertain cases theo sprint.
