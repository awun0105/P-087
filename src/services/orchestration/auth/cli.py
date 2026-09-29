"""Tạo tài khoản lúc deploy (vd Reviewer đầu tiên), không qua mã mời.

    python -m src.services.orchestration.auth.cli create-user --email lead@example.com \\
        --name "Trưởng nhóm" --role reviewer

Mật khẩu nhập ẩn; chạy không tương tác thì đọc biến môi trường `R2S_BOOTSTRAP_PASSWORD`.
Không in mật khẩu ra log.
"""

import argparse
import getpass
import os
import sys

from src.config import get_settings
from src.services.orchestration.auth.service import AuthService
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Tạo một tài khoản")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=["editor", "reviewer"], default="reviewer")
    args = parser.parse_args(argv)

    password = os.environ.get("R2S_BOOTSTRAP_PASSWORD") or getpass.getpass("Mật khẩu (≥ 10 ký tự): ")
    service = AuthService(RuntimeDatabase(get_settings().database_url))
    try:
        user = service.create_user(args.email, args.name, password, args.role)
    except (RuntimeStateConflictError, ValueError) as error:
        print(f"Không tạo được tài khoản: {error}", file=sys.stderr)
        return 1
    print(f"Đã tạo {user.role} {user.email} ({user.user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
