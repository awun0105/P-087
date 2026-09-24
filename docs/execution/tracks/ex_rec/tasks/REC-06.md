# REC-06 — RGB Metric Scale

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M2` |

## 2. Goal

Xác nhận metric scale cho RGB-only reconstruction và propagate cùng scale/coordinate transform tới pose, visual và geometry artifacts.

## 3. Why This Task Exists

Scene không được physics-ready hoặc approved khi metric scale chưa xác nhận.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03/04/05 artifacts.
- Foundation Lock chốt canonical coordinate và real-world anchor; không dùng cùng anchor làm evaluation distance.

## 5. Input Contract

- RGB poses, visual và geometry artifacts.
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
  - Đóng góp cho `MetricCanonicalizer` và qualification spike **`REC-QUAL-FRAME-01`**: Chứng minh Brush Visual, OpenMVS Geometry và Registered LiDAR sau chuẩn hóa đều có chung gốc tọa độ, hệ trục canonical và tỷ lệ mét ($1.0 = 1\text{m}$).
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Không phụ thuộc ChArUco marker**: Re3Sim dùng marker vật lý để lấy metric ground-truth. Real2Sim Studio tại kho bãi TorWIC dựa trên LiDAR và calibration camera/sensor có sẵn.
  - ❌ **Scale phải là $1.0 = 1\text{m}$**: Mọi metric transform phải được kiểm định sai số $< 2\text{cm}$ trước khi công bố `ReconstructionBundle`.

## 9. Implementation Plan

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Scale math/propagation unit tests.
- Missing/unconfirmed anchor negative test.
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

