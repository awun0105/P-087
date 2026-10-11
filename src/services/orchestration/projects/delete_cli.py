"""Thùng rác scene bằng dòng lệnh (cùng thao tác với trang Thùng rác của Studio).

    python -m src.services.orchestration.projects.delete_cli plan --project project-… --import import-…
    python -m src.services.orchestration.projects.delete_cli delete --project project-… --upload upload-…
    python -m src.services.orchestration.projects.delete_cli list
    python -m src.services.orchestration.projects.delete_cli restore --entry <entry_id>
    python -m src.services.orchestration.projects.delete_cli purge --entry <entry_id>
    python -m src.services.orchestration.projects.delete_cli purge-expired
    python -m src.services.orchestration.projects.delete_cli import-entry --dir <thư mục lần gỡ kiểu cũ>

`plan` chỉ in những gì sẽ bị gỡ. `delete` chuyển scene vào thùng rác, khôi phục được bằng `restore`; chỉ `purge` mới
xoá hẳn (kể cả object trên kho file S3/R2). Đọc cấu hình như API/worker (DATABASE_URL, ARTIFACT_ROOT,
PRODUCT_WORKER_ROOT, PRODUCT_RERUN_RECORDING_DIR, PRODUCT_TRASH_ROOT).
"""

import argparse
import sys
from pathlib import Path

from src.config import Settings, get_settings
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects.deletion import (
    DeletionPlan,
    DeletionRefusedError,
    DeletionRequest,
    apply_deletion,
    context_from_settings,
    import_legacy_entry,
    list_trash,
    plan_deletion,
    purge_deletion,
    purge_expired,
    restore_deletion,
)

_KIND_LABEL = {"scene": "scene", "import": "scene nhập", "upload": "upload"}


def _megabytes(size_bytes: int) -> str:
    return f"{size_bytes / 1e6:,.1f} MB"


def _print_plan(plan: DeletionPlan, verb: str) -> None:
    counts = {kind: sum(line.kind == kind for line in plan.summary) for kind in _KIND_LABEL}
    header = ", ".join(f"{count} {_KIND_LABEL[kind]}" for kind, count in counts.items() if count) or "không có gì"
    print(f"{verb}: {header} — {len(plan.items)} thư mục/file, {_megabytes(plan.size_bytes)}")
    for line in plan.summary:
        print(f"  {_KIND_LABEL[line.kind]:10s} {line.identifier}  {line.name} — {line.detail}")
    for unlink in plan.upload_unlinks:
        kept = len(unlink.original_project_ids) - len(unlink.removed_project_ids)
        print(f"  giữ upload {unlink.upload_id}: còn {kept} scene dùng, chỉ bỏ liên kết với scene bị gỡ")


def _print_reasons(title: str, reasons: list[str]) -> None:
    print(title, file=sys.stderr)
    for reason in reasons:
        print(f"  - {reason}", file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("plan", "Chỉ in những gì sẽ bị gỡ"), ("delete", "Chuyển scene vào thùng rác")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--project", action="append", default=[], help="project_id của scene (lặp lại được)")
        command.add_argument("--import", dest="imports", action="append", default=[], help="import_id (lặp lại được)")
        command.add_argument("--upload", action="append", default=[], help="upload_id không còn ai dùng")
        command.add_argument("--allow-released", action="store_true", help="Cho gỡ cả scene đã có bản phát hành")
    commands.add_parser("list", help="Liệt kê thùng rác")
    commands.add_parser("purge-expired", help="Xoá hẳn các mục quá hạn (PRODUCT_TRASH_RETENTION_DAYS); dùng cho cron")
    for name, text in (("restore", "Khôi phục một mục thùng rác"), ("purge", "Xoá hẳn một mục thùng rác")):
        commands.add_parser(name, help=text).add_argument("--entry", required=True, help="entry_id trong thùng rác")
    legacy = commands.add_parser("import-entry", help="Đưa một lần gỡ kiểu cũ (có deletion_record.json) vào thùng rác")
    legacy.add_argument("--dir", type=Path, required=True)
    return parser


def _run(args: argparse.Namespace, settings: Settings) -> int:
    context = context_from_settings(settings)
    if args.command == "list":
        for record in list_trash(context.database):
            print(f"{record.entry_id}  {record.created_at:%Y-%m-%d %H:%M}")
            _print_plan(record.plan, "  gồm")
        return 0
    if args.command == "purge-expired":
        purged = purge_expired(context)
        print(f"Đã xoá hẳn {len(purged)} mục quá {context.retention_days} ngày")
        return 0
    if args.command == "purge":
        result = purge_deletion(context, args.entry)
        on_store = f", {result.remote_objects} object trên kho file" if context.resolver.remote is not None else ""
        print(f"Đã xoá hẳn {args.entry}: {_megabytes(result.local_bytes)} trên máy{on_store}")
        return 0
    if args.command == "restore":
        record = restore_deletion(context, args.entry)
        print(f"Đã khôi phục {len(record.plan.summary)} mục từ {args.entry}")
        return 0
    if args.command == "import-entry":
        record = import_legacy_entry(context, args.dir)
        print(f"Đã đưa {record.entry_id} vào thùng rác ({len(record.plan.summary)} mục)")
        return 0
    request = DeletionRequest(
        project_ids=args.project, import_ids=args.imports, upload_ids=args.upload, allow_released=args.allow_released
    )
    if args.command == "plan":
        plan = plan_deletion(context, request)
        _print_plan(plan, "Sẽ gỡ")
        if plan.blockers:
            _print_reasons("Chưa gỡ được:", plan.blockers)
        return 1 if plan.blockers else 0
    record = apply_deletion(context, request)
    _print_plan(record.plan, "Đã gỡ")
    print(f"Mục thùng rác: {record.entry_id}")
    print(f"Khôi phục: python -m src.services.orchestration.projects.delete_cli restore --entry {record.entry_id}")
    print(f"Xoá hẳn:   python -m src.services.orchestration.projects.delete_cli purge --entry {record.entry_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; trả exit code."""
    args = _parser().parse_args(argv)
    try:
        return _run(args, get_settings())
    except DeletionRefusedError as error:
        _print_reasons("Từ chối:", error.reasons)
    except RuntimeStateConflictError as error:
        _print_reasons("Dữ liệu trong DB vừa đổi nên dừng lại:", [str(error)])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
