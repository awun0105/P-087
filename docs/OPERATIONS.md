# Vận hành Real2Sim Studio

## 0. Phạm vi và cách chọn đường chạy

| Thuộc tính | Nội dung |
| --- | --- |
| Ngày đối chiếu | 20/10/2026 |
| Snapshot source | `develop`, HEAD `ae6d0beb`, có thay đổi chưa commit |
| Vai trò | Cài/chạy Studio, quản lý cấu hình và runtime, bàn giao dữ liệu, theo dõi và khôi phục |
| Trạng thái | Đối chiếu source và kiểm tra cục bộ; chưa nghiệm thu lại stack, GPU, cloud hoặc Isaac |

| Nhu cầu | Đường chạy | Điều kiện chính |
| --- | --- | --- |
| Mở dữ liệu đã xử lý trên máy nhận bàn giao | Compose CPU, mục 2 | Docker Compose, gói dữ liệu hợp lệ; không có worker reconstruction |
| Chạy pipeline trên máy NVIDIA | Compose GPU, mục 3 | Docker dùng được GPU, runtime image và input phù hợp |
| Phát triển trên Linux | Native, mục 4 | Python 3.12, Node, GPU runtime và Docker cho COLMAP theo công thức Makefile hiện tại |
| API/Web và worker tách máy | Production, mục 6 | PostgreSQL, object store, cấu hình từng service, runtime/image đã kiểm định |

Các lệnh dưới đây chạy từ **root checkout** trong Bash, trừ khi có ghi khác. Đường dẫn `/duong/dan/...` phải thay bằng vị trí thật. Cài dependency, build image, `up`, restore, publish và điều khiển worker đều có tác động; chọn đúng mục theo môi trường đang vận hành.

[PRD](PRD.md) giữ phạm vi sản phẩm; [ARCHITECTURE](../ARCHITECTURE.md) giải thích process/storage; [PIPELINE](PIPELINE.md) giải thích chặng xử lý; [CONTRACTS](CONTRACTS.md) giữ quy tắc artifact/state; [UX](UX.md) hướng dẫn thao tác trong Studio. Tài liệu này tập trung vào công việc của người cài và vận hành.

## 1. Chuẩn bị cấu hình và dữ liệu

### 1.1 Các file cấu hình phục vụ mục đích khác nhau

| File | Ai đọc, dùng khi nào |
| --- | --- |
| [`.env.example`](../.env.example) → `.env` | `Settings` backend đọc khi chạy native; `make setup` chỉ tạo nếu chưa có |
| [`.env.studio.example`](../.env.studio.example) → `.env.studio` | Compose đọc biến host, cổng, archive, bootstrap và env API/worker |
| `scripts/gpu/studio.env` | `Makefile.studio env` sinh đường dẫn theo checkout native hiện tại; `run_stack.sh` nạp khi chạy |
| `data/runtime.env` | Installer ghi vị trí runtime trên máy; nạp bằng `load_runtime_env`, mục 4 |
| [`production.env.example`](../deploy/studio/production.env.example) | Mẫu nguồn có các phần shared/api/worker/web; công cụ `deploy_env` tách thành env riêng cho từng service |

Giữ file env thực và mật khẩu ngoài Git/gói bàn giao. Với native, biến đã export trong shell và biến từ `studio.env` có thể ghi đè `.env`; sửa một file không bảo đảm process đang chạy đã dùng giá trị mới. Muốn áp dụng phải khởi động lại đúng service theo mục 10.

`Settings` hiện yêu cầu khóa không rỗng của `LLM_PROVIDER` đã chọn, kể cả khi chỉ dùng Studio. Placeholder trong `.env.studio.example` phục vụ khởi tạo Studio local và không gọi được LLM; môi trường cần LLM phải cấp khóa thật riêng. Xem kiểm tra hiện hành trong [`src/config.py`](../src/config.py), không suy rằng mọi khóa provider đều cần cùng lúc.

### 1.2 Những dữ liệu cần giữ

| Nhóm | Cách xử lý |
| --- | --- |
| `data/studio_local/runtime.db` và `artifacts/` | Cần đi cùng nhau để bàn giao scene local; DB chứa tham chiếu, artifact chứa nội dung |
| `data/demo/library/`, `asset_previews/`, `rerun_recordings/`, thumbnail cache | Có thể nằm trong data package nếu hiện diện; giữ theo nhu cầu thư viện/hiển thị |
| `data/studio_local/workers/` và runtime đã cài trong `data/` | Workspace, cache, checkpoint và binary không thuộc data package; quản lý riêng |
| Env, credentials, chứng nhận runtime, image digest | Bàn giao cấu hình/secret qua kênh riêng; cài lại runtime theo công thức phù hợp |
| PostgreSQL và object store ở production | Backup bằng quy trình riêng, giữ DB và object tương ứng; không thay bằng ZIP SQLite |

`artifact://...` được resolver ánh xạ qua `ARTIFACT_ROOT`; đổi checkout không đòi sửa hàng loạt URI trong manifest. Không đổi nội dung artifact để chữa một lỗi đường dẫn cấu hình.

### 1.3 Phiên bản cài đặt

Core backend dùng [requirements lock](../requirements.lock.txt), development thêm [dev lock](../requirements-dev.lock.txt). Runtime GPU lấy phiên bản/checksum từ [pins.env](../configs/runtime/pins.env), các lock và installer tương ứng. Frontend dùng [package-lock](../frontend/package-lock.json). Giữ các file này cùng snapshot source, tránh tự nâng package trong lúc khôi phục một máy.

## 2. Compose CPU: nhận gói và mở Studio

### 2.1 Chuẩn bị lần đầu

Cần Docker Engine/Compose hoạt động và một ZIP tạo bằng công cụ ở mục 8. Compose hiện dùng API image `linux/amd64`; tài liệu này không chứng minh tính tương thích ARM hoặc GPU trên mọi hệ điều hành.

Chỉ sao chép env khi chưa có file cấu hình của máy:

```bash
test -f .env.studio || cp .env.studio.example .env.studio
python3 scripts/studio/data_package.py verify /duong/dan/r2s-studio-data.zip
```

Mở `.env.studio`, đặt `STUDIO_DATA_ARCHIVE` trỏ tới ZIP đã kiểm tra, `STUDIO_DATA_DIR` tới thư mục dữ liệu đích và kiểm tra hai cổng `STUDIO_API_PORT`/`STUDIO_WEB_PORT`. Mặc định archive là `./r2s-studio-data.zip`, dữ liệu là `./data`, API 8010 và Web 3010.

File mẫu khai báo cả GPU override qua `COMPOSE_FILE`. **Các lệnh CPU dưới đây luôn chỉ rõ `-f docker-compose.yml`** để chọn đúng stack.

### 2.2 Tài khoản đăng nhập

Compose bật xác thực. Nếu gói giữ Reviewer đang active, dùng tài khoản đã được bàn giao riêng. Gói xuất mặc định làm sạch credentials nên có thể cần tạo Reviewer đầu tiên: điền `R2S_BOOTSTRAP_EMAIL`, `R2S_BOOTSTRAP_NAME`, `R2S_BOOTSTRAP_ROLE=reviewer` và `R2S_BOOTSTRAP_PASSWORD` trong env; mật khẩu tối thiểu 10 ký tự.

Chọn email mới nếu email cũ chỉ còn là tài khoản attribution đã vô hiệu hóa. Bootstrap không phải công cụ reset mật khẩu hay kích hoạt lại tài khoản disabled; khi đã có Reviewer active, startup không tạo thêm tài khoản theo mỗi lần restart. Entrypoint cũng hỗ trợ `R2S_BOOTSTRAP_PASSWORD_FILE` nếu service được mount secret file tương ứng. Xem [`container_entrypoint.py`](../scripts/studio/container_entrypoint.py).

### 2.3 Khởi động và kiểm tra

```bash
docker compose --env-file .env.studio -f docker-compose.yml config --services
docker compose --env-file .env.studio -f docker-compose.yml up --build -d --wait
docker compose --env-file .env.studio -f docker-compose.yml ps -a
docker compose --env-file .env.studio -f docker-compose.yml logs --tail=100 api web
```

Stack CPU có bốn service: `data-init` chuẩn bị quyền thư mục; `data-restore` nhập gói; `api` và `web` chạy ứng dụng. Hai service đầu kết thúc thành công là bình thường. Với cổng mặc định, mở `http://localhost:3010/overview`, API docs ở `http://localhost:8010/docs`.

CPU stack không có worker reconstruction. Nó phục vụ API/Web và dữ liệu đã có trong phạm vi runtime cho phép; một nút xử lý vẫn có thể bị khóa vì thiếu năng lực. `/health` đạt không có nghĩa `/ready` hoặc một job mới sẽ đạt, xem mục 7.

### 2.4 Chạy lại và dừng

Để chạy lại cùng dữ liệu, dùng lại lệnh `up`; thêm `--build` khi cần dựng image theo source đã thay đổi. Dừng stack này bằng:

```bash
docker compose --env-file .env.studio -f docker-compose.yml down
```

Dữ liệu bind mount ở `STUDIO_DATA_DIR` được giữ. Khi SQLite đã tồn tại, `restore-if-needed` **bỏ qua archive**: thay ZIP rồi restart không nhập scene mới, không merge dữ liệu và không sửa artifact bị thiếu. Muốn thay bộ dữ liệu, làm quy trình restore ở mục 8 với đích riêng đã xác minh.

## 3. Compose GPU: thêm worker NVIDIA

### 3.1 Điều kiện và chọn image

Dùng bước chuẩn bị env/archive/tài khoản ở mục 2. Máy còn phải có driver NVIDIA và cấu hình container GPU hoạt động; installer trong repo không tự thay driver host. `nvidia-smi` trên host chỉ kiểm tra một phần, chưa chứng minh container, Vulkan hoặc job dùng được GPU.

Nạp đúng digest COLMAP từ repo rồi khởi động với cả hai file Compose:

```bash
export COLMAP_IMAGE="$(sed -n 's/^COLMAP_IMAGE=//p' configs/runtime/pins.env)"
docker compose --env-file .env.studio -f docker-compose.yml -f docker-compose.gpu.yml config --services
docker compose --env-file .env.studio -f docker-compose.yml -f docker-compose.gpu.yml up --build -d --wait
```

Giữ biến `COLMAP_IMAGE` và bộ `-f` này khi thao tác stack GPU. [GPU override](../docker-compose.gpu.yml) thêm `gpu-runtime-init` và `gpu-worker`, tổng cộng sáu service. Bước runtime init tạo manifest, registry và chạy preflight; xem lỗi bước này trước khi kết luận worker đã sẵn sàng.

### 3.2 Theo dõi và dừng đúng stack

```bash
docker compose --env-file .env.studio -f docker-compose.yml -f docker-compose.gpu.yml ps -a
docker compose --env-file .env.studio -f docker-compose.yml -f docker-compose.gpu.yml logs --tail=150 gpu-runtime-init gpu-worker api
```

Khi cần dừng, dùng cùng hai file với lệnh `down`. Lập kế hoạch dừng job theo mục 10 trước nếu máy đang xử lý. Không dùng lệnh CPU để quản lý một nửa stack GPU rồi suy rằng worker đã được dọn.

Image mặc định của [Dockerfile.gpu](../Dockerfile.gpu) là target `production` cho pipeline; Isaac là target riêng. Preflight đạt không thay cho bằng chứng một scene thực đã reconstruction, qua geometry review hay validation thành công.

## 4. Native Linux: môi trường phát triển

### 4.1 Cài core và frontend

Cần Python 3.12 cùng hỗ trợ venv; Node theo baseline runtime trong pins, npm, Docker và các công cụ hệ thống installer yêu cầu. Từ root checkout:

```bash
make setup
source .venv/bin/activate
(cd frontend && npm ci && npm run build:editor)
```

[`setup.sh`](../scripts/setup.sh) sync dependency có hash và kiểm tra dependency; mặc định cài cả development lock. Nó không tự cài USD/GPU/Isaac. Sửa `.env` sau khi tạo, đặc biệt provider/key và chế độ xác thực. `.env.example` mặc định `AUTH_REQUIRED=false` cho development; cấu hình này chỉ phù hợp máy phát triển được kiểm soát. Production bắt buộc bật auth.

### 4.2 Cài và nạp runtime

```bash
make -f Makefile.studio gpu-setup
make -f Makefile.studio env
REPO="$PWD"
source scripts/gpu/install.d/_lib.sh
load_runtime_env "$PWD/data/runtime.env"
```

`gpu-setup` có thể tải, build và cài nhiều runtime vào `data/`; cần mạng, dung lượng và công cụ hệ thống phù hợp. Công thức Makefile chọn COLMAP qua Docker và Node hệ thống. Đọc kết quả installer/doctor, không chỉ kiểm file có tồn tại.

`load_runtime_env` chỉ bổ sung biến đang thiếu hoặc rỗng; giữ các override đã khai báo. Không dùng `eval` để nạp tùy tiện nội dung file. `make ... env` giữ `studio.env` cũ trừ khi `FORCE_ENV=1`; nếu chuyển checkout, kiểm lại đường dẫn trong file cũ trước khi chạy.

Nếu nhận dữ liệu bàn giao, verify/unpack theo mục 8 **trước khi bật stack**. Nếu bật auth trên native, phải chuẩn bị tài khoản hợp lệ; `run_stack.sh` chạy Uvicorn trực tiếp, không thực hiện bootstrap của container entrypoint.

### 4.3 Bật và chạy lại

```bash
make -f Makefile.studio up
```

Lệnh chạy foreground: API, queue worker và Web cùng một stack; Ctrl+C dừng các process con. Mặc định Web chạy development. Dùng `make -f Makefile.studio up FRONTEND_MODE=prod` khi muốn build/start Web ở chế độ production trên máy phát triển này.

Makefile dò cổng từ API 8010/Web 3010, tối đa `PORT_SCAN=20` lựa chọn, rồi in URL thực tế. Cổng được ghi ở `data/studio_local/studio-ports.env`; `up` cập nhật `APP_PORT`, `STUDIO_WEB_PORT`, `REAL2SIM_API_URL` trong `studio.env`.

`up` còn phụ thuộc `lidar-runtime` và `registry`: có thể cài KISS-ICP, tạo thư mục và sinh registry dev-local khi thiếu. Nếu LiDAR cài lỗi, Makefile báo R5/R6 không khả dụng; đây không phải lệnh chỉ bật process. Registry dev-local là khai báo cho phát triển, không phải chứng nhận production.

Chỉ sửa giao diện thì có thể chạy riêng Web: bật API (`make run`, cổng 8000) rồi `cd frontend && npm run dev` (cổng 3000). `next.config.ts` chuyển `/api/v1/*` sang địa chỉ trong `REAL2SIM_API_URL` (mặc định `http://127.0.0.1:8000`), nên không cần bật CORS. `npm run typecheck` chạy `next typegen` trước `tsc` vì kiểu props của trang được sinh tự động; gọi thẳng `tsc` sẽ báo lỗi giả.

### 4.4 Xác định process trước khi dừng

```bash
make -f Makefile.studio status
```

`status` in cổng/PID; không kiểm health hoặc worker. Ưu tiên Ctrl+C trong terminal đã chạy stack. Khi cần dùng `make -f Makefile.studio down`, xác minh PID vẫn thuộc stack này: target gửi TERM cho process đang giữ hai cổng đã lưu, không xác thực độc lập danh tính ứng dụng. Sau khi process dừng, chạy lại bước nạp env/runtime và `up` nếu mở shell mới.

`make run` ở Makefile gốc chỉ chạy API trên cổng 8000. Chạy trực tiếp [`run_stack.sh`](../scripts/gpu/run_stack.sh) có mặc định API 8000/Web 3000, không dò cổng như Makefile; tránh lẫn hai đường chạy khi chẩn đoán URL.

## 5. Thay runtime và bật khả năng tùy chọn

### 5.1 Manifest và registry phải khớp runtime thực

Khi đổi binary, interpreter, model hoặc image, giữ lại identity cũ để truy vết và tạo manifest mới thay vì sửa checksum cho khớp một file tùy ý. [`make_runtime_manifest`](../scripts/gpu/make_runtime_manifest.py) yêu cầu `--out` chưa tồn tại; đổi đường dẫn cấu hình tới manifest mới sau khi kiểm tra.

[`qualify_input_runtimes`](../scripts/gpu/qualify_input_runtimes.py) tạo registry từ bản ghi kiểm định và identity runtime. Worker container chạy bước này khi startup; nếu lỗi, không giả lập registry đạt để mở recipe. API production cần được cấp file registry phù hợp theo cấu hình; heartbeat runtime của worker không tự thay thế bước cấp file này.

Tên runtime ưu tiên tiền tố `R2S_`; loader còn hỗ trợ tên `REC03_`/`REC04_`/`REC05_` tương ứng kèm cảnh báo. Xem [`runtime_env.py`](../src/runtime_env.py). Kiểm cả hai nguồn khi đổi cấu hình, tránh để override cũ âm thầm quyết định binary.

### 5.2 Doctor, preflight và worker có tác động khác nhau

`make -f Makefile.studio doctor` kiểm runtime đã cài và có thể gọi GPU/tool probe. Entrypoint GPU còn có thể tạo manifest/registry hoặc tải weight theo cấu hình trước khi preflight. Chỉ chạy trong môi trường dự kiến, ghi lại log và identity kết quả.

`python -m src.services.orchestration.jobs.worker_cli --once` **thực thi công việc đủ điều kiện trong queue**, không phải dry-run. Tương tự, controller `run`, `once`, `watchdog`, `drain` và `resume` có thể đổi trạng thái hoặc tài nguyên; mục 10 nêu cách dùng trong bảo trì.

### 5.3 Weight và Isaac

EgoBlur cần weight cùng điều kiện sử dụng phù hợp; không mặc định mọi weight đã có trong image hoặc mọi build chạy được offline. ObjectGS, scene runtime và Isaac có môi trường/installer riêng; core venv không thay thế các interpreter này.

Isaac cần target/runtime riêng, tài nguyên robot và cặp `PRODUCT_ISAAC_VALIDATION_CONFIG`/`PRODUCT_ISAAC_VALIDATION_PROFILE` hợp lệ. Việc chấp thuận giấy phép thuộc người vận hành; không tự bật `ISAAC_ACCEPT_EULA` chỉ để build đi tiếp. Chỉ công bố validation khi có report thật cho candidate tương ứng.

## 6. Production: tách cấu hình và triển khai service

### 6.1 Sinh env từ một nguồn

Sao chép `deploy/studio/production.env.example` tới thư mục riêng ngoài repo, điền giá trị của môi trường đích rồi chạy:

```bash
.venv/bin/python -m scripts.studio.deploy_env check --source /duong/dan/production.env
.venv/bin/python -m scripts.studio.deploy_env render --source /duong/dan/production.env --out-dir /duong/dan/generated-env
```

`check` báo lỗi nếu còn giá trị bắt buộc trống; mẫu chưa điền không phải cấu hình deploy thành công. `render` tạo `api.env`, `worker.env`, `web.env` sau khi kiểm tra. **Không source cả file nhiều section** vào một service: cùng tên khóa có giá trị/đường dẫn khác giữa API và worker. Không dùng `render --examples` để cấu hình máy thật; tùy chọn đó sửa file mẫu trong repo.

Hiện có test báo các file `*.env.example` đã sinh không khớp hoàn toàn nguồn. Trong thời gian chờ sửa riêng, dùng nguồn `production.env.example` và công cụ render; không ghép thủ công ba file mẫu như thể đã đồng bộ.

### 6.2 Thứ tự chuẩn bị

1. Chuẩn bị PostgreSQL và object store, quyền truy cập, backup và secret của môi trường đích. API/worker phải cùng hệ dữ liệu và artifact prefix; đường dẫn local có thể khác nhau.
2. Build/tag image từ cùng source và pins; lưu image digest. [API Dockerfile](../Dockerfile), [GPU Dockerfile](../Dockerfile.gpu) và [Web Dockerfile](../frontend/Dockerfile) phục vụ các process khác nhau. Dependency runtime ngoài core vẫn có bước tải/build; digest image là thông tin cần ghi cùng bản triển khai.
3. Cấp env, volume, processing config, registry và thư viện demo đúng loại; đặt URL upstream Web là origin API, không thêm `/api/v1`. Web có cấu hình proxy khi build, nên kiểm cả build argument và runtime env khi đổi API.
4. Bật API qua container entrypoint của image để giữ lifecycle chuẩn bị dữ liệu/bootstrap/supervisor. Kiểm DB/auth, sau đó runtime worker hoặc catalog hợp lệ, rồi kiểm Web và workflow cần cung cấp.
5. Với demo công khai, kiểm bootstrap thư viện và phiên cách ly theo mục 9 trước khi mở nhận người dùng. Ghi lại phần nào đã chạy thật, phần nào mới kiểm cấu hình.

Không đặt SQLite local vào vai trò DB dùng chung giữa các máy. API dùng `PRODUCT_RUNTIME_FROM_WORKERS=true` vẫn cần processing config; khả năng input còn phụ thuộc registry đã cấp. `STUDIO_WORKERS` điều khiển số worker, không tự cấp GPU hay bảo đảm đủ VRAM.

### 6.3 Controller và tài nguyên GPU

Mẫu production để `GPU_CONTROLLER_RUN=false`, `GPU_AUTOPROVISION_ENABLED=false`, `GPU_DRY_RUN=true`. Chỉ đổi sau khi đã điền deployment identity, release catalog/image, provider credentials, ngân sách và chính sách tài nguyên của môi trường đó. Code hỗ trợ controller không chứng minh nhà cung cấp đang có GPU hay catalog hiện còn deploy được.

`PRODUCT_GPU_RELEASE_CATALOG` hợp lệ có thể làm `/ready` đạt khi chưa có worker sống. Theo dõi tiếp trạng thái cấp tài nguyên, worker heartbeat và job; không diễn giải readiness thành GPU đã bật sẵn.

## 7. Theo dõi sức khỏe và chẩn đoán

### 7.1 Hai endpoint trả lời hai câu hỏi

Với API local dùng cổng mặc định:

```bash
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/ready
```

| Endpoint | Điều code kiểm | Giới hạn kết luận |
| --- | --- | --- |
| `/health` | Runtime DB mở được và truy vấn thành công | Không kiểm toàn bộ artifact, Web, GPU hay pipeline |
| `/ready` | DB, profile/runtime hoặc catalog phù hợp; thư viện mẫu nếu bắt buộc | Có thể đạt nhờ catalog; không chứng minh một worker đang chạy hoặc scene đã xử lý thành công |

`503` ở `/ready` cần đọc nội dung `status`, `runtime_published`, `compute_available`, `catalog_available`, `samples`. CPU stack không có processing runtime có thể chờ ở đây dù `/health` đạt. Endpoint mở RuntimeDatabase có thể kích hoạt migration lúc khởi tạo; không gọi nó như một phép kiểm hoàn toàn tách khỏi lifecycle DB. Nguồn: [`main.py`](../src/main.py).

### 7.2 Thu thập log có thể đối chiếu

Ghi thời gian, job/operation/session ID, attempt, bước gần nhất, mã lỗi, source/image/runtime identity và đường dẫn log/report. Phân biệt chờ người dùng, chờ runtime, chờ resource và process đã ngừng. Đọc manifest/event cùng artifact đúng attempt; file trung gian tồn tại chưa đủ để xác nhận thành công.

Compose dùng `ps -a` và `logs` của đúng bộ file ở mục 2/3. Native xem terminal stack và PID/cổng. Production xem log của API, worker và controller theo service đang quản lý. Trước khi chia sẻ log, bỏ secret/token và dữ liệu nhạy cảm; giữ bản gốc trong nơi lưu bằng chứng được phân quyền.

### 7.3 Các lỗi thường gặp

| Dấu hiệu | Kiểm tra và hướng xử lý |
| --- | --- |
| API báo thiếu khóa LLM | Kiểm provider đang chọn và nguồn env thực; không thêm khóa của mọi provider |
| Login không được sau import | Kiểm chính sách scrub và Reviewer active; bootstrap email mới nếu phù hợp, không sửa hash trong DB |
| Restart mà vẫn thấy scene cũ | SQLite có sẵn làm restore bị bỏ qua; restore vào đích riêng theo mục 8 |
| Có DB nhưng artifact 404 | Đối chiếu `ARTIFACT_ROOT`, bind mount, object prefix, checksum và quyền đọc; không chỉ copy DB |
| Web gọi sai API | Kiểm `REAL2SIM_API_URL`, cổng thực và proxy build/runtime; origin không chứa `/api/v1` |
| Có GPU nhưng recipe bị khóa | Kiểm runtime init, identity/registry, lý do capability và input facts; không ép registry thành available |
| Job đứng ở bước xác nhận | Kiểm action đang chờ trong UX; privacy/mét chờ người dùng là trạng thái hợp lệ |
| Worker không nhận queue | Kiểm DB/config/manifest, heartbeat, lease, admission và resource; đừng dùng `--once` như phép thử vô hại |
| API từ chối schema mới hơn | Dừng thử image cũ trên DB đó; phục hồi bản backup phù hợp vào môi trường riêng |

## 8. Bàn giao và khôi phục dữ liệu local

### 8.1 Xuất gói ổn định

Đợi công việc kết thúc và dừng các process có thể ghi trước khi xuất. Công cụ kiểm active jobs/operations, publication, reservations, upload và thùng rác; chỉ một số trạng thái chờ xác nhận mét đã được xác minh được ngoại lệ. Nếu bị từ chối, xử lý đúng lifecycle rồi xuất lại; không chỉnh status trực tiếp để vượt kiểm tra.

```bash
python3 scripts/studio/data_package.py --root "$PWD" pack --out /duong/dan/r2s-studio-data.zip
python3 scripts/studio/data_package.py verify /duong/dan/r2s-studio-data.zip
```

Script dùng Python standard library, có thể verify trước khi cài core. Nó snapshot SQLite, kiểm bytes/checksum và tính ổn định của nguồn khi đóng gói; không sao chép toàn bộ `data/`. Gói mặc định loại credential/session/invite và vô hiệu hóa account để giữ attribution mà không giữ khả năng đăng nhập.

`pack --keep-seed-accounts` chỉ dùng cho bàn giao riêng khi chủ đích giữ **đúng hai user** hiện có; nguồn khác số lượng này bị từ chối. Gói đó chứa password hash và trạng thái active, phải được quản lý như dữ liệu nhạy cảm. Không mặc định thêm flag này vào mọi bản xuất.

### 8.2 Nhập vào checkout đích

Dùng script từ checkout đích và đường dẫn ZIP đã verify:

```bash
python3 scripts/studio/data_package.py --root "$PWD" unpack /duong/dan/r2s-studio-data.zip
```

Đích phải chưa có các nhóm dữ liệu mà công cụ quản lý; unpack từ chối ghi đè khi có xung đột. Sau import, cấu hình runtime/đường dẫn của máy nhận rồi bật Studio. Binary/runtime và env của máy nguồn không được khôi phục từ gói.

Nếu thực sự thay dữ liệu cũ, dừng mọi writer và backup riêng trước. Tùy chọn `unpack ... --force` chuyển các nhóm dữ liệu được quản lý sang `data/studio_local/backups/before-unpack-*` rồi thay bằng gói; **cả nhóm optional không có trong gói mới cũng có thể bị chuyển khỏi vị trí cũ**. Công cụ có rollback khi lỗi, nhưng đây không phải backup toàn máy hay giao dịch chung với PostgreSQL/R2. Không xóa backup trước khi mở và kiểm dữ liệu mới.

### 8.3 Kiểm sau khôi phục

Kiểm tài khoản, danh sách project/scene, preview và việc đọc artifact; mở mẫu nếu gói có thư viện. Khi cần tiếp tục xử lý, kiểm thêm runtime identity, recipe và workspace/checkpoint thực sự còn dùng được. Data package không bảo đảm resume một bước GPU đang chạy dở trên máy khác.

## 9. Backup production, nhập lần đầu và thư viện demo

### 9.1 PostgreSQL và object store

Backup production phải gồm dữ liệu PostgreSQL/schema ứng dụng, artifact object cùng prefix/version tương ứng, thư viện mẫu và cấu hình/identity cần phục hồi. Giữ quyền truy cập/secret qua nơi riêng. Dừng hoặc kiểm soát writer để có mốc nhất quán; chọn công cụ backup/restore của hạ tầng đang dùng và diễn tập trên đích riêng.

Repo không cung cấp một lệnh ZIP duy nhất backup nguyên trạng cả PostgreSQL, R2 và phiên đang hoạt động. Chép SQLite từ máy dev vào volume API production không khôi phục hệ thống này. Cũng không chỉ rollback image nếu schema DB đã tiến lên và bản cũ không hỗ trợ.

### 9.2 Nhập gói local vào production trống

[`scripts.cloud.package_publish`](../scripts/cloud/package_publish.py) là đường chuyển gói SQLite đã làm sạch sang DB/artifact store production **trống**, không merge vào hệ thống đang có dữ liệu. Với env đích đã nạp đúng, chạy kiểm tra trước:

```bash
.venv/bin/python -m scripts.cloud.package_publish publish --package /duong/dan/r2s-studio-data.zip --report /duong/dan/import-check.json
```

Riêng subcommand `publish` không có `--apply` kiểm gói và đích, không import row/upload object; vẫn tạo dữ liệu tạm/report. Thêm `--apply` thực sự ghi DB và object store, cần backup và kiểm đích trước khi chạy. Hai store không cùng một transaction, vì vậy đọc report và trạng thái đích trước mọi lần thử lại.

Subcommand `provision --target-root ...` có thể ghi các nhóm optional như demo/preview/Rerun/cache ngay cả khi không có `--apply`; không gọi toàn bộ CLI này là dry-run chỉ dựa vào việc thiếu flag.

### 9.3 Phát hành và cài thư viện mẫu

[`scripts.demo.release`](../scripts/demo/release.py) có bốn lệnh `pack`, `verify`, `publish`, `bootstrap`. Đây là **demo library archive**, khác data package chứa SQLite; dùng đúng verifier theo loại gói. Kiểm archive demo bằng:

```bash
.venv/bin/python -m scripts.demo.release verify /duong/dan/demo-library.zip
```

`publish` ghi object store; `bootstrap` tải/cài thư viện theo Settings. Khóa object/checksum và prefix bản phát hành phải khớp, giữ baseline bất biến. Nếu thư viện đã provision từ release khác, dùng vị trí mới và cấu hình tương ứng thay vì chồng nội dung lên baseline cũ.

API cần volume thư viện và chỗ staging giải nén đủ dung lượng; thư mục tải ZIP tạm có thể tách khỏi thư viện trên volume. Phiên demo PostgreSQL dùng schema cách ly và output prefix riêng, cần role DB có quyền phù hợp; không công khai các schema này qua Data API. Janitor chờ kết thúc/cancel công việc còn sở hữu trước khi dọn phiên. Nội dung demo đã ghi không phải kết quả vừa chạy reconstruction/Isaac.

### 9.4 Thêm một cảnh vào thư viện mẫu

Thư viện mẫu là các demo bundle (thư mục có `manifest.json` và `files/`) trong `PRODUCT_DEMO_DIR`, mặc định `data/demo/library`. Mẫu hiện ở **Tạo scene mới → Thử mẫu** và xem được khi chưa đăng nhập, nên chỉ xuất scene đã khai quyền sử dụng và đã ẩn danh. Đừng nhầm với **mốc gốc** của scene: mốc gốc chỉ lưu revision để quay lại, không liên quan thư viện.

1. Chạy pipeline thật trên GPU cho video muốn làm mẫu.
2. Xuất bằng nút **Đặt làm bản demo** (Reviewer đã đăng nhập, ghi nhật ký `demo.publish`) hoặc CLI trên máy có job:

   ```bash
   .venv/bin/python -m scripts.demo.export_demo_bundle --out /duong/dan/thu_vien/ma_mau \
     --demo-id ma_mau --title "Tên mẫu" job --job-id job_id [--stage-assets assets.json]
   ```

   Backend từ chối khi thiếu khai báo quyền/ẩn danh, thiếu bản xem 3DGS đã xác minh, scene bị chặn vì riêng tư, hoặc job đã có trong thư viện. Lệnh không bao giờ ghi đè bundle cũ; thư mục đích không trống thì dừng ngay, lỗi giữa chừng thì dọn phần đã tạo nên chạy lại được. Job đã che mặt/biển số thì bundle bỏ video gốc.
3. `--stage-assets` thêm thẻ kết quả theo từng bước: một JSON ánh xạ mã bước sang danh sách thẻ `image` (.png/.jpg/.jpeg), `video` (.mp4/.mov) hoặc `facts` (nhãn/giá trị đo thật); đường dẫn tính từ file JSON, tối đa 8 thẻ mỗi bước. Ví dụ đầy đủ ở docstring của [`export_demo_bundle.py`](../scripts/demo/export_demo_bundle.py).

Thêm một loại thẻ mới cần sửa ba chỗ: `DemoStageAsset.kind` và quy tắc kiểm ở [`samples/models.py`](../src/services/orchestration/samples/models.py); kiểu `DemoStageAsset` và `parseDemoManifest` ở [`frontend/src/lib/contracts/studio.ts`](../frontend/src/lib/contracts/studio.ts); renderer trong `ASSET_RENDERERS` (hoặc `STAGE_PRESENTERS` cho thẻ dựng sẵn) ở [`showcase/registry.tsx`](../frontend/src/features/studio/showcase/registry.tsx).

## 10. Bảo trì, nâng cấp và xử lý gián đoạn

### 10.1 Trước khi dừng service

1. Xác định đúng deployment, DB/object prefix, PID/container và các job/operation/session đang hoạt động; lưu log cùng identity hiện tại.
2. Ngăn công việc mới vào worker theo cơ chế môi trường. Với GPU controller đã cấu hình, `python -m scripts.cloud.runpod_controller drain` đặt cờ drain; theo dõi cho đến khi công việc còn sở hữu được xử lý phù hợp. Drain không đồng nghĩa mọi writer/API đã dừng.
3. Dừng đúng service bằng TERM qua terminal/Compose/service manager; chờ cleanup thay vì xóa workspace hoặc reset queue. Backup dữ liệu trước nâng cấp/migration.

Controller `status` in trạng thái control plane, không chứng minh GPU/worker/job khỏe. Nó vẫn mở RuntimeDatabase khi tạo state store, có thể chạy khởi tạo/migration; chọn đúng env ngay cả khi chỉ xem trạng thái. `watchdog` có thể dừng tài nguyên dù không cấp pod mới, không dùng như kiểm tra chỉ đọc.

### 10.2 Khởi động lại và kiểm tra tiếp tục

Khởi động theo đúng bộ cấu hình cũ hoặc bản mới đã kiểm tra. [`worker_cli`](../src/services/orchestration/jobs/worker_cli.py) có recovery cho job gián đoạn/lease hết hạn và các operation tương ứng; kiểm trạng thái, attempt, lock/lease và event trước khi quyết định Retry. Job đang chờ privacy/mét không được coi là orphan chỉ vì không giữ lease.

Nếu dùng controller đã drain, chỉ `resume` khi môi trường sẵn sàng nhận công việc; lệnh này ghi trạng thái và đặt lại retry control. Không tự khởi chạy controller `once/run` để thử config trên môi trường thật.

Kiểm health/readiness, đăng nhập, một scene hiện có và thao tác cần phục vụ; sau đó mới nhận tải mới. Ghi rõ kiểm bằng dữ liệu thật hay fixture và worker đang chạy hay chỉ có catalog sẵn sàng.

### 10.3 Migration và backfill có mục tiêu

RuntimeDatabase tự chạy các migration được hỗ trợ khi khởi tạo, giữ dữ liệu theo migration hiện có và từ chối schema mới hơn code. Không chốt số schema cố định trong runbook; nguồn là [`database.py`](../src/services/orchestration/jobs/database.py). Backup trước khi chạy image mới, nhất là khi mở cùng DB bằng CLI bảo trì.

[`scripts.studio.scene_head`](../scripts/studio/scene_head.py) kiểm/backfill scene head theo `--job-id`; mặc định inspect, `--apply` mới lưu head theo số trang giới hạn. Việc mở DB vẫn có lifecycle migration. Chỉ dùng sau khi chẩn đoán đúng thiếu head và đã giữ backup; không chọn file revision có tên lớn nhất rồi gán thủ công làm head.

## 11. Mức kiểm chứng của hướng dẫn

Lượt chuẩn hóa này kiểm cú pháp shell, danh sách service Compose, CLI help, Foundation và các test packaging/runtime liên quan. Không thực hiện cài đặt mới, build/start/restart stack, export dữ liệu thật, migration DB vận hành, publish object, cấp GPU hoặc chạy Isaac.

Bộ test chọn lọc chưa đạt toàn bộ; chi tiết kết quả và các vấn đề cần xử lý riêng được lưu trong báo cáo chuẩn hóa. Không sửa code/config/test để làm bộ kiểm tra đạt trong lượt docs này.

Các lệnh khởi động/restore ở đây đã đối chiếu source và điều kiện sử dụng, chưa phải bằng chứng chạy lại end-to-end trên máy sạch. Giữ những giới hạn này khi bàn giao; kết quả kiểm tra chi tiết nằm trong [báo cáo chuẩn hóa](../.ai/reports/2026-10-20-documentation-inventory-and-plan.md).
