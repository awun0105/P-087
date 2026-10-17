# Bulk fixed-background selection

Removed the Draft row's `Mesh riêng` badge and direct mesh checkbox behavior. Row checkboxes now only mark objects for the `Cho N vật đã chọn làm nền` action. Marking alone leaves saved object decisions and the mesh count unchanged. Applying the batch uses the existing ignore command; the mesh count follows returned SceneIR state. Existing individual confirm, ignore and restore controls remain available.

Each request uses the revision returned by the preceding request. Partial success stays visible; completed objects are unmarked, unfinished selections remain marked. Save retry continues with unfinished objects and the last successful revision. No geometry job is launched by this action.

Changed files:

- `frontend/src/features/studio/ObjectReviewView.tsx`
- `frontend/tests/object-review.test.tsx`
- This report.

Verification:

- `npx vitest run tests/object-review.test.tsx tests/geometry-review-banner.test.tsx`: 78 passed, 2 files, 12.55s.
- Tests cover local-only marking, excluding only marked objects, sequential returned revisions, partial failure and save retry, count updates, and no mesh build request.
- `npx tsc --noEmit`: passed.
- `npx eslint src/features/studio/ObjectReviewView.tsx tests/object-review.test.tsx`: passed.
- `git diff --check -- frontend/src/features/studio/ObjectReviewView.tsx frontend/tests/object-review.test.tsx`: passed.
- `graphify update .`: completed, 27,762 nodes / 86,746 edges / 897 communities. Reported one renamed community; no LLM labeling was requested.
- Chrome DevTools, authenticated Studio for `job-f9f14e7fbfb1`: no `Mesh riêng` badges. Marked objects 1 and 3 temporarily; batch button displayed 2 while mesh count remained 59 and revision remained rev-065. Cleared both marks afterward. No real ignore command or mesh build was submitted by this verification.
- Console: no errors; one existing viewer deprecation warning, `"face" literal is deprecated use "f" literal instead`.
- Browser snapshots: `/tmp/p087-bulk-background.txt`, `/tmp/p087-bulk-background-marked.txt`. Screenshot: `/tmp/p087-bulk-fixed-background.png`.

Pre-flight (GUIDE.md Rule 13)

- codegraph: explored ObjectReviewView, existing background helper, run and applyObjectAction; queried graphify before source edits.
- impact: ObjectReviewView is rendered by StudioTab; public props and backend contracts unchanged.
- understand: Draft review selections reuse the existing ignore/restore flow; only transient marking and batch submission changed.
- minimal-code: rung 2, reused existing mutation guard, ignore endpoint and returned revisions.
- checks: TypeScript and ESLint clean; Vitest 78 passed / 0 failed.
- DevTools: authenticated object panel renders and marking behaves as above; no console errors, one viewer deprecation warning.

This supersedes the direct mesh checkbox behavior described in `2026-10-17-direct-mesh-selection.md`. No backend restart, scene rerun, commit or push.
