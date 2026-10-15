# Duyệt tách vật → vỏ Gaussian → collider — handoff

Ngày 2026-10-16. Branch `mvp-pipeline-v2`; baseline HEAD `69611ea9`. Thay đổi T-019 ở worktree, chưa commit/push/merge/PR.

**Trạng thái: round 2 — đã sửa sáu finding của deep review (GR-01…GR-06) và có kiểm chứng tự động; chưa nghiệm thu scene thật.**
Round 1 của T-019 tìm hai P1 (count inpaint không vào revision Ready; box mở lại lệch khỏi membership) và bốn P2. Round 2
sửa chúng ở T-022 (GR-01), T-023 (GR-02), T-024 (GR-03/04/06), T-025 (GR-05, preview 2M) và T-021 (luồng Draft trong
Tiến trình, chuông, đầu trang). Chi tiết và source của từng finding: [review T-019](../../../../.ai/tasks/T-019/review.md).

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
| T-021 | Hàng ảo "Duyệt vật & Tạo mesh" sau "Tách vật thể" trong Tiến trình (trạng thái lấy từ `ObjectifyState.object_geometry`, không đổi job pipeline hay `StageId`); chuông nhánh Draft; đầu trang "Chờ duyệt vật" / "Đang tạo mesh". |
| T-022 | GR-01: builder ghi số Gaussian vá nền của lần inpaint **mới** vào provenance cùng revision (cả dựng toàn bộ và một phần); validator không đổi. |
| T-023 | GR-02: `GET …/region/fit` tính box bao đúng Gaussian hiện có của vật trong khung nguồn; Chỉnh vùng mở sau khi có box, không tạo box từ kích thước. |
| T-024 | GR-03: banner nêu vật đã loại có lỗi vỏ (builder vẫn dựng vỏ cho chúng). GR-04: preview báo donor còn dưới 50 hàng; Apply bị khoá kèm lý do. GR-06: 409 ở preview có nút Tải lại, giữ box và claim. |
| T-025 | GR-05: `_box_contains` chỉ kiểm hàng ứng viên khi chúng ít; một phép đổi world→local mỗi preview; cache nguồn theo PLY với ngân sách byte và không giữ khoá khi đọc PLY. Benchmark `scripts/scene/bench_region_preview.py`. |

Tái dùng SceneIR publication/CAS, immutable artifact store/checksum, source ownership, effective collision compositor dùng
chung cho Walk/USD, surface QA, convex runner, inpaint/SOG runtime và SuperSplat Brush/Lasso. Không viết lại provider và
không chạy train scene mới. Không thay đổi `contracts/StageId`; `check_contract_mirror.py` vẫn PASS.

## Kết quả kiểm thử

Round 1 (trước T-021..T-025) giữ nguyên làm lịch sử: backend full baseline 3502 passed, 28 skipped, 1 failed; budget preview
300k 1,62 s. Round 2 (sau T-021..T-025, các lượt riêng, không cộng thành một số pass):

| Kiểm tra | Kết quả round 2 |
| --- | --- |
| Backend full suite (`pytest tests -q`) | **3538 passed, 28 skipped, 0 failed**, 15 warning httpx ở test error-view, 569,67 s (`pytest tests -q`, một lượt trên source cuối). Failure partial Draft của round 1 đã được sửa và pass. |
| Focused: region, membership, geometry build, queue, routes, role matrix | T-023: 90 passed; T-024: 85 passed; T-021: 105 passed; T-025: 40 passed; T-022 đã có trong full run |
| Budget preview 300k, chạy riêng 5 lần | 0,504 · 0,539 · 0,539 · 0,564 · 0,755 s, PASS |
| Benchmark 2M Gaussian đủ SH (degree 3), sàn fit thật | warm 16 box p50 1,19 s; warm 1 box p50 0,57 s; cold ~4 s; RSS ~1,14 GB |
| Tương đương kết quả preview trước/sau tối ưu | SHA-256 toàn bộ kết quả giống nhau cho 1 box, 16 box và hộp nhỏ lệch tâm |
| Frontend full (`vitest run`) | **83 files, 880 passed**, `vitest run`, exit 0. |
| Typecheck, eslint | `npm run typecheck` PASS; `npm run lint` 0 errors, 7 warnings ở file không đổi trong round 2 (`ImportedScenesHome.tsx`, `LidarCalibrationQAStage.tsx` và hai test liên quan). |
| Ruff check/format, contract mirror | `ruff check src tests scripts` PASS; `ruff format --check` PASS (747 file); `check_contract_mirror.py` PASS (5 enum, 8 model). |

Lệnh và log: [report T-019](../../../../.ai/tasks/T-019/report.md), [evidence](../../../../.ai/tasks/T-019/evidence/README.md),
[benchmark T-025](../../../../.ai/tasks/T-025/evidence/).

## Hướng dẫn chạy scene mới

Các bước sau là quy trình nghiệm thu cần thực hiện; chưa có evidence live (GPU, trình duyệt, Isaac) cho round 2.

1. Khởi động API/worker/Studio theo `RUNTIME.md`. SuperSplat editor đã có build local từ 15/10 sau thay đổi source-selection;
   nếu checkout/deploy mới chưa có `frontend/public/editor`, chạy `cd frontend && npm run build:editor` trước Brush/Lasso.
2. Tạo job từ capture mới. Kiểm params niêm phong: `scene.geometry_method=shell`, `scene.geometry_review=required`,
   `scene.refinement=multiview_v1`. Chọn “Dừng để duyệt và chỉnh vùng vật”. `auto` bỏ điểm dừng giữa extraction và build;
   dùng khi đã chấp nhận quy trình batch và các giới hạn trong review.
3. Xử lý reconstruction và xác nhận mét. Chờ tách vật publish Draft. Trên tab Tiến trình, hàng "Duyệt vật & Tạo mesh" hiện
   "Chỉnh vùng nếu cần, rồi Tạo mesh"; đầu trang hiện "Chờ duyệt vật"; chuông nêu số vật chờ xác nhận. Collider là null và
   Walk/USD/Move/Rotate bị khoá. Job/scene Ready chưa đồng nghĩa được APPROVED/RELEASED.
4. Chọn vật → Chỉnh vùng. Panel hiện "Đang lấy vùng hiện tại…" rồi mở với box bao đúng Gaussian của vật (không phải box từ
   kích thước). Chỉnh bằng box cộng/trừ, Trên/Trước/Cạnh, kéo mặt/xoay/dịch; kiểm bộ đếm, bảo vệ sàn và các vật chồng lấn.
   “Lấy luôn” phải chủ động tick. Nếu một vật được lấy luôn sẽ còn dưới 50 Gaussian, dòng của vật đó hiện cảnh báo và Apply bị
   khoá kèm lý do.
5. Apply Draft tạo revision mới không train. Nếu scene đã đổi ở lượt khác (409), panel giữ box và claim; bấm Tải lại rồi chờ
   preview khớp revision mới trước khi Apply.
6. Bấm Tạo mesh. Theo dõi shell/quality/collider/environment/publish; ObjectGS có thêm phase riêng nếu được chọn. Nếu lỗi,
   kiểm scene revision cũ vẫn là head và thông báo nguyên nhân. Vật Ignore/Delete/Merge có lỗi vỏ vẫn chặn build và được nêu
   trên banner kèm hướng dẫn "Khôi phục, sửa vùng, rồi Tạo mesh"; không dùng OBB để vượt QA.
7. Ready → Confirm vật → Move/Rotate → kiểm Gaussian/collider đi cùng pose → Walk. Kiểm không còn ghost tại vị trí cũ,
   sàn vẫn có support, bỏ Ignore/Restore không làm mất ownership. Brush/Lasso chỉ dùng sau Ready.
8. Xuất USD sau preflight. Nền có hàng inpaint được tính đúng số Gaussian vá trong provenance của revision Ready, nên
   `SOURCE_BACKGROUND_INVALID` không còn xuất hiện vì lỗi đếm (GR-01). Khi có scene thật, kiểm đúng candidate, scene revision,
   checksum, inventory, rồi mở Isaac Sim và ghi evidence physics từ runtime đó.

Capture gợi ý: đi quanh vật chính ở hai độ cao; có sàn và bối cảnh đủ cho pose/floor fitting. Không coi mẹo quay này là bảo
đảm mask, geometry hoặc physics đạt chất lượng.

## Cách thử huỷ, lỗi và xung đột

- Huỷ lúc queued: operation chuyển terminal, không publish revision geometry. Huỷ lúc running: chờ child process dừng,
  kiểm operation_id và head cũ còn nguyên. Không chỉ đóng panel rồi gọi đó là huỷ tác vụ.
- QA vỏ lỗi: xem lỗi và vật bị ảnh hưởng; Draft/head cũ giữ nguyên; sửa box rồi yêu cầu lại. Placeholder trong Draft chỉ để
  hiển thị, không có collider và không chứng minh hình học hợp lệ.
- Hai lượt sửa cùng revision: lượt stale phải 409; tải lại rồi preview lại theo checksum mới. Preview 409 và Apply 409 đều có
  nút Tải lại trong panel; box và claim được giữ.
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
- Benchmark 2M (SH đầy đủ, sàn fit thật, 60% hàng thuộc một vật — trường hợp nặng): warm p50 16 box 1,19 s và 1 box 0,57 s,
  đạt mục tiêu ≤1,5 s trên máy phát triển; cold ~4 s vì phải đọc PLY 472 MB và fit sàn một lần. Chưa đo HTTP, trình duyệt, hay
  máy khác. Cache nguồn giữ tối đa 1 GiB (`product_region_source_cache_mib`).
- Chưa nghiệm thu GPU ObjectGS, kéo box thực, hiển thị/màu/độ tương phản của hàng và panel mới, GPU buffer lifetime, Walk
  feel và Isaac Sim. DevTools chỉ thấy tab `about:blank`, không có phiên Studio để kiểm những việc này.
- Round 2 chưa thêm test riêng cho nhánh Ready của quy tắc donor (GR-04) và ETA của hàng ảo đang chạy (T-021).
