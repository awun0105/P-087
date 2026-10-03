# Phân phối dữ liệu Studio và đóng gói deployment

## 1. Gói nào cần gửi

`data/real2sim-team-data` không phải kho dữ liệu mà app hiện dùng. Không tạo một
thư mục rỗng rồi zip nó. Công cụ `scripts/studio/data_package.py` lấy database và
file từ các vị trí canonical trong checkout và tạo **một ZIP có inventory/checksum**.

Trong gói có database, artifact đã publish (input, 3DGS, geometry, collider,
SceneIR/revisions, candidate/validation/release khi đã có), thumbnail cache,
thư viện demo, GLB asset preview và Rerun recordings khi tồn tại. Metadata
project/job/import/audit và tên actor được giữ. **Gói team hiện tại giữ hai tài
khoản seed, role, trạng thái active và password hash của chúng theo yêu cầu của
owner**: teammate đăng nhập bằng cùng email/mật khẩu hiện tại. Session, invite
và observation/lease tạm của worker không được gửi, nên cần đăng nhập lại.
Không có mật khẩu plaintext hay key provider trong ZIP.

Gói không cài GPU driver hoặc mang theo `.venv`, Node modules, COLMAP/Brush,
runtime máy nguồn, `.env`, key provider, scratch/QA/backup hoặc dataset raw.
Theme, camera tạm và thay đổi chưa lưu trong browser không nằm trong database.
Runtime manifest phải được sinh lại trên máy worker mới.

## 2. Xuất và kiểm gói trên máy nguồn

Không edit/upload/chạy job trong lúc đóng gói. Nếu còn processing đang hoạt động,
công cụ phải từ chối; không đổi status của job để vượt kiểm tra.

Từ root repo, với external drive đã mount:

```bash
make -f Makefile.studio data-pack KEEP_SEED_ACCOUNTS=1 COMPRESSION=stored OUT=/media/usb/real2sim-team-data/r2s-studio-data.zip
make -f Makefile.studio data-verify KEEP_SEED_ACCOUNTS=1 DATA=/media/usb/real2sim-team-data/r2s-studio-data.zip
```

ZIP giữ cấu trúc `data/` và chứa manifest version, source commit, lockfile hashes,
inventory và checksum từng file. Upload ZIP và checksum sidecar lên Drive sau
khi verify thành công. Không upload `.env` hay thư mục runtime của máy nguồn.
`COMPRESSION=stored` tạo ZIP không nén lại binary vốn đã compressed, giúp rút ngắn
thời gian snapshot. Bỏ tham số này nếu muốn dùng Deflate mặc định để giảm dung lượng.

Source của teammate phải có các file packaging này và hỗ trợ schema ghi trong
package. Chỉ có một checkout `develop` cũ không tự có Compose/script mới. Đồng bộ
source qua workflow Git của nhóm hoặc gửi thay đổi đã được review; không dùng
data ZIP để âm thầm thay source.

Gói phân phối trên ổ ngoài còn kèm `real2sim-studio-source.zip`: snapshot source
đã track của phiên bản hiện tại cộng các thay đổi packaging. ZIP này không có
`.git`, data, môi trường Python/Node đã cài hoặc file `.env` thật. Nếu `develop`
của teammate còn cũ, giải nén source ZIP vào một thư mục riêng rồi làm các bước
dưới đây. Nếu đã đồng bộ đúng source mới qua Git, chỉ cần gửi data ZIP.

## 3. Teammate chạy bằng Docker Compose

Cài Docker với Compose một lần (Docker Desktop trên Windows/macOS; Docker Engine
+ Compose hoặc Docker Desktop trên Linux). Không cần cài Python/Node native cho
stack Compose.

Backend dùng `linux/amd64` vì `usd-core==26.8` chưa có wheel Linux ARM64;
Mac Apple Silicon cần bật hỗ trợ giả lập x86 trong Docker Desktop. Điều này có
thể làm build/chạy chậm hơn và chưa được kiểm trực tiếp trên Mac.
Xem [danh sách wheel của USD](https://pypi.org/project/usd-core/26.8/#files).

Đặt ZIP tên `r2s-studio-data.zip` ở root repo. Copy `.env.studio.example` thành
`.env.studio` một lần (`cp .env.studio.example .env.studio` trên Linux/macOS;
`Copy-Item .env.studio.example .env.studio` trên PowerShell). Với gói giữ hai seed,
có thể để trống `R2S_BOOTSTRAP_*`. Sau đó chạy một lệnh từ root repo:

```bash
docker compose --env-file .env.studio up --build -d --wait
```

Nếu ZIP nằm trên ổ ngoài, đặt `STUDIO_DATA_ARCHIVE` trong `.env.studio` bằng đường
dẫn ZIP đó; `STUDIO_DATA_DIR` là thư mục sẽ chứa data đã giải nén. Mặc định cả hai
đường dẫn lấy theo root repo. ZIP vẫn giữ nguyên trên ổ ngoài sau khi restore.

Trên Windows, dùng đường dẫn host dạng `D:/real2sim-team-data/r2s-studio-data.zip`
trong `.env.studio`; ví dụ này không phải path trong container. Nếu Docker Desktop
không truy cập được ổ ngoài/thư mục host, cấp quyền file sharing cho đường dẫn đó
trong Docker Desktop theo backend đang dùng. Trên macOS cũng cần cho Docker truy
cập ổ ngoài. Xem [Docker Desktop file sharing](https://docs.docker.com/desktop/settings-and-maintenance/settings/#file-sharing).

Nếu build báo DNS error dù host truy cập Internet được, kiểm tra network của
Docker. Trên Linux có thể đặt `STUDIO_BUILD_NETWORK=host` trong `.env.studio`
rồi chạy lại cùng lệnh; giữ `default` trên Windows/macOS. Đây là lựa chọn build
network, không thay địa chỉ API hoặc data path.

Mở `http://localhost:3010`, đăng nhập bằng một trong hai tài khoản seed hiện tại.
Nếu xuất gói mặc định không giữ seed, điền `R2S_BOOTSTRAP_EMAIL`,
`R2S_BOOTSTRAP_NAME`, `R2S_BOOTSTRAP_PASSWORD` để tạo Reviewer mới trước khi chạy.
Restore kiểm toàn bộ package trước khi ghi và không thay database đã tồn tại.
Đường dẫn trong container cố định; không cần sửa `/home/...`, `/Users/...` hay `D:\...`.

Các lần chạy sau giữ data đã sửa. Dừng bằng:

```bash
docker compose --env-file .env.studio down
```

Không dùng `down -v` và không chạy thêm native Makefile `up` trên cùng cổng.
Nếu muốn thay snapshot trên máy đã có data, dừng stack rồi dùng `unpack --force`;
công cụ phải verify trước và backup data cũ. ZIP không phải database đang được
hai máy dùng chung: mỗi teammate có bản local độc lập sau khi restore.

## 4. Processing GPU

API/web có thể mở persisted scene, edit theo capability hiện có và dùng các
artifact đã lưu. Job processing mới cần worker thật. Docker không chuyển
NVIDIA/CUDA thành Apple GPU; các máy thiếu runtime này cần worker Linux chung.

GPU local dùng cấu hình `docker-compose.gpu.yml`, cùng database và data
mount của API, với NVIDIA runtime đã được kiểm trên host. Mặc định trong `.env.studio.example`,
`COMPOSE_FILE` đã cấu hình sẵn cả 2 file (`docker-compose.yml:docker-compose.gpu.yml`),
nên teammate có thể chạy ngay bằng:

```bash
docker compose --env-file .env.studio up --build -d --wait
```

Hoặc chỉ định tường minh các file:

```bash
docker compose --env-file .env.studio -f docker-compose.yml -f docker-compose.gpu.yml up --build -d --wait
```

Trên Linux có Make, lệnh tương đương là `make -f Makefile.studio docker GPU=1`.
Không cần chạy Compose rồi chạy Make thêm lần nữa. API/web không cần worker thì
dùng `make -f Makefile.studio docker` (hoặc comment dòng GPU trong `COMPOSE_FILE`).

Đây là cấu hình processing local NVIDIA; phải chạy preflight/real job để xác nhận
CUDA, Vulkan, Brush và kernel gsplat. Chưa kiểm Windows/WSL2 không được báo hỗ trợ
pipeline GPU hoàn chỉnh. Máy Mac không được claim chạy image CUDA này.
Teammate không có NVIDIA nhưng cần processing/tách vật thể dùng deployment chung
có API và worker GPU Linux; worker trên máy khác phải dùng chung PostgreSQL/R2,
không truy cập queue SQLite của bản local độc lập.

## 5. Production tách service

Theo accepted [ADR 0003](../decisions/0003-cloud-architecture-roles-and-browser-budget.md):

| Service | Nơi chạy | Dữ liệu/cấu hình |
| --- | --- | --- |
| Next.js Web | Vercel | `REAL2SIM_API_URL` trỏ API Railway ở build và runtime |
| FastAPI API | Railway | PostgreSQL Supabase; R2; auth/cookie; cache artifact local |
| PostgreSQL | Supabase | Metadata, queue, auth, audit; không lưu binary |
| S3-compatible files | Cloudflare R2 | Published artifact keys/checksums và direct multipart upload |
| GPU worker | Vast.ai; RunPod dự phòng | Cùng DB/R2 của API, runtime riêng, không lưu kết quả lâu dài trên pod |

Các template và quy trình nằm trong `deploy/studio/`. Đây là packaging/config,
không phải bằng chứng các provider đã deploy thành công. Cần thiết lập tài khoản,
URL, secret và region theo service trước khi deploy. Không copy SQLite local vào
hai máy rồi coi đó là queue chung.

Supabase chỉ dùng như PostgreSQL, không thay auth app bằng Supabase Auth. Lấy
session-pooler URL từ Dashboard, dùng SSL và cùng vùng với Railway; không tự ghép
hostname pooler. Giữ runtime schema migrations của app. Bảng app không được phơi
ra Data API với anonymous permissions; cấu hình exposure/RLS trên Supabase theo
runbook trước khi đưa user data vào production.

Published artifact ở R2 có cache resolver sẵn. Demo library, asset previews và
Rerun recordings hiện đọc từ folder local, nên cần provision volume/file tương
ứng trên API. Runbook có lệnh `package_publish provision` để đưa các file phụ
lên volume `/app/data`, giữ riêng PostgreSQL và R2. Volume này dành cho một API
instance; không cung cấp dữ liệu phụ dùng chung cho nhiều region/replica.

Source hiện tại có đủ 34 preview CC0/tự dựng trong
`configs/product/catalog_previews/`, được ưu tiên ở mọi môi trường theo ADR 0010
mục 3. Các file này đi cùng source ZIP/image. Bản chuyển từ asset Isaac chỉ là
fallback khi không có bản CC0 và `PRODUCT_ISAAC_ASSET_PREVIEWS` cho phép; fallback
này mặc định tắt ở staging/production. Packaging giữ cấu hình đó.

## 6. Acceptance và evidence

- Package: source không đổi, verify checksum/reference closure, snapshot giữ đúng
  account policy; round-trip positive, corrupt ZIP/unsafe paths/collision/rollback negative.
- Compose: config hợp lệ, images build, restore và API health, auth, scene/artifact
  endpoints và frontend render. Windows/macOS/ARM cần evidence trên máy đó.
- GPU: preflight CUDA + Vulkan và real published job; build Dockerfile không thay
  được proof này.
- Production: quan sát deploy status trên từng provider, DB query, R2 upload/download,
  login/session qua Vercel proxy, real worker và browser E2E. Không lấy local/mock
  results làm cloud acceptance.

Evidence của đợt implementation này ghi trong
`docs/plans/active/2026-10-03-studio-packaging.md` trong đợt cleanup tiếp nối.
