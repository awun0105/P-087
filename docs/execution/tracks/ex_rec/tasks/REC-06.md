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

Pending implementation.

Expected evidence:

- Anchor/confirmation record.
- Before/after distance evidence.
- Config/checksum và scale error measurement.
