# Object panel and direct mesh selection

The Draft status/counts/errors and mesh button now live inside the existing Objects tab of the management sidebar. The duplicate Duyệt vật thể button and the intermediate Tách riêng các vật đã đánh dấu action were removed.

Each Draft row's checkbox now represents the saved geometry choice: checked selects separate object geometry; unchecked keeps the source in the fixed background. Changing it uses the existing confirm/ignore command and returned SceneIR revision immediately. The mesh count reads that same saved state, and the mesh button is disabled while a choice is being saved. Undecided candidates have an indeterminate checkbox; the explicit Giữ vật chưa chọn làm nền action can resolve remaining candidates without creating geometry. Fixed objects remain visible in the Draft Tất cả filter so users can check them again.

Changed files:

- `frontend/src/features/studio/ObjectReviewView.tsx`
- `frontend/src/features/studio/GeometryReviewBanner.tsx`
- `frontend/tests/object-review.test.tsx`

Verification:

- `npx vitest run tests/object-review.test.tsx tests/geometry-review-banner.test.tsx`: **77 passed**, 2 files, 11.56s.
- Tests exercise immediate checkbox/count updates, exact returned revisions, unchecked objects staying in the list, status region contained in the sidebar, absent duplicate buttons, and resolving pending objects without a mesh request.
- `npx tsc --noEmit`: passed.
- `npx eslint src/features/studio/ObjectReviewView.tsx src/features/studio/GeometryReviewBanner.tsx tests/object-review.test.tsx`: passed.
- `git diff --check`: passed.
- Chrome DevTools on the actual drjohnson Studio: status region is inside the object-list sidebar; no Duyệt vật thể button; current checkboxes reflect the saved 59 separate/1 fixed choice. At an emulated 1366×768 viewport the object list remains scrollable. No console errors/warnings. Browser checks only inspected/navigated the UI; no scene choices were changed and no mesh request was made.
- Screenshot: `/tmp/p087-direct-mesh-panel.png`.
- `graphify update .`: AST refresh performed.

Pre-flight (GUIDE.md Rule 13): CodeGraph/graphify traced ObjectReviewView, GeometryReviewBanner and their callers before changes. Scope is frontend selection and placement; existing backend confirm/ignore and revision contracts were reused. Minimal-code: removed the extra selection state and confirmation step. TypeScript, ESLint, component regression and authenticated browser checks completed. No backend restart, commit or push.

This supersedes the intermediate batch-selection UI described in the earlier Walk/object-review report. Backend selective geometry behavior is unchanged.
