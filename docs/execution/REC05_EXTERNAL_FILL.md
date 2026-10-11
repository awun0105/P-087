# REC-05: external fill trước carve

## Cấu hình và luồng xử lý

GPU Compose, entrypoint và env mẫu dùng `configs/product/geometry_indoor_v1.json`.
Profile này dùng schema `1.2`, `external_fill_size_m = 1.6`. Đây là giá trị mặc định
của upstream splat-transform 3.6.6, chưa được hiệu chỉnh trên scene thật.

Luồng trong adapter:

1. Kiểm tra runtime đã ghim và có cờ `--voxel-external-fill`.
2. Quy đổi mét ở product entrypoint; lọc Gaussian theo profile và giữ cluster bất biến.
3. Kiểm tra giới hạn voxel có tính khoảng đệm fill, căn block và extent Gaussian.
4. Xuất occupancy với fill và seed ban đầu, chưa carve.
5. Nếu upstream bỏ qua fill hoặc không còn vùng đi lại, dừng attempt.
6. Kiểm tra toàn bộ footprint robot trên occupancy sau fill; ghi quyết định seed.
7. Xuất collision với cùng cluster, kích thước fill và seed đã được chấp nhận.
   Upstream thực hiện fill trước carve trong chính lệnh này.
8. Kiểm tra log fill/carve, checksum cluster, voxel/GLB và receipt; publish manifest cuối cùng.

Không viết lại thuật toán fill hoặc carve. Công cụ `eval/path/path_clearance.py`
dùng cùng `_pipeline` nội bộ của adapter trên input đã quy đổi mét, không tự khẳng
định metric confirmation hay publish artifact product.

## Khi nào pipeline dừng

Fill không bảo đảm sửa được mọi lỗ hở. Seed ngoài grid, seed còn nối được với bên
ngoài sau phép giãn của upstream, crop cắt mất phần bao phòng hoặc phòng không kín
đều có thể làm upstream bỏ qua fill. Adapter dừng thay vì tiếp tục carve không fill.
Profile hiện giữ crop baseline; trần cao hoặc scene ngoài trời cần profile phù hợp.
Không tự tăng crop, tăng kích thước fill hay giảm độ phân giải để cho attempt chạy tiếp.

Giới hạn voxel là kiểm tra dung lượng bảo thủ, không phải bảo đảm đủ VRAM/RAM.
Kernel clearance khớp phép làm tròn của carve 3.6.6 để seed đưa vào carve có chỗ cho
robot. Upstream có thể tự tìm seed khác mà không ghi log relocation; implementation
phòng ngừa bằng clearance trước carve, không tuyên bố phát hiện relocation qua log.

## Contract và tương thích

- Giữ nguyên profile `geometry_v1.json`; `Settings` chung vẫn mặc định profile legacy.
  Môi trường GPU indoor chọn profile mới bằng `PRODUCT_GEOMETRY_CONFIG`.
- Schema config/profile `1.0` và `1.1` không serialize trường fill mới, giữ nguyên
  JSON/checksum cũ. Fill khác null chỉ hợp lệ với schema `1.2`.
- Receipt clearance `1.2` ghi `occupancy_stage = post_external_fill`; consumer dùng
  cùng pure replay trên occupancy/config đã publish. Receipt cũ giữ hình dạng cũ.
- GeometryArtifact và manifest công khai giữ schema hiện có. Provenance bổ sung
  trạng thái/kích thước fill và checksum hai log; publisher đối chiếu report với log.
- Bundle mới lưu snapshot profile kèm checksum. Scorecard kiểm tra snapshot trước
  cache, dùng đúng kích thước robot của job. Job cũ chưa có snapshot được đối chiếu
  profile legacy đóng gói khi deployment chuyển sang profile indoor mặc định.
- Job/artifact đã có không được tự dựng lại. Đổi profile chỉ ảnh hưởng lần dựng mới.
- Giữ scratch/log khi attempt lỗi để chẩn đoán; không publish attempt chưa hợp lệ.

## Audit triển khai ngày 2026-10-11

CodeGraph được dùng để lần theo config → adapter → receipt → publication/resolver
→ bundle → scorecard; graphify query/path và AST update được dùng cho quan hệ liên file.
Đường downstream tiếp tục nhận canonical GLB, voxel, seed decision và artifact refs.

Đã chạy các kiểm tra tĩnh trên file sửa: Ruff check, Ruff format check, git diff check,
bash syntax entrypoint. Audit trực tiếp xác nhận JSON/checksum legacy không đổi,
snapshot profile giữ checksum khi đọc lại, receipt 1.2 replay được qua consumer seam,
và cả hai lệnh cùng truyền fill/seed. Audit receipt dùng occupancy fixture sẵn có,
không mô phỏng hay chứng minh external fill.

Compose được kiểm tra bằng `.env.studio.example` sau khi lần gọi không có env mẫu
dừng vì thiếu `.env.studio`. API và worker nhận cùng profile indoor. Audit cuối bổ
sung xử lý overflow trong phép tính dung lượng/extent để cấu hình cực lớn trả lỗi
có kiểm soát trước voxelization.

Theo phạm vi người dùng yêu cầu, chưa chạy pytest, GPU, dữ liệu thật, benchmark,
build/deploy container hoặc đánh giá chất lượng collider. Audit code/contract không
chứng minh mọi scene chạy thành công; lỗi runtime và chất lượng cần thực nghiệm sau.

Gate report: CodeGraph/graphify đã dùng; tái sử dụng upstream, không thêm thuật toán;
kiểm tra tĩnh và audit contract đã thực hiện; kiểm chứng vật lý/runtime còn chờ.
