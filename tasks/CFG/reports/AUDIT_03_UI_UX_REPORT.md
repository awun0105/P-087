# CFG-14: UI/UX audit

Status: PASS - Ready for Final E2E Verification.

## Scope and evidence

Audited current processing contracts/client, ProcessingSettings, useProcessingForm and the real UnifiedInputFlow caller after CFG-12/13. Chrome DevTools used the actual Next/FastAPI application with an isolated temporary database and no reconstruction worker. Browser observations prove local configuration interaction, not GPU reconstruction or production acceptance.

| Requirement | Executable evidence | Result |
| --- | --- | --- |
| Scenario applies values and badge | Component test plus CFG-13 browser requests/DOM values | PASS |
| Manual edit changes preset to custom | Component/browser mesh edit; applied badge removed | PASS |
| Clicking selected choice reapplies preset | Component test resets faces to smooth and restores badge | PASS |
| Navigation preserves choices and values | UnifiedInputFlow integration and browser forward/back probe | PASS |
| Read-only sample hides wizard and locks controls | Real aisle-cw sample: 21 controls, all disabled, no wizard | PASS |
| Older sample missing new fields stays truthful | Browser: 24 unrecorded fields; regression test rejects invented defaults | PASS |
| Debounce waits 300 ms after the last edit | Fake-clock test checks no call at 299 ms, one at 300 ms, old signal aborted | PASS |
| Evaluation 500 preserves form and Retry recovers | Hook regression and actual UnifiedInputFlow component test | PASS |
| Stale suggestions cannot overwrite edits | Hook cancellation regression | PASS |
| Types and static quality | pnpm typecheck and changed-file ESLint | PASS |

## Repair made during audit

The old sample view rendered fallback minimum values for fields absent from its recorded processing dictionary. It now displays “Không được ghi lại trong video mẫu.” for those fields, preserving recorded values and avoiding invented configuration. The editable form behavior is unchanged.

## Verification

- `pnpm exec vitest run tests/ux-processing-form.test.tsx tests/processing-settings.test.tsx tests/studio-contracts.test.ts`: 19 passed; `CFG14-FOCUSED-VERIFICATION.log`.
- `pnpm exec vitest run`: 538 passed across 65 files; `CFG14-FRONTEND-REGRESSION.log`.
- The additional UI error-recovery case was added after that full run. `pnpm exec vitest run tests/unified-input-flow.test.tsx`: 28 passed including the new case; `CFG14-ERROR-RECOVERY.log`. Every current frontend case has executable coverage; final whole-suite verification repeats in CFG-15.
- `pnpm typecheck`: Next type generation and tsc --noEmit clean; `CFG14-TYPECHECK.log`.
- ESLint on changed source/tests: clean; `CFG14-ESLINT.log`.
- Chrome real sample probe: readOnly=true, wizard=false, controls=21, allDisabled=true, unrecorded=24; `CFG14-READONLY-BROWSER.log`. Console error/warning list empty.
- Source changes are limited to missing-value rendering plus tests. `git diff --check` clean; graphify AST update completed.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: ProcessingSettings/ParameterField, form hook, SampleProcessing and sample route consumers inspected.
- impact: read-only samples with incomplete historical processing dictionaries; timing and error-recovery regression coverage.
- understand: UNVERIFIED — understand-anything unavailable; current caller flow and stored sample behavior inspected directly.
- minimal-code: reused existing renderer, placeholder text and existing form/test fixtures; no dependency or new state abstraction.
- checks: TypeScript/ESLint clean and all tested cases pass as detailed above.
- DevTools: real read-only sample verified in local auth-disabled QA mode; editable wizard evidence retained from CFG-13. Production/authenticated deployment acceptance is not claimed.
