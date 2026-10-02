"""Đóng gói / khôi phục dữ liệu Studio để teammate mở lên thấy đúng các scene như máy gốc.

    python scripts/studio/data_package.py pack   [--out r2s-studio-data.tar.gz]
    python scripts/studio/data_package.py unpack r2s-studio-data.tar.gz [--force]

Chỉ dùng thư viện chuẩn của Python nên chạy được trên mọi hệ điều hành và trong container.

Trong gói: `runtime.db` (bản chụp nhất quán), `artifacts/`, ảnh thu nhỏ, thư viện mẫu, bản ghi Rerun nếu có.
KHÔNG có trong gói: mật khẩu và phiên đăng nhập (gỡ khỏi bản chụp), thư mục kiểm thử (`qa/`), thùng rác, bản sao lưu,
scratch của worker, runtime (Brush, COLMAP, scene_runtime). Dữ liệu chỉ chứa đường dẫn logic (`artifact://…`) nên
dùng được ở bất kỳ thư mục nào.
"""

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = Path("data/studio_local")
#: Thư mục dữ liệu đi kèm database (tương đối so với root repo); cái nào không có thì bỏ qua.
PARTS = (STATE / "artifacts", STATE / "thumbnail_cache", Path("data/demo/library"), Path("data/rerun_recordings"))
#: Bảng chỉ có nghĩa trên máy gốc (phiên đăng nhập, mã mời, trạng thái tạm của worker).
LOCAL_TABLES = (
    "r2s_sessions",
    "r2s_invites",
    "r2s_resource_reservations",
    "r2s_resource_waits",
    "r2s_workers",
    "r2s_upload_sessions",
)
ALLOWED_PREFIXES = ("data/studio_local/", "data/demo/", "data/rerun_recordings/")
DEFAULT_NAME = "r2s-studio-data.tar.gz"


def snapshot_database(source: Path, target: Path) -> int:
    """Bản chụp nhất quán của database, đã gỡ thông tin đăng nhập; trả số scene."""
    origin, copy = sqlite3.connect(source), sqlite3.connect(target)
    try:
        with copy:
            origin.backup(copy)
        tables = {row[0] for row in copy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with copy:
            for table in LOCAL_TABLES:
                if table in tables:
                    copy.execute(f"DELETE FROM {table}")  # noqa: S608 - tên bảng là hằng số ở trên
            # Giữ tài khoản để tên người tạo/duyệt vẫn hiện, nhưng vô hiệu mật khẩu: gói này được gửi cho người khác.
            if "r2s_users" in tables:
                for user_id, payload in copy.execute("SELECT user_id, payload FROM r2s_users").fetchall():
                    record = json.loads(payload)
                    record.update(password_hash="disabled-in-data-package", active=False)
                    copy.execute("UPDATE r2s_users SET payload=? WHERE user_id=?", (json.dumps(record), user_id))
        copy.execute("VACUUM")
        return int(copy.execute("SELECT COUNT(*) FROM r2s_projects").fetchone()[0]) if "r2s_projects" in tables else 0
    finally:
        origin.close()
        copy.close()


def pack(root: Path, out: Path) -> Path:
    """Ghi gói `.tar.gz` (nén nhẹ: artifact phần lớn đã nén sẵn) qua file tạm rồi đổi tên."""
    database = root / STATE / "runtime.db"
    if not database.is_file():
        raise SystemExit(f"Không có {database} để đóng gói.")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    with tempfile.TemporaryDirectory() as staging:
        copy = Path(staging) / "runtime.db"
        scenes = snapshot_database(database, copy)
        note = Path(staging) / "DATA_PACKAGE.json"
        present = [part for part in PARTS if (root / part).exists()]
        note.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "git_commit": commit.stdout.strip() or "unknown",
                    "scenes": scenes,
                    "contents": ["data/studio_local/runtime.db", *(part.as_posix() for part in present)],
                },
                indent=2,
            )
        )
        partial = out.with_name(out.name + ".partial")
        with tarfile.open(partial, "w:gz", compresslevel=1) as archive:
            archive.add(copy, arcname=(STATE / "runtime.db").as_posix())
            archive.add(note, arcname=(STATE / "DATA_PACKAGE.json").as_posix())
            for part in present:
                archive.add(root / part, arcname=part.as_posix())
        partial.replace(out)
    print(f"[data] {scenes} scene → {out} ({out.stat().st_size / 1024**2:.0f} MB)")
    return out


def unpack(root: Path, package: Path, force: bool) -> None:
    """Khôi phục gói vào `data/` của checkout này; dữ liệu đang có được chuyển sang thư mục sao lưu, không xoá."""
    if not package.is_file():
        raise SystemExit(f"Không thấy file gói: {package}")
    state = root / STATE
    if (state / "runtime.db").exists() and not force:
        raise SystemExit(
            "Máy này đã có dữ liệu (data/studio_local/runtime.db). Thêm --force để thay; dữ liệu cũ được chuyển sang "
            "thư mục sao lưu, không bị xoá."
        )
    with tarfile.open(package, "r:*") as archive:
        names = archive.getnames()
        outside = [name for name in names if not name.startswith(ALLOWED_PREFIXES) or ".." in Path(name).parts]
        if outside:
            raise SystemExit(f"Gói chứa đường dẫn ngoài data/ ({outside[0]}); từ chối mở.")
        existing = [state / item for item in ("runtime.db", "artifacts", "thumbnail_cache") if (state / item).exists()]
        if existing:
            backup = state / "backups" / f"before-unpack-{datetime.now(UTC):%Y%m%d-%H%M%S}"
            backup.mkdir(parents=True)
            for item in existing:
                shutil.move(str(item), backup / item.name)
            print(f"[data] dữ liệu cũ chuyển sang {backup}")
        print(f"[data] khôi phục từ {package}…")
        archive.extractall(root, filter="data")
    note = state / "DATA_PACKAGE.json"
    scenes = json.loads(note.read_text()).get("scenes", "?") if note.is_file() else "?"
    print(f"[data] xong: {scenes} scene.")


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="root của checkout (mặc định: repo chứa script này)")
    commands = parser.add_subparsers(dest="command", required=True)
    packer = commands.add_parser("pack")
    packer.add_argument("--out", type=Path)
    unpacker = commands.add_parser("unpack")
    unpacker.add_argument("package", type=Path)
    unpacker.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "pack":
        pack(args.root, args.out or args.root / DEFAULT_NAME)
    else:
        unpack(args.root, args.package, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
