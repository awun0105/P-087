# Review T-019 (Architect)

Verdict: CHANGES REQUESTED — chưa đóng được; phần đã làm đạt.

Đọc `report.md`, `review.md` (deep review của engineer), diff chưa commit của `object_geometry_build.py`, `region-overlay.ts`,
`shell-glow.ts`; kiểm lại GR-01 trên source (`object_geometry_build.py:545` bỏ count; validator `representation_integrity.py:52-73`
đọc 0). GR-02 khớp source `region-session.ts:31`, `object_geometry_build.py:818` (`ptp`, tâm không lưu).

## Đạt
- Full regression đã chạy với số thật, không cộng dồn hai lần chạy; failure được nêu rõ.
- Guard partial build trên Draft (`object_geometry_build.py:612`) đúng: `object_ids` chỉ hợp lệ khi Ready. Có test head/artifact không đổi.
- Test package thật cho scene vỏ (yêu cầu từ T-018) đã có.
- Deep review chất lượng tốt: mỗi phát hiện có source, probe, hướng sửa, acceptance. Đây là lỗi tôi bỏ sót ở review T-018 (GR-01:
  test khi đó dùng inpaint 0) và T-016 (GR-02).

## Required changes
1. **Commit** toàn bộ việc T-019 theo nhóm nhỏ (guard + test; palette; test package; handoff; evidence + report). Hiện chưa commit.
2. Palette: vỏ dùng `--studio-sage`, trùng tông với điểm "thêm". Giữ token, nhưng ghi vào handoff là cần nhìn bằng mắt; nếu khó
   phân biệt sẽ thêm token riêng ở task sau. Không chặn.
3. Lỗi mở được tách thành task: GR-01 → **T-022**, GR-02 → **T-023**, GR-03/04/06 → **T-024**, GR-05 → **T-025**. Thêm T-021
   (tiến trình/chuông hiểu Draft). Ghi vào handoff mục "Việc còn mở" với ID task.
4. **Round 2 của T-019** sau khi T-021–T-025 accepted (thứ tự: T-023 → T-024 → T-021 → T-025): chạy lại full backend **một lần trên source cuối**,
   full frontend, lint/typecheck/mirror; cập nhật số trong report và handoff. Test budget 300k: nếu T-025 chưa xong, ghi là
   failure đã biết, có task theo dõi (đúng tiêu chí 1 của plan).

## Thứ tự trước khi chạy scene demo
T-022 → T-023 → T-024 → T-021 → T-025 → T-019 round 2 → chạy thử 1 scene.

## Round 2 — ACCEPTED

Full suite một lượt trên source cuối: backend 3538 passed / 28 skipped / 0 failed; frontend 83 file / 880 passed; ruff,
typecheck, mirror PASS; lint 0 lỗi (7 cảnh báo ở file không đụng). Test budget 300k PASS. Tôi chạy lại các nhóm liên quan
(backend region/queue/regeneration 140 PASS; frontend region/object-review/geometry-review 179 PASS).

T-022..T-025 và T-021 đã accepted. Tiến hành đầu dependency (T-022.. khi T-019 còn changes-requested) là theo lệnh của tôi: chấp nhận.

Suggestion: lưu log full suite round 2 vào `evidence/` như round 1 (hiện chỉ có số trong report).

Còn lại cho chủ dự án: kiểm bằng mắt trên browser, GPU ObjectGS, Isaac Sim, cảm giác Walk; tham số vỏ trên scene thật.
