# Triển khai Studio demo

Landing đã deploy riêng. Runbook này chỉ triển khai Studio/API/GPU và thư viện mẫu.

## 1. Bundle và nguồn code

Các CLI Python dưới đây chạy trong environment theo requirements.lock.txt của repo. Trên host operator mới, tạo bằng `uv venv --python 3.12.14 .venv`, rồi `uv pip sync --python .venv/bin/python requirements.lock.txt`. Không cài GPU runtime vào environment operator chỉ để publish bundle.

Tạo bundle từ code hiện tại và các frozen sample đã công khai:

```bash
.venv/bin/python -m scripts.studio.build_demo_release --release demo-v1 --out /secure/releases/demo-v1
```

For an updated source release with an unchanged library, pass
`--demo-archive /secure/releases/previous/demo-library.zip`. The packager verifies
every member and reuses the archive by hardlink on the same filesystem.
`RELEASE.json` retains the library's own release ID and checksum.

Bootstrap downloads the ZIP to `PRODUCT_DEMO_DOWNLOAD_DIR` (default system temp;
use `/tmp` on Railway), then extracts beside `PRODUCT_DEMO_DIR` for an atomic
rename. Keep those on separate ephemeral/persistent mounts to avoid storing both
copies on a 5 GB volume. Capacity checks reserve 256 MiB; this does not reserve
space for subsequent user uploads or editor caches.

Có thể lặp `--sample <sample-id>` để chọn mẫu. Không chọn thì lấy mọi mẫu đang published. Bundle gồm source ZIP, SOURCE_MANIFEST, demo-library ZIP, RELEASE.json, SHA256SUMS, templates và runbook. Không có database/tài khoản/password dev, active session, worker scratch hay secrets. Source ZIP chứa cả source mới chưa commit trong các thư mục triển khai được cho phép; RELEASE.json ghi base commit và dirty state. Image digest để null tới khi build thật.

Trên máy nhận, kiểm `sha256sum -c SHA256SUMS`, giải nén `studio-source.zip` vào thư mục mới. Không giải nén đè code đang phục vụ. Không đưa bundle lên public repo hay public bucket.

## 2. Cấu hình và quyền

- Giữ GitHub repo private. Vercel private organization integration cần gói phù hợp; có thể dùng frontend container trên host CPU cùng origin với API.
- Tạo PostgreSQL và R2 riêng cho deployment. API và GPU dùng chung DATABASE_URL, main ARTIFACT_S3_PREFIX và PRODUCT_DEMO_OBJECT_PREFIX.
- PostgreSQL role của app cần migration và CREATE/DROP schema do chính role sở hữu. Demo schema chỉ do server tạo dạng `r2s_demo_<uuid>`; không expose qua Supabase Data API. API/worker dùng session pooler hoặc direct connection, không dùng transaction pooler cho các ownership lock giữ dài.
- Bucket luôn private. Quyền server gồm main artifact prefix, immutable demo-library prefix và disposable session prefix. CORS cho đúng Studio origin với GET/HEAD/PUT và expose ETag.
- Đặt lifecycle tự hủy multipart upload dở. Có thể đặt expiration cho `<ARTIFACT_S3_PREFIX>/demo-sessions/` sau thời gian dài hơn session hard TTL để thu gom output mồ côi khi mất kết nối. Không áp expiration đó lên baseline hay normal jobs.
- Secret chỉ ở provider env hoặc file env riêng ngoài repo/bundle. Chỉ web cần REAL2SIM_API_URL; không đưa DB/R2 keys vào frontend.
- Giới hạn ban đầu trong template: một worker GPU, tối đa tám session, hard TTL bốn giờ, idle ba phút. Tác vụ GPU nặng giữ resource reservation ở control DB. Session mới không có GPU riêng.

Điền bản sao production.env.example bên ngoài repo, rồi sinh env theo service:

```bash
.venv/bin/python -m scripts.studio.deploy_env check --source /secure/production.env
.venv/bin/python -m scripts.studio.deploy_env render --source /secure/production.env --out-dir /secure/rendered
```

Lần publish đầu có thể để archive key/checksum trống. Các required credentials còn lại phải có. Không nạp file gốc bốn section trực tiếp làm env cho một service; dùng api.env/worker.env đã render.

## 3. Publish thư viện mẫu

PRODUCT_DEMO_OBJECT_PREFIX phải là đường dẫn mới, ví dụ `demo/releases/demo-v1/library`. Không đổi bytes dưới release prefix đã phát hành.

```bash
.venv/bin/python -m scripts.demo.release --env-file /secure/rendered/api.env publish /secure/releases/demo-v1/demo-library.zip
```

Lệnh verify archive rồi upload các baseline/public files và archive vào R2. Không import DB dev, không tạo tài khoản, không tác động source jobs. Nó trả ba giá trị PRODUCT_DEMO_OBJECT_PREFIX, PRODUCT_DEMO_ARCHIVE_KEY, PRODUCT_DEMO_ARCHIVE_CHECKSUM; điền lại file cấu hình gốc và render lần nữa.

API khởi động sẽ tải archive đã ghim, kiểm toàn bộ member checksums, workspace graph và quyền công khai rồi provision PRODUCT_DEMO_DIR. Khi volume đã chứa release khác, startup từ chối thay thế. Với bản mới dùng volume mới hoặc thư mục release mới; nếu dùng managed volume path của Railway, chuyển sang volume mới để giữ canonical `/app/data/demo/library`.

Volume API cần đủ thư viện giải nén, archive tải tạm và cache/output của session. Worker chỉ tải artifact được yêu cầu qua fallback R2; không phải tải cả library archive. Không cần chép SQLite hoặc toàn bộ thư mục phiên từ API sang GPU.

PRODUCT_DEMO_REQUIRED=true làm startup từ chối phục vụ khi không có workspace mẫu hợp lệ. DrJohnson hiện là mẫu geometry-ready; Room/Playroom vẫn Draft. Không gắn nhãn Isaac-validated cho các mẫu chưa có kết quả đó.

## 4. Build và chạy

API:

```bash
docker build -f Dockerfile -t <registry>/studio-api:<release> .
```

GPU, trên host có đủ disk cho native runtime build:

```bash
docker build -f Dockerfile.gpu --build-arg COLMAP_IMAGE="$(sed -n 's/^COLMAP_IMAGE=//p' configs/runtime/pins.env)" -t <registry>/studio-gpu:<release> .
docker run --rm --gpus all --env-file /secure/rendered/worker.env --mount source=studio-gpu-data,target=/data <registry>/studio-gpu:<release> preflight
docker run -d --name studio-gpu --restart unless-stopped --gpus all --env-file /secure/rendered/worker.env --mount source=studio-gpu-data,target=/data <registry>/studio-gpu:<release> worker
```

Thay placeholder trước khi chạy. Ghim digest image sau build. Workflow `Build Studio release images` hỗ trợ build/push API; GPU dùng self-hosted runner mang label `studio-release`. Workflow không tự chạy khi push và không tự deploy. GitHub billing/runner phải hoạt động; hiện run CI trước đó bị chặn bởi billing.

Input runtime registry: worker tự sinh `/data/input_runtime_registry.json`. Cấp bản qualified của đúng image/runtime đó cho đường PRODUCT_INPUT_RUNTIME_REGISTRY của API. Chưa có cơ chế tự công bố registry input thay cho bước cấp file này.

Isaac là runtime riêng cần được cấp đúng launcher/resources và các config/profile theo template. GPU image reconstruction hiện không tự cài Isaac Sim. Nếu cần nút Isaac chạy thật, mount/cài runtime đó và đặt PRODUCT_ISAAC_VALIDATION_LAUNCHER/RESOURCES; thiếu runtime thì không coi deployment đã cung cấp validation. Không dùng kết quả giả để vượt gate.

Railway API dùng Dockerfile và manifest `deploy/studio/railway-api.json`, mount `/app/data`, nạp api.env. Entrypoint chuẩn bị volume, bootstrap Reviewer theo biến R2S_BOOTSTRAP_* trong README hiện có, rồi chạy Uvicorn. `/health` là liveness; `/ready` yêu cầu worker runtime heartbeat còn sống và library nếu required. Không dùng main data-package importer cho demo-only deployment trống này.

Lần đầu đặt R2S_BOOTSTRAP_EMAIL, R2S_BOOTSTRAP_NAME, R2S_BOOTSTRAP_ROLE=reviewer và R2S_BOOTSTRAP_PASSWORD trong secret store, hoặc dùng R2S_BOOTSTRAP_PASSWORD_FILE. Không điền password vào template. Nếu tải thư viện vượt healthcheck startup window, provision trước bằng `scripts.demo.release bootstrap` với cùng api.env, UID runtime và volume đã chuẩn bị, rồi khởi API dùng receipt có sẵn.

Vercel root `frontend/`, Node 24, đặt REAL2SIM_API_URL tại build time, build:

```bash
npm ci --no-audit --no-fund
npm run build:editor && npm run build
```

Nếu dùng frontend container, build với context `frontend/` và `--build-arg REAL2SIM_API_URL=https://<api-origin>`. Dùng HTTPS và domain Studio riêng. Không đưa job GPU dài vào Vercel Function.

## 5. Phiên đồng thời và cleanup

- Control DB giữ catalog phiên; mỗi phiên có schema PostgreSQL riêng và output R2 riêng. Logical job IDs/URIs giữ nguyên để replay baseline chính xác.
- Artifact resolver đọc output phiên trước rồi baseline chỉ đọc; mọi ghi đi vào session prefix. Download đã qua allowlist được ký URL trực tiếp tới object tương ứng.
- Native pipeline/scene/registration/validation workers được gọi bằng child process. Parent giữ ownership lock và shared-machine reservation. Child kế thừa AUTH_REQUIRED=true ở production.
- Đóng/timeout phiên thu hồi capability trước; parent dừng child đúng process tree. Janitor API mỗi 30 giây chỉ drop schema/xóa output khi không còn owner. Worker cũng quét khi poll.
- Cleanup retry idempotent khi DB/R2 lỗi. Mỗi host xóa cache riêng sau khi state durable đã purged. Baseline không bị xóa.
- Unpublish lưu bền vững trong control DB, đóng phiên đang mở và có hiệu lực ở các API replica.
- R2 signed URLs còn sống tới expiry. Giữ TTL ngắn theo chính sách. App tắt Uvicorn access log mặc định và gửi no-referrer/no-store cho demo; cấu hình cả ingress/provider logs để không lưu capability URL.
- Trước cleanup, r2s_demo_summaries giữ lifecycle, resource timing observations và event counts. Coverage vẫn partial: chưa có đầy đủ human task clock/mesh leaf spans/time-to-usable theo audit telemetry. Không công bố tổng người + máy từ dữ liệu thiếu.

## 6. Promote và rollback

Không gọi bundle là cloud-verified chỉ vì tạo ZIP hoặc static checks đạt. Xác nhận domain thật, DB/R2, image/runtime/registry, mesh/validation theo tính năng được cung cấp. Hai người cùng mẫu phải có state riêng, close/timeout không đổi baseline.

Giữ source bundle, image digests, env version và baseline prefix của từng release. Khi cần rollback: chặn nhận phiên mới, drain/close phiên, chuyển về image/config và volume baseline trước. Không dùng publisher import lên DB có dữ liệu; không drop main schema/bucket để rollback. Schema v24 thêm bảng control demo; image cũ từ chối schema mới theo guard hiện có, nên không chỉ redeploy image cũ vào DB mới. Dùng forward fix hoặc restore DB backup vào target riêng phù hợp rồi chuyển traffic.

Landing chỉ cần trỏ đến URL Studio cuối cùng nếu URL đã đổi. Không cần deploy lại landing khi build Studio/API/GPU.
