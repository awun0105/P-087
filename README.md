# Real2Sim Studio

Real2Sim Studio biến một đoạn video quay không gian trong nhà thành môi trường thử nghiệm cho robot: dựng cảnh 3D đúng tỉ lệ mét, tách từng vật để chỉnh và đặt lại, tạo vùng va chạm, rồi đóng gói OpenUSD để kiểm định trong NVIDIA Isaac Sim. Kho hàng là một ví dụ sử dụng; mục tiêu là mọi không gian trong nhà mà robot di chuyển.

Dự án P-087, VinUni AI20K Cohort 4.

## Dùng thử

Mở **https://real2sim-studio.vercel.app** và bấm **Dùng thử ngay**. Tài khoản dùng thử là Guest: xem được mọi scene, tạo tối đa 3 job mỗi ngày và chỉ sửa scene của chính mình. Tài khoản gắn với trình duyệt đang dùng.

## Studio làm được gì

1. **Tải video** quay bằng điện thoại, có thể kèm dữ liệu LiDAR. Studio kiểm chất lượng video và có thể tự che mặt người, biển số.
2. **Dựng cảnh 3D** bằng Gaussian Splatting (FFmpeg → COLMAP → Brush) trên máy GPU thuê theo nhu cầu.
3. **Xác nhận tỉ lệ mét**: Studio đề xuất tỉ lệ, người dùng xác nhận bằng một đoạn đo thật.
4. **Tách vật**: Studio đề xuất vật thể, người dùng duyệt vùng, rồi Studio tạo hình khối và collider cho từng vật.
5. **Chỉnh bố trí và đi thử** trong trình duyệt; mỗi thay đổi tạo một bản sửa mới, truy vết được.
6. **Đóng gói và kiểm định**: xuất gói OpenUSD, chạy kiểm định Isaac (cần máy có Isaac Sim; bản cloud hiện chưa có), Reviewer duyệt và phát hành.

Phần nào đã chạy thật, phần nào mới có code và còn giới hạn gì: xem [STATUS](docs/STATUS.md).

## Công nghệ

Giao diện Next.js/React/TypeScript với viewer PlayCanvas/SuperSplat; API Python 3.12/FastAPI; PostgreSQL (Supabase) và Cloudflare R2 khi chạy cloud, SQLite và thư mục cục bộ khi chạy một máy. Dựng cảnh bằng FFmpeg, COLMAP và Brush trên worker GPU thuê qua RunPod; kiểm định bằng OpenUSD và NVIDIA Isaac Sim. Sơ đồ: [architecture_diagram](docs/architecture_diagram.md).

## Chạy trên máy của bạn

Cách nhanh nhất là Docker, dùng để mở dữ liệu đã xử lý. Cần Docker có Compose và gói dữ liệu `r2s-studio-data.zip` (nhóm chia sẻ tại [thư mục Drive](https://drive.google.com/drive/folders/1NqZmn3iJO6UuA4YCPq295jwMNMXDdr-f?usp=drive_link)).

```bash
git clone https://github.com/AI20K-Build-Phase-Cohort-4/P-087.git
cd P-087
# đặt r2s-studio-data.zip cạnh docker-compose.yml
cp .env.studio.example .env.studio
docker compose --env-file .env.studio -f docker-compose.yml up --build -d --wait
```

Mở http://localhost:3010 và đăng nhập bằng tài khoản có trong gói. Nếu gói không kèm tài khoản, điền `R2S_BOOTSTRAP_EMAIL`, `R2S_BOOTSTRAP_NAME`, `R2S_BOOTSTRAP_PASSWORD` (ít nhất 10 ký tự) trong `.env.studio` trước khi chạy để tạo Reviewer đầu tiên. Dừng bằng `docker compose --env-file .env.studio -f docker-compose.yml down`; dữ liệu trong `./data` được giữ.

Cách này không xử lý được video mới. Muốn dựng cảnh trên máy NVIDIA, chạy native để phát triển, hoặc triển khai production, xem [OPERATIONS](docs/OPERATIONS.md).

## Kiểm tra khi sửa code

Sau khi cài theo OPERATIONS mục 4, chạy từ thư mục gốc:

```bash
source .venv/bin/activate
ruff check src/ tests/ scripts/ && ruff format --check src/ tests/ scripts/
APP_ENV=test OPENAI_API_KEY=test-key pytest tests/ -q
python -m scripts.check_foundation && python -m scripts.check_contract_mirror
(cd frontend && npm run lint && npm run typecheck && npm test)
```

Test chạy trên dữ liệu giả; chúng không thay cho việc chạy job GPU, kiểm trên trình duyệt hay kiểm định Isaac thật. Không commit `.env`, `.env.studio`, `scripts/gpu/studio.env` hay khóa API.

## Tài liệu

| Muốn biết | Đọc |
| --- | --- |
| Vì sao làm sản phẩm này, cho ai | [BRAINSTORM](docs/BRAINSTORM.md), [MASTER_PITCH](docs/MASTER_PITCH.md) |
| Sản phẩm phải làm gì, nghiệm thu thế nào | [PRD](docs/PRD.md) |
| Hệ thống gồm những phần nào | [ARCHITECTURE](docs/ARCHITECTURE.md) |
| Dữ liệu đi qua những bước xử lý nào | [PIPELINE](docs/PIPELINE.md) |
| Quy tắc dữ liệu giữa các phần | [CONTRACTS](docs/CONTRACTS.md) |
| Dùng Studio thế nào | [UX](docs/UX.md) |
| Cài, chạy, bàn giao, khôi phục | [OPERATIONS](docs/OPERATIONS.md) |
| Đo chất lượng bằng cách nào | [EVALUATION](docs/EVALUATION.md) |
| Đã làm được gì, còn thiếu gì | [STATUS](docs/STATUS.md) |

Toàn bộ bản đồ tài liệu: [docs/README.md](docs/README.md).

## Nhóm

| Thành viên | Mã học viên | GitHub |
| --- | --- | --- |
| Lê Mạnh Cường | 2A202602604 | [@Cuongluadu25](https://github.com/Cuongluadu25) |
| Nguyễn Thọ Đạt | 2A202602484 | [@Usagshfil](https://github.com/Usagshfil) |
| Lâm Quang Anh Quân | 2A202602467 | [@awun0105](https://github.com/awun0105) |
| Nguyễn Minh Đức | 2A202602783 | [@minhduckx2004](https://github.com/minhduckx2004) |

Giấy phép: [MIT](LICENSE). Thành phần bên thứ ba: [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).
