# Chạy Real2Sim Studio trên máy của bạn

Hướng dẫn cho teammate nhận mã nguồn + gói dữ liệu. Không có bước nào phải sửa đường dẫn.

## Bạn cần gì

| Mục đích | Hệ điều hành | Cần cài sẵn |
|---|---|---|
| **Xem và chỉnh scene có sẵn** (khuyên dùng) | Linux, macOS, Windows | Docker Desktop hoặc Docker Engine có `docker compose` |
| Như trên, không dùng Docker | Linux, macOS | git, curl, ffmpeg (Python 3.12 và Node 24 được tự tải nếu thiếu) |
| **Chạy job dựng 3D mới** | Linux x86_64 + GPU NVIDIA | Như dòng trên + Docker + driver NVIDIA có Vulkan |

Chạy job mới cần GPU vì Brush (3DGS) train qua Vulkan trên GPU NVIDIA; trên macOS/Windows Studio mở ở **chế độ chỉ
xem**: mọi scene, viewer 3D, chỉnh vật thể, duyệt đều dùng được, riêng job mới sẽ nằm chờ.

## Cách 1 — Docker (mọi hệ điều hành)

```bash
git clone <repo> P-087 && cd P-087
git checkout feat/pipeline-v2          # hoặc develop sau khi PR được merge
# Đặt gói dữ liệu nhận được vào thư mục này, giữ tên r2s-studio-data.tar.gz
docker compose -f docker-compose.studio.yml up --build
```

Mở <http://localhost:3010>. Lần đầu build mất vài phút (tải thư viện, build giao diện); các lần sau khởi động trong
vài giây. Dừng bằng `Ctrl+C`; chạy lại bằng đúng lệnh trên (bỏ `--build` nếu mã nguồn không đổi).

- Gói dữ liệu được giải vào `./data` ở lần chạy đầu. Dữ liệu nằm trên máy bạn, không nằm trong image.
- Không có gói dữ liệu thì Studio vẫn mở, chỉ là chưa có scene nào.
- Đổi cổng: `API_PORT=9000 WEB_PORT=4000 docker compose -f docker-compose.studio.yml up`.
- Linux mà tài khoản của bạn không phải uid 1000: thêm `R2S_UID=$(id -u) R2S_GID=$(id -g)` trước lệnh.
- Windows: bật WSL 2 backend của Docker Desktop và clone repo trong ổ của WSL để đọc file nhanh.

## Cách 2 — cài native bằng make (Linux, macOS)

```bash
git clone <repo> P-087 && cd P-087 && git checkout feat/pipeline-v2
make -f Makefile.studio start DATA=r2s-studio-data.tar.gz
```

Lệnh này tự làm: tải `uv`, Python 3.12 và Node 24 nếu máy chưa có (đặt trong `data/tools`, không đụng hệ thống), cài thư viện
Python theo lockfile, `npm ci` cho frontend, build trình chỉnh Gaussian, sinh `scripts/gpu/studio.env` theo thư mục
checkout, giải gói dữ liệu, rồi bật API + web (+ worker nếu máy xử lý được). Nó in ra địa chỉ để mở.

Trên Linux có GPU NVIDIA và Docker, `start` cài luôn runtime xử lý (Brush 0.3.0, splat-transform 3.6.6, image COLMAP —
đều ghim phiên bản và kiểm checksum) nên chạy được job mới. Muốn tách vật thể, đề xuất tỉ lệ mét và LPIPS thì cài
thêm một lần (tải ~6 GB, cần `python3.12-dev` và CUDA toolkit):

```bash
scripts/gpu/setup_scene_runtime.sh data/scene_runtime
make -f Makefile.studio env FORCE_ENV=1     # sinh lại env để nhận runtime vừa cài (bản cũ được sao lưu)
```

Lệnh khác: `make -f Makefile.studio help`.

## Đăng nhập

Bản chạy trên máy cá nhân **không bắt đăng nhập** (`AUTH_REQUIRED=false`). Tài khoản trong gói dữ liệu đã bị vô hiệu
mật khẩu: tên người tạo/duyệt vẫn hiện, nhưng không ai đăng nhập được bằng chúng. Muốn bật đăng nhập:

```bash
make -f Makefile.studio account EMAIL=ban@example.com NAME="Tên bạn"   # nhập mật khẩu khi được hỏi
# rồi đặt AUTH_REQUIRED=true trong scripts/gpu/studio.env và chạy lại `up`
```

## Người gửi: tạo gói dữ liệu

```bash
make -f Makefile.studio data-pack            # → r2s-studio-data.tar.gz ở root repo
```

Gói gồm database (bản chụp nhất quán), artifact của mọi scene, ảnh thu nhỏ, thư viện mẫu, bản ghi Rerun. Gói **không**
chứa mật khẩu, phiên đăng nhập, API key, thư mục kiểm thử, thùng rác hay runtime. File không được commit (đã có trong
`.gitignore`); gửi qua kênh chia sẻ file của nhóm. Dữ liệu chỉ dùng đường dẫn logic nên giải ở thư mục nào cũng chạy.

## Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `port is already allocated` | Đổi cổng bằng `API_PORT`/`WEB_PORT` (Docker), hoặc để `make … up` tự dò cổng trống |
| Trang mở nhưng không có scene | Gói dữ liệu chưa được giải: kiểm tra file `r2s-studio-data.tar.gz` nằm ở root repo, rồi xoá `data/studio_local/runtime.db` rỗng (nếu có) và chạy lại |
| Docker báo không ghi được `./data` (Linux) | Chạy với `R2S_UID=$(id -u) R2S_GID=$(id -g)` |
| Viewer 3D trống | Trình duyệt cần WebGL2; thử Chrome/Edge bản mới và bật tăng tốc phần cứng |
| Build Docker lỗi "Temporary failure in name resolution" lúc pip/npm (Linux) | Mạng bridge của Docker trên máy không phân giải được tên miền: thêm `-f docker-compose.studio.hostbuild.yml` sau `-f docker-compose.studio.yml` |
| `make … start` báo thiếu công cụ | Cài theo dòng lệnh nó in ra rồi chạy lại; các bước đã xong được bỏ qua |
