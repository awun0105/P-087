# T-065 report: tải lười Walk, bước lưới chỉ tải lưới, trang bước bớt nối tiếp, chia JS

## Đã làm
- Walk lười: `MetricSceneView` có nút "Đi bộ" riêng trên thanh công cụ viewer. Chưa bấm thì không tải Ammo, lưới va chạm
  Walk hay collider của vật. Bấm thì tải, nút chuyển "Đang chuẩn bị đi bộ…", nạp xong tự vào Walk một lần. Sau đó nút Walk
  của thư viện hiện như cũ. Bước 6 (hệ mét) hưởng cùng cơ chế.
- Bước Collision mesh: chỉ tải lưới; nút "Hiện kèm 3DGS" mới tải SOG hệ mét.
- Trang xem từng bước: tên dự án không còn chặn hiển thị (điền vào khi về); mã khung xem tải song song với request tiến trình.
- `StageViewer` tách: Frames/Cameras ở file nhẹ, phần 3D (`StageViewer3D`: 3DGS, lưới, khung hệ mét, `CollisionMeshCanvas`)
  tải động.
- `NEXT_PUBLIC_VIEWER_RENDERER=auto` cho phép WebGPU khi trình duyệt hỗ trợ; mặc định vẫn `webgl`.

## Lệch so với plan (Ruling trong ledger)
- Không làm Web Worker parse lưới va chạm (bước 3): sau bước 1 việc parse chỉ chạy khi bấm Đi bộ, đã chia lát, và thư viện
  vẫn dựng cấu trúc va chạm trên luồng chính.
- Giữ cổng "bước đã xong" trước request job/artifact (test của phiên khác khẳng định điều này); không tải trước SOG bước 5.
- Không chạy `npm run build` để đo chunk: máy chủ dev của người dùng đang chạy trên `frontend/.next`.
- Bốn test cũ ở `metric-effective-collision.test.tsx` giả định lưới va chạm nạp ngay khi mở; nay bấm "Đi bộ" trước rồi kiểm URL.

## Kiểm thử
`walk-lazy-load`, `stage-mesh-only`, `stage-bundle-split`, `viewer-renderer-setting`, test mới trong `studio-inspection`
(tên dự án chậm không chặn viewer). Toàn bộ frontend: 121 file, 1100 test xanh. Typecheck, eslint sạch.

## Khuyến nghị
Thử `NEXT_PUBLIC_VIEWER_RENDERER=auto` trên Chrome có WebGPU, so độ mượt với `webgl` trước khi đổi mặc định.
