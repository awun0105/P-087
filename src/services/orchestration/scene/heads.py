"""Persist the verified SceneIR head and resumable legacy-head repairs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.models.contracts.artifacts import ArtifactRef, Checksum
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.scene.editor import SceneEditor, scene_artifact_uri
from src.services.orchestration.scene.models import SceneRevision

_SCHEMA_VERSION = "1.0"
_ZERO = "sha256:" + "0" * 64
_REVISION_NUMBER = re.compile(r"^rev-(?P<number>[0-9]+)$")
_REVISION_FILE = re.compile(r"^scene_ir\.(?P<revision>.+)\.json$")
_CursorItem = TypeVar("_CursorItem")


class SceneHeadRecord(BaseModel):
    """Checksummed operational pointer to one immutable SceneIR artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    job_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    scene_revision: str = Field(min_length=1)
    scene_ir_checksum: Checksum
    scene_reference: ArtifactRef
    generation: int = Field(ge=1)
    allocation_sequence: int = Field(ge=1)
    updated_at: datetime
    head_checksum: Checksum

    @model_validator(mode="after")
    def _require_timezone(self) -> SceneHeadRecord:
        if self.updated_at.utcoffset() is None:
            raise ValueError("scene head updated_at must be timezone-aware")
        return self

    @classmethod
    def freeze(cls, item: SceneHeadBackfillItem, *, generation: int, allocation_sequence: int) -> SceneHeadRecord:
        draft = cls(
            schema_version=_SCHEMA_VERSION,
            job_id=item.job_id,
            scene_id=item.scene_id,
            scene_revision=item.scene_revision,
            scene_ir_checksum=item.scene_ir_checksum,
            scene_reference=item.scene_reference,
            generation=generation,
            allocation_sequence=allocation_sequence,
            updated_at=datetime.now(UTC),
            head_checksum=_ZERO,
        )
        head = draft.model_copy(update={"head_checksum": canonical_content_checksum(draft, "head_checksum")})
        verify_scene_head(head)
        return head


class SceneHeadBackfillItem(BaseModel):
    """One verified legacy revision edge, retained while a large backfill is paged."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    job_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    scene_revision: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    supersedes_revision: str | None = None
    scene_ir_checksum: Checksum
    scene_reference: ArtifactRef
    item_checksum: Checksum

    @classmethod
    def from_revision(cls, revision: SceneRevision) -> SceneHeadBackfillItem:
        match = _REVISION_NUMBER.fullmatch(revision.scene.scene_revision)
        if match is None:
            raise ValueError("scene revision name is not numeric")
        draft = cls(
            schema_version=_SCHEMA_VERSION,
            job_id=revision.job_id,
            scene_id=revision.scene.scene_id,
            scene_revision=revision.scene.scene_revision,
            revision_number=int(match.group("number")),
            supersedes_revision=revision.supersedes_revision,
            scene_ir_checksum=revision.scene.scene_ir_checksum,
            scene_reference=revision.scene_reference,
            item_checksum=_ZERO,
        )
        item = draft.model_copy(update={"item_checksum": canonical_content_checksum(draft, "item_checksum")})
        verify_backfill_item(item)
        return item


class SceneHeadRepairRecord(BaseModel):
    """Safe, resumable progress for one explicit legacy-head backfill."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    job_id: str = Field(min_length=1)
    status: Literal["IN_PROGRESS", "BLOCKED", "COMPLETE"]
    phase: Literal["VERIFY", "RECHECK"]
    inventory_checksum: Checksum
    cursor_revision: str | None = None
    verified_count: int = Field(ge=0)
    rechecked_count: int = Field(ge=0)
    generation: int = Field(ge=1)
    diagnostic_code: Literal["ARTIFACT_INVALID", "LINEAGE_INVALID", "INVENTORY_CHANGED"] | None = None
    updated_at: datetime
    repair_checksum: Checksum

    @model_validator(mode="after")
    def _validate_progress(self) -> SceneHeadRepairRecord:
        if self.updated_at.utcoffset() is None:
            raise ValueError("scene head repair updated_at must be timezone-aware")
        if self.cursor_revision is not None and _REVISION_NUMBER.fullmatch(self.cursor_revision) is None:
            raise ValueError("scene head repair cursor is not a numeric revision")
        if self.rechecked_count > self.verified_count:
            raise ValueError("scene head repair cannot recheck more revisions than it verified")
        if self.phase == "VERIFY" and self.rechecked_count:
            raise ValueError("scene head repair recheck count must be zero during VERIFY")
        if (self.status == "BLOCKED") != (self.diagnostic_code is not None):
            raise ValueError("scene head repair diagnostics must match its status")
        if self.status == "COMPLETE" and (self.phase != "RECHECK" or self.rechecked_count != self.verified_count):
            raise ValueError("completed scene head repair must recheck every revision")
        return self

    @classmethod
    def start(cls, job_id: str, inventory_checksum: str, generation: int) -> SceneHeadRepairRecord:
        draft = cls(
            schema_version=_SCHEMA_VERSION,
            job_id=job_id,
            status="IN_PROGRESS",
            phase="VERIFY",
            inventory_checksum=inventory_checksum,
            cursor_revision=None,
            verified_count=0,
            rechecked_count=0,
            generation=generation,
            diagnostic_code=None,
            updated_at=datetime.now(UTC),
            repair_checksum=_ZERO,
        )
        return draft.model_copy(update={"repair_checksum": canonical_content_checksum(draft, "repair_checksum")})


class PendingScenePublication(BaseModel):
    """Schema contract for the single reserved scene writer slot used by AUD-10.S2."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    job_id: str = Field(min_length=1)
    writer_id: str = Field(min_length=1)
    fencing_token: str = Field(min_length=1)
    expected_generation: int = Field(ge=1)
    expected_scene_revision: str = Field(min_length=1)
    target_scene_revision: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    payload_checksum: Checksum
    artifact_reference: ArtifactRef
    lease_expires_at: datetime
    status: Literal["RESERVED", "PUBLISHED"]


@dataclass(frozen=True)
class SceneHeadBackfillResult:
    job_id: str
    status: Literal["NO_SCENE", "IN_PROGRESS", "BLOCKED", "COMPLETE"]
    verified_count: int
    cursor_revision: str | None = None
    phase: Literal["VERIFY", "RECHECK"] | None = None
    head: SceneHeadRecord | None = None
    diagnostic_code: str | None = None


class SceneHeadBackfillError(RuntimeError):
    """A legacy head cannot be verified; diagnostic_code contains no provider text."""

    def __init__(self, message: str, diagnostic_code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code


class SceneHeadRepository:
    """Typed access to immutable head identity and resumable repair staging."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database

    def get(self, job_id: str) -> SceneHeadRecord | None:
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT job_id,generation,allocation_sequence,head_checksum,payload FROM r2s_scene_heads WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return _parse_head_row(row) if row is not None else None

    def get_repair(self, job_id: str) -> SceneHeadRepairRecord | None:
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT job_id,status,generation,repair_checksum,payload FROM r2s_scene_head_repairs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return _parse_repair_row(row) if row is not None else None

    def begin_backfill(self, job_id: str, inventory_checksum: str) -> SceneHeadRepairRecord:
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT job_id,status,generation,repair_checksum,payload FROM r2s_scene_head_repairs WHERE job_id=?"
                + tx.lock_suffix(),
                (job_id,),
            ).fetchone()
            if row is None:
                repair = SceneHeadRepairRecord.start(job_id, inventory_checksum, 1)
                tx.execute(
                    "INSERT INTO r2s_scene_head_repairs(job_id,status,generation,repair_checksum,payload) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO NOTHING",
                    (job_id, repair.status, repair.generation, repair.repair_checksum, repair.model_dump_json()),
                )
                row = tx.execute(
                    "SELECT job_id,status,generation,repair_checksum,payload FROM r2s_scene_head_repairs WHERE job_id=?"
                    + tx.lock_suffix(),
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeStateConflictError("Scene head repair insert conflicted without a visible row")
            current = _parse_repair_row(row)
            if current.status == "IN_PROGRESS" and current.inventory_checksum == inventory_checksum:
                return current
            tx.execute("DELETE FROM r2s_scene_head_backfill_items WHERE job_id=?", (job_id,))
            repair = SceneHeadRepairRecord.start(job_id, inventory_checksum, current.generation + 1)
            tx.execute(
                "UPDATE r2s_scene_head_repairs SET status=?,generation=?,repair_checksum=?,payload=? WHERE job_id=?",
                (repair.status, repair.generation, repair.repair_checksum, repair.model_dump_json(), job_id),
            )
            return repair

    def items(self, job_id: str) -> list[SceneHeadBackfillItem]:
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT job_id,scene_revision,item_checksum,payload FROM r2s_scene_head_backfill_items "
                "WHERE job_id=? ORDER BY scene_revision",
                (job_id,),
            ).fetchall()
        return [_parse_item_row(row) for row in rows]

    def save_item(self, item: SceneHeadBackfillItem) -> SceneHeadBackfillItem:
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_scene_head_backfill_items(job_id,scene_revision,item_checksum,payload) "
                "VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                (item.job_id, item.scene_revision, item.item_checksum, item.model_dump_json()),
            )
            row = tx.execute(
                "SELECT job_id,scene_revision,item_checksum,payload FROM r2s_scene_head_backfill_items "
                "WHERE job_id=? AND scene_revision=?",
                (item.job_id, item.scene_revision),
            ).fetchone()
        if row is None:
            raise RuntimeStateConflictError("Scene head backfill item insert conflicted without a visible row")
        existing = _parse_item_row(row)
        if existing != item:
            raise RuntimeStateConflictError("Scene revision changed during legacy head backfill")
        return existing

    def advance_backfill(
        self,
        current: SceneHeadRepairRecord,
        cursor_revision: str,
        *,
        verified_count: int | None = None,
        rechecked_count: int | None = None,
    ) -> SceneHeadRepairRecord:
        updated = _seal_repair(
            current.model_copy(
                update={
                    "cursor_revision": cursor_revision,
                    "verified_count": current.verified_count if verified_count is None else verified_count,
                    "rechecked_count": current.rechecked_count if rechecked_count is None else rechecked_count,
                    "generation": current.generation + 1,
                    "updated_at": datetime.now(UTC),
                    "repair_checksum": _ZERO,
                }
            )
        )
        with self.database.transaction(write=True) as tx:
            changed = tx.execute(
                "UPDATE r2s_scene_head_repairs SET status=?,generation=?,repair_checksum=?,payload=? "
                "WHERE job_id=? AND generation=? AND repair_checksum=? AND status='IN_PROGRESS'",
                (
                    updated.status,
                    updated.generation,
                    updated.repair_checksum,
                    updated.model_dump_json(),
                    current.job_id,
                    current.generation,
                    current.repair_checksum,
                ),
            ).rowcount
        if changed != 1:
            raise RuntimeStateConflictError("Scene head repair progress changed; resume from the persisted cursor")
        return updated

    def begin_recheck(self, current: SceneHeadRepairRecord) -> SceneHeadRepairRecord:
        """Start a second bounded pass so changes after the first verification are detected."""
        if current.phase != "VERIFY":
            raise RuntimeStateConflictError("Scene head repair is not in the initial verification phase")
        updated = _seal_repair(
            current.model_copy(
                update={
                    "phase": "RECHECK",
                    "cursor_revision": None,
                    "rechecked_count": 0,
                    "generation": current.generation + 1,
                    "updated_at": datetime.now(UTC),
                    "repair_checksum": _ZERO,
                }
            )
        )
        with self.database.transaction(write=True) as tx:
            changed = tx.execute(
                "UPDATE r2s_scene_head_repairs SET status=?,generation=?,repair_checksum=?,payload=? "
                "WHERE job_id=? AND generation=? AND repair_checksum=? AND status='IN_PROGRESS'",
                (
                    updated.status,
                    updated.generation,
                    updated.repair_checksum,
                    updated.model_dump_json(),
                    current.job_id,
                    current.generation,
                    current.repair_checksum,
                ),
            ).rowcount
        if changed != 1:
            raise RuntimeStateConflictError("Scene head repair phase changed; resume from persisted state")
        return updated

    def block_backfill(
        self,
        current: SceneHeadRepairRecord,
        diagnostic_code: Literal["ARTIFACT_INVALID", "LINEAGE_INVALID", "INVENTORY_CHANGED"],
    ) -> SceneHeadRepairRecord:
        updated = _seal_repair(
            current.model_copy(
                update={
                    "status": "BLOCKED",
                    "diagnostic_code": diagnostic_code,
                    "generation": current.generation + 1,
                    "updated_at": datetime.now(UTC),
                    "repair_checksum": _ZERO,
                }
            )
        )
        with self.database.transaction(write=True) as tx:
            changed = tx.execute(
                "UPDATE r2s_scene_head_repairs SET status=?,generation=?,repair_checksum=?,payload=? "
                "WHERE job_id=? AND generation=? AND repair_checksum=? AND status='IN_PROGRESS'",
                (
                    updated.status,
                    updated.generation,
                    updated.repair_checksum,
                    updated.model_dump_json(),
                    current.job_id,
                    current.generation,
                    current.repair_checksum,
                ),
            ).rowcount
        if changed != 1:
            raise RuntimeStateConflictError("Scene head repair progress changed before diagnostic was recorded")
        return updated

    def complete_backfill(self, current: SceneHeadRepairRecord, head: SceneHeadRecord) -> SceneHeadRecord:
        if current.status != "IN_PROGRESS" or current.phase != "RECHECK" or head.job_id != current.job_id:
            raise RuntimeStateConflictError("Scene head is not ready for a verified repair commit")
        if current.rechecked_count != current.verified_count:
            raise RuntimeStateConflictError("Scene head repair has not rechecked every verified revision")
        complete = _seal_repair(
            current.model_copy(
                update={
                    "status": "COMPLETE",
                    "diagnostic_code": None,
                    "generation": current.generation + 1,
                    "updated_at": datetime.now(UTC),
                    "repair_checksum": _ZERO,
                }
            )
        )
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT job_id,status,generation,repair_checksum,payload FROM r2s_scene_head_repairs WHERE job_id=?"
                + tx.lock_suffix(),
                (current.job_id,),
            ).fetchone()
            if row is None or _parse_repair_row(row) != current:
                raise RuntimeStateConflictError("Scene head repair changed before commit")
            existing = tx.execute(
                "SELECT job_id,generation,allocation_sequence,head_checksum,payload FROM r2s_scene_heads WHERE job_id=?",
                (head.job_id,),
            ).fetchone()
            if existing is None:
                tx.execute(
                    "INSERT INTO r2s_scene_heads(job_id,generation,allocation_sequence,head_checksum,payload) "
                    "VALUES (?,?,?,?,?)",
                    (
                        head.job_id,
                        head.generation,
                        head.allocation_sequence,
                        head.head_checksum,
                        head.model_dump_json(),
                    ),
                )
            elif _parse_head_row(existing) != head:
                raise RuntimeStateConflictError("A different committed scene head already exists")
            changed = tx.execute(
                "UPDATE r2s_scene_head_repairs SET status=?,generation=?,repair_checksum=?,payload=? "
                "WHERE job_id=? AND generation=? AND repair_checksum=?",
                (
                    complete.status,
                    complete.generation,
                    complete.repair_checksum,
                    complete.model_dump_json(),
                    current.job_id,
                    current.generation,
                    current.repair_checksum,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeStateConflictError("Scene head repair CAS failed")
        return head


class SceneHeadBackfill:
    """Validate all immutable legacy revisions and persist a head in bounded pages."""

    def __init__(self, resolver: ArtifactResolver, editor: SceneEditor, repository: SceneHeadRepository) -> None:
        self.resolver = resolver
        self.editor = editor
        self.repository = repository

    def inspect(self, job_id: str) -> SceneHeadBackfillResult:
        """Read-only full validation for the CLI dry run; does not write DB rows."""
        revisions, _ = self._inventory(job_id)
        if not revisions:
            return SceneHeadBackfillResult(job_id, "NO_SCENE", 0)
        try:
            items = [self._load_item(job_id, revision) for _, revision in revisions]
        except Exception as error:
            raise SceneHeadBackfillError("Scene revision artifact failed verification", "ARTIFACT_INVALID") from error
        try:
            head = _head_from_chain(job_id, items)
        except ValueError as error:
            raise SceneHeadBackfillError("Legacy SceneIR lineage is invalid", "LINEAGE_INVALID") from error
        return SceneHeadBackfillResult(job_id, "COMPLETE", len(items), head=head)

    def backfill_page(self, job_id: str, *, page_size: int = 250) -> SceneHeadBackfillResult:
        """Advance one bounded verification page; commit only after a bounded recheck pass."""
        if page_size < 1:
            raise ValueError("page_size must be positive")
        existing_head = self.repository.get(job_id)
        if existing_head is not None:
            self._verify_existing_head(existing_head)
            return SceneHeadBackfillResult(job_id, "COMPLETE", 0, head=existing_head)

        revisions, inventory_checksum = self._inventory(job_id)
        if not revisions:
            return SceneHeadBackfillResult(job_id, "NO_SCENE", 0)
        repair = self.repository.begin_backfill(job_id, inventory_checksum)
        if repair.status == "COMPLETE":
            raise SceneHeadBackfillError("Completed head repair has no committed head", "LINEAGE_INVALID")
        items = self.repository.items(job_id)
        if repair.phase == "VERIFY":
            revision_names = [revision for _, revision in revisions]
            try:
                remaining = _after_cursor(revision_names, repair.cursor_revision)
            except ValueError as error:
                self.repository.block_backfill(repair, "LINEAGE_INVALID")
                raise SceneHeadBackfillError(
                    "Scene repair cursor is absent from its inventory", "LINEAGE_INVALID"
                ) from error
            page = remaining[:page_size]
            for revision in page:
                try:
                    item = self._load_item(job_id, revision)
                except Exception as error:
                    self.repository.block_backfill(repair, "ARTIFACT_INVALID")
                    raise SceneHeadBackfillError(
                        "Scene revision artifact failed verification", "ARTIFACT_INVALID"
                    ) from error
                self.repository.save_item(item)
                repair = self.repository.advance_backfill(repair, revision, verified_count=repair.verified_count + 1)
            if len(page) < len(remaining):
                return SceneHeadBackfillResult(
                    job_id,
                    "IN_PROGRESS",
                    repair.verified_count,
                    cursor_revision=repair.cursor_revision,
                    phase=repair.phase,
                )
            items = self.repository.items(job_id)
            if len(items) != len(revisions) or repair.verified_count != len(revisions):
                self.repository.block_backfill(repair, "LINEAGE_INVALID")
                raise SceneHeadBackfillError("Verified revision inventory is incomplete", "LINEAGE_INVALID")
            repair = self.repository.begin_recheck(repair)
            return SceneHeadBackfillResult(
                job_id,
                "IN_PROGRESS",
                repair.verified_count,
                cursor_revision=repair.cursor_revision,
                phase=repair.phase,
            )

        items.sort(key=lambda item: (item.revision_number, item.scene_revision))
        try:
            remaining_items = _after_cursor(items, repair.cursor_revision, key=lambda item: item.scene_revision)
        except ValueError as error:
            self.repository.block_backfill(repair, "LINEAGE_INVALID")
            raise SceneHeadBackfillError(
                "Scene repair cursor is absent from verified revisions", "LINEAGE_INVALID"
            ) from error
        page_items = remaining_items[:page_size]
        for item in page_items:
            try:
                observed = self._load_item(job_id, item.scene_revision)
            except Exception as error:
                self.repository.block_backfill(repair, "ARTIFACT_INVALID")
                raise SceneHeadBackfillError(
                    "Scene revision artifact failed its recheck", "ARTIFACT_INVALID"
                ) from error
            if observed != item:
                self.repository.block_backfill(repair, "ARTIFACT_INVALID")
                raise SceneHeadBackfillError("Scene revision bytes changed after verification", "ARTIFACT_INVALID")
            repair = self.repository.advance_backfill(
                repair, item.scene_revision, rechecked_count=repair.rechecked_count + 1
            )
        if len(page_items) < len(remaining_items):
            return SceneHeadBackfillResult(
                job_id,
                "IN_PROGRESS",
                repair.verified_count,
                cursor_revision=repair.cursor_revision,
                phase=repair.phase,
            )

        if len(items) != len(revisions) or repair.rechecked_count != len(revisions):
            self.repository.block_backfill(repair, "LINEAGE_INVALID")
            raise SceneHeadBackfillError("Rechecked revision inventory is incomplete", "LINEAGE_INVALID")
        current_revisions, current_inventory = self._inventory(job_id)
        if current_inventory != inventory_checksum or current_revisions != revisions:
            self.repository.block_backfill(repair, "INVENTORY_CHANGED")
            raise SceneHeadBackfillError("Scene revision inventory changed during backfill", "INVENTORY_CHANGED")
        try:
            head = _head_from_chain(job_id, items)
        except ValueError as error:
            self.repository.block_backfill(repair, "LINEAGE_INVALID")
            raise SceneHeadBackfillError("Legacy SceneIR lineage failed verification", "LINEAGE_INVALID") from error
        committed = self.repository.complete_backfill(repair, head)
        return SceneHeadBackfillResult(job_id, "COMPLETE", len(items), head=committed)

    def _inventory(self, job_id: str) -> tuple[list[tuple[str, str]], str]:
        uris = self.resolver.list_uris(f"artifact://jobs/{job_id}/scene/")
        revisions: list[tuple[str, str]] = []
        for uri in uris:
            filename = uri.rsplit("/", 1)[-1]
            if not filename.startswith("scene_ir.") or not filename.endswith(".json"):
                continue
            match = _REVISION_FILE.fullmatch(filename)
            if match is None or _REVISION_NUMBER.fullmatch(match.group("revision")) is None:
                raise SceneHeadBackfillError(
                    "SceneIR inventory contains an unsupported revision name", "ARTIFACT_INVALID"
                )
            revisions.append((uri, match.group("revision")))
        revisions.sort(key=lambda pair: (_revision_number(pair[1]), pair[1]))
        serialized = json.dumps([uri for uri, _ in revisions], separators=(",", ":")).encode("utf-8")
        checksum = "sha256:" + hashlib.sha256(serialized).hexdigest()
        return revisions, checksum

    def _load_item(self, job_id: str, revision: str) -> SceneHeadBackfillItem:
        loaded = self.editor.revision(job_id, revision)
        if loaded is None:
            raise ValueError("listed SceneIR revision is not resolvable")
        if loaded.job_id != job_id or loaded.scene.scene_revision != revision:
            raise ValueError("SceneIR artifact identity changed")
        return SceneHeadBackfillItem.from_revision(loaded)

    def _verify_existing_head(self, head: SceneHeadRecord) -> None:
        item = self._load_item(head.job_id, head.scene_revision)
        if (
            item.scene_id != head.scene_id
            or item.scene_ir_checksum != head.scene_ir_checksum
            or item.scene_reference != head.scene_reference
        ):
            raise SceneHeadBackfillError("Committed scene head does not match its artifact", "ARTIFACT_INVALID")


def _revision_number(revision: str | None) -> int:
    if revision is None:
        return 0
    match = _REVISION_NUMBER.fullmatch(revision)
    if match is None:
        raise ValueError("scene revision name is not numeric")
    return int(match.group("number"))


def _head_from_chain(job_id: str, items: list[SceneHeadBackfillItem]) -> SceneHeadRecord:
    by_revision = {item.scene_revision: item for item in items}
    if len(by_revision) != len(items) or not by_revision:
        raise ValueError("SceneIR revision set is empty or duplicated")
    if len({item.revision_number for item in items}) != len(items):
        raise ValueError("SceneIR revision numbers are duplicated")
    roots = [item for item in items if item.supersedes_revision is None]
    if len(roots) != 1 or roots[0].scene_revision != "rev-001":
        raise ValueError("SceneIR revision chain must have exactly one rev-001 root")
    root = roots[0]
    if any(item.job_id != job_id or item.scene_id != root.scene_id for item in items):
        raise ValueError("SceneIR revisions do not belong to one job and scene")
    children: dict[str, list[SceneHeadBackfillItem]] = {}
    for item in items:
        if item.supersedes_revision is None:
            continue
        if item.supersedes_revision not in by_revision:
            raise ValueError("SceneIR revision has a missing parent")
        parent = by_revision[item.supersedes_revision]
        if item.revision_number <= parent.revision_number:
            raise ValueError("SceneIR revision number does not advance past its parent")
        children.setdefault(item.supersedes_revision, []).append(item)
    if any(len(values) != 1 for values in children.values()):
        raise ValueError("SceneIR lineage has competing child revisions")
    visited: set[str] = set()
    current = root
    while current.scene_revision not in visited:
        visited.add(current.scene_revision)
        next_items = children.get(current.scene_revision, [])
        if not next_items:
            break
        current = next_items[0]
    if len(visited) != len(items):
        raise ValueError("SceneIR inventory contains an orphan or cycle")
    allocation_sequence = max(item.revision_number for item in items)
    return SceneHeadRecord.freeze(current, generation=1, allocation_sequence=allocation_sequence)


def _after_cursor(
    values: list[_CursorItem], cursor: str | None, *, key: Callable[[_CursorItem], str] | None = None
) -> list[_CursorItem]:
    """Return a bounded-pass suffix, requiring the durable cursor to still exist."""
    if cursor is None:
        return values
    value_key = key if key is not None else lambda value: str(value)
    matches = [index for index, value in enumerate(values) if value_key(value) == cursor]
    if len(matches) != 1:
        raise ValueError("repair cursor does not identify one item")
    return values[matches[0] + 1 :]


def verify_scene_head(head: SceneHeadRecord) -> None:
    verify_content_checksum(head, "head_checksum")
    revision_number = _revision_number(head.scene_revision)
    if head.allocation_sequence < revision_number:
        raise ValueError("scene head allocation sequence is behind its committed revision")
    if head.scene_reference.job_id != head.job_id or head.scene_reference.artifact_uri != scene_artifact_uri(
        head.job_id, head.scene_revision
    ):
        raise ValueError("scene head reference does not match its identity")


def verify_backfill_item(item: SceneHeadBackfillItem) -> None:
    verify_content_checksum(item, "item_checksum")
    match = _REVISION_NUMBER.fullmatch(item.scene_revision)
    if (
        match is None
        or int(match.group("number")) != item.revision_number
        or item.scene_reference.job_id != item.job_id
        or item.scene_reference.artifact_uri != scene_artifact_uri(item.job_id, item.scene_revision)
    ):
        raise ValueError("scene backfill item reference does not match its identity")


def _seal_repair(repair: SceneHeadRepairRecord) -> SceneHeadRepairRecord:
    return repair.model_copy(update={"repair_checksum": canonical_content_checksum(repair, "repair_checksum")})


def _parse_head_row(row: tuple) -> SceneHeadRecord:
    try:
        head = SceneHeadRecord.model_validate_json(row[4])
        verify_scene_head(head)
    except (ValidationError, ValueError) as error:
        raise RuntimeStateConflictError("Persisted scene head is invalid") from error
    if (row[0], row[1], row[2], row[3]) != (
        head.job_id,
        head.generation,
        head.allocation_sequence,
        head.head_checksum,
    ):
        raise RuntimeStateConflictError("Scene head indexed columns do not match its payload")
    return head


def _parse_repair_row(row: tuple) -> SceneHeadRepairRecord:
    try:
        repair = SceneHeadRepairRecord.model_validate_json(row[4])
        verify_content_checksum(repair, "repair_checksum")
    except (ValidationError, ValueError) as error:
        raise RuntimeStateConflictError("Persisted scene head repair record is invalid") from error
    if (row[0], row[1], row[2], row[3]) != (
        repair.job_id,
        repair.status,
        repair.generation,
        repair.repair_checksum,
    ):
        raise RuntimeStateConflictError("Scene head repair indexed columns do not match its payload")
    return repair


def _parse_item_row(row: tuple) -> SceneHeadBackfillItem:
    try:
        item = SceneHeadBackfillItem.model_validate_json(row[3])
        verify_backfill_item(item)
    except (ValidationError, ValueError) as error:
        raise RuntimeStateConflictError("Persisted scene head backfill item is invalid") from error
    if (row[0], row[1], row[2]) != (item.job_id, item.scene_revision, item.item_checksum):
        raise RuntimeStateConflictError("Scene head backfill indexed columns do not match its payload")
    return item
