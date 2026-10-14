# Studio scene-state panel — 2026-10-13

The left Studio panel now has **Trạng thái scene** followed by **Vật thể**, with scene state selected initially. Save, original restore, saved-state restore and clear controls live in the first tab. The header retains publication/sample-library controls.

The state tab shows the current state, saved timestamp and actor, save replacement guidance and a separate immutable-original section. It reuses DemoControls commands and authorization rather than duplicating restore logic. StudioTab passes the controls into ObjectReviewView; successful restores propagate their revision to ScenePage and reload the current scene through the existing path.

Tabs reuse the existing Radix components. Inactive panel contents remain mounted but hidden, preserving controls, filters and selection. The viewer sits outside the panel tabs. Picking a collider opens the objects tab. The state panel has priority over overlapping inspector content on narrow screens and scrolls within the viewport.

## Verification

- `pnpm exec vitest run tests/demo-controls.test.tsx tests/object-review.test.tsx tests/ux-scene-flow.test.tsx tests/studio-ownership.test.tsx`: **67 passed across four files**.
- New regressions check publication-only header controls, state-only controls/information, tab order and default, unchanged viewer element, preserved selection and no extra scene read on tab switches.
- `pnpm exec tsc --noEmit`: clean. ESLint on all changed source/tests: clean. `git diff --check`: clean.
- Authenticated Chrome on Room: correct panel tab order, all four state commands in the panel, publication link on the header, unchanged canvas while switching tabs and preserved object selection.
- At 390px: panel fits the viewport width, state content scrolls vertically, and the center of the save button hits that button rather than the inspector. Desktop browser console contained no errors or warnings.
- UI inspection did not accept any save/reset/delete operation against the live scene.

## Changed files and pre-flight

- `frontend/src/features/studio/scene/DemoControls.tsx`: state/publication scopes and panel layout.
- `frontend/src/features/studio/ObjectReviewView.tsx`: ordered panel tabs, mounted hidden contents and panel priority.
- `frontend/src/features/studio/scene/StudioTab.tsx`: state controls and restore callback wiring.
- `frontend/src/features/studio/ScenePage.tsx`: publication-only header.
- `frontend/tests/demo-controls.test.tsx`, `frontend/tests/object-review.test.tsx`: relevant regressions.

CodeGraph explored the affected exports and API/scene flow; callers for DemoControls, ObjectReviewView, StudioTab and ScenePage were checked. Graphify query and final AST update completed. Minimal code reuses the existing controls and tabs. Backend/state persistence is unchanged. UNVERIFIED: understand-anything plugin unavailable; current source and browser/component evidence establish the wiring. DevTools acceptance is local, not cloud deployment.
