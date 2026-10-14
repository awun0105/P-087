"""Chạy lại tách scene theo vật cho một job đã có SceneIR (pipeline v2, ADR 0007 chặng 4–7).

Dùng khi job được dựng bằng đường hộp (job cũ, hoặc bước tách theo vật lỗi nên pipeline lùi về hộp):
không dựng lại từ video, chỉ đọc `ReconstructionBundle` hệ mét đã có và ghi **revision kế tiếp**.
Chạy bằng `.venv` của app với cùng file env của stack (cần runtime `data/scene_runtime`, GPU):

    set -a; . scripts/gpu/studio.env; set +a
    .venv/bin/python scripts/scene/reobjectify.py <job_id> [--workspace <thư_mục>]
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import get_settings  # noqa: E402
from src.services.orchestration.projects import get_project_registry  # noqa: E402
from src.services.orchestration.scene.objectify import ObjectifyError, reobjectify  # noqa: E402


def main() -> int:
    """CLI: job_id → revision SceneIR mới; lỗi provider in ra kèm nơi có log."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_id")
    parser.add_argument("--workspace", type=Path, help="thư mục làm việc (giữ log/kết quả trung gian)")
    parser.add_argument(
        "--geometry-method",
        choices=["legacy", "objectgs"],
        help="explicit audited producer choice for this scene operation",
    )
    parser.add_argument("--expected-revision", help="refuse to replace a scene edited since this revision")
    args = parser.parse_args()
    workspace = args.workspace or Path(tempfile.mkdtemp(prefix=f"reobjectify-{args.job_id}-"))
    try:
        revision = reobjectify(
            get_project_registry(),
            args.job_id,
            get_settings(),
            workspace,
            expected_revision=args.expected_revision,
            geometry_method=args.geometry_method,
        )
    except ObjectifyError as error:
        print(f"[!] Tách theo vật lỗi: {error} (log trong {workspace})", file=sys.stderr)
        return 1
    print(f"{args.job_id}: {revision} (workspace {workspace})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
