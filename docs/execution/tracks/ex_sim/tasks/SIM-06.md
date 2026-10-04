# SIM-06 — Isaac Validation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M1/M2/M4` |

## 2. Goal

Load exact candidate in Isaac and record observed load, metric, spawn, collision, penetration and path results.

## 3. Why This Task Exists

AC-08 requires runtime evidence before human review.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-01 locked runtime smoke.
- SIM-05 exact CandidatePackage.
- Locked robot footprint and Start–Goal configuration.

## 5. Input Contract

- Immutable CandidatePackage/checksum.
- Product-visible path config; locked expected labels remain evaluator-only for acceptance.
- `REQUIRED_ROUTE_BLOCKED` chỉ áp dụng khi ordinary product config công khai đánh dấu route đó là required; rule này không thuộc static preflight và không được suy ra từ hidden expected label.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Observed check/path evidence bound to candidate checksum.
- Per-pair CLEAR/BLOCKED/ERROR with reason/evidence.
- Replay MP4, screenshots và logs của đúng candidate/run được publish thành
  artifact refs/checksums khi capture thành công; capture error được báo riêng.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/isaac/`
- `src/services/simulation/validation/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` worker on Isaac/IsaacLab APIs; do not read hidden expected labels inside generic validator.
Native Omniverse MP4 capture là đường chính. Frame capture → FFmpeg chỉ là
fallback khi native không chạy trong locked Isaac runtime; ghi rõ lý do đổi
đường capture và version của extension/encoder liên quan.

**Code Donor Reference (Audit #3 & #5):**
- Candidate integration donor: [`zst1406217/VR-Robo`](https://github.com/zst1406217/VR-Robo) (xem chi tiết tại [`docs/execution/audits/03_vr_robo.md`](../../../audits/03_vr_robo.md)).
- Candidate visual/physics sync reference: [`discoverse-dev/DISCOVERSE`](https://github.com/discoverse-dev/DISCOVERSE) (xem chi tiết tại [`docs/execution/audits/05_discoverse.md`](../../../audits/05_discoverse.md)).
- Core patterns đáng adapt (**`ADAPT-HIGH`**):
  - **Runtime Execution**: Load Candidate USD (`UsdFileCfg`), spawn robot, sensor attachment, simulation stepping loop từ `vrrobo_isaaclab`.
  - **Replay Video Fallback**: Tận dụng pattern `gym.wrappers.RecordVideo` khi môi trường headless gặp vấn đề với native viewport capture.
  - **Visual ↔ Physics Separation & Binding**: Phân tách rõ ràng process giữa physics simulation (IsaacLab) và visual preview (3DGS). Tham chiếu mô hình `gs_model_dict` của DISCOVERSE: ánh xạ khóa ổn định `SceneObject.object_id` giữa visual asset (`visual_ref`) và physics body (`body_id`).
  - **Remote Streaming Transport (P1 Candidate)**: Phân hệ `gaussian_web_renderer` (`ZeroMQ` + binary numpy-like payload + hardware `NVENC` H.264 stream) từ DISCOVERSE sạch hơn và an toàn hơn hẳn giao thức TCP pickle của VR-Robo.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **Không dùng RPyC + pickle network**: VR-Robo dùng RPC port 18861 và pickle serialization qua raw TCP. Đây là lỗ hổng bảo mật nghiêm trọng; dự án bắt buộc dùng process-local IPC hoặc artifact-based exchange.
  - ❌ **Không copy nguyên renderer Inria**: Code renderer dính Inria non-commercial license.
  - ❌ **Không hard-code camera/axes convention**: Toàn bộ camera pose synchronization phải đi qua `CoordinateSystem` canonical contract.
  - ❌ **Remote visual stream không thay thế ValidationReport**: Luồng stream H.264 (DISCOVERSE) chỉ chứa RGB và lược bỏ Depth; do đó nó chỉ đóng vai trò visual evidence/preview (P1), tuyệt đối không dùng để suy luận physics truth hay thay thế structured validation từ Isaac.

## 9. Implementation Plan

1. Thiết lập worker load Candidate USD vào IsaacLab sử dụng `UsdFileCfg`.
2. Khởi tạo robot footprint và sensor listeners (contact, collision, raycast).
3. Thực thi validation run loop cho từng Start–Goal pair; ghi nhận trạng thái CLEAR/BLOCKED/ERROR.
4. Ghi video replay bằng native capture (hoặc `RecordVideo` fallback) và publish artifact.
5. Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Path result/error mapping unit tests.
- Candidate checksum mismatch and ERROR-as-pass negative tests.
- Real smoke with one CLEAR/one BLOCKED; acceptance observes 5/5 pairs.
- Real candidate capture/publish/readability check; lỗi capture/publish không
  được đổi observed validation PASS/FAIL hoặc CLEAR/BLOCKED/ERROR.
- Native failure → fallback test nếu cần; missing/corrupt media và checksum
  mismatch phải được báo riêng, không được giả làm valid evidence.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Exact candidate loads and all required runtime checks execute.
- [ ] Every configured pair has observed CLEAR/BLOCKED/ERROR; ERROR is never pass.
- [ ] Required-route blocking chỉ được đánh giá từ product-visible required-route config.
- [ ] Worker output contains no hidden evaluation comparison.
- [ ] Ít nhất một real candidate validation run có replay MP4, screenshots và
  logs đã publish với ref/checksum/provenance đúng candidate/run; ordinary run
  thiếu replay báo warning/error riêng, không sửa kết quả simulator validation.
  Primary Demo E2E acceptance được kiểm tra riêng tại PRODUCT-12.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Isaac logs/screenshots/video.
- Native capture command/config/version, MP4 readability và published refs;
  fallback proof chỉ khi native thất bại.
- Per-check/per-pair observed evidence.
- Load/spawn/path failure samples.
