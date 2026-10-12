TASK: CFG-02-VOCAB-TREE-ASSET
STATUS: COMPLETED (2026-10-13)

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Khi người dùng quay video đi quanh phòng theo vòng tròn 360° (điểm kết thúc trùng điểm xuất phát), chế độ `sequential_matcher` thông thường chỉ so khớp các ảnh cạnh nhau theo thời gian ($t$ với $t+1$). Khi camera quay đủ một vòng và nhìn lại điểm xuất phát ở frame cuối cùng, khoảng cách thời gian giữa frame đầu và frame cuối quá xa nên COLMAP không biết chúng là cùng một nơi, dẫn đến mô hình bị vặn xoắn hoặc đứt gãy thành hai mảng rời rạc. Để khâu vòng lặp (loop closure), COLMAP bắt buộc phải dùng một từ điển thị giác nhị phân (Vocabulary Tree, ~112 MB). Nếu không có script tải tự động và cơ chế kiểm tra sẵn sàng, pipeline sẽ bị crash khi người dùng kích hoạt loop detection.
- **Yêu cầu cốt lõi (What):** Viết script Python tự động tải file từ điển `vocab_tree_clustering_flickr100k_words256K.bin` từ máy chủ chính thức của tác giả COLMAP về thư mục chuẩn `data/checkpoints/colmap/` kèm kiểm tra SHA-256, thêm cấu hình đường dẫn vào `src/config.py`, và viết một module adapter `vocab_tree.py` để các service khác dễ dàng kiểm tra xem từ điển đã sẵn sàng hay chưa.

GOAL:
Tải, lưu trữ và thiết lập cơ chế quản lý file từ điển chuẩn COLMAP Vocabulary Tree (`vocab_tree_clustering_flickr100k_words256K.bin`, ~112 MB) trong hệ thống, kèm script kiểm tra toàn vẹn và helper tích hợp vào runtime.

INPUT CONTRACT:
- Nguồn tải chính thức: `https://demuc.de/colmap/vocab_tree_clustering_flickr100k_words256K.bin`
- SHA-256 chính thức của file từ điển.
- Cấu hình hệ thống trong `src/config.py`.

OUTPUT CONTRACT:
- Thư mục lưu trữ tài nguyên chuẩn: `data/checkpoints/colmap/vocab_tree_clustering_flickr100k_words256K.bin`
- Cài đặt hệ thống: `product_colmap_vocab_tree: Path | None = None` trong `src/config.py` (Settings).
- Script tải tự động: `scripts/assets/download_vocab_tree.py` (hỗ trợ resumable download, timeout, sha256 verification, cờ `--check-only`).
- Module helper: `src/services/reconstruction/adapters/vocab_tree.py` cung cấp hàm `get_vocab_tree_path() -> Path | None` và `is_vocab_tree_available() -> bool`.

OWNED FILES:
- `scripts/assets/download_vocab_tree.py`
- `src/services/reconstruction/adapters/vocab_tree.py`
- `src/config.py`
- `tests/test_reconstruction/test_vocab_tree_asset.py`

FILES YOU MAY MODIFY:
- `scripts/assets/`
- `src/services/reconstruction/adapters/`
- `src/config.py`
- `tests/test_reconstruction/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/`
- `frontend/`

PRIMARY TOOL:
- Python 3.12, `urllib.request` / `requests`, `hashlib`.

IMPLEMENT:
1. Cập nhật `src/config.py`:
   - Thêm trường `product_colmap_vocab_tree: Path | None = None` vào `Settings`.
2. Viết `scripts/assets/download_vocab_tree.py`:
   - Tải file từ điển về `data/checkpoints/colmap/vocab_tree_clustering_flickr100k_words256K.bin`.
   - Nếu file đã tồn tại và đúng SHA-256 thì bỏ qua không tải lại.
   - Thêm cờ `--check-only` để chỉ kiểm tra file có sẵn và hợp lệ không mà không tải.
3. Viết `src/services/reconstruction/adapters/vocab_tree.py`:
   - Hàm `get_vocab_tree_path(settings: Settings | None = None) -> Path | None` trả về `Path` nếu file tồn tại và dung lượng hợp lệ (>100 MB), ngược lại trả về `None`.
   - Hàm `is_vocab_tree_available() -> bool` kiểm tra tính sẵn sàng.
4. Viết unit test trong `tests/test_reconstruction/test_vocab_tree_asset.py`:
   - Kiểm tra logic fallback khi file chưa tải hoặc file đã có sẵn (dùng mock/tempfile).

TEST:
- `.venv/bin/pytest tests/test_reconstruction/test_vocab_tree_asset.py -v`
- `python scripts/assets/download_vocab_tree.py --check-only`
- `ruff check src/services/reconstruction/adapters/vocab_tree.py src/config.py`
- `ruff format --check src/services/reconstruction/adapters/vocab_tree.py src/config.py`

DONE WHEN:
- Script tải tự động hoạt động ổn định, có xác thực checksum.
- Unit test pass 100%.

EVIDENCE:
- File `scripts/assets/download_vocab_tree.py`
- File `src/services/reconstruction/adapters/vocab_tree.py`
- Test log `.venv/bin/pytest tests/test_reconstruction/test_vocab_tree_asset.py`

## Implementation and executable evidence — 2026-10-13

- Added `Settings.product_colmap_vocab_tree`; an explicit path takes precedence over the canonical repo asset. Missing, partial, non-regular or corrupt files are unavailable. Availability hashes are cached by file metadata and rechecked after mutation.
- Added standalone stdlib downloader with socket timeout, `.part` resume via HTTP Range, restart when Range is ignored, process lock, SHA-256 + exact size verification and atomic publication. `--check-only` performs no download or writes; a verified existing asset skips the network.
- Real asset installed locally at the specified canonical path: **117,893,693 bytes**. Large binary and lock/partial files stay under ignored `data/`, not in Git.
- **Source correction from current evidence:** task's `https://demuc.de/colmap/vocab_tree_clustering_flickr100k_words256K.bin` returns HTTP 404. The author's [current download page](https://demuc.de/colmap/) links [COLMAP release 3.11.1](https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_flickr100K_words256K.bin). Downloaded that official 256K asset and kept the requested local filename.
- SHA-256 pin: `d2055600452a531b5b0a62aa5943e1a07195273dc4eeebcf23d3a924d881d53a`. This is the project pin measured from official release bytes, **not a publisher-signed/published digest**; the supplied task contained no checksum and GitHub metadata lookup was rate limited. Future downloads must match this pin.
- Real-source downloader exercised with a 1 MiB partial file; completed successfully and published the verified asset. `python3 scripts/assets/download_vocab_tree.py --check-only` returned **0**. Runtime helper reported available with default location.
- `.venv/bin/pytest tests/test_reconstruction/test_vocab_tree_asset.py tests/test_config.py -v`: **19 passed** (12 asset cases + 7 settings cases). Tests include missing/corrupt/mutated files, env override, idempotence, check-only without network, resume, ignored Range, truncated transfer, wrong Content-Range, wrong checksum, complete partial and invalid timeout.
- Ruff check/format passed for all 4 changed Python files. Full commands/output: [CFG-02-VERIFICATION.log](reports/CFG-02-VERIFICATION.log).

Pre-flight (GUIDE.md Rule 13):
- codegraph: inspected Settings, COLMAP artifact staging/config/runtime and existing weight-management helper; Settings callers checked (API, workers, scripts, settings tests).
- impact: new opt-in setting and new asset helper/CLI; existing reconstruction commands/job artifact contracts unchanged. Settings shared callers retain old defaults.
- understand: UNVERIFIED — understand-anything tool unavailable; current source/callers and official upstream download page used instead.
- minimal-code: reuse Settings and stdlib hashing/urllib/locking/atomic replace; no dependency or request-time downloader added.
- checks: 19 focused tests passed; Ruff lint/format clean; graphify AST update run.
- DevTools: n/a — no rendered UI change.

Scope limit: asset-management proof only; no live COLMAP loop-matching or 360-scene quality claim. Matching modes belong to CFG-03.
