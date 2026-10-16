# Report T-038: Một công thức cài cho mọi máy GPU

## Kết luận ngắn
- Một lệnh `scripts/gpu/install.sh <gốc>` dựng và nhận ra mọi runtime GPU (COLMAP, Brush, splat-transform, LiDAR
  odometry, scene, ObjectGS). Chạy lại thì thành phần đúng không được cài lại. `scripts/gpu/doctor.sh <gốc>` kiểm.
- Phiên bản ghim chỉ ở `configs/runtime/pins.env` (cộng SAM2/LaMa/MoGe trong `setup_scene_runtime.sh` và commit ObjectGS
  trong `src/services/scene/objectgs.py`, đúng ngoại lệ của plan). Quét tự động trong `tests/test_gpu` chứng minh điều đó.
- Laptop: `make -f Makefile.studio gpu-setup` trên `data/` nhận ra cả sáu thành phần (không cài lại gì), ghi
  `data/runtime.env`, và `doctor` in OK cho mọi mục. Stack `r2s-stack` không bị khởi động lại; API và web vẫn trả lời.
- COLMAP cài được không cần Docker (`--colmap=binary`): gói 4.x ghim sha256, kiểm được `pose_prior_mapper`.
- Mục review T-037 (bắt buộc): khoá ObjectGS nay liệt kê hash của mọi file pip tương thích CPython 3.8 Linux x86_64;
  torch được khoá có hash riêng. Kiểm bằng cài online không `--wheels` (xem mục "Kiểm chứng").
- Image `Dockerfile.gpu` và entrypoint không còn tự cài hay tự đặt đường dẫn công cụ. **Chưa build image** (T-039).

## Commit (theo thứ tự)
| Commit | Nội dung |
|---|---|
| `9751ed41` | Bước 1: `pins.env`, `apt-packages.txt`, `install.sh`, `doctor.sh`, `install.d/*.sh`, test tĩnh |
| `d375ac0f` | Bước 2: `export_colmap_binary.sh`, `colmap_binary.py` (đẩy/tải có sha256), nhánh `--colmap=binary`, test |
| `36df8c5f` | Bước 3 (Makefile): `gpu-setup`, `doctor`; `lidar-runtime`/`objectgs-runtime` gọi `install.sh --only` |
| `ac62a5c4` | Probe ObjectGS dùng đúng môi trường biên dịch của runner; bỏ ép `TORCH_CUDA_ARCH_LIST` |
| `8f5ad64f` | `runtime.env` ghi cộng dồn (không xoá dòng của thành phần khác); bỏ timeout khỏi `runtime.env`; `R2S_NODE_BIN_DIR`; COLMAP đã giải nén thì chỉ tạo wrapper; `python3-venv` |
| `f755a495` | Kiểm ObjectGS không cần GPU (cho build image); `load_runtime_env` coi biến rỗng là chưa có |
| `4e32f108` | Bước 4: `Dockerfile.gpu` dựng qua `install.sh`; `docker_entrypoint.sh` nạp `runtime.env` |
| `4dd78410` | Bước 4: compose, `Makefile.studio` lấy phiên bản từ `pins.env`, mặc định lidar |
| `8c65364c` | Bước 5: `RUNPOD_GUIDE.md`, `scripts/gpu/README.md`, `deploy/studio/OVERVIEW.md` |
| `2dcc2230` | Review T-037: khoá hash đầy đủ (`objectgs_lock.py`), `torch.lock.txt`, bỏ `torch.txt` |
| `57ef3db4` | Review T-037: ghim `wheel==0.45.1` có hash (lỗi thật của khoá, phát hiện khi cài sạch) |

## Quyết định và lệch so với plan
1. **Node trên laptop là Node hệ thống** (`--system-node`, v24.11.1 từ mise). Lý do: máy đang chạy đã có Node; cài thêm
   bản ghim v22.20.0 sẽ là bản thứ hai không cần thiết. Pod và image dùng Node ghim (không `--system-node`).
   `R2S_NODE_BIN_DIR` chỉ được ghi khi node do `install.sh` cài. Đây là biến mới ngoài danh sách plan, vì app gọi
   `node` từ PATH và image cần thư mục bin của node.
2. **Giấy phép COLMAP và onnxruntime lấy từ kho mã upstream** (ghim sha256 trong `pins.env`), vì image ghim không chứa
   file giấy phép. Lệch so với plan (plan không nói rõ nguồn).
3. **Cache gsplat đã được xác minh sai trước đó, nay đã sửa.** Lần đầu `objectgs.sh` chỉ kiểm tra file `.so` tồn tại,
   và probe của doctor không có đủ biến biên dịch nên gsplat biên dịch lại. Nay probe và kiểm đều dùng
   `objectgs_probe_env()` (`scripts/kaggle/preflight.py`), là môi trường giống `src/services/scene/objectgs.py`.
4. **Bỏ ép `TORCH_CUDA_ARCH_LIST`** khỏi các script ObjectGS: runner để torch tự dò kiến trúc GPU, nên ép một danh sách
   khác sẽ tạo cache mà runner không dùng. Lệch: cache sm_75 trên laptop được biên dịch lại, chỉ cho GPU của máy này
   (cache 4 kiến trúc cũ bị bỏ). Image vẫn đặt `TORCH_CUDA_ARCH_LIST` bằng ENV vì build không có GPU để dò; runtime
   của container kế thừa đúng giá trị đó.
5. **Timeout không nằm trong `runtime.env`** (plan: chỉ đường dẫn và identity). Timeout nằm ở `studio.env.example` và
   ở mặc định của entrypoint container.
6. **`runtime.env` ghi cộng dồn** (lỗi phát hiện khi làm bước 3: `--only scene` làm mất dòng brush). Hệ quả: khoá đã
   bỏ khỏi danh sách không tự mất; muốn dọn thì xoá file rồi chạy lại.
7. **Biến rỗng được nạp từ `runtime.env`.** Compose để trống các ô công cụ để đường dẫn máy host trong `.env.studio`
   không lọt vào image GPU. Hệ quả: tên `REC*` cũ do người vận hành đặt không còn ghi đè `runtime.env` (tên mới luôn
   thắng; app vẫn cảnh báo khi đọc tên cũ).
8. **Dockerfile không tự cài**: COLMAP vào image qua `COPY` của cây đã giải nén, `install.sh --colmap=binary` chỉ tạo
   wrapper `colmap-run`. `COLMAP_IMAGE` không còn là giá trị mặc định trong Dockerfile: truyền bằng `--build-arg` từ
   `pins.env` (xem đầu file). Test quét Dockerfile không cho phép chép digest hay phiên bản.
9. **Trạng thái T-036**: accepted (round 3). Không lệch.

## Thay đổi đáng chú ý trên laptop (không khởi động lại stack)
- `data/objectgs_runtime/torch_extensions`: cache gsplat được biên dịch lại cho sm_75 (`Quadro T2000`).
  Đây là lần biên dịch thật (log `gpu-setup-3.log` và `gpu-setup-final.log` trong scratchpad của phiên).
- `data/runtime.env`: xoá rồi sinh lại (`[ghi] … (6 thành phần)`). Không còn khoá timeout.
- `scripts/gpu/studio.env` **không được sửa**. Chênh lệch để bạn quyết định (xem "Việc còn dở").

## Lệnh đã chạy và kết quả
```
.venv/bin/python -m pytest tests/test_gpu tests/test_packaging tests/test_kaggle -q
  171 passed
for f in scripts/gpu/install.sh scripts/gpu/doctor.sh scripts/gpu/install.d/*.sh scripts/gpu/docker_entrypoint.sh \
         scripts/gpu/setup_objectgs_runtime.sh scripts/gpu/export_colmap_binary.sh; do bash -n "$f"; done
  (không lỗi)
.venv/bin/ruff check <file py đã sửa>  →  All checks passed!
.venv/bin/ruff format --check <file py đã sửa>  →  20 files already formatted
make -n -f Makefile.studio gpu-setup doctor  →  đúng lệnh install.sh / doctor.sh
python -m scripts.studio.deploy_env render --examples  →  không đổi file nào (khớp test)
graphify update .  →  27362 nodes, 85350 edges
make -f Makefile.studio gpu-setup  (laptop, bản cuối)  →  EXIT=0
  [bỏ qua] colmap, brush, splat, lidar_odometry, scene, objectgs (đã đúng công thức, không cài lại)
  Runtime ObjectGS  2.1.2+cu118 Quadro T2000
  doctor: GPU, ffmpeg, COLMAP (4.x, pose_prior_mapper), Vulkan, Brush 0.3.0, splat-transform 3.6.6,
          splat-transform GPU, Runtime tách theo vật, Runtime ObjectGS: OK
```

### Bằng chứng khác (từ các bước trước trong task)
- COLMAP 4.x: `colmap help` báo `4.3.0.dev0`, có `pose_prior_mapper --prior_position_std_x`, chạy trong container
  Ubuntu 24.04 sạch sau khi cài đúng `apt-packages.txt` (kiểm bằng container tạm, đã xoá).
- Gói COLMAP xuất từ image ghim: `colmap-bundle.tar.zst`, sha256 `9dcb18e2…954438` (ghim `COLMAP_BINARY_SHA`), 52,7 MB.
  Kiểm bằng test `tests/test_gpu/test_colmap_binary.py` (đường `--from-file`, sai sha256 bị từ chối, idempotent) và
  bằng `test_install_scripts.py` (install.sh từ chối gói sai sha256 trước khi tạo thư mục). **Chưa upload R2** (T-041).

## Kiểm chứng review T-037: cài online không `--wheels` (PASS)
- Môi trường thử: venv mới (`-m venv`) từ đúng Python 3.8.19 của runtime ObjectGS trên laptop, pip cache riêng trong thư
  mục tạm (đã xoá sau khi xong). Không dùng `--wheels`, không dùng laptop cache, không `data/objectgs_runtime`.
- Bước 1 (torch): `pip install --no-deps --require-hashes -r torch.lock.txt --index-url <cu118> --find-links <PyG>` →
  `Successfully installed torch-2.1.2+cu118 torchaudio-2.1.2+cu118 torchvision-0.16.2+cu118 torch-scatter-2.1.2+pt21cu118`.
- Bước 2 (khoá chính, PyPI): `pip install --require-hashes -r requirements.lock.txt` → thoát 0 (127 gói, có sdist
  `setproctitle` được build; pip không kiểm hash phụ thuộc build).
- `pip check`: "No broken requirements found". Import torch/torchvision/torchaudio/torch_scatter/wheel OK; torch
  `2.1.2+cu118`, CUDA build 11.8.
- `pip freeze` của venv mới: 130 dòng, khớp 100% với laptop (`comm` không có dòng nào chỉ ở một bên).
- Lần thử trước đó đã thất bại hai lần, ghi lại để minh bạch:
  1. Đứt mạng khi tải `scipy` (`ReadTimeoutError` từ files.pythonhosted.org). Không có lỗi hash nào trong log.
  2. Lần thử lại lộ lỗi thật của khoá: tensorboard yêu cầu `wheel>=0.26` mà `wheel` không được ghim, nên
     `--require-hashes` từ chối. Trên laptop `wheel` đến từ conda (`wheel=0.45.1`) nên không có trong pip freeze.
     Sửa bằng commit `57ef3db4` (ghim `wheel==0.45.1` có hash). Mọi hash của laptop vẫn nằm trong khoá.
- Khoá sinh bởi `scripts/gpu/objectgs_lock.py`: 127 gói, 255 hash (mỗi gói 1–4 file tương thích cp38 Linux x86_64);
  `torch.lock.txt`: 4 gói. Test `tests/test_gpu` kiểm: mỗi gói có hash, không trùng, hash file laptop nằm trong khoá,
  và bộ lọc tương thích đúng (cp38/manylinux/musllinux/macOS/Windows).

## Việc còn dở / cần bạn quyết định
1. **Laptop `studio.env` thiếu `PRODUCT_OBJECTGS_*`**: stack đang chạy chưa thấy ObjectGS. Dán 7 dòng từ
   `data/runtime.env` (chỉ đường dẫn, không secret) vào `scripts/gpu/studio.env` rồi khởi động lại stack nếu muốn dùng.
   Chưa làm vì sửa env của stack đang chạy là việc bạn quyết định.
2. **`studio.env` của laptop đặt timeout 3600 cho COLMAP và Brush** (mẫu khuyến nghị 7200/14400). Giữ nguyên, đây là
   lựa chọn của bạn.
3. **Rác pip trong `/tmp`**: `/tmp/pip-unpack-rcdcb1bh/` (torch wheel 1,9 GB) là từ lần cài sạch đầu bị ngắt của
   chính task này. Chưa xoá vì pip dùng chung `/tmp` với các lần cài khác; có thể xoá bằng đường dẫn đó khi cần chỗ.
4. **Image chưa build** (T-039): lần build thật sẽ kiểm `install.sh` trong container, OBJECTGS trong container (cần
   GPU lúc chạy, không lúc build) và `preflight` trong container.
5. **Gói COLMAP chưa lên R2** (T-041): trên pod hiện tại dùng `--colmap-from-file`.
6. Chưa chạy `make objectgs-runtime` vào `data/objectgs_runtime` (đúng yêu cầu); `gpu-setup` chỉ xác minh và biên dịch
   gsplat trong cache đó.
