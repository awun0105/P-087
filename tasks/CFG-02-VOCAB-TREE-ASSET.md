TASK: CFG-02-VOCAB-TREE-ASSET

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
