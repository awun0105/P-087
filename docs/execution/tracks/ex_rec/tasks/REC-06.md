# REC-06 — RGB Metric Scale

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | `@awun0105` |
| Target milestone | `M2` |

### Owner chốt quy tắc gốc `world` 2026-09-27

**Quyết định: dịch mặt sàn về `z = 0`.**

Căn cứ đo được (không phải giả định):
- Sàn đo từ raw scan `000110.pcd` (đã lọc zero-return Ouster) → `z_world = -0,2345 m`
- Cộng ba nguồn độc lập: merged cloud `-0,2213 m`, `groundtruth_map.ply` `≈ -0,25 m`
- Cảm biến ở `+0,2330 m`; camera Azure trái ở `+0,1199 m` (cao `35,4 cm` trên sàn)

Lý do chọn dịch, không phải giữ nguyên:
`src/services/simulation/colliders/generator.py:62-80` đặt **analytic ground plane
cứng ở `z = 0`** (`offset_xyz = (0,0,-thickness/2)` → mặt trên ở `z=0`), và
`tasks/REC-05.md:82` cấm dùng mesh làm sàn — Isaac phải tạo plane. Nếu giữ frame
gốc thì sàn của Isaac lệch **23,45 cm** so với sàn thật.

Áp dụng trong `CanonicalFrameDeclaration.translation_m` của REC-06
(`src/services/reconstruction/rgb/canonical/metric_models.py:36`) — **thuộc ownership
EX-REC**, không cần sửa EX-SIM.

Ghi chú phạm vi: đây là lựa chọn cho **demo Aisle_CW**. Với video người dùng upload,
`translation_m` suy ra từ anchor của họ; số `0,2345` không được nhúng vào `src/`.

### Tolerance — chờ số đo trên baseline thật

Owner chọn **không chốt số tròn**, yêu cầu tính từ đúng baseline của cặp A/B sẽ
dùng. Số hardcode hiện tại `tolerance_m = 0.05` tại
`src/services/reconstruction/rgb/canonical/metric_verification.py:24` **chưa được chốt là
authority** và sẽ bị thay khi có số đo. PRD §11.4 câu 4 vẫn `TBD` cho tới lúc đó.

### 2026-09-27 — thử tự suy A/B từ dữ liệu: KHÔNG ĐẠT, cần người chọn

Owner cho phép thử tự dựng ứng viên cặp A/B. Đã làm đủ chuỗi và **kết luận
không dùng được**. Ghi lại cả thành công lẫn thất bại để không ai lặp lại.

**Đã xác minh được thêm (quan trọng cho REC-06):**
`visual.ply` của Brush và `points3D.bin` của COLMAP nằm **cùng một frame** —
median nearest-neighbour = **0,000665 sfm-unit**, 100% trong dung sai, range XYZ
trùng khớp. Comment `"Vertical axis: y"` trong Brush PLY chỉ là **nhãn**, dữ liệu
không bị hoán đổi. Nên `DistanceAnchor.point_a/point_b` có thể lấy thẳng tọa độ
COLMAP, không cần bước chuyển frame.

**Cách đã thử:** chiếu raw scan qua chuỗi camera **đã verify** (inverse(T_os_from_cam),
optical, không distortion) thành z-buffer theo pixel → chiếu `points3D` quan sát
được ở frame 110 ra pixel → ghép hai bảng tại cùng pixel.

**Kết quả — scale KHÔNG nhất quán:**

| max depth | số cặp | median scale (m/sfm-unit) | p95/p50 | trong ±5% |
| --- | --- | --- | --- | --- |
| 3 m | 102 | 0,5876 | 1,268 | 51,0% |
| 4 m | 597 | 0,6585 | 1,274 | 22,4% |
| 5 m | 2.191 | 0,6698 | 1,975 | 23,8% |
| 6 m | 3.035 | 0,6700 | 2,067 | 23,2% |
| 8 m | 3.190 | 0,6692 | 2,042 | 22,7% |
| 25 m | 3.834 | 0,6749 | 1,983 | 25,1% |

Median **ổn định ~0,67 m/sfm-unit** qua mọi lát cắt độ sâu — đó là ước lượng
trung tâm đáng tin. Nhưng **độ rộng cực lớn**: p95/p50 ≈ 2,0 và chỉ ~23% cặp trong
±5%. RANSAC + Umeyama trên 831 tương ứng chỉ giữ được 22 inlier, residual median
2,36 m — **hỏng**. Một cặp 2 điểm đơn lẻ có sai số cỡ **±30%**, không dùng làm
bằng chứng nghiệm thu được.

**Vì sao hỏng — và vì sao đây là kết quả ĐÚNG, không phải thất bại:**
ADR 0001 §"Chọn A/B" đã cấm rõ: *"không đo khoảng cách pixel, **dùng điểm gần bất
kỳ** hoặc tự điền số giả"*. Cách của agent đúng là "dùng điểm LiDAR gần nhất tại
pixel" — bị cấm. Nguyên nhân vật lý: sàn nhìn xiên ở tầm xa định vị kém (2 ứng viên
tự chọn đều rơi vào `y≈358-364`, tức **đúng đường chân trời**, tầm xa nhất), và
tại điểm nhảy độ sâu thể tích LiDAR ở pixel đó không cùng bề mặt với điểm ảnh.

**Kết luận và nội dung còn lại cho REC-06:**
1. **A/B phải do người chọn**, nhúng thẳng vào design sản phẩm: user click 2 điểm
   trên 3D viewport, hệ thống đo khoảng cách tương ứng trên LiDAR đã căn chỉnh,
   người dùng xác nhận. Người chọn phải thấy được vật thể cụ thể (ví dụ chân cột,
   góc vạch sàn vàng, đế kệ) — **không** chọn pixel sàn trước đống kệ.
2. `scale ≈ 0,67 m/sfm-unit` (median 831+ cặp) là **sanity anchor** để kiểm tra kết
   quả sau khi có cặp do người chọn, không phải giá trị để khóa.
3. **Hệ quả trực tiếp cho `tolerance_m`:** sai số quan sát được lớn hơn nhiều so
   với 0,05m. Tolerance phải suy từ phép đo trên **đúng cặp người chọn**, không từ
   tương ứng tự động ở trên.
4. Cần thêm 1 chỗ nữa mới đạt được `CONFIRMED` thật: **canonical visual
   publication** — adapter similarity REC-05 đã có, nhưng chưa có bản visual
   canonical đã áp transform, và chưa có independent-distance verifier production.

**Evidence:** `data/rec07_axis_evidence_20260927/ab_candidates.png`
(`5fff470e…`) và `scale_depth.py` (script tái lập bảng trên).


## 2. Goal

Xác nhận metric scale cho RGB-only reconstruction và propagate cùng scale/coordinate transform tới pose, visual và geometry artifacts.

## 3. Why This Task Exists

Scene không được physics-ready hoặc approved khi metric scale chưa xác nhận.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Pha xác nhận anchor: REC-03/04 artifacts, thực hiện trước REC-05 metric voxelization.
- Pha final verification: REC-05 geometry, thực hiện trước REC-10 publication.
- Foundation Lock chốt canonical coordinate và real-world anchor; không dùng cùng anchor làm evaluation distance.

Không giữ dependency toàn-task `REC-06 phải đợi REC-05` của arbitrary-unit
OpenMVS flow cũ: pha xác nhận metric/canonical transform là prerequisite cho
primary SplatTransform voxel/capsule theo mét. Chỉ final verification chờ geometry.
Adapter/unit/synthetic qualification REC-05 có thể phát triển song song; không
dùng synthetic fixture để xác nhận scale scene thật.

## 5. Input Contract

- RGB poses, visual và geometry artifacts.
- Geometry chưa bắt buộc ở pha xác nhận anchor, nhưng bắt buộc trước khi hoàn tất
  task. Giữ cùng source identity/transform khi geometry được tạo sau đó.
- Locked real-world anchor và canonical coordinate policy.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Confirmed metric/scale record.
- Canonicalized artifact refs hoặc deterministic conversion records.
- Scale propagation provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/rgb/`
- `src/services/reconstruction/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` anchor workflow và scale propagation; không dùng evaluation geometry/trajectory làm hidden product input.

**Code Donor Reference (Audit #7):**
- [`InternRobotics/Re3Sim`](https://github.com/InternRobotics/Re3Sim) (chi tiết: [`docs/execution/audits/07_re3sim.md`](../../../audits/07_re3sim.md)):
  - Tham khảo `re3sim/utils/frame_tools.py`: Kiến trúc `FrameTools` quản lý frame graph, tách bạch scale (tính từ ma trận determinant), rotation và translation để chuyển đổi giữa các hệ tọa độ.
  - Thuật toán `get_transform_between_two_frames()` (`compute_transform_to_marker_aruco.py`): Ước tính similarity transform $p_B = s R p_A + t$ giữa hai tập trajectories.
  - Đóng góp cho `MetricCanonicalizer` và qualification spike **`REC-QUAL-FRAME-01`**: Chứng minh Brush Visual, REC-05 voxel geometry (hoặc OpenMVS fallback) và Registered LiDAR khi có sau chuẩn hóa đều có chung gốc tọa độ, hệ trục canonical và tỷ lệ mét ($1.0 = 1\text{m}$).
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Không phụ thuộc ChArUco marker**: Re3Sim chỉ là reference. Dùng locked
    product-safe real-world anchor; LiDAR/calibration chỉ tham gia khi contract
    cho phép và có provenance. Không lấy evaluation-only trajectory/geometry làm anchor.
  - ❌ **Scale phải là $1.0 = 1\text{m}$**: Mọi metric transform phải được kiểm định sai số $< 2\text{cm}$ trước khi công bố `ReconstructionBundle`.
  - 📌 **Chiến lược Metric Scale chính thức (xem [ADR 0001](../../../../decisions/0001-metric-scale-strategy-and-roadmap.md)):**
    - *Testing Pipeline & Demo mang tính chất đưa lên hệ thống (`Aisle_CW`):* Tận dụng dữ liệu 3D LiDAR (Ouster OS1-128) có sẵn đã có đơn vị mét chuẩn ($1.0 = 1\text{m}$) để trích xuất khoảng cách vật lý chuẩn xác (calibration anchor) hoặc thông qua quy trình alignment RGB-LiDAR (REC-07/08/09), tuyệt đối không phỏng đoán số liệu.
    - *Ứng dụng thực tế (Khi người dùng gửi video RGB thật của họ):* Bắt buộc hỗ trợ đầy đủ các phương án xử lý, trong đó cốt lõi P0 là luồng **Human-In-The-Loop Known Distance Anchor** (chọn 2 điểm trực tiếp trên 3D Viewport tại Web Studio sau REC-04 và nhập khoảng cách thật để chuyển thành `CONFIRMED`).
    - *Backlog P1 (AI Auto-Scale Assist):* Tích hợp bộ ba `MoGe2Backend` + `ColmapSparseDepthProjector` (từ DN-Splatter) + `RobustScaleAligner` (từ MonoSplat, scale-only $z_{\text{metric}} \approx s \cdot z_{\text{colmap}}$) để tự động điền gợi ý kích thước (`ESTIMATED`) khi hệ thống có GPU CUDA.

## 9. Implementation Plan

### Resume implementation 2026-09-27

Status vẫn IN_PROGRESS. Sửa false final verification theo audit ở active plan:
1. Publish/resolve canonical camera poses với exact confirmation/raw lineage,
   full s/R/t và immutable checksums; không đổi shared schema.
2. Verifier hiện tại chỉ kiểm dependencies/distance math, chưa có canonical visual
   payload và production measurement authority. Không được trả final CONFIRMED.
3. Bắt buộc independent sample và caller-provided tolerance; kiểm geometry bytes
   và full transform provenance, published canonical poses thay vì discard kết quả.
4. Positive/negative fixture tests rồi full track/static checks. Real Aisle_CW
   acceptance và phép đo tolerance vẫn pending, không lấy fixture threshold thay thế.

Tiếp tục sau 99f2399 — canonical visual publication:
- Reuse `SplatTransformSimilarityAdapter` pinned 3.6.6/afbc281 và
  `SplatArtifactProcessor` SOG encode/roundtrip, không viết Gaussian codec mới.
- Inputs: exact confirmation, published canonical poses, explicit product/fixture
  scope. Outputs: immutable metric Gaussian PLY, real SOG bytes, shared
  VisualArtifact metadata và internal checksum-bound publication manifest.
- Giữ shared VisualArtifact producer stage ST-VISUAL-RECON theo contract; record
  conversion/manifest thuộc ST-METRIC-CANONICALIZE. Không tự đổi shared schema.
- Bind source InputManifest checksum từ normalized frame lineage, raw master,
  canonical pose và full transform vào provenance. Không upgrade fixture/demo
  assistance thành real metric/Brush/browser acceptance.
- Proof: native codec trên Gaussian fixture với s/R/t, PLY source bất biến,
  published SOG resolve/roundtrip, tamper/lineage/product-fixture negatives.
  Chưa triển khai Editor authorization UI hoặc final distance approval ở bước này.

Tiếp tục sau 427ab83 — final RGB bundle verification port:
- Bind exact bundle candidate, canonical visual manifest, confirmation, canonical
  poses/geometry, independent sample và explicit tolerance vào checksum review.
- Reuse diagnostic geometry/distance checks + canonical visual/pose consumer
  loaders; kiểm source InputManifest/frame inventory, cùng transform/lineage.
- Publish immutable verification record chỉ sau injected review authority; load
  phải recheck payload và authority. Không default accept, không bật fixture bằng
  product CLI; PRODUCT sở hữu authenticated decision adapter.
- Hỗ trợ canonical RGB geometry selection ở bước này; không ngầm promote native
  LiDAR frame, depth hoặc alternate geometry thành canonical. Mixed alignment
  vẫn phải qua REC-09 loader ở REC-10, không thay bằng final RGB proof.
- Proof: fixture producer→canonical artifacts→verified bundle→SCENE consumer,
  missing/revoked review, source/transform/derivative/tolerance tamper negatives.
  Synthetic authority/codec không thay real measurement/GPU/browser acceptance.

### Owner clarification: ba chế độ demo, 2026-09-26

Triển khai backend chung cho RGB+LiDAR fusion, RGB LiDAR-assisted scale và
RGB chọn hai điểm nhận khoảng cách hỗ trợ từ LiDAR theo ADR 0001. Đây không
phải thay goal RGB-only ngoài đời hoặc acceptance bằng assisted demo.
Ba hướng hệ thống thật vẫn là RGB + measured anchor, RGB + LiDAR, RGB + auto
estimator (future). Adapter này chỉ thay nguồn measurement/scale khi dùng thử
dataset; không thêm LiDAR dependency hoặc automatic demo fallback vào core.

1. Sửa ADR/Integration/Dataset và plan để cả ba mode dùng chung preparation;
   không buộc demo đi theo một shortcut anchor duy nhất.
2. Thêm internal typed measurement record và demo adapter tại
   `src/services/reconstruction/rgb/`: bind source visual/master, registered
   LiDAR ref, scene/traversal, selection/correspondence và preprocessing lineage.
3. Tính khoảng cách từ hai điểm LiDAR đã đối chiếu; injected verifier phải
   xác minh evidence trước preview. Mode chọn điểm không nhận measurement của
   selection khác. Thiếu evidence/verifier thì fail closed, không fake distance.
4. Dùng lại MetricCanonicalizer.preview và acceptance gate; ghi rõ assisted
   provenance ở measurement ref. Chỉ mode fusion trả LiDAR geometry để compose;
   hai mode còn lại không ngầm thay RGB geometry bằng LiDAR geometry.
5. Positive/negative tests cả ba mode qua real fixture store/resolver; giữ
   synthetic label. Không claim real correspondence, Web UI hoặc fusion đã chạy.
6. Tiếp theo chuẩn bị REC-07/08 và REC-09 evidence thật. Không sửa shared
   AlignmentRecord/Transform hoặc implementation EX-PRODUCT trong bước này.

### Bootstrap / Task Capsule 2026-09-26

- Outcome: pha đầu REC-06 bằng fixture — similarity math, scale preview, explicit
  confirmation/provenance và checksum-bound internal handoff. Không xác nhận scale
  Aisle_CW khi chưa có locked anchor và canonical frame evidence.
- Bootstrap: branch `feat/ex-rec`, HEAD `33718fe`, worktree sạch. User đồng ý
  triển khai và tiếp tục commits nhỏ; không push/merge hoặc cập nhật branch từ remote.
- Authority: PRD FR-06 (chọn A/B → khoảng cách thật → preview → user confirm),
  AC-03; Contract §3.1/§4; Dataset Playbook Track A2 (anchor khác evaluation
  distance); Integration §3.3/§4.1; Track Guide REC-06; Architecture EX-REC paths.
- Inputs: published REC-03/04 refs + anchor/frame declarations + acceptance proof.
  Outputs: internal EX-REC preview/confirmation record và deterministic conversion
  provenance. Không sửa shared `MetricScale`, `Transform` hoặc `ReconstructionBundle`.
- Dependencies: REC-03/04 resolvers và injected ArtifactWriter đã có; REC-05 có
  synthetic pipeline. Real anchor/frame/robot inputs, Editor authorization backend
  và final independent-distance protocol chưa có. Fixtures phải gắn nhãn synthetic.
- Owned: `src/services/reconstruction/rgb/`, `tests/test_reconstruction/`, task này
  và checkpoint plan đang có. Do-not-modify: shared contracts, other tracks,
  master PLY, evaluation-only data và task scope/DoD đã khóa.
- Source audit: Re3Sim `681da6f5d842f0de6c573a077926fe3722924708`, root CC BY-NC 4.0;
  `frame_tools.py` chỉ REFERENCE concept `s R p + t`, frame direction, xyzw/wxyz
  boundary. Không copy source hoặc thêm NumPy/SciPy/Torch chỉ để mang frame graph
  vào task. Locked runtime hiện dùng Pydantic 2.13.5; stdlib đủ cho bounded math.
- Một anchor distance chỉ xác định scale, không suy rotation/origin. Canonical
  frame phải explicit và được xác nhận cùng preview. Không auto-align bằng GT.
- Proof trước code: finite positive scale/unit quaternion, nontrivial rotation +
  translation, inverse/pose propagation; missing verifier/acceptance rejected;
  stale preview/source/decision checksum rejected; immutable published record
  resolve được; synthetic record không được consumer nhận như real confirmation;
  applied-transform provenance chặn scale lần hai.
- Sequence: typed math + unit tests → internal record models/validators →
  preview/confirmation/resolver qua existing storage seam → fixture handoff và
  negative tests → full suite/lint/diff review → task evidence, granular commits.
- Boundary: phase này không áp transform lên real Gaussian payload, không expose
  product UI/auth, không final bundle/publication hoặc claim REC-06 DONE.
  Tolerance final theo locked protocol; không tự hardcode ghi chú `<2cm` ở §8
  thành product gate khi PRD §2.2/AC-03 yêu cầu threshold được khóa trước evaluation.

Ordering đã khóa theo Integration §3.3 và ADR 0001:
1. Xác nhận locked real-world anchor và similarity transform từ REC-03/04 (thực hiện trên Visual 3DGS scene trước REC-05); xuất
   confirmation record cho REC-05 tạo metric working derivative.
2. REC-05 chạy voxel/capsule theo mét; giữ master PLY immutable và ghi transform
   checksum trong provenance. Anchor chưa confirmed phải chặn bước này.
3. Đọc geometry và applied-transform provenance; canonicalize pose/visual và
   kiểm tra geometry cùng frame, không scale lần hai. Xác minh bằng khoảng cách
   độc lập trước khi complete REC-06 và cho REC-10 publish.

## 10. Tests

- Scale math/propagation unit tests.
- Missing/unconfirmed anchor negative test.
- REC-05 prerequisite handoff và geometry đã metric không bị scale lần hai.
- Known-distance fixture and artifact metadata contract test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Scale status chỉ CONFIRMED khi anchor workflow hoàn tất.
- [ ] Pose/visual/geometry dùng cùng scale và canonical metadata.
- [ ] Independent test distance chứng minh tolerance theo locked protocol.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Resume 2026-09-27 — canonical camera pose publication

- `rgb/canonical/canonical_poses.py`: immutable content-addressed derivative, giữ nguyên
  intrinsics và inventory; áp full s/R/t lên camera centers/orientations. Không
  sửa raw pose manifest. Resolver kiểm checksum, identity/provenance, confirmation
  authority và recompute payload từ exact raw source; rehash payload sai vẫn bị chặn.
- `.venv/bin/pytest tests/test_reconstruction/test_rec06_canonical_poses.py -q`:
  **9 passed** (4.03s). Ruff check/format và AST ≤30 dòng/≤3 params/return types
  cho hai file mới pass. Đây là fixture authority + real artifact store, không
  phải real Aisle_CW confirmation hay full bundle acceptance.
- Lần test đầu phát hiện assertion dùng sai exception type của store, rồi import
  nhầm facade chưa export error; đã sửa test sang exact `ArtifactChecksumError`,
  không swallow hoặc sửa behavior storage để làm test pass.
- Next: verifier dùng artifact đã publish này, bỏ false final CONFIRMED; canonical
  visual publication và production distance/approval adapter vẫn chưa hoàn thành.

### Resume 2026-09-27 — verifier không cấp false final confirmation

- `MetricVerificationService` nhận published canonical pose manifest thay raw
  poses rồi convert/discard trong memory. Bắt buộc independent sample và explicit
  finite positive tolerance; không còn implicit 0.05m.
- Check exact raw visual ref; resolve và parse collision GLB, kiểm producer/job,
  full s/R/t, source master, confirmation ref, coordinate/evidence provenance.
  Measurement payload cũng phải resolve đúng checksum. Việc đo có authority và
  tolerance đã được owner khóa hay chưa **không** được suy từ opaque bytes.
- Internal request/report version **1.1**, report luôn
  `PENDING_FINAL_VERIFICATION`, scope `canonical_poses_geometry_lineage_distance_math`;
  bỏ trường metric_scale CONFIRMED sai. Đây không phải shared schema change;
  source search cho thấy consumer hiện tại chỉ nằm trong EX-REC tests. Không
  wire report này làm REC-10 `verify_metric` hoặc worker authorization.
- `.venv/bin/pytest tests/test_reconstruction/test_rec06_final_verification.py -q`:
  **23 passed** (10.64s). Positive scoped report + negatives cho missing sample,
  tolerance, corrupt/malformed geometry, lineage, raw/other-confirmation poses,
  reused calibration pair. Ruff và AST checks changed files pass.
- Canonical visual publication/verification và real independent evidence vẫn là
  next implementation, không tuyên bố REC-06 DONE.

### Resume 2026-09-27 — chặn derivative namespace sai job + native visual proof

- `metric.py::load` nay gọi `_require_job_identity`: confirmation ref phải có `job_id`
  và `artifact_uri` phải trỏ đúng job đó. Trước đó `CanonicalPoseService.build` lấy thẳng
  `job_id` để dựng URI, nên `job_id=None` ra `artifact://jobs/None/...` còn job khác vẫn ghi
  derivative sang namespace của job khác. Guard đặt ở loader vì mọi consumer REC-06
  (canonical poses, canonical visual, metric verification) đều đi qua đây, theo đúng
  convention đã có ở `metric_verification.py:89-92` và `bundle_validation.py:32`.
- Negative proof: `test_confirmation_job_identity_is_required[None|another-job]` ở
  `test_rec06_canonical_poses.py` (test đã viết trước, 2 case đỏ trước khi có guard) và
  `test_confirmation_ref_requires_consistent_job_identity` ở `test_rec06_confirmation.py`
  khoá invariant ngay tại layer owner. Không sửa test để xanh, không nới guard.
- Canonical visual publication WIP đã verify với **codec thật**:
  `test_native_metric_ply_and_sog_publication` chạy `splat-transform` 3.6.6 thật, áp
  s=2/Rz90/t=(10,20,30) lên 256 Gaussian, đọc lại SOG bytes thật (`PK`), raw master PLY
  không đổi. Đây là codec proof, **không** phải browser QA hay Brush acceptance.

**Validation do agent bàn giao ghi nhận trước Codex resume từ 56f987b**

- `.venv/bin/pytest tests/test_reconstruction/ -q` → **380 passed, 21 skipped** (89,10s),
  0 failed. Trước đó: 2 failed, 376 passed, 21 skipped.
- Cùng suite với real codec + GPU opt-in
  (`REC04_TEST_SPLAT_MODULE`/`REC05_TEST_SPLAT_MODULE` →
  `data/rec04_runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs`,
  `REC05_TEST_GPU=1`, `REC05_VOXEL_CLI` → `bin/cli.mjs`, `REC05_VOXEL_MODULE_PATH` →
  `dist/index.mjs`) → **401 passed, 0 skipped** (112,44s).
- `.venv/bin/ruff check src/ tests/ scripts/torwic` pass; `ruff format --check` 191 files
  unchanged; `git diff --check` pass; AST check 7 file (≤30 dòng/≤3 non-self params/
  typed args+return) → 0 vi phạm.
- `.venv` vẫn thiếu `numpy` → `pytest tests/` vẫn dừng collection ở EX-SIM
  `tests/test_simulation/test_colliders.py`. Lỗi môi trường, ngoài ownership EX-REC.

**Limits / next**

- Codex rerun sau resume (không dựa vào kết quả agent khác): full EX-REC với
  `REC04_TEST_SPLAT_MODULE=.../dist/index.mjs`, `REC05_TEST_SPLAT_MODULE` và
  `REC05_VOXEL_MODULE_PATH` trỏ package root, `REC05_VOXEL_CLI=.../bin/cli.mjs`,
  `REC05_TEST_GPU=0`: **399 passed, 2 skipped (449.19s)**. Package được dùng là
  `data/rec04_runtime/node_modules/@playcanvas/splat-transform`. Hai GPU cases
  được tắt chủ động; native CPU codec vẫn chạy. Canonical visual producer đã
  hoàn tất ở boundary derivative, không còn chỉ là plan; final verification
  và real dataset acceptance vẫn pending.
- Canonical visual publication vẫn là **metric derivative**, không phải final
  `CONFIRMED`; chưa có Editor authorization UI, chưa có production metric verifier.
- A/B points và `tolerance_m` vẫn chờ người chọn như `41ca8eb` ghi; không lấy sanity
  anchor `≈0,67 m/sfm-unit` hay số `0.05` làm authority.
- REC-06 giữ `IN_PROGRESS`. Full worker dispatch (`InputManifest`/`JobManifest`) + retry và
  real alignment REC-09 chưa đụng.

### Final RGB metric bridge sau 427ab83 — implementation/fixture proof

- `bundle_metric_models.py` + `bundle_metric.py`: canonical RGB bundle candidate
  bind exact refs/config/provenance với independent sample/tolerance; injected
  reviewer phải xác minh authenticated decision + measurement protocol. Không
  có mặc định accept hoặc default tolerance. Review bị thu hồi, payload hỏng hoặc
  caller tráo artifact sau review đều không publish được bundle.
- Native canonical visual/pose loaders và diagnostic geometry/distance verifier
  được reuse. Proof record có status VERIFIED và scope `canonical_rgb_bundle_metric`,
  không phải physics/Isaac proof; product deployment từ chối fixture scope.
- `BundleDependencies.verify_metric=verifier.verify_bundle` là composition seam
  cho REC-10. CLI cũ chưa được cấp PRODUCT authority adapter nên vẫn fail closed;
  không thêm CLI flag fake approval. Mixed alignment vẫn do REC-09 loader kiểm riêng.
- Fixture chain producer→canonical visual/poses→geometry→final proof→bundle→SCENE
  consumer chạy không remap output refs hoặc sửa artifact bằng tay. Đây là fixture
  orchestration/payload contract proof, không real measurement/GPU qualification.
- `.venv/bin/pytest tests/test_reconstruction/test_rec06_bundle_metric.py -q`:
  **19 passed (76.72s)**. Sau refactor helpers, regression REC-06 bridge + preview
  + REC-10 + REC-11 với `REC04_TEST_SPLAT_MODULE` trỏ pinned dist/index.mjs:
  **64 passed (137.11s)**. Ruff check/format EX-REC source/tests: **104 files pass**;
  AST changed modules/tests ≤30 lines, ≤3 non-self params, typed args/returns pass.
- Scope hiện tại chỉ canonical RGB geometry selection, chưa sensor depth hoặc
  alternate LiDAR canonical geometry. Real measurement/frame confirmation,
  tolerance, seed/collision qualification và full dispatch vẫn pending.

### Checkpoint 2026-09-26 — DONE, final cross-artifact verification

Historical claim, **superseded by 2026-09-27 audit**: status CONFIRMED của report
cũ không chứng minh canonical visual/published poses hay independent measurement.
Không dùng checkpoint này để đóng task hoặc cho phép real bundle publication.

**Implemented / VERIFIED:**
- `src/services/reconstruction/rgb/canonical/metric_verification.py`:
  - `CrossArtifactVerificationRequest`: yêu cầu kiểm định chéo metric scale giữa `RGBMetricConfirmation`, `VisualArtifact`, `RgbGeometry` và `CameraPoseArtifact`.
  - `MetricVerificationService`:
    - Thẩm định `RgbGeometry` mang đúng `applied_confirmation_checksum` và `scale_applied`, loại bỏ rủi ro double-scaling.
    - Thẩm định `VisualArtifact` mang đúng master PLY ràng buộc với distance anchor.
    - Chuyển đổi và chuẩn hóa camera poses sang canonical world Z-up mà không double scaling.
    - Kiểm định mẫu khoảng cách độc lập (`independent_sample`) qua `independent_distance_error`, đảm bảo sai số nằm trong dung sai khóa (`tolerance_m`).
  - `CrossArtifactVerificationReport`: xuất báo cáo nghiệm thu khẳng định metric scale đã `CONFIRMED` với $1.0 = 1\text{m}$.
- `tests/test_reconstruction/test_rec06_final_verification.py`:
  - 4/4 test cases pass: nghiệm thu thành công, đối chiếu khoảng cách độc lập đạt dung sai, từ chối khi sai số vượt ngưỡng dung sai, từ chối geometry artifact không khớp confirmation provenance.
- Bộ test suite REC-06 tổng thể: **88 passed** (38.15s).

### Checkpoint demo adapter — 2026-09-26


- User khóa ba system paths giữ nguyên: RGB + measured anchor, RGB + LiDAR,
  RGB + future auto-estimator. LiDAR hỗ trợ chỉ thuộc dataset demo adapter.
- Added `rgb/canonical/demo_metric_models.py`, `rgb/canonical/demo_metric.py`: bắt buộc explicit
  `prepared_dataset_demo`, ba modes `rgb_lidar_fusion`, `rgb_auto_scale_proxy`,
  `rgb_two_point`. Prepared measurement chứa RGB/LiDAR pair và exact refs;
  injected verifier xác minh physical correspondence/scene/frame/unit, không có
  default verifier. Preview không tự cấp CONFIRMED. Two-point selection chưa
  được map thì reject; không dùng nearest point tùy ý hoặc measurement cũ.
- Chỉ fusion trả geometry input để compose; đó chưa là fused output. Hai modes
  RGB giữ RGB geometry và assisted provenance. Core `metric.py`, shared contracts
  và frontend không đổi. Actual source/correspondence solver và demo UI chưa có.
- `tests/test_reconstruction/support/rec06_demo_fixtures.py` và
  `test_rec06_demo_metric.py`: 35 new fixture cases, store/resolver thật,
  synthetic correspondence/authority. Có GT-lineage, immutable publish,
  wrong scene/selection, source-byte tamper, missing verifier và normal-upload
  rejection. Không chứng minh real dataset accuracy, fusion hoặc auto-estimator.
- `.venv/bin/pytest tests/test_reconstruction/test_rec06_*.py -q` → **84 passed**
  (42.12s). `.venv/bin/pytest tests/test_reconstruction/ -q` → **242 passed,
  11 skipped** (53.30s), không bật optional real codec/GPU env ở checkpoint này.
- `.venv/bin/ruff check src/ tests/` pass;
  `.venv/bin/ruff format --check src/ tests/` pass, 140 files unchanged;
  `git diff --check` pass. AST check bốn file mới: functions <=30 lines,
  <=3 non-self parameters và typed args/returns.
- `.venv/bin/pytest tests/ -q` → **collection error**, EX-SIM
  `test_colliders.py` thiếu NumPy trong `.venv`. Không claim full repo green.
- Next: REC-07/08 prepared LiDAR + REC-09 correspondence producer; actual
  geometry/alignment/metric payload handoff và EX-PRODUCT integration còn pending.
  REC-06 giữ IN_PROGRESS. `ff875ba` lưu quyết định demo/system và dependency.

### Checkpoint 2026-09-26 — pha đầu triển khai, IN_PROGRESS

**VERIFIED implementation**

- `rgb/canonical/metric_math.py`: finite positive scale từ distance anchor, explicit
  `p_world = s R p_sfm + t_m`, unit quaternion xyzw, inverse và canonical camera
  pose derivative. Camera center được scale; orientation được compose đúng thứ tự,
  không scale quaternion/intrinsics hoặc mutate raw pose.
- `rgb/canonical/metric_models.py`: internal EX-REC `MetricRequest`, `MetricPreview`,
  `MetricAcceptance`, `MetricConfirmation`, `MetricConversionPlan`. Preview luôn
  `UNCONFIRMED`; record scope chỉ `anchor_and_frame_only`. Không sửa shared schema
  hoặc tự cho whole scene/bundle `CONFIRMED`/physics-ready.
- `rgb/canonical/metric.py`: consume published REC-03/04 refs qua existing `VisualResolver`;
  verify master/measurement/frame/decision bytes và lineage. Confirm/publish/load
  đều cần injected acceptance verifier; default không có verifier nên fail closed.
  Content-addressed record path và existing atomic ArtifactWriter giữ revisions
  bất biến. Typed `CONFIRMED` hoặc checksum tự nó không phải Editor authorization.
- Synthetic records có nhãn trong payload và ref provenance; `require_real()`
  reject fixture confirmation. `conversion_plan()` chỉ trả plan có
  `payload_converted: false`, source refs, confirmation checksum, transform và
  shared canonical CoordinateSystem. Input ngoài raw dependency hoặc đã có
  applied-record checksum đều bị reject để tránh double scaling.
- `rgb/canonical/metric_seed.py` + `propose_navigation_seed()`: lấy camera đầu **registered**,
  áp confirmed transform, trả source pose/frame/checksum và point trong world.
  Luôn `UNVALIDATED`, `capsule_clearance_verified: false`. Test riêng cho trường
  hợp frame đầu registered là 7; không giả định Frame 0 luôn tồn tại. Chưa tự nối
  candidate này vào carving trước validation bounds/capsule.
- Local independent-distance helper reject dùng lại calibration anchor kể cả
  đảo A/B và đổi ID; không đặt acceptance threshold. Actual independent evidence
  và locked protocol vẫn cần để nghiệm thu task.

**Proof và reproducibility**

```bash
.venv/bin/pytest tests/test_reconstruction/test_rec06_*.py -q
.venv/bin/python -m tests.test_reconstruction.smoke.rec06_smoke --output data/rec06_smoke/fixture-20260926-02
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
git diff --check
```

- Focused REC-06: **49 passed** (20.20s), gồm numeric/unit, actual immutable store
  round-trip, missing/denied/stale acceptance, missing frame, eval-only input,
  source/decision/record tamper, mismatched pose lineage, double scaling, numeric
  collapse/overflow và storage failure. Reconstruction/authority trong các tests
  là fixture; resolver/store và domain logic là implementation thật.
- Fixture smoke exit 0, local ignored evidence tại
  `data/rec06_smoke/fixture-20260926-02/evidence.json`, `conversion-plan.json`
  và `seed-proposal.json`; attempt `-01` giữ lịch sử trước khi thêm seed proposal.
  confirmation bytes được published trong fixture artifact store bằng logical URI.
  Script cần output directory mới nếu rerun, không overwrite attempt cũ.
- Known fixture: scale `2`, rotation `Rz(90°)`, translation `(10,20,30)m`;
  sample `(1,2,3) → (~6,22,36)`. Independent fixture segment dự đoán `0.50m`,
  khai báo measured `0.51m`, absolute error `0.01m`. Đây là test cố ý có sai số,
  không là measurement hay accuracy claim của Aisle_CW.
- Record logical checksum:
  `sha256:616670d81c902147e14eafa8c1707e723f32750b806ae60bd61599348c1f8506`.
  Serialized record byte checksum:
  `sha256:2d4df4597602ad2216bb39f282a0c349294bea1f667b1715678b8a597611e1b6`.
- Full suite trước concurrent merges: **333 passed** (31.72s), với
  `REC04_TEST_SPLAT_MODULE` và `REC05_TEST_SPLAT_MODULE` cùng trỏ tới installed
  `data/rec04_runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs`,
  `REC05_TEST_GPU=1`, `REC05_VOXEL_CLI` trỏ tới package `bin/cli.mjs` và
  `REC05_VOXEL_MODULE_PATH` trỏ tới `dist/index.mjs`. Không auto-install runtime.
- **Sau merge `5c0f20d`: full suite không pass.** Cùng command/env
  `.venv/bin/pytest tests/ -q` dừng collection (exit 2):
  `tests/test_simulation/test_colliders.py` import NumPy nhưng `.venv` thiếu `numpy`.
  Không tự cài dependency hoặc sửa code EX-SIM ngoài scope.
- Rerun `.venv/bin/pytest tests/test_reconstruction/ tests/test_contracts/ -q`
  cùng env: **295 passed, 2 failed** (42.54s). Hai lỗi tại
  `tests/test_contracts/test_identity.py` là scene/edited_scene content checksums.
  Diff merge thêm `SceneObject.semantic_class=None`, `tags=[]` vào shared model;
  serialized defaults đổi content hash. Read-only counterfactual bỏ hai field này
  khỏi in-memory dumps của hai fixtures cho checksum khớp lại. Không sửa expected
  checksum hoặc shared schema chỉ để test xanh; cần owner xử lý migration/fixtures.
- Ruff check pass; format check 136 files unchanged trên merged checkout.
- Toàn bộ EX-REC sau merge và sau seed proposal, với real REC-04/05 codec + GPU
  env như trên: `.venv/bin/pytest tests/test_reconstruction/ -q` → **218 passed**
  (43.95s). Đây là track result, không thay kết quả full-suite bị lỗi nêu trên.

**Concurrent updates / authority audit**

Lưu ý recovery: diễn giải ở checkpoint dưới về một shortcut LiDAR anchor duy
nhất đã được owner làm rõ lại. Xem §9 và ADR 0001 hiện hành: ba system paths giữ
nguyên, chỉ demo dataset dùng LiDAR hỗ trợ anchor/estimator proxy. Không dùng
đoạn lịch sử này để bỏ fusion hoặc thay real RGB-only bằng LiDAR-assisted.

- Trong execution, branch được cập nhật ngoài lượt implementation này bằng
  `bbf3bf5`, `3c96276`, `cc385cc`, `5c0f20d`: ADR 0001, task/documentation và
  SCENE/SIM changes. Re-read ADR/task/diff tại `5c0f20d`; không reset/revert/pull
  hoặc ghi đè các thay đổi đó. EX-REC source/tests của checkpoint này không bị đổi.
- ADR 0001 §Decision 1 cho phép hướng LiDAR-assisted **testing/demo**;
  Dataset Playbook Track A2 vẫn cấm reconstruction runtime đọc raw LiDAR/GT.
  Đọc hai nguồn này như hai bước khác nhau: đo anchor ngoại tuyến có provenance,
  rồi RGB runtime nhận locked anchor. Không tự dùng cả map để dự đoán hoặc claim
  RGB-only independent result. User đã được giải thích bằng ví dụ “LiDAR như
  thước đo cùng hai chân cột” và đồng ý; ADR/Integration đã làm rõ boundary này.
- ADR 0001 §Decision 1 và REC-05 §9 nói camera Frame 0 bảo đảm free/walkable và
  không skip carve. Source `splat-transform` 3.6.6 `voxel/carve.ts` thực tế kiểm
  capsule-dilated occupancy, có relocate hoặc skip khi blocked/outside. Camera
  center không chứng minh clearance của cả capsule; Frame 0 còn có thể unregistered.
  Owner đã đồng ý sửa rule: camera đầu registered, convert metric/world làm
  **candidate**, kiểm bounds/capsule bắt buộc, invalid thì reject hoặc chọn lại.
  ADR/REC-05 đã cập nhật theo quyết định đó; code mới chỉ tạo proposal, không auto-pass.
- REC-05 §9 nay có demo capsule `radius=0.35m`, `height=1.20m`. Đây là config
  trong task; không tự claim đó là kích thước thật đã đo của OTTO 100. Isaac Sim
  `4.0` và số `205 tests` trong phân tích ngoài không là verified runtime evidence.

**Limits / next executable step**

1. Giữ REC-06 `IN_PROGRESS`, chưa DONE. Không tạo Aisle_CW real confirmation;
   chưa có cặp landmark correspondence RGB–LiDAR đã review, đo anchor, canonical
   frame evidence hoặc independent-distance protocol thật.
2. Authenticated Editor decision backend/UI thuộc EX-PRODUCT chưa được nối;
   fixture verifier không dùng cho product. `preview()` không tự cấp confirmation.
3. Tiếp theo ở phần không phụ thuộc seed: adapter áp confirmed transform lên
   immutable Gaussian working derivative, giữ orientation/scale/SH đúng upstream,
   bind applied-transform provenance rồi nối REC-05. Conversion plan hiện không
   phải artifact đã convert; chưa có real producer→consumer payload handoff này.
4. Seed candidate đã implement theo owner clarification; actual capsule clearance
   validation và consumer binding còn pending. Chưa import raw LiDAR vào product
   runtime, chưa mở REC-07 hoặc triển khai
   P1 AI auto-scale. REC-07 độc lập theo dependency của task, không bắt buộc đợi
   toàn REC-06 DONE chỉ vì số thứ tự.

Commits: `fc5093e` bootstrap → `590a5a8` math/poses → `b07c322` confirmation/
provenance → `5c7c732` guards → `b80c3d9` fixture smoke → `f823f99` seed rule
clarification → `b1ed5d8` typed camera seed proposal → `9643125` seed smoke evidence
→ `7f15874` LiDAR anchor boundary. Không push từ lượt này.
