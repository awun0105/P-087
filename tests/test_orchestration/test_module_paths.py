"""Hằng đường dẫn tính theo vị trí file phải trỏ tới script có thật.

Các runner chạy trong runtime GPU riêng được gọi bằng đường dẫn file (`<python> <runner>.py`), tính từ `__file__`
của module điều phối. Dời module sang thư mục khác mà quên sửa độ sâu thì chỉ lộ ra lúc chạy job thật trên GPU.
"""

from src.services.orchestration.review import simulation_package
from src.services.orchestration.scene import objectify


def test_runner_paths_resolve_to_real_files() -> None:
    assert objectify.LIFT_RUNNER.is_file()
    assert objectify.CONVEX_RUNNER.is_file()
    assert objectify.INPAINT_RUNNER.is_file()
    assert simulation_package.HYBRID_RUNNER.is_file()
