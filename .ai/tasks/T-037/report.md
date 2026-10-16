# Report T-037

Trạng thái: **in-progress, đang chờ chủ dự án** (bước 4 chưa chạy được vì thiếu đĩa). Bước 1, 2, 3 và 5 đã xong và commit.

## Done

- **Bước 1 — cache extension dùng chung** (`d63be3f4`): thêm `product_objectgs_extension_cache_dir` vào Settings
  (`src/config.py`); `objectgs_runtime_for` truyền vào `ObjectGSRuntime(extension_cache_dir=…)`. Không đặt biến thì giữ hành vi cũ.
  Test: `tests/test_scene/test_objectgs_runtime_config.py` (2 test).
- **Bước 2 — danh sách gói** (`0e6e7b1f`): `configs/runtime/objectgs/`:
  - `requirements.lock.txt`: sao từ `data/objectgs_runtime/packages.txt`, 126 gói ghim `==`, không có torch.
  - `torch.txt`: torch 2.1.2+cu118, torchvision 0.16.2+cu118, torchaudio 2.1.2+cu118, torch-scatter 2.1.2+pt21cu118
    (gộp từ `pytorch.txt` và `scatter.txt`).
  - `conda-python.txt`: python=3.8.19, wheel=0.45.1.
  - `conda-cuda.txt`: cuda-nvcc, cuda-cudart, cuda-cudart-dev, cuda-cccl = 11.8.89; gxx_linux-64=11.4.0; sysroot_linux-64=2.39.
- **Bước 3 — script** (`f2589a37`): `scripts/gpu/setup_objectgs_runtime.sh`:
  - Đọc ba commit ghim từ `src/services/scene/objectgs.py` (không chép tay). Cờ `--print-plan` chỉ in số ghim và danh sách, không cài gì.
  - Tải micromamba 2.0.5 bản ghim, kiểm sha256; tạo hai prefix `python/` và `cuda/` từ danh sách ở `configs/`.
  - Cài torch từ index cu118 (hoặc `--wheels` để cài offline), PyG, rồi `requirements.lock.txt`.
  - Clone và checkout detach ba repo ở commit ghim; kiểm `git status` sạch và đúng commit.
  - Biên dịch sẵn kernel gsplat bằng `import gsplat.cuda._backend` với đúng biến môi trường như `objectgs.py`
    (`PYTHONPATH`, `TORCH_EXTENSIONS_DIR`, `CUDA_HOME`, `CXX`, `CPLUS_INCLUDE_PATH`, `MAX_JOBS`, `TORCH_CUDA_ARCH_LIST`).
  - In các dòng `PRODUCT_OBJECTGS_*` để dán vào env; có dấu `.r2s-installed` (công thức + commit + hash danh sách) nên
    chạy lại trên đích đã cài thì thoát ngay.
  - Test tĩnh: `tests/test_gpu/test_setup_objectgs_runtime.py` (9 test, không cài gì).
- **Bước 5 — kết nối** (`2997baca`):
  - `Makefile.studio`: target `objectgs-runtime` (gọi script với `data/objectgs_runtime`, thêm `--wheels` nếu có thư mục wheels).
    Đã kiểm bằng `make -n`.
  - `scripts/kaggle/preflight.py`: mục "Runtime ObjectGS" là **tuỳ chọn** (không chặn), có test.
  - `scripts/gpu/studio.env.example`: khối `PRODUCT_OBJECTGS_*` (đã comment).
  - `scripts/gpu/README.md`: mục dựng runtime ObjectGS.

## Files changed (của T-037)

- `src/config.py`, `src/services/orchestration/scene/objectify.py`: cache extension.
- `tests/test_scene/test_objectgs_runtime_config.py`: mới.
- `configs/runtime/objectgs/{requirements.lock.txt,torch.txt,conda-python.txt,conda-cuda.txt}`: mới.
- `scripts/gpu/setup_objectgs_runtime.sh`: mới (chmod +x).
- `tests/test_gpu/test_setup_objectgs_runtime.py`: mới.
- `Makefile.studio`, `scripts/kaggle/preflight.py`, `scripts/gpu/studio.env.example`, `scripts/gpu/README.md`.

Không sửa `data/objectgs_runtime` (kích thước vẫn 9,3 GB, chỉ đọc).

## Tests (kết quả thật)

- Bộ bắt buộc của plan + test mới: `pytest tests/test_gpu/test_setup_objectgs_runtime.py tests/test_scene/test_objectify_draft.py
  tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_objectgs_objectify_flow.py tests/test_scene/test_objectgs.py
  tests/test_config.py tests/test_scene/test_objectgs_runtime_config.py -q` → **69 passed, 0 failed**.
- `bash -n scripts/gpu/setup_objectgs_runtime.sh` → ok.
- `ruff check` và `ruff format --check` trên các file Python đã sửa → pass.
- `scripts/gpu/setup_objectgs_runtime.sh <dir> --print-plan` → in đúng ba commit và danh sách; không tạo thư mục đích.

## Chưa làm (bước 4: dựng thật và smoke test)

- **Bị chặn bởi đĩa:** `df -h /` còn **3,3 GB** (lúc kiểm đầu), **4,1 GB** lúc cuối; bước 4 cần khoảng **12 GB**.
  Theo plan tôi không tự xoá gì và dừng ở đây. Chưa chạy script thật, nên các mục sau **chưa được kiểm**:
  - Acceptance 1 (chạy được và kiểm checksum thật): chỉ kiểm tĩnh.
  - Acceptance 2 (`pip freeze` trùng bản laptop): chưa làm.
  - Acceptance 3 (smoke ObjectGS PASS): chưa làm.
- Acceptance 4 (commit ghim chỉ ở `objectgs.py`): **đạt**, có test.
- Acceptance 5 (không sửa `data/objectgs_runtime`): **đạt**.

## Deviations from plan

1. **Thêm `configs/runtime/objectgs/torch.txt`** (plan không liệt kê): torch và torch-scatter không nằm trong
   `requirements.lock.txt` (đúng như `packages.txt` trên laptop), nên cần một file riêng để script đọc số ghim.
2. **sha256 của micromamba là trust-on-first-use:** `ff1a10b4…1f07fc` tính từ lần tải đầu (2026-10-16). Chưa đối chiếu với
   checksum chính thức của nhà phát hành.
3. **Gói pip chưa kiểm hash:** `requirements.lock.txt` không có hash (plan ghi "thêm hash nếu lấy được"; tôi chưa lấy được).
   Phần này chỉ được bảo vệ bằng ghim phiên bản `==`, chưa có kiểm checksum từng wheel.
4. **Target `make objectgs-runtime` trỏ tới `data/objectgs_runtime`** (đúng plan), tức là chạy trên laptop sẽ đụng vào thư mục
   đang dùng: tạo dấu `.r2s-installed`, và `git checkout --detach` trên ba repo. Pip sẽ no-op nếu đã đúng phiên bản.
   Nên đừng chạy target này trên laptop trước khi chủ dự án đồng ý.
5. **Phụ thuộc T-036:** một thay đổi khác đang chưa commit trong cây (đổi `data/*_runtime` và biến `REC*` → `R2S*`,
   thuộc T-036). Nếu thư mục `data/objectgs_runtime` bị đổi tên theo T-036 thì target `objectgs-runtime` và các
   ví dụ đường dẫn cần cập nhật. Tôi không commit phần đổi của T-036.

## Cần chủ dự án quyết định (cần để tiếp tục bước 4)

1. **Chỗ đặt runtime và đĩa:** dựng cần khoảng 12 GB. Có thể (a) cho phép dọn một phần ổ `/` (tôi không tự xoá),
   hoặc (b) dựng vào một ổ khác còn đủ chỗ (cho biết đường dẫn). Trên ổ `/` còn 4,1 GB.
2. **Smoke test thật** cần GPU và một việc nặng một lúc trên laptop: stack hiện có đang chạy job không? Nếu có, dừng
   stack trước hay chờ.

Trạng thái giữ `in-progress | engineer`: task chưa xong, và việc còn lại cần chủ dự án cho phép.

## Cập nhật: bước 4 đã dựng thật (vào /home/lqaq/objectgs_runtime_build, không đụng data/objectgs_runtime)

- Chủ dự án đã giải phóng đĩa; ổ `/` còn ~6,4 GB sau khi dựng (dựng tốn ~10 GB tạm, gồm cache conda/pip).
- `scripts/gpu/setup_objectgs_runtime.sh /home/lqaq/objectgs_runtime_build --wheels data/objectgs_runtime/wheels`:
  **EXIT=0**. Đã tạo prefix python và cuda, cài torch cu118, PyG, 126 gói pip, checkout ba repo đúng commit ghim,
  biên dịch sẵn extension gsplat (`ok: gsplat extension`), in đủ biến `PRODUCT_OBJECTGS_*`.
- **Acceptance 1 (chạy được, kiểm checksum):** dựng xong; chạy lại lần hai thoát sau 0,035 s (`[bỏ qua] đã cài đúng công thức`).
  Sha256 micromamba khớp khi tải.
- **Acceptance 2 (pip freeze trùng laptop):** `pip freeze` của runtime mới và `data/objectgs_runtime/python` đều 130 dòng và **giống hệt nhau** (diff rỗng).
- **Acceptance 3 (smoke ObjectGS thật):** **chưa chạy.** Smoke dùng GPU (Quadro T2000, 4 GB). Trên máy đang có
  stack chạy (`run_stack.sh`, API cổng 8010 trả 200), GPU hiện rảnh. Chờ chủ dự án xác nhận trước khi chạy.
- Chưa xoá thư mục build `/home/lqaq/objectgs_runtime_build`: vẫn cần cho smoke; xoá sau khi xong theo quy tắc dọn tạm.
