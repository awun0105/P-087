# Demo Sample Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One source of truth for the public demo library: a database catalog plus the object store; the API disk is only a cache that the API repairs at startup instead of refusing to start.

**Architecture:** A new `r2s_demo_samples` table records every sample a Reviewer published (state `published`/`unpublished`, file inventory with checksums). Publishing from Studio uploads the bundle to the object store under `PRODUCT_DEMO_OBJECT_PREFIX/<sample_id>/…` before the catalog row is written. Startup seeds the catalog once from the pinned archive or from bundles already on disk, then verifies every published sample on disk and re-downloads what is missing or changed. Listing, serving and demo sessions consult the catalog, never on-disk markers.

**Tech Stack:** Python 3.12, FastAPI, RuntimeDatabase (SQLite/PostgreSQL), `ObjectStore` protocol (S3/R2 or `MemoryObjectStore` in tests), pytest.

**Spec:** The decision recorded in this conversation on 2026-10-24: "một nguồn sự thật duy nhất là kho R2 cộng cơ sở dữ liệu, đĩa chỉ là bộ đệm".

## Global Constraints

- Object keys for a sample are `"{PRODUCT_DEMO_OBJECT_PREFIX}/{sample_id}/{relative path inside the bundle}"`, the same layout `publish_library` already writes and `session_settings` already reads.
- Files whose name (any path part) starts with `.` are never catalogued or uploaded.
- Objects are immutable: an existing object with a different checksum is an error, same checksum is a no-op.
- Startup never raises because disk content differs from the catalog; it logs and repairs. It raises only when `PRODUCT_DEMO_REQUIRED=true` and no published sample is healthy.
- The `.unpublished` marker and the `r2s_demo_unpublished` table are no longer read or written by application code (the table stays for the one-time import).
- User-facing API shapes (`/samples`, `/jobs/{id}/demo`) do not change.
- Commit after each task; no Claude attribution in commit messages.

## Review Focus

1. A published sample whose directory someone deleted on the VM: startup re-downloads it from the store and the sample still lists. Test in Task 3.
2. A sample published from Studio when no object store is configured (local SQLite dev): it still lists and serves from disk. Test in Task 4.
3. Unpublish then publish the same unchanged job again: the old row flips back to `published`; no second copy. Test in Task 4.
4. A sample in the catalog that neither disk nor store can provide: startup logs it, skips it, the rest serve. Test in Task 3.
5. First boot on production after this change: catalog empty, library on disk from the pinned archive, every file already in the store: import must not re-upload or fail on "already exists". Test in Task 3.

---

### Task 1: Catalog table and record access

**Files:**
- Modify: `src/services/orchestration/jobs/database.py` (append migration 28)
- Create: `src/services/orchestration/samples/catalog.py`
- Test: `tests/test_orchestration/test_demo_catalog.py`

**Interfaces:**
- Produces:
  - `class SampleFile(BaseModel)`: `path: str`, `size_bytes: int`, `checksum: str`.
  - `class SampleRecord(BaseModel)`: `sample_id: str`, `state: Literal["published","unpublished"]`, `job_id: str | None`, `manifest_checksum: str`, `files: list[SampleFile]`, `published_by: str | None`, `published_at: datetime`, `updated_at: datetime`.
  - `class DemoCatalog`: `__init__(self, database: RuntimeDatabase)`; `get(sample_id) -> SampleRecord | None`; `records(state: str | None = None) -> list[SampleRecord]`; `published_ids() -> set[str]`; `is_published(sample_id) -> bool`; `by_job(job_id, *, state="published") -> SampleRecord | None`; `save(record) -> None` (upsert); `set_state(sample_id, state) -> SampleRecord` raising `DemoUnavailableError` when the row is absent.
  - `inventory(root: Path) -> list[SampleFile]`: every regular file under `root`, posix relative paths, skipping dot-prefixed parts, sorted; symlink → `ValueError`.

- [ ] **Step 1: Write failing tests** `test_save_get_and_state_roundtrip`, `test_by_job_only_returns_published_rows`, `test_inventory_skips_dotfiles_and_refuses_symlinks` using `RuntimeDatabase(f"sqlite:///{tmp_path/'runtime.db'}")`.
- [ ] **Step 2: Run** `pytest tests/test_orchestration/test_demo_catalog.py -v` → fail on import.
- [ ] **Step 3: Implement** migration 28:
  ```sql
  CREATE TABLE r2s_demo_samples (sample_id TEXT PRIMARY KEY, state TEXT NOT NULL, job_id TEXT,
    manifest_checksum TEXT NOT NULL, published_by TEXT, published_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, payload TEXT NOT NULL)
  CREATE INDEX r2s_demo_samples_by_job ON r2s_demo_samples(job_id, state)
  ```
  `payload` holds `{"files": [...]}`. Implement `catalog.py` per the interface.
- [ ] **Step 4: Run** the test file → pass. Also `pytest tests/test_orchestration/test_runtime_database*.py -q` (schema version assertions).
- [ ] **Step 5: Commit** `feat(demo): catalog table and record access for published samples`.

### Task 2: Register a bundle (inventory, upload, catalog row)

**Files:**
- Modify: `src/services/orchestration/samples/catalog.py`
- Test: `tests/test_orchestration/test_demo_catalog.py`

**Interfaces:**
- Produces:
  - `object_key(prefix: str, sample_id: str, relative: str) -> str`.
  - `upload_bundle(store: ObjectStore, prefix: str, sample_id: str, root: Path, files: list[SampleFile]) -> int` returns objects uploaded; existing object with other checksum → `ValueError("Immutable demo object already exists with different bytes")`; 4 worker threads like `publish_member`.
  - `register_bundle(settings: Settings, catalog: DemoCatalog, root: Path, *, actor: str | None, state: str = "published", job_id: str | None = None) -> SampleRecord`: reads `manifest.json` for `demo_id` (must equal `root.name`) and `provenance.job_id` when `job_id` is None, builds inventory, uploads when `artifact_remote(settings)` is not None, then `catalog.save`.

- [ ] **Step 1: Tests** `test_register_bundle_uploads_every_file_once_and_saves_the_row` (MemoryObjectStore via monkeypatching `catalog.artifact_remote`), `test_register_bundle_without_store_only_writes_the_row`, `test_register_bundle_refuses_an_object_with_other_bytes`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(demo): register a bundle in the catalog and object store`.

### Task 3: Startup: seed, import, verify and repair

**Files:**
- Modify: `src/services/orchestration/samples/catalog.py`
- Modify: `src/main.py:22-40` (`lifespan`)
- Modify: `scripts/demo/release.py` (add `import` command; `bootstrap` calls `prepare_library`)
- Test: `tests/test_orchestration/test_demo_catalog.py`

**Interfaces:**
- Produces:
  - `import_library(settings, catalog, *, actor="import") -> list[str]`: for each child dir of `settings.product_demo_dir` with `manifest.json` and no catalog row → `register_bundle`; state is `unpublished` when `<dir>/.unpublished` exists or `r2s_demo_unpublished` has the id (table may not exist in fresh DBs: catch and treat as empty). Returns registered ids.
  - `sync_library(settings, catalog) -> SyncReport` where `SyncReport(BaseModel)`: `verified: list[str]`, `repaired: list[str]`, `broken: list[str]`. For each published record: each file missing, symlinked or checksum-mismatched is fetched from `object_key(...)` into a temp file beside it and renamed over; no store or object missing → sample goes to `broken` (logged `warning`), no exception.
  - `prepare_library(settings, database: RuntimeDatabase) -> SyncReport`: if `product_demo_archive_key` is set and the catalog has no rows and the library dir has no bundle → call existing `release.bootstrap_library(settings)`; then `import_library`; then `sync_library`; raise `RuntimeError("Demo library is required but no published sample is usable")` only when `product_demo_required` and `verified + repaired` is empty.
- `lifespan` replaces `bootstrap_library` + the `product_demo_required` block with `await run_in_threadpool(prepare_library, settings, RuntimeDatabase(settings.database_url))`.

- [ ] **Step 1: Tests** `test_sync_repairs_a_deleted_file_from_the_store`, `test_sync_reports_a_sample_nobody_can_provide_and_keeps_the_rest`, `test_import_registers_disk_bundles_and_honours_the_legacy_unpublished_row`, `test_import_does_not_reupload_objects_already_in_the_store` (MemoryObjectStore `puts` stays 0), `test_prepare_seeds_from_the_pinned_archive_once` (monkeypatch `catalog.bootstrap_library` to extract a fixture dir; second call does not invoke it).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement**, wire `lifespan`, add `import` to `scripts/demo/release.py`.
- [ ] **Step 4: Run** test file and `pytest tests/test_api/test_health*.py -q` if present → pass.
- [ ] **Step 5: Commit** `feat(demo): seed, import and repair the sample library from the catalog at startup`.

### Task 4: Publish, unpublish and restore through the catalog

**Files:**
- Modify: `src/services/orchestration/samples/bundle.py` (`DemoLibrary(root, catalog=None)`; `bundles()` filtered by `catalog.published_ids()` when a catalog is given; `unpublish` → `catalog.set_state(..., "unpublished")`, raise `DemoUnavailableError` without catalog; delete `UNPUBLISHED_MARKER`)
- Modify: `src/services/orchestration/samples/export.py` (`published_sample_id(catalog, job_id)`; `restore_unpublished(registry, catalog, library_root, job_id, *, title, description)` checks the unpublished record's disk snapshot revision and inventory then `set_state("published")`; `publish_job_bundle(registry, job_id, settings, catalog, *, ...)` and `publish_in_background(registry, job_id, settings, catalog, lock, *, ...)` call `register_bundle` after `_publish_locked` and `rmtree` the new dir if registration fails; `_publish_locked` keeps `library_root` but checks the catalog instead of the marker)
- Modify: `src/services/orchestration/samples/distributed.py` (delete `unpublished`, `republish`, `unpublish`; `reserve` and `publish` read `r2s_demo_samples.state='published'`; add `close_sessions_of(settings, sample_id) -> int`)
- Modify: `src/api/studio/deps.py` (`sample_catalog() -> DemoCatalog` from `registry().persistence.database`; `sample_library()` passes it)
- Modify: `src/api/studio/samples.py` (drop `distributed.unpublished` checks; `remove_sample` → `sample_library().unpublish` then `distributed.close_sessions_of` when enabled)
- Modify: `src/api/studio/demo.py` (`_with_publication` uses catalog; drop `distributed.republish`; pass `settings, catalog` to the thread)
- Modify: `src/main.py:128-145` (`inspect` uses `DemoLibrary(dir, catalog=DemoCatalog(db))`)
- Modify: the 410 check for revoked sessions (grep `unpublished\|DemoUnavailableError` in `src/api/demo_sessions.py`) to use the catalog.
- Modify: `scripts/studio/build_demo_release.py:73` (drop the marker test).
- Test: `tests/test_orchestration/test_sample_export.py`, `tests/test_api/test_sample_routes.py`, `tests/test_api/test_demo_routes.py`, `tests/test_api/test_demo_sessions.py`.

- [ ] **Step 1: Update tests**: replace marker assertions with catalog state; `test_unpublished_sample_revokes_its_session` uses `DELETE /samples/sample` or `catalog.set_state`; add `test_publish_without_store_lists_and_serves_from_disk` and `test_republishing_an_unchanged_job_restores_the_old_row`.
- [ ] **Step 2: Run** the four files → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_orchestration/test_sample_export.py tests/test_orchestration/test_demo_catalog.py tests/test_api/test_sample_routes.py tests/test_api/test_demo_routes.py tests/test_api/test_demo_sessions.py tests/test_orchestration/test_demo_distributed_hold.py -q` → pass; `ruff check src scripts tests && ruff format --check` clean.
- [ ] **Step 5: Commit** `feat(demo): publish, remove and restore samples through the catalog`.

### Task 5: Docs and production cut-over

**Files:**
- Modify: `docs/OPERATIONS.md` section 9 (library = catalog + store; disk is a cache; `scripts.demo.release import` for a library copied by hand; pinned archive seeds once).
- Modify: `.env.example` comment next to `PRODUCT_DEMO_ARCHIVE_KEY` if present.

- [ ] **Step 1: Write docs.** Commit `docs: demo library catalog and repair at startup`.
- [ ] **Step 2: Full suite** `pytest -q -x --ignore=tests/integration` → pass; push `develop`; watch `gh run list -R awun0105/P-087`.
- [ ] **Step 3: Production**: first boot imports the three samples on disk into the catalog (objects already in R2 from `publish_library`). Verify `GET /health/ready` lists them. Then the user can republish the three newer samples from Studio.
