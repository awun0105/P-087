# T-070 report: xem scene lớn bằng LOD (thay bản nhẹ T-068)

## Đã làm
- `artifacts/lod.py`: tạo bộ LOD ba mức (gốc, 1/2, 1/4 số điểm) cho SOG > 600 nghìn điểm bằng splat-transform 3.6.6; lưu
  `jobs/<job>/derived/lod/<checksum>/` ở cache cục bộ và kho file, `lod-meta.json` ghi/đẩy sau cùng.
- **Bước chính thức:** runner tạo bộ LOD ngay sau khi job chuyển sang thành công, trong cùng lượt giữ lease (máy GPU không bị
  tắt); mốc `ST-VIEW-LOD` hiện trên dòng tiến trình "Chuẩn bị xem 3D mượt" sau "Tách vật"; lỗi → "bỏ qua", job vẫn thành công.
- **Chạy ngầm:** worker có GPU, lúc rảnh, mỗi phút một SOG còn thiếu (job cũ, `background.sog` sau Tạo mesh); scene nhỏ / lỗi
  ghi dấu ở `cache/lod-skip` (lỗi thử lại sau 24 giờ).
- Route `GET /jobs/{job_id}/lod/{checksum}/{path}`: SOG phải thuộc allow-list; chỉ nhận tên file đúng dạng bộ LOD; `.webp`
  chuyển hướng tới kho file, `.json` đi qua API.
- Giao diện: `useLodView` (khung Studio, bước hệ mét, lớp 3DGS trang bước). Gỡ bản nhẹ, nút "Chất lượng đầy đủ", PLY nén cho
  vật; vật dùng PLY gốc (giữ hàng đợi 4 vật).

## Đo (máy dev, GPU Quadro T2000, dữ liệu `data/studio_local`)
| Job / file | Số điểm | SOG gốc | Phần hiện đầu tiên | Cả bộ LOD | Thời gian tạo |
|---|---|---|---|---|---|
| job-a14981f78f85 scene.sog | 830 nghìn | 14,3 MB | 5,4 MB | 29,2 MB | 147–151 s |
| job-7c9820b4834f scene.sog | 960 nghìn | 16,7 MB | 6,2 MB | 34,0 MB | 166–173 s |
| job-f9f14e7fbfb1 scene.sog | 2,0 triệu | 31,0 MB | 9,4 MB | 63,7 MB | 350–368 s |
| job-f9f14e7fbfb1 background.sog | 1,6 triệu | 25,2 MB | 8,0 MB | 52,4 MB | 295 s |

Nhiệt độ GPU 66–71 °C. Hình hiện ra sau khoảng 1/3 dung lượng SOG gốc; tải đủ mọi mức thì tổng lượng tải gấp ~2 lần SOG.

## Kiểm thử
`test_lod_bundles.py` (9), `test_lod_routes.py` (5), `test_runner_view_lod.py` (3), `test_pipeline_view.py` (3 ca mới),
`frontend/tests/lod-view.test.tsx` (3), `use-pipeline.test.ts` (1 ca mới). Python orchestration + tích hợp: 1497 qua.
Frontend: 1110 qua. Chưa mở thử trong trình duyệt (chủ dự án kiểm bằng mắt).
