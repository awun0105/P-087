"""Verified, resumable SceneIR head recovery for legacy artifact histories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.studio import scene_head as scene_head_cli
from src.config import Settings
from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver, InvalidArtifactUriError
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.scene.editor import SceneEditor, scene_artifact_uri
from src.services.orchestration.scene.heads import (
    SceneHeadBackfill,
    SceneHeadBackfillError,
    SceneHeadRepository,
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


def test_backfill_handles_more_than_one_thousand_numeric_revisions(scene_state: SimpleNamespace) -> None:
    scene_state.editor.current(_JOB_ID)
    revision = "rev-001"
    for number in range(2, 1006):
        revision = _edit(scene_state.editor, revision, float(number))
    assert revision == "rev-1005"

    result = _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=250)
    calls = 1
    while result.status != "COMPLETE":
        result = _new_backfill(scene_state).backfill_page(_JOB_ID, page_size=250)
        calls += 1
        assert calls < 20

    assert result.head is not None
    assert result.head.scene_revision == "rev-1005"
    assert result.head.allocation_sequence == 1005
    assert result.verified_count == 1005


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
