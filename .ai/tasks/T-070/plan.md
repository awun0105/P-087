# T-070: Xem scene lớn bằng LOD — đủ chất lượng, mở nhanh, không lag (thay bản nhẹ T-068)

Yêu cầu của chủ dự án (2026-10-20): scene giữ chất lượng cao nhất, người dùng không phải chờ lâu lúc mở, dùng không lag; bỏ
bản nhẹ.

## Thiết kế
- Thư viện khung 3D (supersplat-viewer 1.35.2) đọc bộ LOD (`lod-meta.json` + khối `<mức>_<khối>/meta.json|*.webp`): hiện
  mức thô nhất trước rồi tải thêm chi tiết; máy bàn vẽ tối đa 4 triệu điểm (scene lớn nhất hiện có ~1,9 triệu) nên tải xong là
  đủ chất lượng gốc.
- Tạo: worker có GPU, lúc rảnh, mỗi phút một SOG (`LodBuilder.tick`), cho mọi SOG xem được của mọi job (job mới trước) >
  600 nghìn điểm. Ba mức: gốc, 1/2, 1/4 (`splat-transform` 3.6.6, nén SOG cần GPU). Scene nhỏ / lỗi ghi dấu (`cache/lod-skip`;
  lỗi thử lại sau 24 giờ).
- Lưu: `jobs/<job>/derived/lod/<checksum SOG>/` trong cache cục bộ và kho file; `lod-meta.json` ghi và đẩy sau cùng.
- Cấp: `GET /jobs/{job_id}/lod/{checksum}/{path}`; SOG nguồn phải thuộc allow-list (`authorized_sog_by_checksum`), chỉ nhận
  tên file đúng dạng bộ LOD; khối `.webp` chuyển hướng tới kho file, file `.json` đi qua API (đường dẫn tương đối trỏ về API).
- Giao diện: `useLodView` hỏi `lod-meta.json`; có thì mở bộ LOD, không thì SOG gốc. Áp cho khung Studio, bước hệ mét, lớp
  3DGS trang bước.
- Gỡ: route `/objects/compact`, `/artifacts/quick(/status)`, module `compact_gaussians`, `quick_sog`, nút "Chất lượng đầy đủ".
  Gaussian của vật dùng PLY gốc (giữ hàng đợi 4 vật).
