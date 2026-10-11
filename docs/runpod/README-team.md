# Real2Sim Studio — gói gửi teammate

Folder này chứa:

- `r2s-studio-data.zip`: dữ liệu app, 2.97 GB, 1.421 file payload.
- `r2s-studio-data.zip.sha256`: checksum ZIP dữ liệu.
- `real2sim-studio-source.zip`: source tương thích và cấu hình Docker mới.
- `real2sim-studio-source.zip.sha256`: checksum ZIP source.
- `VERIFICATION.json`: kết quả kiểm package, khởi động local và dry-run production.

Data giữ 5 project/scene, 2 demo, 34 asset preview và bản ghi Rerun hiện có.
Hai tài khoản seed giữ nguyên email, role, trạng thái active và mật khẩu. Phiên
đăng nhập cũ đã bị bỏ; hãy đăng nhập lại bằng tài khoản seed đang dùng. Không có
mật khẩu plaintext hoặc key provider trong ZIP dữ liệu.

## Chuẩn bị một lần

1. Cài Docker + Docker Compose. Windows/macOS dùng Docker Desktop; Windows chạy
   Linux containers. Backend dùng linux/amd64; Mac ARM cần hỗ trợ giả lập x86.
2. Nếu source Git của bạn đã có cấu hình packaging mới thì dùng checkout đó.
   Nếu còn source develop cũ, giải nén `real2sim-studio-source.zip` vào thư mục
   riêng. Root app là thư mục `real2sim-studio/` vừa giải nén.
3. Đặt `r2s-studio-data.zip` ở root app. Không cần giải nén ZIP dữ liệu bằng tay.
   Hoặc đặt `STUDIO_DATA_ARCHIVE` trong `.env.studio` trỏ tới ZIP trên ổ ngoài.
4. Copy `.env.studio.example` thành `.env.studio`:

```bash
cp .env.studio.example .env.studio
```

PowerShell dùng `Copy-Item .env.studio.example .env.studio`. Với gói giữ seed này,
để trống `R2S_BOOTSTRAP_*`. `STUDIO_DATA_DIR=./data` là đích data đã giải nén.
Windows dùng path host dạng `D:/real2sim-team-data/r2s-studio-data.zip`; cấp quyền
Docker Desktop đọc ổ ngoài nếu backend của bạn yêu cầu.

## Một lệnh để chạy API và web

Từ root app:

```bash
docker compose --env-file .env.studio up --build -d --wait
```

Compose tự build dependency, kiểm/restore ZIP nếu chưa có database, rồi chờ API
và web healthy. Mở `http://localhost:3010`. Dữ liệu cập nhật sau đó nằm trong
`STUDIO_DATA_DIR`; khởi động lại không ghi đè snapshot mới của bạn.

Trên Linux có Make, `make -f Makefile.studio docker` là alias của lệnh trên.
Không cần chạy Compose rồi chạy native `make ... up` thêm lần nữa.

Nếu Docker bridge trên Linux lỗi DNS trong lúc build, đặt
`STUDIO_BUILD_NETWORK=host` trong `.env.studio` rồi chạy lại cùng lệnh. Giữ
`default` trên Windows/macOS.

## Một lệnh gồm worker GPU local

Trong `.env.studio.example`, `COMPOSE_FILE` đã bật sẵn cả worker GPU. Vì vậy
máy Linux có NVIDIA driver/runtime và Vulkan phù hợp chỉ cần chạy:

```bash
docker compose --env-file .env.studio up --build -d --wait
```

(Hoặc chỉ định tường minh: `docker compose --env-file .env.studio -f docker-compose.yml -f docker-compose.gpu.yml up --build -d --wait`).
Alias trên Linux: `make -f Makefile.studio docker GPU=1`. Override cài runtime
COLMAP/Brush/splat-transform và worker từ image GPU; preflight kiểm khả năng thực
tế trước khi API chạy. Docker không cung cấp CUDA cho Apple GPU. Máy thiếu NVIDIA
nhưng cần job processing/tách vật thể dùng deployment chung với worker Linux và
PostgreSQL/R2 chung; worker từ xa không dùng queue SQLite local của bạn.

GPU image/real job, Windows/macOS và browser visual QA chưa được kiểm trực tiếp
trong đợt đóng gói này. Job đã lưu giữ nguyên trạng thái, gồm cả bước đang chờ
người chọn tỉ lệ; gói không thay runtime/checksum hay tự báo job thành công.

## Production

Source kèm `deploy/studio/` với template Vercel web, Railway API, Supabase
PostgreSQL, Cloudflare R2 và worker Vast.ai/RunPod. Quy trình import có verify,
dry-run mặc định và `--apply` explicit. Dữ liệu phụ được provision vào volume
`/app/data`; runtime manifest phải lấy từ worker thật đã qua preflight.

Đọc `docs/guide/studio-distribution.md` và `deploy/studio/README.md` trong source
trước khi cấu hình provider. Đây là package/configuration đã kiểm local; chưa có
deploy cloud. Production còn cần xử lý boundary credential của worker thuê,
QA privacy cho video mới, monitoring/backup và acceptance trên provider thật.
Source có đủ 34 preview CC0/tự dựng, dùng ở mọi môi trường. Bản chuyển từ asset
Isaac là fallback và mặc định tắt trên staging/production; provision file cũ
không tự bật fallback đó.
