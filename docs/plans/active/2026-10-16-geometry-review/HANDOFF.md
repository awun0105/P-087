# Duyệt tách vật → vỏ Gaussian → collider — handoff

Ngày 2026-10-16. Branch `mvp-pipeline-v2`; baseline HEAD `69611ea9`. Thay đổi T-019 ở worktree, chưa commit/push/merge/PR.

**Trạng thái: có implementation và kiểm chứng local; chưa nghiệm thu scene thật.** Deep review T-019 tái hiện hai lỗi P1:
count inpaint không đi vào revision Ready, và box mở lại không khớp membership lệch tâm. Cần xử lý GR-01/GR-02 trước khi
chốt luồng scene mới. Chi tiết, source và test cần bổ sung: [review T-019](../../../../.ai/tasks/T-019/review.md).

## Phần đã triển khai

| Task | Kết quả và phần tái sử dụng |
| --- | --- |
| T-001/T-002 | Tách `occupancy_surface`; Gaussian shell qua opacity/outlier filtering, occupancy morphology, smoothing và surface QA. Voxel thích ứng, grid có budget. |
| T-003/T-004 | Contract shell/membership/region command; add/subtract box trong source-local, floor protection, ownership/claim và preview counts. |
| T-005/T-006 | `objectify` dừng ở Draft khi `geometry_review=required`; tái sử dụng helper CoACD, inpaint/SOG và background collision. |
| T-007/T-008 | Builder Draft → shell mịn → QA → collider → environment → Ready. ObjectGS là lựa chọn nâng cấp; surface của từng vật chỉ được chọn khi QA pass, có lý do giữ shell. |
| T-009/T-010/T-011 | Queue mode geometry/region, lease/cancel/revision fence; Apply Draft đồng bộ; Ready rebuild chỉ vật bị ảnh hưởng và môi trường trong một revision. |
| T-012/T-013 | Khoá Walk/USD/Move/Rotate ở Draft; banner Tạo mesh và phase tiến độ; API client và preset mặc định. |
| T-014/T-015/T-016/T-017 | Box math thuần TS; overlay mặt/xoay/dịch; Region Editor debounce/claim/Apply; vỏ phát sáng và điểm thêm/bớt. Draft không vẽ Gaussian vật trùng nền. |
| T-020 | Radio Duyệt trước/Tạo mesh ngay ở màn tạo job, cùng state `scene.geometry_review`, có chế độ chỉ đọc. |
| T-018 | Test tương thích legacy/ObjectGS, Move/Rotate, Walk và USD với shell/CoACD local. |
| T-019 | Full regression, sửa palette regression, fixture Gaussian đầy đủ và test public simulation package cho scene shell; deep review và handoff. |

Tái dùng SceneIR publication/CAS, immutable artifact store/checksum, source ownership, effective collision compositor dùng
chung cho Walk/USD, surface QA, convex runner, inpaint/SOG runtime và SuperSplat Brush/Lasso. Không viết lại provider và
không chạy train scene mới.

## Kết quả kiểm thử

| Kiểm tra | Kết quả ngày 16/10 |
| --- | --- |
| Backend full baseline | **3502 passed, 28 skipped, 1 failed**, 23 phút 53 giây. Failure partial Draft build đã sửa và 2 regression guard trên source cuối PASS. Chưa rerun full backend sau guard. |
| Builder/ObjectGS/region sau guard | **81 passed, 1 failed, 2 deselected**. Failure là budget preview 300k 1,620 s > 1,5 s; GR-05 còn mở. |
| Queue/regeneration/API/role matrix sau guard | **116 passed** |
| Public simulation package shell trên source cuối | **1 passed**, CoACD/OpenUSD local thật, một vật Confirm và một ứng viên |
| Frontend full sau sửa palette | **839 passed**, 80 test files |
| Ruff check/format + contract mirror | PASS; 746 file đúng format, 5 enum/8 model khớp |
| TypeScript + eslint | PASS; 0 errors, 7 warnings ở file không sửa |
| Graphify AST update | PASS; 25.574 nodes, 79.508 edges, 832 communities |

Lần focused 90 test trước guard có 2 failed/88 passed: partial Draft và preview budget. Test budget chạy riêng vẫn fail
1,873 s; không tăng threshold hoặc giấu failure. Kết quả full baseline, focused và rerun là các lượt riêng, không cộng
thành một số pass. Chi tiết lệnh/log ở [report T-019](../../../../.ai/tasks/T-019/report.md).

## Hướng dẫn chạy scene mới

Các bước sau là quy trình nghiệm thu cần thực hiện, chưa có evidence live của T-019.

1. Khởi động API/worker/Studio theo `RUNTIME.md`. SuperSplat editor đã có build local từ 15/10 sau thay đổi source-selection;
   nếu checkout/deploy mới chưa có `frontend/public/editor`, chạy `cd frontend && npm run build:editor` trước Brush/Lasso.
2. Tạo job từ capture mới. Kiểm params niêm phong: `scene.geometry_method=shell`, `scene.geometry_review=required`,
   `scene.refinement=multiview_v1`. Chọn “Dừng để duyệt và chỉnh vùng vật”. `auto` bỏ điểm dừng giữa extraction và build;
   dùng khi đã chấp nhận quy trình batch và các giới hạn trong review.
3. Xử lý reconstruction và xác nhận mét. Chờ tách vật publish Draft. Kiểm banner “Đang duyệt tách vật”, collider null và
   Walk/USD/Move/Rotate bị khoá. Job/scene Ready chưa đồng nghĩa được APPROVED/RELEASED.
4. Chọn vật → Chỉnh vùng → box cộng/trừ, Trên/Trước/Cạnh, kéo mặt/xoay/dịch. Chờ preview đúng box; kiểm bộ đếm, bảo vệ sàn
   và các vật chồng lấn. “Lấy luôn” phải chủ động tick. GR-04: preview hiện chưa báo đủ trường hợp donor còn dưới 50 hàng.
5. Apply Draft tạo revision mới không train. **GR-02:** trước khi bản sửa có mặt, không coi box mặc định sau khi đóng/mở lại
   là vùng đã duyệt; kiểm lại bộ đếm removed và hình trước khi Apply.
6. Bấm Tạo mesh. Theo dõi shell/quality/collider/environment/publish; ObjectGS có thêm phase riêng nếu được chọn. Nếu lỗi,
   kiểm scene revision cũ vẫn là head và thông báo nguyên nhân. Vật Ignore có lỗi vỏ vẫn có thể chặn build: Restore vật đó,
   sửa vùng rồi thử lại theo GR-03; không dùng OBB để vượt QA.
7. Ready → Confirm vật → Move/Rotate → kiểm Gaussian/collider đi cùng pose → Walk. Kiểm không còn ghost tại vị trí cũ,
   sàn vẫn có support, bỏ Ignore/Restore không làm mất ownership. Brush/Lasso chỉ dùng sau Ready.
8. Xuất USD sau preflight. **GR-01:** nếu nền có hàng inpaint và còn vật cần SOURCE representation, preflight có thể báo
   `SOURCE_BACKGROUND_INVALID`; đây là lỗi metadata chưa xử lý, không bỏ qua kiểm tra. Khi có bản sửa, kiểm đúng candidate,
   scene revision, checksum, inventory, rồi mở Isaac Sim và ghi evidence physics từ runtime đó.

Capture gợi ý: đi quanh vật chính ở hai độ cao; có sàn và bối cảnh đủ cho pose/floor fitting. Không coi mẹo quay này là bảo
đảm mask, geometry hoặc physics đạt chất lượng.

## Cách thử huỷ, lỗi và xung đột

- Huỷ lúc queued: operation chuyển terminal, không publish revision geometry. Huỷ lúc running: chờ child process dừng,
  kiểm operation_id và head cũ còn nguyên. Không chỉ đóng panel rồi gọi đó là huỷ tác vụ.
- QA vỏ lỗi: xem lỗi và vật bị ảnh hưởng; Draft/head cũ giữ nguyên; sửa box rồi yêu cầu lại. Placeholder trong Draft chỉ để
  hiển thị, không có collider và không chứng minh hình học hợp lệ.
- Hai lượt sửa cùng revision: lượt stale phải 409; tải lại rồi preview lại theo checksum mới. GR-06: preview409 hiện thiếu
  CTA Tải lại trực tiếp trong panel khi cha chưa nhận revision mới.
- Ready partial rebuild lỗi/huỷ: membership, object geometry và environment mới không được publish riêng lẻ thành head.

## Giới hạn và khác biệt với handoff cũ

- ObjectGS mask dựng lại từ membership hiện tại; chất lượng mask chỉ được nghiệm thu bằng GPU/scene thật. Test CPU không
  chứng minh training, TSDF surface hoặc chất lượng reconstruction của scene mới.
- Partial rebuild dùng shell cho vật bị ảnh hưởng kể cả job chọn ObjectGS, với lý do `partial_rebuild_uses_shell`; vật khác
  giữ surface cũ. Không retrain model đa nhãn toàn scene ở đường này.
- Partial rebuild ghi `membership_correction.evidence_ref`, không sinh `object_pipeline_evidence` mới như lần extraction đầy
  đủ. Consumer chẩn đoán phải đọc đúng receipt theo operation.
- `objectify(correction=…)` cũ không còn được gọi bởi đường regeneration hiện tại; chưa dọn trong T-019.
- Collider shell có thể xuất hiện cả `geometry` và `colliders` trong CandidatePackage inventory. Đây là tham chiếu lặp đã
  biết, không phải evidence mesh được đặt hai lần trong USD. Chưa sửa inventory trong task này.
- Opacity 0,1, voxel preview 0,05 m/fine 0,02 m và adaptive grid là giá trị khởi đầu cần chỉnh trên scene thật. Shell kín
  không chứng minh thể tích khối đặc đúng; không suy mass/inertia từ thể tích vỏ rỗng.
- Benchmark 2M local: cold 3,5–7,0 s, warm 1,57–2,16 s, floor fit stub, 7-field PLY, máy có tải đồng thời. Chưa đạt mục tiêu
  preview <1,5 s trong phép đo này; chưa có latency HTTP/browser hoặc memory test với SH đầy đủ.
- Chưa nghiệm thu GPU ObjectGS, kéo box thực, hiển thị/màu/độ tương phản, GPU buffer lifetime, Walk feel và Isaac Sim.
  DevTools chỉ thấy tab `about:blank`, không có phiên Studio để kiểm những việc này.
