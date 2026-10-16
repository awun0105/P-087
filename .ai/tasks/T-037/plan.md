# T-037: Script dựng runtime ObjectGS (`setup_objectgs_runtime.sh`)

## Goal
Runtime ObjectGS dựng lại được từ đầu bằng một lệnh, trên laptop, máy GPU thuê và trong image Docker, cho ra đúng môi
trường đang chạy được trên laptop (dựng tay ngày 15/10 ở `data/objectgs_runtime`).

## Context
- Code chỉ đọc đường dẫn qua Settings `PRODUCT_OBJECTGS_*` (`src/config.py:80–87`), dựng runtime ở
  `objectgs_runtime_for()` (`src/services/orchestration/scene/objectify.py:445`). Runner kiểm commit ghim
  (`src/services/scene/objectgs.py:32–34`, `_revision()` dòng 151: checkout phải sạch và đúng commit) và đặt
  `PYTHONPATH`, `TORCH_EXTENSIONS_DIR`, `CUDA_HOME`, `CXX`, `CPLUS_INCLUDE_PATH` (dòng 239–256).
- gsplat-object **không cài như gói**: nó được biên dịch JIT từ checkout qua `PYTHONPATH` vào `TORCH_EXTENSIONS_DIR`.
  Nếu không có `extension_cache_dir`, mỗi lần chạy biên dịch lại trong workspace (vài phút). `ObjectGSRuntime` có trường
  `extension_cache_dir` (dòng 57) nhưng Settings **chưa có** biến cho nó.
- Môi trường hiện có trên laptop, đọc từ `conda-meta/history` và file đi kèm:

| Thành phần | Giá trị đang chạy | Cách đã cài |
| --- | --- | --- |
| Python | 3.8.19 + wheel 0.45.1 | `conda create --prefix <root>/python python=3.8.19 wheel=0.45.1` |
| CUDA toolkit riêng | cuda-nvcc, cuda-cudart, cuda-cudart-dev, cuda-cccl **11.8.89**; gxx_linux-64 **11.4.0**; sysroot_linux-64 **2.39** | `conda create --prefix <root>/cuda --override-channels -c conda-forge -c nvidia ...` |
| torch | torch 2.1.2+cu118, torchvision 0.16.2+cu118, torchaudio 2.1.2+cu118 (`pytorch.txt`) | pip, index cu118 |
| torch-scatter | 2.1.2+pt21cu118 (`scatter.txt`) | pip, wheel của PyG |
| Gói khác | 126 dòng có ghim bản ở `packages.txt` (có `numpy==1.24.4`, `open3d-cpu==0.18.0`) | pip |
| Mã nguồn | ObjectGS `https://github.com/RuijieZhu94/ObjectGS.git` @ `0f6842b0…`; gsplat-object `https://github.com/RuijieZhu94/gsplat-object.git` @ `68a61a44…`; GLM `https://github.com/g-truc/glm.git` @ `bf71a834…` | git clone + checkout |
| Bản cài offline | 133 wheel trong `wheels/` (torch 2,3 GB) | đã tải sẵn |

- Mẫu cần theo: `scripts/gpu/setup_scene_runtime.sh` (hàm `need`, `fetch` có kiểm sha256, chạy lại được, in biến cuối
  script).

## Files
- Tạo: `scripts/gpu/setup_objectgs_runtime.sh`, `configs/runtime/objectgs/requirements.lock.txt` (chép từ
  `data/objectgs_runtime/packages.txt`, thêm hash nếu lấy được), `configs/runtime/objectgs/conda-cuda.txt` và
  `conda-python.txt` (danh sách gói conda kèm bản), `tests/test_gpu/test_setup_objectgs_runtime.py`.
- Sửa: `src/config.py` (thêm `product_objectgs_extension_cache_dir: Path | None = None`),
  `src/services/orchestration/scene/objectify.py` (`objectgs_runtime_for` truyền `extension_cache_dir`),
  `scripts/kaggle/preflight.py` (thêm mục ObjectGS, tuỳ chọn), `Makefile.studio` (target `objectgs-runtime`),
  `scripts/gpu/studio.env.example`, `scripts/gpu/README.md`.
- Không sửa: `Dockerfile.gpu` (T-038 gọi script này), `data/objectgs_runtime` hiện có.

## Thiết kế script
```
scripts/gpu/setup_objectgs_runtime.sh <thư_mục_đích> [--wheels <thư_mục_wheel>] [--skip-gpu-check]
```
Bố cục đích (giống laptop để code không phải đổi):
```
<đích>/python/        Python 3.8.19 (conda prefix)
<đích>/cuda/          CUDA 11.8.89 + gxx 11.4.0 (conda prefix)
<đích>/ObjectGS/      checkout @ OBJECTGS_COMMIT
<đích>/gsplat-object/ checkout @ GSPLAT_COMMIT
<đích>/glm/           checkout @ GLM_COMMIT
<đích>/torch_extensions/  cache biên dịch gsplat-object (dựng sẵn ở bước cuối)
<đích>/.r2s-installed     một dòng: phiên bản công thức + 3 commit; khớp thì script thoát sớm
```
Yêu cầu:
1. **Lấy conda không cần cài sẵn**: tải `micromamba` bản ghim (URL + sha256 ghi trong script) vào thư mục tạm của lần
   cài; dùng nó để tạo hai prefix với đúng gói và kênh như bảng trên. Máy đã có `conda` thì vẫn dùng micromamba (một
   đường duy nhất, không rẽ nhánh).
2. Commit ghim **đọc từ `src/services/scene/objectgs.py`** (grep 3 hằng số), không chép tay vào script: đổi commit ở
   code thì script đi theo.
3. pip cài theo thứ tự: torch/torchvision/torchaudio (index `https://download.pytorch.org/whl/cu118`), torch-scatter
   (index `https://data.pyg.org/whl/torch-2.1.2+cu118.html`), rồi `requirements.lock.txt`. Có `--wheels` thì thêm
   `--no-index --find-links <dir>` (cài offline từ `data/objectgs_runtime/wheels`).
4. Clone ba repo, `git checkout --detach <commit>`, kiểm `git status --porcelain` rỗng.
5. **Dựng sẵn extension**: chạy một lệnh Python trong runtime với đúng biến như `objectgs.py:239–256`
   (`PYTHONPATH=<gsplat-object>`, `CUDA_HOME=<cuda>`, `CXX/CC=<cuda>/bin/x86_64-conda-linux-gnu-g++`,
   `CPLUS_INCLUDE_PATH=<python>/include:<glm>`, `TORCH_EXTENSIONS_DIR=<đích>/torch_extensions`,
   `TORCH_CUDA_ARCH_LIST` lấy từ biến môi trường, mặc định `7.5;8.0;8.6;8.9`) để import gsplat-object và kích hoạt
   biên dịch. Đọc mã gsplat-object ở commit ghim để biết import nào kích hoạt JIT; không đoán. Bước này không cần GPU
   (như `setup_scene_runtime.sh` với `R2S_SKIP_GPU_CHECK`); có `--skip-gpu-check` thì bỏ kiểm `nvidia-smi`.
6. Cuối script in đúng các dòng để dán vào file env:
   `PRODUCT_OBJECTGS_RUNTIME_PYTHON`, `PRODUCT_OBJECTGS_REPOSITORY`, `PRODUCT_OBJECTGS_GSPLAT_REPOSITORY`,
   `PRODUCT_OBJECTGS_CUDA_HOME`, `PRODUCT_OBJECTGS_CXX`, `PRODUCT_OBJECTGS_GLM_REPOSITORY`,
   `PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR`.
7. `set -euo pipefail`; mọi tải về kiểm sha256; lỗi thì dừng với thông báo nói thiếu gì.
8. Chạy lại trên đích đã cài đúng bản: thoát trong vài giây, không tải lại.

## Steps
1. **Settings cho cache extension.** Thêm `product_objectgs_extension_cache_dir`; `objectgs_runtime_for` truyền vào
   `ObjectGSRuntime(extension_cache_dir=...)`. Test: Settings có biến → runtime có đúng đường dẫn; không có → `None`
   (giữ hành vi cũ). Commit `Let deployments share a prebuilt ObjectGS extension cache`.
2. **Danh sách gói.** Tạo các file trong `configs/runtime/objectgs/` từ dữ liệu laptop (chép, không sửa bản). Commit.
3. **Script.** Viết theo thiết kế. Test tĩnh `test_setup_objectgs_runtime.py` (không cài thật): `bash -n`; commit
   trong script là grep từ `objectgs.py` (test đổi hằng số giả trong bản sao và kiểm script đọc theo); có kiểm sha256
   cho mọi `curl`; bản trong `conda-*.txt` khớp bảng Context. Commit.
4. **Dựng thật trên laptop vào thư mục mới** (không đụng `data/objectgs_runtime`):
   - Ổ đĩa đang gần đầy: kiểm `df -h` trước. Cần khoảng 12 GB. Không đủ thì **dừng, hỏi chủ dự án** dọn gì; không tự xoá.
   - Chạy `scripts/gpu/setup_objectgs_runtime.sh <thư mục tạm của bạn>/objectgs --wheels data/objectgs_runtime/wheels`.
   - So: `<mới>/python/bin/python -m pip freeze` với `data/objectgs_runtime/python/bin/python -m pip freeze`: phải trùng
     (khác thì ghi từng dòng khác vào report và giải thích).
   - Chạy smoke thật: `scripts/scene/smoke_objectgs.py` với runtime mới (đọc tham số của script). Máy local: **một việc
     nặng một lúc**, hỏi chủ dự án trước nếu stack đang chạy job; ghi thời gian, VRAM đỉnh, kết quả.
   - Chạy lại script lần hai trên cùng đích: phải thoát sớm.
   - Xong thì xoá thư mục tạm bằng đường dẫn đầy đủ (quy tắc 11).
5. **Kết nối.** `Makefile.studio` target `objectgs-runtime` (gọi script với đích `data/objectgs_runtime`, mặc định dùng
   `data/objectgs_runtime/wheels` nếu có); `preflight.py` thêm mục ObjectGS **tuỳ chọn** (thiếu thì ghi "tách vật dùng
   đường khác", không exit 1); cập nhật `studio.env.example`, `scripts/gpu/README.md`. Commit.

## Acceptance criteria
1. Một lệnh dựng runtime ObjectGS ở thư mục bất kỳ, chạy lại được, có kiểm checksum.
2. `pip freeze` của bản dựng mới trùng bản laptop (hoặc khác có giải thích được chấp nhận).
3. Smoke ObjectGS thật PASS trên runtime mới, hoặc report ghi rõ vì sao chưa chạy được.
4. Commit ghim chỉ ở một chỗ (`objectgs.py`).
5. `data/objectgs_runtime` không bị sửa.

## Tests required
```
.venv/bin/python -m pytest tests/test_gpu/test_setup_objectgs_runtime.py tests/test_scene/test_objectify_draft.py \
  tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_objectgs_objectify_flow.py \
  tests/test_scene/test_objectgs.py tests/test_config.py -q
bash -n scripts/gpu/setup_objectgs_runtime.sh
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
