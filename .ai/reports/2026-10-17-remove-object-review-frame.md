# Remove object review information frame

Removed the amber review frame, object review summary and per-object shell warning text from the Objects panel. Kept the existing mesh action as a standalone button. Candidate-review gating, busy/running guards, API error messages and revision submission remain in place. The operation failure panel in the Inspector continues to display actual processing failures.

Changed files:

- `frontend/src/features/studio/GeometryReviewBanner.tsx`
- `frontend/tests/geometry-review-banner.test.tsx`
- `frontend/tests/object-review.test.tsx`
- This report.

Verification:

- Initial focused run: 77 passed / 1 failed. One integration assertion still expected the removed title; updated it to assert the mesh button remains and the old title is absent.
- Final `npx vitest run tests/geometry-review-banner.test.tsx tests/object-review.test.tsx`: 78 passed / 0 failed, 2 files, 12.00s.
- TypeScript: `npx tsc --noEmit` passed.
- `npx eslint src/features/studio/GeometryReviewBanner.tsx tests/geometry-review-banner.test.tsx tests/object-review.test.tsx`: passed.
- `git diff --check` on the changed source/test files: passed.
- Chrome DevTools: authenticated Objects tab on job-f9f14e7fbfb1 renders without the old title, summary or shell warning frame. Standalone `Tạo mesh cho 59 vật đã chọn` and bulk-background controls remain. Console contains no errors or warnings. Only panel navigation was performed; no scene mutation or mesh request was submitted.
- Screenshot: `/tmp/p087-without-review-frame.png`; snapshot: `/tmp/p087-without-review-frame.txt`.

Pre-flight (GUIDE.md Rule 13)

- codegraph: GeometryReviewBanner source and callers; ObjectReviewView -> StudioTab -> ScenePage. Queried graphify before changes.
- impact: existing Draft Objects panel only; no public prop or backend contract changes.
- understand: same geometry command, review gating and revision flow; removed presentation requested by the user.
- minimal-code: removed Notice wrapper and unused summary/warning derivation; reused the existing Button and useObjectify flow.
- checks: TypeScript clean; ESLint clean; Vitest 78 passed / 0 failed.
- DevTools: authenticated rendered panel verified; console clean.

No backend restart, pipeline rerun, commit or push.
