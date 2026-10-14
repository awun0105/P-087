# Job Studio fills the viewport

## Outcome and scope

Opening Studio in a job now fills the browser viewport. The job header remains available for scene name, save status, notifications and sample publication. The job tab row is hidden while Studio is open. An arrow button at the top left returns to the same job's Progress tab through the existing URL navigation.

This is application fullscreen, not the browser Fullscreen API. Existing preview/editor mounting, saved-state commands, metric draft and permission handling remain in place. Locked Studio still falls back to Progress.

Changed files: `frontend/src/features/studio/ScenePage.tsx`, `frontend/tests/ux-scene-flow.test.tsx`, and this report.

## Verification and gates

- codegraph: read `ScenePage`, `StudioTab`, `ObjectReviewView`, `AppShell`, and layout relationships; `codegraph callers ScenePage` identifies the job route and workflow tests.
- impact: the job scene page only; shared shell and backend contracts unchanged.
- understand: existing URL tab navigation and retained viewer mounting reviewed. Understand-anything tool unavailable.
- minimal-code: reused `openTab`, existing header and viewport CSS; no duplicate viewer or new route.
- checks: `pnpm exec vitest run tests/ux-scene-flow.test.tsx` — **20 passed**; `pnpm exec tsc --noEmit` and ESLint on the changed files — clean; `git diff --check` clean.
- DevTools: attempted localhost Room Studio with Chrome DevTools. Browser had no authenticated session and redirected to login; console had no errors or warnings. **UNVERIFIED: live Studio layout/responsive rendering — no logged-in session.** Tests prove fullscreen classes and exit navigation, not real GPU rendering.
- graphify: AST graph refresh run after source changes.
