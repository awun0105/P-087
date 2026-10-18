# LPIPS JPEG pairing fix — 2026-10-18

## Outcome

Fixed the LPIPS runner's PNG-only ground-truth filename assumption. Render `000000.png` now pairs with exactly one source having stem `000000` and suffix PNG/JPG/JPEG, including uppercase suffixes. Missing or ambiguous source images fail before scoring any view. Source files are read without conversion or modification.

The original drjohnson attempt logged `không có cặp render/ảnh thật nào trùng tên` and LPIPS exit code 1. Its source frames are JPEG. PSNR/SSIM were produced independently by Brush. The existing immutable visual artifact remains unchanged, with LPIPS null.

## Changed files

- `src/services/reconstruction/adapters/lpips_runner.py`
- `tests/test_reconstruction/test_lpips_runner.py`
- This report and `real-lpips-fixture.json`.
- Graph artifacts updated with `graphify update .` as required by AGENTS.md.

## Verification

- Before fix: new regression tests **7 failed, 1 passed**.
- `.venv/bin/python -m pytest tests/test_reconstruction/test_lpips_runner.py tests/test_reconstruction/test_rec04_brush.py -q`: **44 passed, 5 skipped in 12.55s**. Five codec cases require explicit `REC04_TEST_SPLAT_MODULE`; they are not LPIPS failures.
- `.venv/bin/ruff check src/ tests/`: **All checks passed**.
- `.venv/bin/ruff format --check src/ tests/`: **723 files already formatted**.
- `git diff --check`: exit 0.
- Actual LPIPS-VGG on CPU in `data/scene_runtime`, with two synthetic PNG renders and JPEG sources of different resolution: **2/2 views scored**, mean **0.0004190022009424865**. Source SHA-256 hashes unchanged. See `real-lpips-fixture.json`. This is a runtime compatibility check, not drjohnson's score.
- The scene runtime intentionally lacks app dependencies: the initial package import failed on missing pydantic. Loading the standalone runner by file, as production does, succeeded.

## Remaining limitation

The original drjohnson attempt no longer contains `training/images` or `output/eval_40000`; the source artifacts and final PLY remain. The fix cannot recover deleted renders or backfill the old immutable artifact. No training/reconstruction job was rerun and no replacement metric was fabricated. An exact model/camera evaluation that reproduces Brush rendering is needed to obtain a new measured LPIPS result.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: inspected LPIPS `score`/`main`, Brush `_holdout`/`_lpips`, and the standalone evaluator invocation; graphify query used first.
- impact: `score` is called by runner `main`; the same CLI serves BrushAdapter and `eval/visual/brush_quality.py`. Public CLI/JSON shape unchanged. CodeGraph's additional `bev_search.score` reference is a name collision, not an LPIPS call.
- understand: held-out PNG render → unique source frame → VGG score → nullable quality artifact; failure remains optional at the adapter boundary.
- minimal-code: standard-library Path/dict/list pairing in the existing runner; no new dependency or image transcoding.
- checks: red→green and real CPU LPIPS evidence above; no frontend changes.
- DevTools: n/a — standalone evaluation, no rendered UI change.
- Git: no commit, push, branch change, or existing artifact/database mutation.
