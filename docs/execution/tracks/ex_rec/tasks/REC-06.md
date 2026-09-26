# REC-06 — RGB Metric Scale

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | `@awun0105` |
| Target milestone | `M2` |

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

- [ ] Scale status chỉ CONFIRMED khi anchor workflow hoàn tất.
- [ ] Pose/visual/geometry dùng cùng scale và canonical metadata.
- [ ] Independent test distance chứng minh tolerance theo locked protocol.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

### Checkpoint 2026-09-26 — pha đầu triển khai, IN_PROGRESS

**VERIFIED implementation**

- `rgb/metric_math.py`: finite positive scale từ distance anchor, explicit
  `p_world = s R p_sfm + t_m`, unit quaternion xyzw, inverse và canonical camera
  pose derivative. Camera center được scale; orientation được compose đúng thứ tự,
  không scale quaternion/intrinsics hoặc mutate raw pose.
- `rgb/metric_models.py`: internal EX-REC `MetricRequest`, `MetricPreview`,
  `MetricAcceptance`, `MetricConfirmation`, `MetricConversionPlan`. Preview luôn
  `UNCONFIRMED`; record scope chỉ `anchor_and_frame_only`. Không sửa shared schema
  hoặc tự cho whole scene/bundle `CONFIRMED`/physics-ready.
- `rgb/metric.py`: consume published REC-03/04 refs qua existing `VisualResolver`;
  verify master/measurement/frame/decision bytes và lineage. Confirm/publish/load
  đều cần injected acceptance verifier; default không có verifier nên fail closed.
  Content-addressed record path và existing atomic ArtifactWriter giữ revisions
  bất biến. Typed `CONFIRMED` hoặc checksum tự nó không phải Editor authorization.
- Synthetic records có nhãn trong payload và ref provenance; `require_real()`
  reject fixture confirmation. `conversion_plan()` chỉ trả plan có
  `payload_converted: false`, source refs, confirmation checksum, transform và
  shared canonical CoordinateSystem. Input ngoài raw dependency hoặc đã có
  applied-record checksum đều bị reject để tránh double scaling.
- `rgb/metric_seed.py` + `propose_navigation_seed()`: lấy camera đầu **registered**,
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
.venv/bin/python -m tests.test_reconstruction.rec06_smoke --output data/rec06_smoke/fixture-20260926-02
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
