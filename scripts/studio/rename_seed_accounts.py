"""Rename the two explicitly identified Studio seed accounts without changing credentials.

Example (use verified stable IDs from the target database)::

    python -m scripts.studio.rename_seed_accounts --reviewer-user-id <reviewer-id> --editor-user-id <editor-id>

The command intentionally does not discover users by role. A wrong/missing ID or
role aborts the whole transaction; it never chooses an arbitrary Reviewer/Editor.
"""

from __future__ import annotations

import argparse
import json

from src.config import get_settings
from src.services.orchestration.auth.seed_migration import migrate_seed_account_names
from src.services.orchestration.jobs.database import RuntimeDatabase


def main(argv: list[str] | None = None) -> int:
    """Apply the idempotent seed-name migration to the configured runtime database."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reviewer-user-id", required=True, help="verified stable ID of the seed Reviewer")
    parser.add_argument("--editor-user-id", required=True, help="verified stable ID of the seed Editor")
    args = parser.parse_args(argv)

    settings = get_settings()
    changed_ids = migrate_seed_account_names(
        RuntimeDatabase(settings.database_url), args.reviewer_user_id, args.editor_user_id
    )
    print(json.dumps({"updated_user_ids": changed_ids}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
