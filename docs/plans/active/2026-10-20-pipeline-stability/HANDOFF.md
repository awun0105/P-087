# Sprint 8 — Pipeline ổn định, tiến trình rõ ràng, xem scene nhanh (bàn giao)

Kế hoạch: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`. Báo cáo từng task: `.ai/tasks/T-046…T-069/report.md`.
Nhánh `develop`, chưa push.

## Thay đổi theo đợt

1. **Pipeline chạy ổn định (T-046…T-050).** Worker không chết khi một hàng đợi lỗi (lùi dần 1→60 s). Tắt worker giữa chừng →
   lỗi `INTERRUPTED_SHUTDOWN`, chạy lại được. Job `RUNNING` không ai giữ quá thời hạn → tự đánh dấu lỗi. Mất DB ngắn không làm
   rơi job (chịu tới 2/3 thời hạn lease). Chờ tài nguyên có giới hạn 30 phút (`RESOURCE_WAIT_EXCEEDED`).
2. **API nhẹ (T-051…T-055).** Artifact cache bất biến theo checksum + ETag/304; lưới va chạm Walk đệm bộ nhớ + đĩa; SceneIR
   đệm parse + gzip; `/scenes` chỉ đọc usage của job đang hiện; một hàm trạng thái hình học.
3. **Mô hình tiến trình (T-056…T-062).** Mốc từng bước (`r2s_step_marks`, migration **v26**), pha của thao tác Studio,
   hàm `next_action` duy nhất, route `/jobs/{id}/pipeline`, trang scene hỏi một route với nhịp theo trạng thái, dòng thời
   gian từ bước của backend, một bảng câu chữ cho chuông/đầu trang/danh sách/Studio.
4. **Xem scene nhanh (T-063…T-068).** Một lần tải scene/gói/duyệt cho cả trang; viewer không vẽ lại thừa, dựng một lần, nghỉ
   khi ẩn; Walk tải lười; bước lưới chỉ tải lưới; chia JS; ảnh frame thu nhỏ; Gaussian vật tải 4 cái một lúc (vật đang chọn trước);
   vỏ không tải lại khi chọn; scene lớn mở bằng bộ LOD (T-070): hiện bản thô ngay rồi mịn dần tới đủ chất lượng gốc.
5. **T-069.** Sửa `/scenes` gọi đôi `preview_ready` (do T-059), định dạng một file test, tài liệu.

## Số đo trước / sau

Dữ liệu `data/studio_local`, bản sao DB SQLite, gọi trong tiến trình (không qua mạng).

| Việc | Trước | Sau |
|---|---|---|
| Tải lưới va chạm Walk | 760–1121 ms mỗi lần, không 304 | lần đầu như cũ; sau đó 107 ms (đĩa) / 0,1 ms (bộ nhớ); 304 không dựng |
| Tải một artifact | ~60 ms + SHA-256 cả file (SOG 31 MB: 69,7 ms băm) | băm 0,13 ms (lần 2+); trình duyệt giữ bản bất biến |
| `GET /jobs/{id}/scene` | 35–45 ms, 590 KB không nén | 16,9 ms, 588 KB → 28 KB gzip; 304: 4,1 ms |
| `GET /jobs/{id}/scene/objectify` | 34–42 ms | 5,6 ms |
| `GET /scenes` (ấm) | 31 ms | 27,5 ms (kèm `next_action`) |
| `GET /jobs/{id}/pipeline` (mới) | — | 21–29 ms trên 4 job thật; 304 khi không đổi |
| Request trang scene đã xong | ~18/phút, tải lại SceneIR mỗi 10 s | 1/phút (304 không thân); SceneIR tải một lần mỗi revision |
| Viewer khi trang render lại | prop mới mỗi render → vẽ lại, dựng lại dấu bề mặt | 0 prop đổi; viewer dựng 1 lần (trước 2) |
| Phát quỹ đạo 1 s | 60 lần báo trạng thái | ≤ 5 |
| Vỏ vật đang chọn | vẽ lại cả cảnh mỗi khung | ≈ 10 lần/giây |
| Tab Studio ẩn | vẫn cập nhật, Walk vẫn vẽ | nghỉ, thoát Walk |
| Mở Studio scene Ready | Ammo 1,2 MB + lưới va chạm + collider tải ngay | chỉ tải khi bấm "Đi bộ" |
| Bước Collision mesh | SOG 10–30 MB + lưới | chỉ lưới (0,1–1 MB); SOG khi bấm "Hiện kèm 3DGS" |
| Bước Frames (48 ảnh, job-a14981f78f85) | 362,9 MB | ≈ 0,7 MB ảnh thu nhỏ |
| Gaussian 61 vật (job-bfc7d73f0dbf) | 56,2 MB PLY, 60 request cùng lúc | 56,2 MB PLY gốc, ≤ 4 cùng lúc, vật đang chọn trước |
| Chọn/bỏ chọn vật 5 lần | 11 lần tải GLB vỏ | 1 |
| SOG scene lớn (2 triệu điểm, job-f9f14e7fbfb1) | phải tải 31 MB mới hiện | hiện sau 9,4 MB (bộ LOD), mịn dần tới đủ chất lượng |

Không đo được: kích thước chunk JS sau khi chia (không chạy `next build` vì máy chủ dev đang dùng `frontend/.next`).

## Chủ dự án kiểm bằng mắt

1. Mở một scene **đang chạy**: dòng thời gian đúng bước; khi chờ GPU có thông báo bật máy và số phút.
2. Scene **chờ xác nhận tỉ lệ mét**: chuông và đầu trang nói "Cần bạn xác nhận tỉ lệ mét", nút đưa vào Studio.
3. Scene **Draft** (chờ duyệt vật): bước "Duyệt vật" ở trạng thái chờ; bấm chọn vật nhiều lần — vỏ đổi sáng ngay, không nhấp nháy tải lại.
4. Scene **Ready**: mở Studio — 3DGS hiện, vật hiện dần (vật đang chọn trước). Bấm nút **Đi bộ** (bàn chân) — "Đang chuẩn bị
   đi bộ…" rồi tự vào Walk. Scene lớn đã có bộ LOD: hình hiện gần như ngay (bản thô) rồi mịn dần; nhìn gần phải đủ chi tiết
   như bản gốc, xoay không giật.
5. Từng **trang bước**: Frames hiện ảnh nhỏ, bấm ảnh mở ảnh gốc; Cameras không có thư viện 3D; Collision mesh chỉ có lưới,
   nút "Hiện kèm 3DGS".
6. **Đổi tab** Studio ↔ Tiến trình khi đang Walk: quay lại không còn Walk, không giật.
7. Danh sách scene: nhãn trạng thái giống đầu trang scene.

## Lưu ý deploy

- **Mã bước mới `ST-VIEW-LOD`** (danh sách bước của backend và Studio): API, worker và Studio lên cùng đợt.
- **Migration v26** (`r2s_step_marks`). API và worker phải lên **cùng lúc**: code cũ từ chối DB ở schema mới hơn.
  Thứ tự: dừng worker → deploy API (tự chạy migration) → deploy worker (CPU và GPU image).
- Migration v26 và 13 test `test_step_marks.py` đã chạy qua trên PostgreSQL 16 thật (phiên GPU kiểm, 2026-10-20). Phần ghi
  mốc từ `save_job`/runner trên PostgreSQL chỉ được kiểm khi chạy job thật sau deploy.
- Bản vá production `becd0b3e` (bỏ `json_extract` chỉ SQLite có trong hai lần quét job RUNNING, gồm lần quét của T-048) đã ở
  `develop` và production; không cần làm lại.
- Header `Cache-Control` của R2 chỉ áp cho file tải lên **sau** khi deploy; file cũ vẫn dùng được (API trả cache header).
- **Bộ LOD (T-070)**: job xong thì runner tạo ngay trong cùng lượt (bước "Chuẩn bị xem 3D mượt"); ngoài ra worker **có GPU** tạo lúc rảnh (cần `R2S_VOXEL_CLI` và `nvidia-smi` trên máy đó; image GPU đã có
  splat-transform). Không cần cấu hình thêm. Job cũ được tạo bù tự động, job mới trước. Mỗi SOG lớn tốn vài phút GPU một lần;
  chưa có bộ LOD thì giao diện mở SOG gốc như trước. Bộ LOD nằm ở `jobs/<job>/derived/lod/` trong kho file (xoá job là xoá
  theo); dấu bỏ qua ở `cache/lod-skip` (xoá để thử lại).
- Thư mục đệm dẫn xuất cạnh `ARTIFACT_ROOT`: `cache/walk-collision` (tự dọn 7 ngày), `cache/thumbnails` (chưa tự dọn; xoá lúc
  nào cũng được).
- `NEXT_PUBLIC_VIEWER_RENDERER=auto` (tuỳ chọn) cho phép WebGPU; mặc định `webgl`.
- Khuyến nghị chạy API nhiều tiến trình uvicorn: việc dựng lưới va chạm lần đầu vẫn chiếm CPU.

## Test

Xem `.ai/tasks/T-069/report.md` (số pass/fail thật và các test đỏ có từ trước).

## Backlog còn lại

- Web Worker parse lưới va chạm (T-065 bước 3); tải trước SOG bước 5 song song với camera.
- Báo cáo tổng thời gian máy + người từ `r2s_step_marks` (mục tiêu telemetry ban đầu).
- Dọn tự động cho `cache/thumbnails`. Bộ LOD cho bản xem bước 5 khi Studio chưa có scene (`PreviewScene` nhận URL sẵn).
- Test role matrix đỏ do các route `demo-sessions`/`samples` chưa khai báo (có trước Sprint 8).
