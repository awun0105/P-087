# Landing page positioning refresh — 2026-10-18

## Outcome

Updated Vietnamese and English landing copy using `BRAINSTORM.md` and
`MASTER_PITCH.md`, especially Product Strategy, Master Messaging, Landing Page
Content Foundation, and Claims Policy. Positioning now emphasizes an editable
Real-to-Sim workspace for indoor robotics simulation preparation.

- Rooms, offices, corridors, and small storage areas replace warehouse-only scope.
- Reconstruction, object editing, and collision inspection form the main workflow.
- Move/Rotate and browser Walk are described as implemented capabilities, following
  the supplied product narrative; this task does not revalidate the robot pipeline.
- Isaac Sim robot tests, real-scene reliability, and time savings require validation.
- Spatial Imagination is presented as a long-term vision.
- Removed old production claims, hardware-specific progress copy, and future-only
  cloud deployment copy. Updated title and search description.

Preserved the seven navigation labels and anchors, section order, number of cards,
workflow steps, and main section layout. Section headlines and supporting copy
were updated to match the new positioning. Follow-up work fixes the responsive
header and configures local Studio destinations, as requested by the user.

## Changed files

- `landing/src/features/landing/content.ts`: bilingual copy and status wording.
- `landing/src/app/layout.tsx`: metadata title and description only.
- `landing/src/features/landing/LandingHeader.tsx`: responsive navigation and sample
  CTA in the mobile menu.
- `landing/src/features/landing/landing.css`: scoped mobile header spacing and CTA
  visibility.
- `landing/.env.example`: document local development overrides.
- `.ai/reports/2026-10-18-landing-positioning.md`: this report.

Local-only file: `landing/.env.development.local` sets the Studio URL to
`http://localhost:3010` and login to `/login?next=%2Foverview`. It is ignored by Git
and applies only to Next.js development mode.

## Verification

Commands run from `landing/` unless stated otherwise:

- `./node_modules/.bin/tsc --noEmit --incremental false`: exit 0.
- `npm test -- --reporter=dot`: 1 file passed, 8 tests passed, 0 failed.
- `../frontend/node_modules/.bin/eslint --config ../frontend/eslint.config.mjs src/app/layout.tsx src/features/landing/content.ts src/features/landing/LandingHeader.tsx --max-warnings=0`: exit 0.
- `git diff --check` from repository root: exit 0.
- `graphify update .` from repository root: exit 0; graph refreshed after the header
  change. The final run found no further topology changes. Generated graph outputs
  are not part of the tracked diff.
- One-time TypeScript AST/content comparison against HEAD: object keys, array
  lengths, value types, and navigation labels/anchors preserved in both languages;
  only string literals and the source comment changed in `content.ts`.
- Chrome DevTools on the existing server at `http://127.0.0.1:3011/`: Vietnamese
  and English content rendered; all seven navigation targets exist; metadata
  updated; no horizontal overflow at 1920px; no console errors, warnings, or issues.
  Snapshots: `/tmp/p087-landing-final-vi.txt`, `/tmp/p087-landing-en.txt`.

An initial ESLint invocation from `frontend/` ignored files outside its base path.
The invocation above from `landing/` linted both target files successfully.
An initial comparison using Node child_process failed with `spawnSync git EPERM`;
separating `git show` from the comparison succeeded.

Screenshots and resizing were initially rejected by the tool permission layer:
`MCP tool call requires approval, but approval policy is never`.
After the session permissions changed, screenshot capture and mobile viewport
emulation succeeded. Native window resizing returned a maximized-window protocol
error, so the same Chrome DevTools toolset was used to emulate a 390×844 viewport.

### Mobile follow-up

- Vietnamese and English render the updated content at 390×844. Page scroll width
  equals viewport width (390px). English section paragraphs/headings outside the
  viewport: 0. Language switching was exercised by clicking the control at 768px.
- Console: 0 errors, warnings, or issues on the mobile verification page.
- Screenshots inspected: `/tmp/p087-mobile-vi-390-top.png` and
  `/tmp/p087-mobile-en-390-top.png`.
- Snapshots: `/tmp/p087-mobile-vi-390.txt`, `/tmp/p087-mobile-en-390.txt`.
- **Initial issue, fixed below:** the existing header clipped controls at 390px. The menu button's
  right edge is approximately 589px in Vietnamese and 586px in English. Document
  overflow checks alone miss this because the page clips horizontal overflow.
  `LandingHeader.tsx` and `landing.css` have no diff against HEAD; the header CTA
  labels also remained unchanged during the positioning refresh. This is an
  existing header layout issue. The user subsequently requested the responsive fix.

### Responsive header fix

- Cause: unlayered `.lp-btn` styles override Tailwind's mobile `hidden` utility;
  the CTA links remain visible and push utility controls outside the viewport.
  Full navigation also appeared at 1024px before all controls could fit.
- Below 640px, scoped CSS hides the top-row CTAs and reduces horizontal padding.
  Both CTA destinations remain available in the existing mobile menu.
- Full navigation now starts at 1280px, with a smaller gap at that breakpoint.
  The menu button and expandable navigation use the same breakpoint.
- Chrome DevTools checked Vietnamese and English at widths 320, 360, 390, 640,
  768, 1024, 1279, 1280, 1440, and 1920px: 20 combinations, no header controls
  outside the viewport, no overlap with full navigation, no document overflow.
- Mobile menu contains all seven section links and both CTA links. Clicking
  `Quy trình` at 390px navigated to `#workflow` and closed the menu.
- Inspected screenshots: `/tmp/p087-header-final-390-vi.png`,
  `/tmp/p087-header-fixed-320-vi.png`. Snapshot:
  `/tmp/p087-header-final-menu-vi.txt`. Console: no errors, warnings, or issues.

### Local Studio routing

- The local landing `.env` used the production Studio URLs. The Studio web server
  was verified running at port 3010; `/login?next=%2Foverview` returns HTTP 200.
- Added ignored `.env.development.local` overrides; Next.js reloaded the config
  without restarting Studio or changing any application routing code.
- Browser verification on `http://localhost:3011/`: Studio links point to
  `http://localhost:3010/login?next=%2Foverview`; sample links point to
  `http://localhost:3010/new/try-demo`.
- Clicking `Truy cập Studio` opened the local login page with a login form.
  Snapshot: `/tmp/p087-local-studio-login.txt`.
- Separate `@next/env` loader processes verified development uses the local URLs,
  while production still uses `https://app.real2sim.vn` and its `/login` page.
- `git check-ignore landing/.env.development.local`: ignored. It will not be pushed.
- Existing `.github/workflows/deploy-landing.yml` continues to supply production
  URLs during its build. No Cloudflare configuration was changed. Pushing landing
  changes to `develop` triggers this existing deployment workflow.

No new server was left running.
Delivery target: `origin/develop`, as requested. No manual Cloudflare deployment
was run; the existing workflow handles deployment after push.

## Pre-flight — GUIDE.md Rule 13

- codegraph: explored landing route, `LandingPage`, `content.ts`, `HeroScene`,
  `CompareScene`, and landing layout; queried callers of content exports.
- impact: landing header/page, default diagram content, and landing tests;
  metadata affects the standalone landing document only.
- understand: read product positioning and claims policy; content-only change.
- minimal-code: rung 2 — reused the bilingual content objects, static metadata,
  existing mobile menu, and Next.js development environment overrides.
- checks: TypeScript clean; ESLint clean; Vitest 8 passed, 0 failed.
- DevTools: desktop and mobile Vietnamese/English header verified at 20 viewport
  combinations; screenshots inspected, console clean, local Studio navigation
  verified by clicking through to the login form.
