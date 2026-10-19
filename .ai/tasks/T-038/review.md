# Review T-038

Verdict: ACCEPTED

Audit: 13 commit `9751ed41` → `62466381`. Đọc `Dockerfile.gpu`, `scripts/gpu/docker_entrypoint.sh`, `scripts/gpu/install.d/_lib.sh`
(`load_runtime_env`, `write_runtime_env`, danh sách biến cho phép), khoá ObjectGS mở rộng. Chạy `tests/test_gpu tests/test_packaging
tests/test_kaggle`: 171 PASS.

Đã kiểm, đúng:
- `Dockerfile.gpu` chỉ cài apt theo `configs/runtime/apt-packages.txt`, chép cây COLMAP từ stage image ghim, rồi gọi
  `install.sh /opt/real2sim --colmap=binary --skip-gpu-check --no-doctor`; `install_colmap` dùng lại cây đã chép nên build không
  cần R2.
- `load_runtime_env` chỉ đặt biến **chưa có hoặc rỗng**, đọc nguyên văn (không eval), từ chối tên biến lạ: giá trị người vận hành
  đặt (tên `R2S_*`) không bị ghi đè; `R2S_BRUSH_ENVIRONMENT` của người vận hành được giữ trước khi nạp.
- `runtime.env` (laptop `data/runtime.env`) chỉ có đường dẫn và định danh trong danh sách cho phép, không secret/DATABASE_URL;
  định danh COLMAP/Brush khớp ghim cũ.
- Khoá ObjectGS: hash của mọi file pip có thể chọn cho CPython 3.8 Linux x86_64, torch có khoá hash riêng, cài sạch online
  không `--wheels` thành công, `pip freeze` khớp laptop 130 dòng; phát hiện và ghim `wheel==0.45.1`.

## Suggestions (không bắt buộc)
- Entrypoint đặt mặc định timeout theo tên mới (`R2S_*_TIMEOUT_SECONDS:-…`) trước khi Settings đọc. Người vận hành còn dùng
  tên cũ (`REC04_BRUSH_TIMEOUT_SECONDS`…) sẽ bị **bỏ qua im lặng** vì tên mới đã có giá trị mặc định. Sửa: chỉ đặt mặc định khi
  cả tên mới lẫn tên cũ đều trống (dùng `legacy_name` qua một hàm nhỏ trong `_lib.sh`). File mẫu đã dùng tên mới nên không chặn.

## Quyết định cho 3 câu hỏi của report
1. `PRODUCT_OBJECTGS_*` vào `scripts/gpu/studio.env`: **chưa bật** trên stack local. ObjectGS đang có lỗi chất lượng mesh
   (backlog; scene Room hỏng lưới va chạm vì bề mặt ObjectGS). Bật khi mục đó được sửa.
2. Timeout laptop 3600 s: để chủ dự án quyết; khuyến nghị nâng lên 7200 (COLMAP) / 14400 (Brush) ở lần khởi động lại kế tiếp
   vì T2000 chậm hơn GPU thuê.
3. Thư mục `/tmp/pip-unpack-rcdcb1bh`: đã không còn khi Architect kiểm.
