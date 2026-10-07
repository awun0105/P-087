"""Contract and safety proof for the portable Studio data package."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from scripts.studio import data_package


def _checksum(path: Path) -> str:
    """Return the public checksum spelling used by artifact contracts."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    """Write deterministic fixture JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _create_schema(connection: sqlite3.Connection) -> None:
    """Create the smallest SQLite state needed by the packer's gates."""
    connection.executescript(
        """
        CREATE TABLE r2s_users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE r2s_projects (project_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_uploads (upload_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_jobs (job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, manifest_ref TEXT NOT NULL);
        CREATE TABLE r2s_job_events (job_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE r2s_imports (import_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_sessions (token_hash TEXT, user_id TEXT, payload TEXT NOT NULL);
        CREATE TABLE r2s_invites (code_hash TEXT, payload TEXT NOT NULL);
        CREATE TABLE r2s_workers (worker_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_resource_reservations (reservation_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_resource_waits (wait_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_upload_sessions (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE r2s_scene_requests (job_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE r2s_scene_heads (
            job_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
            allocation_sequence INTEGER NOT NULL, head_checksum TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE r2s_scene_head_repairs (
            job_id TEXT PRIMARY KEY, status TEXT NOT NULL, generation INTEGER NOT NULL,
            repair_checksum TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE r2s_scene_head_backfill_items (
            job_id TEXT NOT NULL, scene_revision TEXT NOT NULL, item_checksum TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(job_id, scene_revision)
        );
        CREATE TABLE r2s_scene_publications (
            job_id TEXT PRIMARY KEY, expected_generation INTEGER NOT NULL, target_revision TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE r2s_validation_runs (
            run_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, candidate_checksum TEXT NOT NULL,
            config_checksum TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,
            run_checksum TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE r2s_validation_selections (
            job_id TEXT NOT NULL, candidate_checksum TEXT NOT NULL, config_checksum TEXT NOT NULL,
            run_id TEXT NOT NULL, report_checksum TEXT NOT NULL, generation INTEGER NOT NULL,
            selection_checksum TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(job_id, candidate_checksum, config_checksum)
        );
        CREATE TABLE r2s_audit_log (entry_id TEXT PRIMARY KEY, user_id TEXT, action TEXT, payload TEXT NOT NULL);
        CREATE TABLE r2s_trash (trash_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """
    )


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    """Build a small, checksum-linked Studio state in a temporary checkout."""
    root = tmp_path / "source"
    state = root / "data/studio_local"
    artifacts = state / "artifacts/jobs/job-a/manifests"
    artifacts.mkdir(parents=True)

    input_file = artifacts / "input.json"
    input_file.write_text('{"kind":"input"}\n', encoding="utf-8")
    geometry = artifacts / "geometry.glb"
    geometry.write_bytes(b"fixture-glb")
    input_uri = "artifact://jobs/job-a/manifests/input.json"
    geometry_uri = "artifact://jobs/job-a/manifests/geometry.glb"
    geometry_checksum = _checksum(geometry)
    manifest = artifacts / "job_manifest.json"
    _write_json(
        manifest,
        {
            "stage_artifacts": [
                {
                    "stage_id": "ST-RGB-GEOMETRY",
                    "artifact_uri": geometry_uri,
                    "artifact_checksum": geometry_checksum,
                }
            ],
            "input_file": {"artifact_uri": input_uri, "checksum": _checksum(input_file)},
        },
    )
    manifest_uri = "artifact://jobs/job-a/manifests/job_manifest.json"
    manifest_checksum = _checksum(manifest)

    _write_json(state / "thumbnail_cache/thumb.json", {"thumbnail": True})
    _write_json(root / "data/demo/library/demo.json", {"name": "demo"})
    (root / "data/asset_previews").mkdir(parents=True)
    (root / "data/asset_previews/preview.png").write_bytes(b"png")
    (root / "data/rerun_recordings").mkdir(parents=True)
    (root / "data/rerun_recordings/run.jsonl").write_text('{"stage":"done"}\n', encoding="utf-8")
    _write_json(state / "runtime_manifest.json", {"host": "/private/machine"})
    _write_json(root / "data/qa/should-not-ship.json", {"qa": True})
    (state / "backups").mkdir()
    (state / "backups/old.db").write_bytes(b"old")

    database_path = state / "runtime.db"
    connection = sqlite3.connect(database_path)
    _create_schema(connection)
    user = {
        "user_id": "user-a",
        "email": "teammate@example.invalid",
        "display_name": "Fixture Operator",
        "role": "editor",
        "password_hash": "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
        "active": True,
    }
    second_user = {
        "user_id": "user-b",
        "email": "reviewer@example.invalid",
        "display_name": "Fixture Reviewer",
        "role": "reviewer",
        "password_hash": "scrypt$16384$8$1$CCCCCCCCCCCCCCCCCCCCCC==$DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=",
        "active": True,
    }
    project = {
        "project_id": "project-a",
        "input_manifest": {"artifact_uri": input_uri, "artifact_checksum": _checksum(input_file)},
    }
    manifest_ref = {"artifact_uri": manifest_uri, "artifact_checksum": manifest_checksum}
    connection.executemany(
        "INSERT INTO r2s_users(user_id,email,payload) VALUES (?,?,?)",
        [(record["user_id"], record["email"], json.dumps(record)) for record in (user, second_user)],
    )
    connection.execute("INSERT INTO r2s_projects(project_id,payload) VALUES (?,?)", ("project-a", json.dumps(project)))
    connection.execute(
        "INSERT INTO r2s_uploads(upload_id,payload) VALUES (?,?)",
        ("upload-a", json.dumps({"artifact_uri": input_uri, "checksum": _checksum(input_file)})),
    )
    connection.execute(
        "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?)",
        ("job-a", "project-a", 1, json.dumps(manifest_ref)),
    )
    connection.execute(
        "INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)",
        ("job-a", 1, json.dumps({"status": "SUCCEEDED", "current_stage": "ST-RGB-GEOMETRY"})),
    )
    connection.execute(
        "INSERT INTO r2s_imports(import_id,payload) VALUES (?,?)", ("import-a", json.dumps({"status": "READY"}))
    )
    connection.execute(
        "INSERT INTO r2s_sessions(token_hash,user_id,payload) VALUES (?,?,?)",
        ("known-session-token", "user-a", json.dumps({"token": "known-session-token"})),
    )
    connection.execute(
        "INSERT INTO r2s_invites(code_hash,payload) VALUES (?,?)",
        ("known-invite-code", json.dumps({"code": "known-invite-code"})),
    )
    connection.execute(
        "INSERT INTO r2s_workers(worker_id,payload) VALUES (?,?)", ("worker-a", json.dumps({"token": "worker-secret"}))
    )
    connection.execute(
        "INSERT INTO r2s_scene_requests(job_id,status,payload) VALUES (?,?,?)", ("job-a", "done", json.dumps({}))
    )
    connection.execute(
        "INSERT INTO r2s_audit_log(entry_id,user_id,action,payload) VALUES (?,?,?,?)",
        ("audit-a", "user-a", "project.created", json.dumps({"actor": "user-a"})),
    )
    connection.commit()
    connection.close()
    return root


def test_pack_verify_and_scrub_preserves_actor_metadata(source_tree: Path, tmp_path: Path) -> None:
    """Package verification keeps UI state while removing reusable credentials."""
    archive = data_package.pack(source_tree, tmp_path / "studio-data.zip")
    summary = data_package.verify(archive)

    assert summary.project_count == 1
    assert summary.artifact_reference_count == 3
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        assert "DATA_PACKAGE.json" in names
        assert "data/studio_local/runtime_manifest.json" not in names
        assert "data/qa/should-not-ship.json" not in names
        raw_database = package.read("data/studio_local/runtime.db")
        assert b"scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==" not in raw_database
        assert b"known-session-token" not in raw_database
        assert b"known-invite-code" not in raw_database
        extracted = tmp_path / "snapshot.db"
        extracted.write_bytes(raw_database)

    connection = sqlite3.connect(extracted)
    try:
        row = connection.execute("SELECT email,payload FROM r2s_users").fetchone()
        assert row[0] == "teammate@example.invalid"
        user = json.loads(row[1])
        assert user["display_name"] == "Fixture Operator"
        assert user["password_hash"] == data_package.PASSWORD_SENTINEL
        assert user["active"] is False
        assert connection.execute("SELECT COUNT(*) FROM r2s_sessions").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM r2s_invites").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM r2s_audit_log").fetchone() == (1,)
    finally:
        connection.close()


def test_pack_allows_empty_trash_table(source_tree: Path, tmp_path: Path) -> None:
    """An empty trash table is a valid clean source state."""
    archive = data_package.pack(source_tree, tmp_path / "empty-trash.zip")
    data_package.verify(archive)


def test_pack_rejects_nonempty_trash_table(source_tree: Path, tmp_path: Path) -> None:
    """Packing never discards recoverable trashed records."""
    database = source_tree / "data/studio_local/runtime.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO r2s_trash(trash_id,payload) VALUES (?,?)",
        ("trash-a", json.dumps({"artifact_uri": "artifact://jobs/job-a/manifests/geometry.glb"})),
    )
    connection.commit()
    connection.close()

    output = tmp_path / "trash.zip"
    with pytest.raises(data_package.PackageError, match="r2s_trash"):
        data_package.pack(source_tree, output)
    assert not output.exists()
    assert not Path(str(output) + ".partial").exists()


def test_pack_preserves_scene_head_state_and_rejects_pending_publication(source_tree: Path, tmp_path: Path) -> None:
    """Stable verified head/backfill rows survive; pending publication blocks handoff."""
    database = source_tree / "data/studio_local/runtime.db"
    expected = {
        "r2s_scene_heads": [("job-a", 2, 7, "sha256:" + "a" * 64, '{"scene_revision":"rev-007"}')],
        "r2s_scene_head_repairs": [("job-a", "COMPLETE", 9, "sha256:" + "b" * 64, '{"verified_count":7}')],
        "r2s_scene_head_backfill_items": [
            ("job-a", "rev-007", "sha256:" + "c" * 64, '{"supersedes_revision":"rev-006"}')
        ],
    }
    connection = sqlite3.connect(database)
    try:
        for table, rows in expected.items():
            columns = {
                "r2s_scene_heads": "job_id,generation,allocation_sequence,head_checksum,payload",
                "r2s_scene_head_repairs": "job_id,status,generation,repair_checksum,payload",
                "r2s_scene_head_backfill_items": "job_id,scene_revision,item_checksum,payload",
            }[table]
            placeholders = ",".join("?" for _ in rows[0])
            connection.execute(f"INSERT INTO {table}({columns}) VALUES ({placeholders})", rows[0])
        connection.commit()
    finally:
        connection.close()

    archive = data_package.pack(source_tree, tmp_path / "scene-head-state.zip")
    with zipfile.ZipFile(archive) as package:
        restored_db = tmp_path / "scene-head-snapshot.db"
        restored_db.write_bytes(package.read(data_package.RUNTIME_DB_MEMBER))
    restored = sqlite3.connect(restored_db)
    try:
        for table, rows in expected.items():
            assert restored.execute(f"SELECT * FROM {table}").fetchall() == rows
    finally:
        restored.close()

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO r2s_scene_publications(job_id,expected_generation,target_revision,lease_expires_at,payload) "
            "VALUES (?,?,?,?,?)",
            ("job-a", 2, "rev-008", "2026-10-08T00:00:00+00:00", "{}"),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(data_package.PackageError, match="scene publication"):
        data_package.pack(source_tree, tmp_path / "pending-scene-publication.zip")


def test_verify_rejects_nonempty_trash_table(source_tree: Path, tmp_path: Path) -> None:
    """Verification rejects an archive carrying recoverable trash state."""
    original = data_package.pack(source_tree, tmp_path / "clean.zip")
    database = tmp_path / "mutated-runtime.db"
    with zipfile.ZipFile(original) as source:
        payloads = {info.filename: source.read(info) for info in source.infolist()}
        infos = source.infolist()
    database.write_bytes(payloads[data_package.RUNTIME_DB_MEMBER])
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO r2s_trash(trash_id,payload) VALUES (?,?)",
        ("trash-a", json.dumps({"reason": "restore-me"})),
    )
    connection.commit()
    connection.close()
    payloads[data_package.RUNTIME_DB_MEMBER] = database.read_bytes()

    manifest = json.loads(payloads[data_package.MANIFEST_NAME])
    for record in manifest["files"]:
        if record["path"] == data_package.RUNTIME_DB_MEMBER:
            record["size"] = len(payloads[data_package.RUNTIME_DB_MEMBER])
            record["sha256"] = hashlib.sha256(payloads[data_package.RUNTIME_DB_MEMBER]).hexdigest()
    manifest["total_bytes"] = sum(record["size"] for record in manifest["files"])
    payloads[data_package.MANIFEST_NAME] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    mutated = tmp_path / "trash-archive.zip"
    with zipfile.ZipFile(mutated, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in infos:
            target.writestr(info, payloads[info.filename])

    with pytest.raises(data_package.PackageError, match="r2s_trash"):
        data_package.verify(mutated)


def test_pack_keep_seed_accounts_preserves_only_selected_passwords(source_tree: Path, tmp_path: Path) -> None:
    """Seed convenience mode keeps exactly two hashes and still removes sessions."""
    archive = data_package.pack(source_tree, tmp_path / "seed-data.zip", keep_seed_accounts=True)
    summary = data_package.verify(archive, expect_seed_accounts=True)
    assert summary.project_count == 1

    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(package.read("DATA_PACKAGE.json"))
        assert manifest["account_policy"] == {
            "mode": data_package.ACCOUNT_MODE_SEED,
            "kept_user_ids": ["user-a", "user-b"],
        }
        raw_database = package.read("data/studio_local/runtime.db")
        assert b"scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==" in raw_database
        assert b"scrypt$16384$8$1$CCCCCCCCCCCCCCCCCCCCCC==" in raw_database
        assert b"known-session-token" not in raw_database
        extracted = tmp_path / "seed-snapshot.db"
        extracted.write_bytes(raw_database)

    connection = sqlite3.connect(extracted)
    try:
        rows = connection.execute("SELECT user_id,payload FROM r2s_users ORDER BY user_id").fetchall()
        assert [row[0] for row in rows] == ["user-a", "user-b"]
        for _, payload in rows:
            record = json.loads(payload)
            assert record["password_hash"] != data_package.PASSWORD_SENTINEL
            assert record["active"] is True
        assert connection.execute("SELECT COUNT(*) FROM r2s_sessions").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM r2s_invites").fetchone() == (0,)
    finally:
        connection.close()


def test_pack_keep_user_id_requires_exactly_two_accounts(source_tree: Path, tmp_path: Path) -> None:
    """Explicit preservation cannot accidentally expand to an arbitrary account set."""
    with pytest.raises(data_package.PackageError, match="đúng hai"):
        data_package.pack(source_tree, tmp_path / "one-seed.zip", keep_user_ids=("user-a",))
    with pytest.raises(data_package.PackageError, match="seed account"):
        data_package.pack(source_tree, tmp_path / "unknown-seeds.zip", keep_user_ids=("user-a", "missing"))


def test_pack_keep_user_id_round_trip_policy(source_tree: Path, tmp_path: Path) -> None:
    """The repeatable explicit CLI policy is persisted and checked by verify."""
    archive = data_package.pack(source_tree, tmp_path / "explicit-seeds.zip", keep_user_ids=("user-a", "user-b"))
    data_package.verify(archive, expected_user_ids=("user-a", "user-b"))


def test_pack_rejects_missing_or_wrong_artifact_checksum(source_tree: Path, tmp_path: Path) -> None:
    """A linked artifact must exist and match every published checksum pair."""
    database = source_tree / "data/studio_local/runtime.db"
    connection = sqlite3.connect(database)
    project = {"project_id": "project-a", "input_manifest": {"artifact_uri": "artifact://jobs/job-a/missing.json"}}
    connection.execute("UPDATE r2s_projects SET payload=? WHERE project_id=?", (json.dumps(project), "project-a"))
    connection.commit()
    connection.close()

    output = tmp_path / "missing.zip"
    with pytest.raises(data_package.PackageError, match="Artifact reference"):
        data_package.pack(source_tree, output)
    assert not output.exists()
    assert not Path(str(output) + ".partial").exists()


def test_pack_allows_human_metric_wait_but_rejects_other_running_work(source_tree: Path, tmp_path: Path) -> None:
    """The intentional metric confirmation state is the only running exception."""
    database = source_tree / "data/studio_local/runtime.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE r2s_job_events SET payload=? WHERE job_id=?",
        (json.dumps({"status": "RUNNING", "current_stage": data_package.METRIC_STAGE}), "job-a"),
    )
    connection.commit()
    connection.close()
    data_package.pack(source_tree, tmp_path / "metric-wait.zip")

    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE r2s_job_events SET payload=? WHERE job_id=?",
        (json.dumps({"status": "RUNNING", "current_stage": "ST-RGB-GEOMETRY"}), "job-a"),
    )
    connection.commit()
    connection.close()
    with pytest.raises(data_package.PackageError, match="job"):
        data_package.pack(source_tree, tmp_path / "running.zip")


def test_pack_rejects_queued_or_running_validation_attempt(source_tree: Path, tmp_path: Path) -> None:
    """Mutable validation evidence cannot be snapshotted and resumed as if idle."""
    database = source_tree / "data/studio_local/runtime.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO r2s_validation_runs
               (run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                "run-active",
                "job-a",
                "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
                1,
                "RUNNING",
                "sha256:" + "c" * 64,
                "{}",
            ),
        )
    with pytest.raises(data_package.PackageError, match="validation run"):
        data_package.pack(source_tree, tmp_path / "active-validation.zip")


def test_pack_rejects_verifying_upload_session(source_tree: Path, tmp_path: Path) -> None:
    """VERIFYING is still mutable upload work and cannot enter a snapshot."""
    database = source_tree / "data/studio_local/runtime.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO r2s_upload_sessions(session_id,payload) VALUES (?,?)",
        ("upload-session-a", json.dumps({"status": "VERIFYING"})),
    )
    connection.commit()
    connection.close()
    with pytest.raises(data_package.PackageError, match="upload session"):
        data_package.pack(source_tree, tmp_path / "verifying.zip")


def test_pack_detects_database_edit_after_snapshot(
    source_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logical DB fingerprint catches a committed edit even if file metadata is restored."""
    database = source_tree / "data/studio_local/runtime.db"
    original_write = data_package._write_stream
    changed = False

    def write_then_edit(archive: zipfile.ZipFile, source: Path, member: str) -> data_package.FileRecord:
        nonlocal changed
        record = original_write(archive, source, member)
        if member != "data/studio_local/runtime.db" and not changed:
            before = database.stat()
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE r2s_projects SET payload=? WHERE project_id=?",
                (json.dumps({"project_id": "project-a", "label": "changed-after-snapshot"}), "project-a"),
            )
            connection.commit()
            connection.close()
            # Keep lstat metadata stable; the row fingerprint still changes.
            os.utime(database, ns=(before.st_atime_ns, before.st_mtime_ns))
            changed = True
        return record

    monkeypatch.setattr(data_package, "_write_stream", write_then_edit)
    output = tmp_path / "changed.zip"
    with pytest.raises(data_package.PackageError, match="SQLite product state"):
        data_package.pack(source_tree, output)
    assert not output.exists()
    assert not Path(str(output) + ".partial").exists()


def test_pack_allows_worker_lease_wal_checkpoint_mutation(
    source_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker lease/WAL metadata may change while product rows stay stable."""
    database = source_tree / "data/studio_local/runtime.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.commit()
    connection.close()

    original_write = data_package._write_stream
    changed = False

    def write_then_renew_worker(archive: zipfile.ZipFile, source: Path, member: str) -> data_package.FileRecord:
        nonlocal changed
        record = original_write(archive, source, member)
        if member != data_package.RUNTIME_DB_MEMBER and not changed:
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE r2s_workers SET payload=? WHERE worker_id=?",
                (json.dumps({"lease_id": "renewed"}), "worker-a"),
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.close()
            changed = True
        return record

    monkeypatch.setattr(data_package, "_write_stream", write_then_renew_worker)
    archive = data_package.pack(source_tree, tmp_path / "worker-lease.zip")
    assert changed
    data_package.verify(archive)


def test_pack_rejects_runtime_database_replacement(
    source_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-content replacement is rejected by runtime.db file identity."""
    database = source_tree / "data/studio_local/runtime.db"
    original_write = data_package._write_stream
    replaced = False

    def write_then_replace_database(archive: zipfile.ZipFile, source: Path, member: str) -> data_package.FileRecord:
        nonlocal replaced
        record = original_write(archive, source, member)
        if member != data_package.RUNTIME_DB_MEMBER and not replaced:
            replacement = database.with_name("runtime.db.replacement")
            replacement.write_bytes(database.read_bytes())
            os.replace(replacement, database)
            replaced = True
        return record

    monkeypatch.setattr(data_package, "_write_stream", write_then_replace_database)
    output = tmp_path / "replaced-db.zip"
    with pytest.raises(data_package.PackageError, match="runtime.db bị thay thế"):
        data_package.pack(source_tree, output)
    assert replaced
    assert not output.exists()
    assert not Path(str(output) + ".partial").exists()


def test_pack_supports_stored_compression(source_tree: Path, tmp_path: Path) -> None:
    """Already-compressed geometry can use a fast uncompressed ZIP stream."""
    archive = data_package.pack(source_tree, tmp_path / "stored.zip", compression="stored")
    data_package.verify(archive)
    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(package.read(data_package.MANIFEST_NAME))
        assert manifest["compression"] == "stored"
        assert all(info.compress_type == zipfile.ZIP_STORED for info in package.infolist())


def test_pack_rejects_embedded_metadata_secret(source_tree: Path, tmp_path: Path) -> None:
    """Credential-like JSON fields fail closed instead of being rewritten."""
    secret_file = source_tree / "data/demo/library/secret.json"
    _write_json(secret_file, {"api_key": "must-not-ship"})
    with pytest.raises(data_package.PackageError, match="credential"):
        data_package.pack(source_tree, tmp_path / "secret.zip")


def test_verify_rejects_tampered_payload(source_tree: Path, tmp_path: Path) -> None:
    """Checksum inventory protects verification and restore from byte tampering."""
    original = data_package.pack(source_tree, tmp_path / "original.zip")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename.endswith("geometry.glb"):
                payload = b"tampered"
            target.writestr(info, payload)
    with pytest.raises(data_package.PackageError, match="không khớp"):
        data_package.verify(tampered)


def test_unpack_requires_force_and_keeps_backup(source_tree: Path, tmp_path: Path) -> None:
    """Restore refuses collisions and force mode retains a recoverable backup."""
    archive = data_package.pack(source_tree, tmp_path / "source.zip")
    destination = tmp_path / "destination"
    old_artifacts = destination / "data/studio_local/artifacts"
    old_artifacts.mkdir(parents=True)
    (old_artifacts / "old.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(data_package.PackageError, match="force"):
        data_package.unpack(destination, archive)

    data_package.unpack(destination, archive, force=True)
    backups = list(
        (destination / "data/studio_local/backups").glob("before-unpack-*/data/studio_local/artifacts/old.txt")
    )
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "keep"
    assert (
        destination / "data/studio_local/artifacts/jobs/job-a/manifests/geometry.glb"
    ).read_bytes() == b"fixture-glb"
    assert (destination / "data/studio_local/DATA_PACKAGE.json").is_file()


def test_unpack_rejects_symlink_ancestor_before_writing(source_tree: Path, tmp_path: Path) -> None:
    """A data symlink cannot redirect restore into an unrelated directory."""
    archive = data_package.pack(source_tree, tmp_path / "source.zip")
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    outside.mkdir()
    destination.mkdir()
    (destination / "data").symlink_to(outside, target_is_directory=True)

    with pytest.raises(data_package.PackageError, match="symlink"):
        data_package.unpack(destination, archive, force=True)
    assert not (outside / "studio_local").exists()
