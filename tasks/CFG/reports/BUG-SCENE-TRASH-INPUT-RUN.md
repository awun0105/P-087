# Scene trash foreign-key repair — 2026-10-13

## Outcome

Cancelled job `job-764ed1e2e71b` could not be moved to trash. A read-only deletion plan had no blockers. Executing the row deletion on an isolated SQLite backup reproduced `sqlite3.IntegrityError: FOREIGN KEY constraint failed` at `DELETE FROM r2s_jobs`. Its accepted `r2s_input_runs` row references both the job and its project; the deletion collector omitted that table.

The collector now saves the accepted run alongside the job, deletes it before its foreign-key parents, and restores it after the project/job. Its composite requester/idempotency key is retained. Assembly revisions and resolution records remain live because other jobs may share them. No schema migration or foreign-key bypass is needed.

## Changed files

- `src/services/orchestration/projects/deletion.py`: include input-run columns, composite key, collection and child-first deletion order.
- `tests/test_orchestration/test_scene_deletion.py`: reproduce accepted-run foreign keys, verify exact restoration, shared-assembly isolation and permanent deletion on fixtures.
- `tests/test_api/test_trash_routes.py`: verify real HTTP delete/restore preserves the accepted run.

## Verification

- Before repair, both new regressions failed with the same foreign-key error.
- `.venv/bin/pytest tests/test_orchestration/test_scene_deletion.py tests/test_api/test_trash_routes.py -q`: **42 passed in 3.67s**.
- Ruff check and format check on all three changed Python files: clean; three files already formatted. `git diff --check`: clean.
- Live local stack had no RUNNING/QUEUED jobs and was restarted using its existing `scripts/gpu/studio.env` and dev frontend mode to load the repair.
- Authenticated Chrome UI: moved the exact job's `input` scene to trash; `DELETE /api/v1/scenes/project-466686891070` returned 200. Trash showed the scene and its source file. Restored it through the UI; restoration succeeded.
- Read-only database verification afterward: original JobManifest checksum preserved, accepted input run restored, trash empty, and zero foreign-key violations. No permanent deletion of user data was performed. Browser console had no errors or warnings after returning to the job.

## Pre-flight — GUIDE.md Rule 13

- codegraph: deletion collector/order, restore, runtime schema and API/CLI callers inspected; graphify query used and AST update requested after changes.
- impact: shared scene-trash service used by Studio API and delete CLI; existing lifecycle, ownership and restore guards remain in place.
- understand: input assembly → accepted run → job/project foreign keys → reversible trash. UNVERIFIED: understand-anything plugin unavailable; source/schema inspection and isolated reproduction established the flow.
- minimal-code: reuse the existing stored-row collection and restore mechanism; add one missing dependent table.
- checks: both red regressions reproduced; 42 focused tests passed, Ruff and whitespace checks clean. No frontend code changed.
- DevTools: authenticated local scene deletion and restore verified; no cloud deployment claim.
