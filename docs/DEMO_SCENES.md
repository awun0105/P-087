# Thêm cảnh demo vào thư viện mẫu

Thư viện mẫu là các **demo bundle**: thư mục chứa `manifest.json` và `files/`, nằm trong `PRODUCT_DEMO_DIR`
(mặc định `data/demo/library`). Mỗi thư mục con là một mẫu, hiện ở **Tạo scene mới → Thử mẫu** và công khai (xem được
khi chưa đăng nhập). Bundle chỉ chứa output thật của một lần chạy pipeline; giao diện không tự điền số liệu nào.

## Hai việc dễ nhầm
| Việc | Nút / lệnh | Tác dụng |
|---|---|---|
| **Đặt làm bản demo** | nút ở header scene (chỉ Reviewer) hoặc CLI | Xuất scene vào thư viện mẫu |
| **Mốc gốc** | "Đặt mốc gốc", "Khôi phục về mốc gốc" | Lưu revision để quay lại sau khi chỉnh scene; không liên quan thư viện mẫu |

## Quy trình thêm một cảnh demo mới
1. **Chạy pipeline thật** trên GPU (runbook `scripts/gpu/README.md`) cho video muốn làm mẫu. Video phải được khai
   đã có quyền sử dụng và đã ẩn danh khi tạo scene.
2. **Xuất vào thư viện** bằng một trong hai cách:
   - Reviewer mở scene, bấm **Đặt làm bản demo**, tick xác nhận công khai. Backend từ chối nếu project chưa khai
     quyền sử dụng và ẩn danh, nếu thiếu bản xem 3DGS đã xác minh, hoặc nếu job này đã nằm trong thư viện.
   - CLI trên máy có job: `python -m scripts.demo.export_demo_bundle --out <thư_viện>/<id> --demo-id <id> --title ... job --job-id <job_id>`.
3. Bundle tự có: video gốc, ~12 frame đại diện, bản xem 3DGS (`scene.sog`), quỹ đạo camera, thời lượng thật từng bước,
   thông số xử lý và máy đã chạy. Không bao giờ ghi đè bundle cũ.

## Thêm "thẻ" kết quả cho từng bước
Khung xem trước (cột trái của phát lại) ghép các thẻ theo bước. Bước chưa có thẻ nào chỉ hiện "mẫu chưa kèm hình hay
số đo", bước chưa chạy hiện "chưa ghi kết quả". Để thêm thẻ từ artifact GPU, viết `assets.json` rồi truyền
`--stage-assets assets.json` cho lệnh `job`:

```json
{
  "ST-METRIC-CANONICALIZE": [
    {"kind": "image", "title": "Điểm đo", "caption": "A, B và mặt sàn", "path": "metric.png"},
    {"kind": "facts", "facts": [{"label": "Khoảng cách A–B", "value": "1.35 m"}]}
  ],
  "ST-RGB-GEOMETRY": [{"kind": "video", "title": "Collision mesh", "path": "collision.mp4"}]
}
```

- `kind`: `image` | `video` (cần `path`, đường dẫn tính từ file JSON) | `facts` (danh sách nhãn/giá trị **đo thật**).
- Mỗi stage tối đa 8 thẻ; file được copy vào `files/` với tên phẳng và có checksum.
- Mẫu có bước LiDAR thì dòng thời gian tự có thêm các bước LiDAR như một job thật.

## Thêm một loại thẻ mới
1. Backend: thêm giá trị vào `DemoStageAsset.kind` (`src/services/orchestration/samples/models.py`) và quy tắc kiểm tra.
2. Frontend: thêm kiểu ở `DemoStageAsset` (`frontend/src/lib/contracts/studio.ts`, kèm kiểm tra trong `parseDemoManifest`)
   và một renderer trong `ASSET_RENDERERS` (`frontend/src/features/studio/showcase/registry.tsx`).
3. Thẻ dựng sẵn cho một bước (dùng file chung của bundle) đăng ký ở `STAGE_PRESENTERS` cùng file đó.

## Lưu ý riêng tư
Thư viện mẫu không cần đăng nhập, nên bundle chứa video gốc và frame của scene. Chỉ xuất scene có quyền công khai.
Khi xuất từ giao diện, thao tác được ghi nhật ký (`demo.publish`).
