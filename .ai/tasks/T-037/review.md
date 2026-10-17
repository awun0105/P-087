# Review T-037

Verdict: ACCEPTED

Audit: `ecc6c7fb` (micromamba từ release chính thức, kiểm sha của tarball và của binary bên trong), `40749a7e` (126 gói có
`--hash`, cài `--require-hashes`), `bb2402bd` (từ chối thư mục đích có nội dung mà thiếu `.r2s-installed`, trước mọi bước tải,
không xoá gì). Chạy `tests/test_gpu/test_setup_objectgs_runtime.py`: 14 PASS. Bằng chứng dựng thật: hai lần dựng (lần sau có
`--require-hashes`) đều EXIT 0, `pip freeze` 130 dòng giống hệt `data/objectgs_runtime`, `pip check` sạch; chạy lại thoát sớm;
thư mục tạm đã xoá. Commit ghim chỉ ở `src/services/scene/objectgs.py`.

Acceptance 3: smoke chạy hết kiểm runtime, train, export trên runtime dựng lại = PASS về thực thi. Cổng chất lượng mesh trên cube
tổng hợp không đạt, giống runtime gốc (`data/pr05_objectgs_smoke_20261015/quality.json`, 8000 vòng, `watertight: false`); đã đưa
vào backlog, ngoài phạm vi T-037.

## Chuyển sang T-038 (bắt buộc ở đó)
Hash trong `configs/runtime/objectgs/requirements.lock.txt` là hash của **đúng file trên laptop** (có `setproctitle-1.3.8.tar.gz`
là sdist). Cài **online** (không `--wheels`, ví dụ lúc build image) pip có thể chọn wheel khác trên PyPI → hash không khớp →
`--require-hashes` từ chối. T-038 phải làm một trong hai, có kiểm thật:
- (khuyến nghị) bổ sung vào lock hash của **mọi file** pip có thể chọn cho `cp38`/`manylinux x86_64` (pip nhận nhiều `--hash`
  cho một dòng): lấy bằng `pip download --no-deps --python-version 3.8 --platform manylinux2014_x86_64 --only-binary=:all:`
  cộng sdist khi gói không có wheel; hoặc
- đưa bộ wheel offline lên R2 theo mẫu `colmap_binary.py` và để `install.sh` tải về trước khi cài.
Torch/torchvision/torchaudio/torch-scatter đang cài theo phiên bản ghim, chưa có hash: cùng xử lý trong T-038.
`make objectgs-runtime` trỏ `data/objectgs_runtime` nay bị script từ chối (đúng thiết kế); T-038 đổi target sang đích mới khi
cần dựng lại trên laptop.
