"""Verified, resumable SceneIR head recovery for legacy artifact histories."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.studio import scene_head as scene_head_cli
from src.config import Settings
from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactRemote,
    ArtifactResolver,
    InvalidArtifactUriError,
    with_canonical_checksum,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.scene.editor import SceneEditor, scene_artifact_uri
from src.services.orchestration.scene.errors import (
    SceneHeadNotReadyError,
    SceneNotAvailableError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.heads import (
    SceneHeadBackfill,
    SceneHeadBackfillError,
    SceneHeadRepository,
    _seal_publication,
)
from src.services.orchestration.scene.models import SceneEditCommand, TransformEdit
from tests.test_orchestration.memory_object_store import MemoryObjectStore

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"
_JOB_ID = "job-fixture-001"


@pytest.fixture
def scene_state(tmp_path: Path) -> SimpleNamespace:
    database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
    database = RuntimeDatabase(database_url)
    resolver = ArtifactResolver(tmp_path / "artifacts")
    editor = SceneEditor(_FIXTURE_ROOT, resolver)
    repository = SceneHeadRepository(database)
    return SimpleNamespace(
        database_url=database_url,
        database=database,
        resolver=resolver,
        editor=editor,
        repository=repository,
    )


def _edit(editor: SceneEditor, expected_revision: str, value: float) -> str:
    result = editor.apply(
        _JOB_ID,
        SceneEditCommand(
            expected_scene_revision=expected_revision,
            edits=[TransformEdit(object_id="object-rack-001", translation_xyz=(value, value, 0.0))],
        ),
    )
    return result.revision.scene.scene_revision


def _artifact_checksums(resolver: ArtifactResolver) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for uri in resolver.list_uris(f"artifact://jobs/{_JOB_ID}/scene/"):
        path = resolver.resolve(uri)
        checksums[uri] = hashlib.sha256(path.read_bytes()).hexdigest()
    return checksums


def _new_backfill(state: SimpleNamespace) -> SceneHeadBackfill:
    """Recreate the service boundary to model a process restart between pages."""
    editor = SceneEditor(_FIXTURE_ROOT, state.resolver)
    return SceneHeadBackfill(state.resolver, editor, SceneHeadRepository(state.database))


def _head_editor(state: SimpleNamespace, database: RuntimeDatabase | None = None) -> SceneEditor:
    return SceneEditor(_FIXTURE_ROOT, state.resolver, SceneHeadRepository(database or state.database))


def _publish_root(editor: SceneEditor) -> None:
    editor.publish_initial(_JOB_ID, editor._fixture_scene())


def test_artifact_listing_merges_local_and_remote_and_rejects_symlink_prefix(tmp_path: Path) -> None:
    store = MemoryObjectStore()
    resolver = ArtifactResolver(tmp_path / "cache", ArtifactRemote(store, "tenant"))
    local = resolver.resolve("artifact://jobs/job-a/scene/scene_ir.rev-001.json")
    local.parent.mkdir(parents=True)
    local.write_text("{}", encoding="utf-8")
    store.objects["tenant/jobs/job-a/scene/scene_ir.rev-002.json"] = (b"{}", None)

    assert resolver.list_uris("artifact://jobs/job-a/scene/") == [
        "artifact://jobs/job-a/scene/scene_ir.rev-001.json",
        "artifact://jobs/job-a/scene/scene_ir.rev-002.json",
    ]

    external = tmp_path / "external"
    external.mkdir()
    (resolver.artifact_root / "jobs").mkdir(parents=True, exist_ok=True)
    (resolver.artifact_root / "jobs" / "job-alias").symlink_to(external, target_is_directory=True)
    with pytest.raises(InvalidArtifactUriError, match="symlink"):
        resolver.list_uris("artifact://jobs/job-alias/scene/")


def test_backfill_resumes_across_pages_and_preserves_immutable_artifacts(scene_state: SimpleNamespace) -> None:
    editor = scene_state.editor
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-001"
    assert _edit(editor, "rev-001", 1.0) == "rev-002"
    assert _edit(editor, "rev-002", 2.0) == "rev-003"
    artifact_checksums = _artifact_checksums(scene_state.resolver)
    backfill = _new_backfill(scene_state)

    inspected = backfill.inspect(_JOB_ID)
    assert inspected.status == "COMPLETE"
    assert inspected.head is not None and inspected.head.scene_revision == "rev-003"
    assert scene_state.repository.get(_JOB_ID) is None
    assert scene_state.repository.get_repair(_JOB_ID) is None

    result = backfill.backfill_page(_JOB_ID, page_size=1)
    assert result.status == "IN_PROGRESS" and result.phase == "VERIFY"
    assert result.verified_count == 1 and result.cursor_revision == "rev-001"
    calls = 1
    while result.status != "COMPLETE":
        result = _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=1)
        calls += 1
        assert calls < 10

    assert calls == 6
    assert result.head is not None
    assert result.head.scene_revision == "rev-003"
    assert result.head.allocation_sequence == 3
    assert result.head.scene_reference.artifact_checksum
    repair = scene_state.repository.get_repair(_JOB_ID)
    assert repair is not None
    assert repair.status == "COMPLETE" and repair.verified_count == repair.rechecked_count == 3
    assert _artifact_checksums(scene_state.resolver) == artifact_checksums

    repeated = _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=1)
    assert repeated.status == "COMPLETE" and repeated.head == result.head
    assert _artifact_checksums(scene_state.resolver) == artifact_checksums


def test_backfill_handles_long_history_and_current_reads_stay_bounded(
    scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backfill a 1,005-revision chain and compare DB/resolver calls at both sizes."""
    short_reader = _head_editor(scene_state)
    _publish_root(short_reader)

    calls = {"head": 0, "locate": 0, "list": 0}
    repository_get = SceneHeadRepository.get
    resolver_locate = ArtifactResolver.locate
    resolver_list = ArtifactResolver.list_uris

    def counted_get(repository: SceneHeadRepository, job_id: str):
        calls["head"] += 1
        return repository_get(repository, job_id)

    def counted_locate(resolver: ArtifactResolver, uri: str, *, fresh: bool = False):
        calls["locate"] += 1
        return resolver_locate(resolver, uri, fresh=fresh)

    def counted_list(resolver: ArtifactResolver, prefix: str):
        calls["list"] += 1
        return resolver_list(resolver, prefix)

    monkeypatch.setattr(SceneHeadRepository, "get", counted_get)
    monkeypatch.setattr(ArtifactResolver, "locate", counted_locate)
    monkeypatch.setattr(ArtifactResolver, "list_uris", counted_list)

    def read_current(editor: SceneEditor) -> dict[str, int]:
        calls.update(head=0, locate=0, list=0)
        assert editor.current(_JOB_ID).scene.scene_revision in {"rev-001", "rev-1005"}
        return calls.copy()

    short_calls = read_current(short_reader)
    assert short_calls == {"head": 1, "locate": 1, "list": 0}

    # Rebuild the same job as a legacy artifact-only chain, then backfill its head.
    with scene_state.database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_scene_heads WHERE job_id=?", (_JOB_ID,))
    scene_state.editor.current(_JOB_ID)
    revision = "rev-001"
    for number in range(2, 1006):
        revision = _edit(scene_state.editor, revision, float(number))
    assert revision == "rev-1005"

    result = _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=250)
    page_calls = 1
    while result.status != "COMPLETE":
        result = _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=250)
        page_calls += 1
        assert page_calls < 20

    assert result.head is not None
    assert result.head.scene_revision == "rev-1005"
    assert result.head.allocation_sequence == 1005
    assert result.verified_count == 1005

    long_reader = _head_editor(scene_state, RuntimeDatabase(scene_state.database_url))
    long_calls = read_current(long_reader)
    assert long_reader.current(_JOB_ID).scene.scene_revision == "rev-1005"
    assert long_calls == short_calls


def test_remote_head_freshness_and_bad_checksum_fail_closed(scene_state: SimpleNamespace, tmp_path: Path) -> None:
    """Independent DB/cache clients observe new heads; remote byte corruption is rejected."""
    store = MemoryObjectStore()
    writer_resolver = ArtifactResolver(tmp_path / "writer-cache", ArtifactRemote(store))
    writer = SceneEditor(_FIXTURE_ROOT, writer_resolver, SceneHeadRepository(scene_state.database))
    _publish_root(writer)

    reader_resolver = ArtifactResolver(tmp_path / "reader-cache", ArtifactRemote(store))
    reader = SceneEditor(
        _FIXTURE_ROOT,
        reader_resolver,
        SceneHeadRepository(RuntimeDatabase(scene_state.database_url)),
    )
    assert reader.current(_JOB_ID).scene.scene_revision == "rev-001"

    root = writer.current(_JOB_ID).scene
    writer.publish_next(_JOB_ID, "rev-001", root.model_copy(update={"objects": []}), "remote_freshness")
    assert reader.current(_JOB_ID).scene.scene_revision == "rev-002"

    uri = scene_artifact_uri(_JOB_ID, "rev-002")
    key = writer_resolver.relative_key(uri)
    payload, checksum = store.objects[key]
    store.objects[key] = (payload + b"tampered", checksum)
    corrupt_resolver = ArtifactResolver(tmp_path / "corrupt-reader-cache", ArtifactRemote(store))
    corrupt_reader = SceneEditor(
        _FIXTURE_ROOT,
        corrupt_resolver,
        SceneHeadRepository(RuntimeDatabase(scene_state.database_url)),
    )
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        corrupt_reader.current(_JOB_ID)
    assert not corrupt_resolver.resolve(uri).exists()


def test_corrupt_artifact_is_blocked_with_a_safe_diagnostic(scene_state: SimpleNamespace) -> None:
    revision = scene_state.editor.current(_JOB_ID)
    path = scene_state.resolver.resolve(revision.scene_reference.artifact_uri)
    path.write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(SceneHeadBackfillError) as caught:
        _new_backfill(scene_state).backfill_page(_JOB_ID)

    assert caught.value.diagnostic_code == "ARTIFACT_INVALID"
    repair = scene_state.repository.get_repair(_JOB_ID)
    assert repair is not None and repair.status == "BLOCKED"
    assert repair.diagnostic_code == "ARTIFACT_INVALID"
    assert "tampered" not in str(caught.value)
    assert scene_state.repository.get(_JOB_ID) is None


def test_missing_parent_and_orphan_revision_are_not_promoted_to_head(scene_state: SimpleNamespace) -> None:
    scene_state.editor.current(_JOB_ID)
    _edit(scene_state.editor, "rev-001", 1.0)
    _edit(scene_state.editor, "rev-002", 2.0)
    scene_state.resolver.resolve(scene_artifact_uri(_JOB_ID, "rev-002")).unlink()
    backfill = _new_backfill(scene_state)

    result = backfill.backfill_page(_JOB_ID, page_size=5)
    assert result.status == "IN_PROGRESS" and result.phase == "RECHECK"
    with pytest.raises(SceneHeadBackfillError) as caught:
        _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=5)

    assert caught.value.diagnostic_code == "LINEAGE_INVALID"
    repair = scene_state.repository.get_repair(_JOB_ID)
    assert repair is not None and repair.status == "BLOCKED"
    assert repair.diagnostic_code == "LINEAGE_INVALID"
    assert scene_state.repository.get(_JOB_ID) is None


def test_empty_inventory_does_not_create_a_head_or_repair(scene_state: SimpleNamespace) -> None:
    result = _new_backfill(scene_state).backfill_page("job-without-scene")

    assert result.status == "NO_SCENE"
    assert scene_state.repository.get("job-without-scene") is None
    assert scene_state.repository.get_repair("job-without-scene") is None


def test_scene_head_cli_is_read_only_by_default_and_applies_bounded_pages(
    scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene_state.editor.current(_JOB_ID)
    _edit(scene_state.editor, "rev-001", 1.0)
    monkeypatch.setattr(
        scene_head_cli,
        "get_settings",
        lambda: Settings(database_url=scene_state.database_url, artifact_root=scene_state.resolver.artifact_root),
    )

    assert scene_head_cli.main(["--job-id", _JOB_ID]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["mode"] == "inspect" and inspected["head"]["scene_revision"] == "rev-002"
    assert scene_state.repository.get_repair(_JOB_ID) is None

    assert scene_head_cli.main(["--job-id", _JOB_ID, "--apply", "--page-size", "1"]) == 0
    first_page = json.loads(capsys.readouterr().out)
    assert first_page["status"] == "IN_PROGRESS" and first_page["phase"] == "VERIFY"
    assert scene_head_cli.main(["--job-id", _JOB_ID, "--apply", "--page-size", "1"]) == 0
    second_page = json.loads(capsys.readouterr().out)
    assert second_page["status"] == "IN_PROGRESS" and second_page["phase"] == "RECHECK"

    assert scene_head_cli.main(["--job-id", _JOB_ID, "--apply", "--page-size", "1"]) == 0
    third_page = json.loads(capsys.readouterr().out)
    assert third_page["status"] == "IN_PROGRESS" and third_page["phase"] == "RECHECK"

    assert scene_head_cli.main(["--job-id", _JOB_ID, "--apply", "--page-size", "1"]) == 0
    final_page = json.loads(capsys.readouterr().out)
    assert final_page["status"] == "COMPLETE" and final_page["head"]["scene_revision"] == "rev-002"
    assert scene_state.repository.get(_JOB_ID) is not None


def test_database_backed_editor_commits_initial_and_next_head(scene_state: SimpleNamespace) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)

    first = scene_state.repository.get(_JOB_ID)
    assert first is not None
    assert first.scene_revision == "rev-001" and first.generation == first.allocation_sequence == 1
    assert scene_state.repository.get_publication(_JOB_ID) is None

    root = editor.current(_JOB_ID)
    result = editor.publish_next(
        _JOB_ID, root.scene.scene_revision, root.scene.model_copy(update={"objects": []}), "reject_object"
    )
    committed = scene_state.repository.get(_JOB_ID)
    assert result.revision.scene.scene_revision == "rev-002"
    assert committed is not None and committed.scene_revision == "rev-002" and committed.generation == 2
    assert scene_state.repository.get_publication(_JOB_ID) is None
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-002"


def test_two_independent_editors_cannot_commit_the_same_expected_head(scene_state: SimpleNamespace) -> None:
    first = _head_editor(scene_state)
    _publish_root(first)
    second_database = RuntimeDatabase(scene_state.database_url)
    second = _head_editor(scene_state, second_database)
    first_scene = first.current(_JOB_ID).scene
    second_scene = second.current(_JOB_ID).scene

    def write(editor: SceneEditor, scene) -> str:  # noqa: ANN001 - concise concurrent test helper
        try:
            editor.publish_next(_JOB_ID, "rev-001", scene.model_copy(update={"objects": []}), "concurrent_edit")
            return "committed"
        except SceneRevisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda pair: write(*pair), [(first, first_scene), (second, second_scene)]))

    assert sorted(outcomes) == ["committed", "conflict"]
    head = scene_state.repository.get(_JOB_ID)
    assert head is not None and head.scene_revision == "rev-002" and head.generation == 2
    assert scene_state.repository.get_publication(_JOB_ID) is None
    assert len(scene_state.resolver.list_uris(f"artifact://jobs/{_JOB_ID}/scene/")) == 2


def test_pending_initial_artifact_is_not_visible_and_legacy_writes_adopt_the_head_first(
    scene_state: SimpleNamespace,
) -> None:
    legacy_editor = SceneEditor(_FIXTURE_ROOT, scene_state.resolver)
    legacy_editor.current(_JOB_ID)
    pending = scene_state.repository.reserve_publication(_JOB_ID, None, "publish_initial", writer_id="initial-writer")
    assert pending.target_scene_revision == "rev-001"

    editor = _head_editor(scene_state)
    with pytest.raises(SceneNotAvailableError, match="not committed"):
        editor.current(_JOB_ID)
    assert editor.artifact_references_for_job(_JOB_ID) == []

    # A legacy scene (artifacts, no DB head) adopts its verified head on first use, then the edit proceeds.
    database = RuntimeDatabase(f"sqlite:///{scene_state.resolver.artifact_root.parent / 'legacy.db'}")
    legacy_repo = SceneHeadRepository(database)
    legacy_runtime_editor = SceneEditor(_FIXTURE_ROOT, scene_state.resolver, legacy_repo)
    result = legacy_runtime_editor.apply(
        _JOB_ID,
        SceneEditCommand(
            expected_scene_revision="rev-001",
            edits=[TransformEdit(object_id="object-rack-001", translation_xyz=(3.0, 2.0, 0.0))],
        ),
    )
    assert result.revision.scene.scene_revision == "rev-002"
    adopted = legacy_repo.get(_JOB_ID)
    assert adopted is not None and adopted.scene_revision == "rev-002"


def test_failed_after_artifact_publish_keeps_orphan_and_never_reuses_its_uri(
    scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    root = editor.current(_JOB_ID).scene

    def fail_before_head_commit(_pending) -> None:  # noqa: ANN001 - injected failure point
        raise RuntimeError("injected failure after immutable upload")

    with monkeypatch.context() as patcher:
        patcher.setattr(editor.head_repository, "mark_published", fail_before_head_commit)
        with pytest.raises(RuntimeError, match="after immutable upload"):
            editor.publish_next(_JOB_ID, "rev-001", root.model_copy(update={"objects": []}), "failed_edit")

    pending = scene_state.repository.get_publication(_JOB_ID)
    assert pending is not None and pending.status == "ABORTED" and pending.target_scene_revision == "rev-002"
    assert scene_state.resolver.locate(scene_artifact_uri(_JOB_ID, "rev-002")) is not None
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-001"
    assert editor.revision(_JOB_ID, "rev-002") is None

    committed = editor.publish_next(_JOB_ID, "rev-001", root.model_copy(update={"objects": []}), "retry_edit")
    assert committed.revision.scene.scene_revision == "rev-003"
    head = scene_state.repository.get(_JOB_ID)
    assert head is not None and head.scene_revision == "rev-003" and head.allocation_sequence == 3


def test_cancelled_writer_is_aborted_without_advancing_the_head(
    scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    root = editor.current(_JOB_ID).scene

    def cancel_before_publish(_reference, _payload) -> None:  # noqa: ANN001 - injected cancellation point
        raise asyncio.CancelledError()

    with monkeypatch.context() as patcher:
        patcher.setattr(editor, "_publish_once", cancel_before_publish)
        with pytest.raises(asyncio.CancelledError):
            editor.publish_next(_JOB_ID, "rev-001", root.model_copy(update={"objects": []}), "cancelled_edit")

    head = scene_state.repository.get(_JOB_ID)
    pending = scene_state.repository.get_publication(_JOB_ID)
    assert head is not None and head.scene_revision == "rev-001"
    assert pending is not None and pending.status == "ABORTED"
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-001"


def test_expired_writer_is_fenced_and_late_artifact_stays_orphaned(scene_state: SimpleNamespace) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    root = editor.current(_JOB_ID).scene
    old = scene_state.repository.reserve_publication(_JOB_ID, "rev-001", "slow_edit", writer_id="slow-worker")
    proposed = with_canonical_checksum(
        root.model_copy(update={"scene_revision": old.target_scene_revision, "objects": []}), "scene_ir_checksum"
    )
    payload = proposed.model_dump_json(indent=2).encode("utf-8") + b"\n"
    reference = editor._reference_for(
        _JOB_ID, old.target_scene_revision, "sha256:" + hashlib.sha256(payload).hexdigest()
    )
    old = scene_state.repository.bind_publication(old, reference)

    expired = _seal_publication(
        old.model_copy(
            update={
                "lease_expires_at": datetime.now(UTC) - timedelta(seconds=1),
                "publication_checksum": "sha256:" + "0" * 64,
            }
        )
    )
    with scene_state.database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_scene_publications SET lease_expires_at=?,payload=? WHERE job_id=?",
            (expired.lease_expires_at.isoformat(), expired.model_dump_json(), _JOB_ID),
        )

    replacement = scene_state.repository.reserve_publication(_JOB_ID, "rev-001", "fast_edit", writer_id="fast-worker")
    assert replacement.target_scene_revision == "rev-003"
    assert replacement.fencing_token != old.fencing_token
    editor._publish_once(reference, payload)  # the old upload may finish after the lease takeover
    with pytest.raises(RuntimeStateConflictError, match="fenced"):
        scene_state.repository.mark_published(old)
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-001"
    assert editor.revision(_JOB_ID, "rev-002") is None

    assert scene_state.repository.abort_publication(replacement)
    following = scene_state.repository.reserve_publication(_JOB_ID, "rev-001", "next_edit", writer_id="next-worker")
    assert following.target_scene_revision == "rev-004"


def test_response_loss_after_database_commit_keeps_exactly_one_winner(
    scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    root = editor.current(_JOB_ID).scene
    commit = editor.head_repository.commit_publication

    def commit_then_lose_response(pending, revision):  # noqa: ANN001 - injected DB response loss
        commit(pending, revision)
        raise RuntimeError("injected response loss after commit")

    with monkeypatch.context() as patcher:
        patcher.setattr(editor.head_repository, "commit_publication", commit_then_lose_response)
        with pytest.raises(RuntimeError, match="after commit"):
            editor.publish_next(_JOB_ID, "rev-001", root.model_copy(update={"objects": []}), "committed_edit")

    head = scene_state.repository.get(_JOB_ID)
    assert head is not None and head.scene_revision == "rev-002" and head.generation == 2
    assert scene_state.repository.get_publication(_JOB_ID) is None
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-002"
    with pytest.raises(SceneRevisionConflictError):
        editor.publish_next(_JOB_ID, "rev-001", root, "duplicate_request")
    assert scene_state.repository.get(_JOB_ID) == head


def test_reservation_retry_is_idempotent_only_for_the_same_live_writer(scene_state: SimpleNamespace) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    writer_id = uuid4().hex
    first = scene_state.repository.reserve_publication(_JOB_ID, "rev-001", "same_action", writer_id=writer_id)
    repeated = scene_state.repository.reserve_publication(_JOB_ID, "rev-001", "same_action", writer_id=writer_id)
    assert repeated == first
    with pytest.raises(RuntimeStateConflictError, match="holds the writer lease"):
        scene_state.repository.reserve_publication(_JOB_ID, "rev-001", "other_action", writer_id=uuid4().hex)


@pytest.mark.skipif(not os.environ.get("R2S_TEST_POSTGRES_URL"), reason="R2S_TEST_POSTGRES_URL is not configured")
def test_postgres_initial_reservation_has_one_winner() -> None:
    database_url = os.environ["R2S_TEST_POSTGRES_URL"]
    database = RuntimeDatabase(database_url)
    repository = SceneHeadRepository(database)
    job_id = f"scene-cas-{uuid4().hex}"

    def reserve(writer_id: str) -> str:
        try:
            repository.reserve_publication(job_id, None, "publish_initial", writer_id=writer_id)
            return "reserved"
        except RuntimeStateConflictError:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, ["writer-a", "writer-b"]))
        assert sorted(outcomes) == ["conflict", "reserved"]
        pending = repository.get_publication(job_id)
        assert pending is not None and pending.expected_generation == 1 and pending.target_scene_revision == "rev-001"
    finally:
        with database.transaction(write=True) as tx:
            tx.execute("DELETE FROM r2s_scene_publications WHERE job_id=?", (job_id,))


def test_walking_every_ancestor_loads_each_revision_once_and_follows_a_moving_head(
    scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ownership recovery asks revision() for each ancestor in turn; that must stay linear, not quadratic."""
    editor = _head_editor(scene_state)
    _publish_root(editor)
    current = "rev-001"
    for index in range(12):
        current = _edit(editor, current, float(index))
    lineage_loads: list[str] = []
    original = editor._load_revision

    def counting(job_id: str, revision: str, *, fresh: bool = False):  # noqa: ANN202
        if fresh:
            lineage_loads.append(revision)
        return original(job_id, revision, fresh=fresh)

    monkeypatch.setattr(editor, "_load_revision", counting)

    walked = []
    revision: str | None = current
    while revision is not None:
        record = editor.revision(_JOB_ID, revision)
        assert record is not None
        walked.append(revision)
        revision = record.supersedes_revision

    assert len(walked) == 13 and len(lineage_loads) == 13 and len(set(lineage_loads)) == 13

    newest = _edit(editor, current, 99.0)
    lineage_loads.clear()
    assert editor.revision(_JOB_ID, "rev-001") is not None
    assert editor.revision(_JOB_ID, newest) is not None
    assert len(lineage_loads) == 14


def test_legacy_scene_without_head_is_adopted_on_first_read_with_the_same_checks_as_the_script(
    scene_state: SimpleNamespace,
) -> None:
    legacy = SceneEditor(_FIXTURE_ROOT, scene_state.resolver)
    legacy.current(_JOB_ID)
    newest = _edit(legacy, "rev-001", 1.0)
    database = RuntimeDatabase(f"sqlite:///{scene_state.resolver.artifact_root.parent / 'no-head.db'}")
    repository = SceneHeadRepository(database)
    editor = SceneEditor(_FIXTURE_ROOT, scene_state.resolver, repository)

    assert editor.current(_JOB_ID).scene.scene_revision == newest
    head = repository.get(_JOB_ID)
    repair = repository.get_repair(_JOB_ID)
    assert head is not None and head.scene_revision == newest
    # Đi qua đúng hai lượt kiểm của repair, không phải ghi tắt một head.
    assert repair is not None and repair.status == "COMPLETE" and repair.rechecked_count == 2
    # Lần đọc sau dùng head đã commit, không chạy lại.
    assert editor.current(_JOB_ID).scene.scene_revision == newest


def test_legacy_scene_with_invalid_artifacts_stays_blocked_with_a_user_safe_message(
    scene_state: SimpleNamespace,
) -> None:
    SceneEditor(_FIXTURE_ROOT, scene_state.resolver).current(_JOB_ID)
    path = scene_state.resolver.resolve(scene_artifact_uri(_JOB_ID, "rev-001"))
    path.write_bytes(path.read_bytes().replace(b"object-rack-001", b"object-rack-999"))
    database = RuntimeDatabase(f"sqlite:///{scene_state.resolver.artifact_root.parent / 'blocked.db'}")
    repository = SceneHeadRepository(database)
    editor = SceneEditor(_FIXTURE_ROOT, scene_state.resolver, repository)

    for _ in range(2):  # lần hai đọc bản ghi repair BLOCKED, không thử nhận lại
        with pytest.raises(SceneHeadNotReadyError) as info:
            editor.current(_JOB_ID)
        # Chi tiết vận hành chỉ nằm trong log/exception; câu gửi cho UI không chứa tên script.
        assert "scene_head" not in info.value.user_message
        assert info.value.user_message.startswith("Dữ liệu scene này không qua được bước kiểm tra")
    assert repository.get(_JOB_ID) is None
    assert repository.get_repair(_JOB_ID).status == "BLOCKED"


# ── T-053: the committed head revision is parsed once per checksum ───────────


def test_current_scene_parses_once_per_head(scene_state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.scene import editor as editor_module

    editor = _head_editor(scene_state)
    _publish_root(editor)
    parses: list[int] = []
    real = editor_module.SceneIR.model_validate_json
    monkeypatch.setattr(editor_module.SceneIR, "model_validate_json", lambda data: parses.append(1) or real(data))
    first = editor.current(_JOB_ID)
    second = editor.current(_JOB_ID)
    assert first.scene.scene_revision == second.scene.scene_revision == "rev-001"
    assert len(parses) <= 1


def test_new_head_is_loaded(scene_state: SimpleNamespace) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    editor.current(_JOB_ID)
    _edit(editor, "rev-001", 1.0)
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-002"


def test_tampered_head_scene_file_is_rejected(scene_state: SimpleNamespace) -> None:
    editor = _head_editor(scene_state)
    _publish_root(editor)
    editor.current(_JOB_ID)
    path = scene_state.resolver.resolve(scene_artifact_uri(_JOB_ID, "rev-001"))
    os.chmod(path, 0o644)
    path.write_text(path.read_text(encoding="utf-8").replace("object-rack-001", "object-rack-999"), encoding="utf-8")
    from src.services.orchestration.scene.errors import SceneEditRejectedError

    with pytest.raises(SceneEditRejectedError):
        editor.current(_JOB_ID)
