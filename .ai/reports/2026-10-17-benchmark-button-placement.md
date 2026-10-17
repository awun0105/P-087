# Benchmark button placement

Moved the Benchmark entry from the viewer's bottom-right overlay into the management panel header in `frontend/src/features/studio/ObjectReviewView.tsx`. With that panel collapsed, the entry remains next to the panel opener. Benchmark panel behavior is unchanged.

Verification:

- `npx vitest run tests/object-review.test.tsx`: 65 passed.
- The initial name-filtered run failed 2 cases because its existing beforeEach assumes another suite has initialized mocked fetch; the complete file passed without changing tests.
- `npx tsc --noEmit`: passed.
- `npx eslint src/features/studio/ObjectReviewView.tsx`: passed.
- `git diff --check`: passed.
- Chrome DevTools: at 1920 × 908, button moved from (1804.86, 864) to (174.89, 84); it is inside the management panel, does not overlap toolbar button groups, and remains visible with the management panel collapsed. Opening and closing Benchmark was verified without saving data. Screenshot: `/tmp/p087-benchmark-after.png`.
- `graphify update .`: AST refresh executed; standard extractor warnings about symbol-free files were emitted.

Pre-flight: small layout change — CodeGraph/graphify traced ObjectReviewView, BenchmarkPanel and their callers; reused the existing button and handler. TypeScript, ESLint, existing component tests and browser placement/open-close checks completed. No backend or live scene changes, no commit/push.
