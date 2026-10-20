# T-067 report: vật nhẹ — PLY nén, tải giới hạn đồng thời, vỏ không tải lại khi chọn

## Đã làm
- Route `GET /jobs/{job_id}/objects/compact?artifact_uri=&artifact_checksum=` (`src/api/product/artifacts.py`) và
  `artifacts/compact_gaussians.py`: Gaussian của vật (`ObjectGaussians`) chuyển sang PLY nén của PlayCanvas bằng
  splat-transform (`-g cpu`), đệm đĩa theo checksum (`cache/compact-objects/`), tối đa 2 lần chuyển đồng thời, khoá theo vật.
  Cùng allow-list với route content; artifact khác loại → 404. ETag + 304, cache immutable. Thiếu runtime hoặc chuyển lỗi →
  307 về PLY gốc (`no-store`), viewer vẫn mở được. Không đổi SceneIR; scene cũ cũng được hưởng.
- Frontend: Gaussian của vật dùng URL nén. `SceneOverlay` có hàng đợi tải vật: tối đa 4 cùng lúc, vật đang chọn trước
  (`prioritizeObject`, gọi từ `MetricSceneView`), vật ẩn sau cùng; vật bị gỡ khi còn trong hàng đợi thì không tải.
- Vỏ vật (`shell-glow`): gọi lại với cùng URL chỉ đổi kiểu (vật liệu, độ mờ, viền) trên GLB đã nạp; không tải lại khi đổi chọn.

## Lệch so với plan (Ruling trong ledger)
Không publish SOG cạnh PLY. Đo trên máy này: SOG ≈ 3 s/vật có GPU (≈ 3 phút thêm vào bước tách vật với 60 vật) và 265 s/vật
chỉ CPU; PLY nén 0,5 s/vật trên CPU. Vì vậy dùng PLY nén tạo lười trên API.

## Đo
| | Trước | Sau |
|---|---|---|
| 61 vật của job-bfc7d73f0dbf | 56,2 MB PLY | 14,7 MB PLY nén (3,8×) |
| CPU tạo lần đầu (cả 61 vật) | — | ≈ 14 s, sau đó lấy từ đệm |
| Request tải vật đồng thời | 60 | ≤ 4 |
| Lần nạp GLB vỏ khi chọn/bỏ chọn 5 lần | 11 | 1 |

## Kiểm thử
`tests/test_api/test_compact_object_gaussians.py` (7, gồm một lần chuyển thật bằng runtime local),
`frontend/tests/object-visual-loading.test.ts`, test mới trong `shell-glow.test.ts`, `object-review.test.tsx`.
Toàn bộ frontend 1106 test xanh.

## Việc còn để ngỏ
Thư mục đệm `cache/thumbnails/` (T-066) và `cache/compact-objects/` chưa có dọn tự động như đệm Walk; xoá tay lúc nào cũng được.
