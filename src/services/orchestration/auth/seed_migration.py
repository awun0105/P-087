"""Explicit, idempotent display-name migration for the two Studio seed accounts."""

from src.services.orchestration.auth.models import Role, UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase

_SEED_NAMES: tuple[tuple[Role, str], ...] = (("reviewer", "Minh An"), ("editor", "Hà Linh"))


class SeedAccountMigrationError(ValueError):
    """The supplied stable IDs do not identify the expected seed accounts."""


def migrate_seed_account_names(
    database: RuntimeDatabase, reviewer_user_id: str, editor_user_id: str
) -> tuple[str, ...]:
    """Rename only the two explicitly selected IDs after verifying their roles.

    Both rows are validated before either is updated. Existing email, password hash,
    role, active state, quota, creation time, and ID are preserved.
    """
    ids = (reviewer_user_id.strip(), editor_user_id.strip())
    if not all(ids) or ids[0] == ids[1]:
        raise SeedAccountMigrationError("Cần hai stable user ID riêng cho seed Reviewer và Editor")

    selected: list[tuple[str, UserRecord, str, str]] = []
    with database.transaction(write=True) as tx:
        for (expected_role, display_name), user_id in zip(_SEED_NAMES, ids, strict=True):
            row = tx.execute(
                "SELECT payload FROM r2s_users WHERE user_id=?" + tx.lock_suffix(),
                (user_id,),
            ).fetchone()
            if row is None:
                raise SeedAccountMigrationError(f"Không tìm thấy seed account được chọn cho role {expected_role}")
            user = UserRecord.model_validate_json(row[0])
            if user.user_id != user_id or user.role != expected_role:
                raise SeedAccountMigrationError(f"Stable ID được chọn không có role seed {expected_role}")
            selected.append((user_id, user, display_name, row[0]))

        changed: list[str] = []
        for user_id, user, display_name, previous_payload in selected:
            if user.display_name == display_name:
                continue
            updated = user.model_copy(update={"display_name": display_name})
            cursor = tx.execute(
                "UPDATE r2s_users SET payload=? WHERE user_id=? AND payload=?",
                (updated.model_dump_json(), user_id, previous_payload),
            )
            if cursor.rowcount != 1:
                raise SeedAccountMigrationError("Seed account đã đổi trong lúc chạy migration")
            changed.append(user_id)
    return tuple(changed)
