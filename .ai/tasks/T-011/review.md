# Review T-011

Verdict: ACCEPTED

**Lưu ý về tính độc lập:** Architect đã tự viết một phần task này khi agent Codex hết quota (bước 2 `07166cbf`, các hàm
`rebuild_region_ready`/`validate_region_rebuild` được gộp vào `67465cdb`, và route bước 4 được agent dùng nguyên trong `8c452297`).
Vì vậy review dựa vào test thay vì đánh giá code của chính mình. Chủ dự án có thể nhờ agent khác review lại nếu muốn.

Chạy lại Tests required + `test_objectgs_objectify_flow.py`, `test_objectify_draft.py`, `test_shell_geometry_walk_usd.py`:
208 passed, không skip.

## Acceptance criteria
0. Vật bị ảnh hưởng ở trạng thái IGNORED/DELETED/MERGED vẫn được dựng: **pass** (`test_partial_membership_build_keeps_other_geometry_and_uses_shell`,
   tham số hoá theo review).
0b. ObjectGS + rebuild một phần dùng vỏ, `reason = partial_rebuild_uses_shell`, vật khác giữ surface ObjectGS: **pass** (cùng test, `method=objectgs`).
1. Chỉ vật bị sửa có collider mới; vật khác giữ nguyên ref; môi trường + membership mới; một revision: **pass**
   (`test_ready_region_edit_rebuilds_only_the_edited_object_and_the_environment`).
2. Không gọi ObjectGS khi `shell`: **pass** (`test_shell_method_never_runs_objectgs`).
3. Claim từ B dựng lại cả A và B: **pass** (`test_claimed_object_is_rebuilt_with_the_edited_object`, `test_ready_region_claim_rebuilds_both_owners_...`).
4. Lỗi/huỷ/revision lệch/dưới 50 Gaussian → head giữ nguyên: **pass** (`test_failed_region_rebuild_keeps_the_ready_head`).
5. Brush/Lasso (`membership/regenerate`) đi qua builder mới: **pass** (`test_brush_correction_uses_real_partial_builder_and_preserves_other_objects`);
   ràng buộc "chỉ ObjectGS" đổi thành "scene phải Ready" (`test_membership_queue_accepts_ready_shell_without_objectgs_marker`).
6. `ObjectifyState.mode = "region"`, lưu lệnh bền, phase, fence: **pass** (`test_region_queue_durable_command_progress_and_fencing`); route 202 có test.

## Ghi chú cho T-019 / handoff
- Đường cũ `objectify(correction=…)` không còn được gọi; để dọn sau (plan cho phép).
- Rebuild một phần không sinh `object_pipeline_evidence` như lần tách đầy đủ; evidence là `membership_correction.evidence_ref`.
  Ghi vào handoff phần "khác với hệ chẩn đoán cũ".
