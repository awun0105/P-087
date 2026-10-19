"""Container boundary for the portable Studio API.

The image never invents a dataset.  On startup it can optionally call the
repository-owned data package verifier/unpacker, then requires the configured
SQLite file to exist before starting Uvicorn.  A fresh authenticated install
also needs explicit bootstrap credentials; no password is generated or
printed by this process.  Railway-style root-mounted volumes can opt into
preparing the canonical managed directories and dropping to ``appuser`` before
the server is started with ``R2S_PREPARE_VOLUME=true``.
"""

from __future__ import annotations

import argparse
import os
import pwd
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
ROLES = frozenset({"editor", "reviewer"})
APP_USER = "appuser"
MANAGED_VOLUME_DIRS = (
    Path("."),
    Path("studio_local"),
    Path("studio_local/artifacts"),
    Path("studio_local/thumbnail_cache"),
    Path("studio_local/workers"),
    Path("studio_local/trash"),
    Path("studio_local/chroma"),
    Path("demo"),
    Path("demo/library"),
    Path("asset_previews"),
    Path("rerun_recordings"),
)
MANAGED_VOLUME_PATHS = {
    "ARTIFACT_ROOT": Path("studio_local/artifacts"),
    "PRODUCT_WORKER_ROOT": Path("studio_local/workers"),
    "PRODUCT_TRASH_ROOT": Path("studio_local/trash"),
    "CHROMA_PERSIST_DIR": Path("studio_local/chroma"),
    "PRODUCT_DEMO_DIR": Path("demo/library"),
    "PRODUCT_ASSET_PREVIEW_DIR": Path("asset_previews"),
    "PRODUCT_RERUN_RECORDING_DIR": Path("rerun_recordings"),
}


class StartupError(RuntimeError):
    """Configuration/data error that must stop the container before serving."""


def _truthy(value: str | None) -> bool:
    """Parse the small boolean surface used by the container environment."""
    return (value or "").strip().lower() in TRUE_VALUES


def _reject_symlink_components(path: Path, label: str) -> None:
    """Reject a configured path or any existing ancestor that is a symlink."""
    current = path
    while True:
        try:
            if current.is_symlink():
                raise StartupError(f"{label} chứa symlink: {current}")
        except OSError as error:
            raise StartupError(f"Không kiểm tra được {label}: {current}") from error
        if current.parent == current:
            return
        current = current.parent


def _sqlite_path(database_url: str, root: Path) -> Path | None:
    """Resolve a file SQLite URL without accepting URI/query options."""
    if not database_url.startswith("sqlite:///"):
        return None
    value = database_url.removeprefix("sqlite:///")
    if not value or value == ":memory:" or "?" in value:
        raise StartupError("DATABASE_URL phải là SQLite file bền vững, không phải memory/URI option")
    path = Path(value).expanduser()
    if ".." in path.parts:
        raise StartupError("DATABASE_URL không được chứa path traversal")
    path = path if path.is_absolute() else (root / path)
    _reject_symlink_components(path, "DATABASE_URL")
    return path


def _require_database(root: Path) -> Path | None:
    """Fail closed when the portable stack was started without restored data."""
    database_url = os.environ.get("DATABASE_URL", "")
    path = _sqlite_path(database_url, root)
    if _truthy(os.environ.get("R2S_REQUIRE_DATA")) and path is not None and not path.is_file():
        raise StartupError(
            f"Không tìm thấy runtime database tại {path}; giải nén gói dữ liệu vào ./data trước khi khởi động"
        )
    return path


def _user_record() -> pwd.struct_passwd:
    """Resolve the image's unprivileged API account before changing IDs."""
    try:
        user = pwd.getpwnam(APP_USER)
    except KeyError as error:
        raise StartupError(f"Không tìm thấy user runtime {APP_USER}") from error
    if user.pw_uid == 0:
        raise StartupError(f"User runtime {APP_USER} không được là root")
    return user


def _validate_managed_volume_paths(data_root: Path) -> None:
    """Reject volume env paths that leave the canonical managed directories."""
    for variable, relative in MANAGED_VOLUME_PATHS.items():
        configured = os.environ.get(variable, "").strip()
        if not configured:
            continue
        candidate = Path(configured).expanduser()
        expected = data_root / relative
        if not candidate.is_absolute() or ".." in candidate.parts or candidate != expected:
            raise StartupError(f"{variable} phải trỏ đúng managed path dưới {data_root}")


def _ensure_owned_directory(path: Path, uid: int, gid: int) -> None:
    """Create one managed directory and chown only that directory, never files."""
    try:
        parent_mode = path.parent.lstat().st_mode
    except OSError as error:
        raise StartupError(f"Không kiểm tra được parent volume path: {path.parent}") from error
    if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
        raise StartupError(f"Volume path chứa symlink hoặc parent không phải directory: {path.parent}")

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o775)
            mode = path.lstat().st_mode
        except OSError as error:
            raise StartupError(f"Không tạo được managed volume directory: {path}") from error
    except OSError as error:
        raise StartupError(f"Không kiểm tra được managed volume directory: {path}") from error

    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise StartupError(f"Managed volume path phải là directory thường, không phải symlink: {path}")
    try:
        os.chown(path, uid, gid, follow_symlinks=False)
    except OSError as error:
        raise StartupError(f"Không đổi owner managed volume directory: {path}") from error


def _validate_application_root(root: Path) -> None:
    """Require the application root to be a real directory before volume work."""
    try:
        root_mode = root.lstat().st_mode
    except OSError as error:
        raise StartupError(f"Không kiểm tra được application root: {root}") from error
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise StartupError(f"Application root phải là directory thường: {root}")


def _prepare_data_volume(root: Path) -> None:
    """Prepare only /data and /data/studio_local for the restore service."""
    if os.geteuid() != 0:
        raise StartupError("prepare-data yêu cầu container khởi động với UID 0")
    user = _user_record()
    _validate_application_root(root)
    data_root = root / "data"
    _ensure_owned_directory(data_root, user.pw_uid, user.pw_gid)
    _ensure_owned_directory(data_root / "studio_local", user.pw_uid, user.pw_gid)


def _prepare_volume_and_drop(root: Path) -> None:
    """Prepare the canonical volume as root, then permanently drop to appuser."""
    if os.geteuid() != 0:
        raise StartupError("R2S_PREPARE_VOLUME=true yêu cầu container khởi động với UID 0")
    user = _user_record()
    data_root = root / "data"
    _validate_managed_volume_paths(data_root)
    _validate_application_root(root)

    for relative in sorted(MANAGED_VOLUME_DIRS, key=lambda item: len(item.parts)):
        _ensure_owned_directory(data_root / relative, user.pw_uid, user.pw_gid)

    try:
        os.setgroups([])
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)
    except OSError as error:
        raise StartupError(f"Không drop privilege sang user {APP_USER}") from error


def _read_secret() -> str | None:
    """Read the bootstrap password from a secret file or environment, silently."""
    secret_file = os.environ.get("R2S_BOOTSTRAP_PASSWORD_FILE", "").strip()
    if secret_file:
        path = Path(secret_file)
        try:
            password = path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as error:
            raise StartupError(f"Không đọc được R2S_BOOTSTRAP_PASSWORD_FILE: {path}") from error
        if not password:
            raise StartupError("R2S_BOOTSTRAP_PASSWORD_FILE đang rỗng")
        return password
    password = os.environ.get("R2S_BOOTSTRAP_PASSWORD")
    return password if password else None


def _bootstrap_reviewer(database_url: str) -> None:
    """Create the configured first user, idempotently, without exposing secrets."""
    if not _truthy(os.environ.get("AUTH_REQUIRED")):
        return

    email = os.environ.get("R2S_BOOTSTRAP_EMAIL", "").strip().lower()
    display_name = os.environ.get("R2S_BOOTSTRAP_NAME", "").strip()
    password = _read_secret()
    role = os.environ.get("R2S_BOOTSTRAP_ROLE", "reviewer").strip().lower()

    from src.services.orchestration.auth import AuthService
    from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError

    service = AuthService(RuntimeDatabase(database_url))
    users = service.list_users()
    if email and any(user.email == email for user in users):
        existing = next(user for user in users if user.email == email)
        if not existing.active:
            raise StartupError("R2S_BOOTSTRAP_EMAIL đang trỏ tới tài khoản đã bị vô hiệu hóa")
        if role == "reviewer" and existing.role != "reviewer":
            raise StartupError("R2S_BOOTSTRAP_EMAIL hiện không có role reviewer")
        return
    if any(user.active and user.role == "reviewer" for user in users):
        return
    if not email or not display_name or not password:
        raise StartupError(
            "AUTH_REQUIRED=true nhưng chưa có tài khoản; cần R2S_BOOTSTRAP_EMAIL, "
            "R2S_BOOTSTRAP_NAME và R2S_BOOTSTRAP_PASSWORD(_FILE)"
        )
    if role not in ROLES:
        raise StartupError("R2S_BOOTSTRAP_ROLE phải là editor hoặc reviewer")
    try:
        service.create_user(email, display_name, password, role)  # password chỉ đi vào scrypt, không log
    except ValueError as error:
        raise StartupError(f"Bootstrap account không hợp lệ: {error}") from error
    except RuntimeStateConflictError:
        # Một API replica có thể bootstrap đồng thời.  Confirm the winner by
        # rereading the DB; never hide a different failure.
        if not any(user.email == email for user in service.list_users()):
            raise


def _restore(root: Path, archive: Path) -> None:
    """Delegate restore to the package verifier; never implement ZIP copying here."""
    archive = archive if archive.is_absolute() else (root / archive)
    if not archive.is_file():
        raise StartupError(f"Không tìm thấy archive dữ liệu: {archive}")
    command = [sys.executable, "-m", "scripts.studio.data_package", "--root", str(root), "unpack", str(archive)]
    try:
        subprocess.run(command, cwd=root, check=True)
    except subprocess.CalledProcessError as error:
        raise StartupError(f"Khôi phục gói dữ liệu thất bại (exit {error.returncode})") from error


def _restore_if_needed(root: Path, archive: Path) -> None:
    """Restore the default package only when the mounted runtime DB is absent."""
    database = root / "data" / "studio_local" / "runtime.db"
    _reject_symlink_components(database, "runtime database")
    if database.is_file():
        return
    _restore(root, archive)


def _serve(root: Path, command: Sequence[str]) -> int:
    """Restore/check/bootstrap then replace this process with the server."""
    archive_value = os.environ.get("R2S_DATA_ARCHIVE", "").strip()
    prepare_volume = _truthy(os.environ.get("R2S_PREPARE_VOLUME"))
    if archive_value and prepare_volume:
        raise StartupError("R2S_DATA_ARCHIVE không thể dùng cùng R2S_PREPARE_VOLUME=true")
    if archive_value:
        if not _truthy(os.environ.get("R2S_RESTORE_DATA")):
            raise StartupError("R2S_DATA_ARCHIVE đã đặt; bật R2S_RESTORE_DATA=true để restore explicit")
        _restore(root, Path(archive_value).expanduser())
    if prepare_volume:
        _prepare_volume_and_drop(root)
    _require_database(root)
    database_url = os.environ.get("DATABASE_URL", "")
    if _truthy(os.environ.get("AUTH_REQUIRED")) and database_url.startswith(
        ("sqlite:///", "postgresql://", "postgres://")
    ):
        _bootstrap_reviewer(database_url)
    if _truthy(os.environ.get("GPU_CONTROLLER_RUN")) or _truthy(os.environ.get("GPU_CPU_LANE_ENABLED")):
        from src.services.orchestration.gpu.supervisor import supervise

        return supervise(command)
    os.execvp(command[0], list(command))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("R2S_APP_ROOT", "/app"), type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    serve = commands.add_parser("serve", help="Check data/auth and exec the API server")
    serve.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Server command (default: uvicorn src.main:app --host 0.0.0.0 --port $PORT)",
    )
    restore = commands.add_parser("restore", help="Run the data package verifier/unpacker")
    restore.add_argument("archive", type=Path)
    restore_if_needed = commands.add_parser("restore-if-needed", help="Restore only when the runtime DB is absent")
    restore_if_needed.add_argument("archive", type=Path)
    commands.add_parser("prepare-data", help="Prepare only the data and studio_local volume directories")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one container action and return a process exit code."""
    args = _parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.action == "restore":
            _restore(root, args.archive.expanduser())
            return 0
        if args.action == "restore-if-needed":
            _restore_if_needed(root, args.archive.expanduser())
            return 0
        if args.action == "prepare-data":
            _prepare_data_volume(root)
            return 0
        command = list(args.command)
        if command and command[0] == "--":
            command.pop(0)
        if not command:
            port = os.environ.get("PORT", os.environ.get("APP_PORT", "8000"))
            command = [
                "uvicorn",
                "src.main:app",
                "--host",
                os.environ.get("APP_HOST", "0.0.0.0"),
                "--port",
                port,
                "--no-access-log",
            ]
        return _serve(root, command)
    except StartupError as error:
        print(f"Studio startup blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
