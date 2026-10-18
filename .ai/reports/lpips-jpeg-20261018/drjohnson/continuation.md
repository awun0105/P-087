# Deferred drjohnson LPIPS measurement

User authorized recovering LPIPS from the saved drjohnson model/cameras. When offered pausing the active job versus waiting, user explicitly selected **wait for the current job to finish**. Do not stop, pause, retry, or mutate job-bfc7d73f0dbf.

## Prepared state

- Repository: `/home/lqaq/PROJECT/AI20K/P-087`.
- Target: `job-f9f14e7fbfb1`; raw Brush visual namespace `attempts/preview-c7f1927a25d747d5912cb4e6cddf874a/rec04/`.
- Workspace: `data/studio_local/evaluations/drjohnson-lpips-20261018`.
- `source/` contains copies of all 263 checksum-verified JPEG frames and original sparse files. No undistortion/rendering has run in this workspace yet.
- `source-metadata.json` contains source visual checksum, immutable model/camera refs, 33 held-out frame IDs, original quality metrics, and original Brush bridge checksums.
- Input preparation script beside this file executed successfully. Do not rerun it on the existing directory (it intentionally requires a fresh directory).
- LPIPS runner fix is already in the working tree and tested (44 passed, 5 codec skips; real LPIPS-VGG CPU fixture passed).

## Waiting condition

Read `data/studio_local/runtime.db` in SQLite `mode=ro`, find current `manifest_ref` in `r2s_jobs`, then load the referred file beneath `data/studio_local/artifacts`. Wait until job-bfc7d73f0dbf is terminal. Check for other heavy workers, GPU availability, and safe CPU/GPU temperatures before compute. If the job is missing, correlate its durable event/trash state rather than assuming success. Do not run concurrently with another heavy job. Existing thermal guard for r2s-stack must remain untouched.

## Recovery route to validate

1. Use existing `BrushInputAdapter` / pinned COLMAP undistortion to reconstruct `training/` from the prepared `source/`. Original bridge says `undistorted=true`, so raw JPEG inputs and original distorted camera are NOT the actual Brush training input. Never skip this step. All reconstructed training-file hashes must match `original_bridge.training_files` in metadata; mismatch blocks claims of exact reproduction.
2. Use the exact raw GaussianPLY referenced by metadata (2,000,000 Gaussians; SHA-256 `6d28a28303384e3a81a9549409bb0f050059c32c52e51c2417f1b8370e66ed01`) as a private `training/init.ply`. Keep original artifacts unchanged. Verify runtime binary against the configured pin and original job identity.
3. Source of the pinned upstream tag v0.3.0 is readable using `git -C /home/lqaq/PROJECT/AI20K/private/brush show v0.3.0:...`. Current third-party checkout is newer; do not use current main as authority for the installed binary. Do not change that checkout.
4. Pinned Brush has no eval-only CLI. In `crates/brush-process/src/train_stream.rs` evaluation happens AFTER `trainer.step` and refinement, inside the start_iter..total_steps loop. Setting start_iter=total_steps produces no evaluation. A candidate workaround is a single frozen step (start_iter=39999,total_steps=40000), refinement disabled, zero color/opacity/rotation learning rates, zero mean noise and auxiliary losses. Mean/scale exponential schedules divide end/start, so both mean/scale rates cannot be zero; investigate tiny equal positive rates such as 1e-30 and verify that no stored float changes. This route is a candidate, NOT a proven measurement yet.
5. Preserve original max_resolution=1920, SH degree=3, seed=0, max_splats=2000000, eval_split_every=8, final eval/save. Export to this private workspace. Confirm all 33 rendered frame IDs exactly match metadata.
6. Verify exported model after the frozen step against the original PLY, field by field over every Gaussian. Positions/scales/opacity/SH must be unchanged; compare rotations in their normalized physical form (export normalizes quaternions). Refuse to call it the original model if parameters changed. Source model and all source artifacts must retain their original hashes. Also compare PSNR/SSIM with original 29.73522 / 0.9213881 and investigate material discrepancies. Do not retrain or substitute another renderer silently.
7. Run fixed standalone `src/services/reconstruction/adapters/lpips_runner.py` using `data/scene_runtime/bin/python`, --net vgg, restored undistorted ground truth, and the verified 33 renders. Do not import the app package into scene_runtime (no pydantic); CLI-by-file is supported.
8. Run heavy stages sequentially, monitor temperatures and timeout, pause ONLY your own process group if needed. Do not change global power/thermal policy. Save commands, logs, model comparison, source/render checksums, original and new PSNR/SSIM, LPIPS mean/per-view/count, timings and hardware to a fresh measurement JSON/report beside this file. Never overwrite the old immutable visual.json or database entries to backfill the missing number.
9. If exact rerendering cannot be validated, report the concrete limitation instead of a fabricated LPIPS. If it succeeds, report the real score, count=33, original model identity and any numerical reload tolerance. This is image reconstruction evaluation, not collision/Isaac validation.

## State at deferral

job-bfc7d73f0dbf remained RUNNING at ST-CAMERA-POSE. Its COLMAP exhaustive matcher was processing blocks [5/7,*]. CPU previously reached 90 C. No drjohnson GPU work has started.
