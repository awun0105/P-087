# T-068 report: bản xem nhanh của SOG

## Kiểm công cụ (splat-transform 3.6.6, không nâng phiên bản)
- Bỏ dải SH: có (`-H 0`). Giảm splat: có (`-d n`, phải là bước cuối và ra PLY → làm hai lần gọi). LOD (`lod-meta.json`): có,
  nhưng cần các mức đã giảm splat (cùng chi phí), chưa làm.
- Đo trên SOG 28,7 MB, 1,86 triệu splat (máy dev, chỉ CPU):

| Cách | Kích thước | Thời gian CPU |
|---|---|---|
| Chỉ bỏ SH (`-H 0`) | 22,8 MB | 5 s |
| 500 nghìn splat + bỏ SH | 6,3 MB | ≈ 77 s (giảm splat 75 s) |

  Scene ≤ 500 nghìn splat (vd. 291 nghìn) giảm splat không có tác dụng.

## Đã làm (khác plan, Ruling trong ledger)
- Không publish `QuickViewSog` trong pipeline và không đổi SceneIR/StageView. API tạo bản nhẹ **nền** cho SOG > 600 nghìn
  splat (đọc `count` trong `meta.json`), một việc một lúc, `nice`, đệm theo checksum (`cache/quick-sog/`).
  - `GET /jobs/{id}/artifacts/quick/status` → `ready` / `building` / `unavailable` (lần đầu thì bắt đầu tạo).
  - `GET /jobs/{id}/artifacts/quick` → file khi đã có (immutable, ETag, 304), chưa có thì 404.
  - Cùng allow-list với route content; chỉ cho file `.sog`.
- Frontend: `useQuickView` hỏi trạng thái trước khi dựng viewer; có bản nhẹ thì mở bản nhẹ, nút "Chất lượng đầy đủ" (biểu
  tượng lấp lánh trên thanh công cụ) tải bản gốc (viewer dựng lại, góc nhìn về ban đầu). Áp cho khung Studio, bước hệ mét và
  lớp 3DGS ở trang bước. Lỗi hỏi trạng thái → bản gốc.
- Job cũ dùng được luôn, không cần lệnh backfill.

## Hệ quả
Lần đầu mở một scene lớn vẫn là bản đầy đủ (bản nhẹ đang tạo ≈ 1 phút CPU trên API); từ lần sau mở bản nhẹ (≈ 4,5× nhỏ hơn,
≈ 3,7× ít splat → quay mượt hơn). Tạo lỗi thì để file đánh dấu `*.unavailable` trong đệm; xoá file đó để thử lại.

## Kiểm thử
`tests/test_api/test_quick_view_sog.py` (5), `frontend/tests/quick-view-sog.test.tsx` (4). Toàn bộ frontend 1110 test xanh.
Người dùng tự kiểm bằng mắt chất lượng bản nhẹ.
