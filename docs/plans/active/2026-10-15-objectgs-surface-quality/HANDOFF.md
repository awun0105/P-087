# ObjectGS surface cleanup, controlled repair and strict quality gate

Branch: `mvp-pipeline-v2`. Local commits only, no push/merge/PR. No new training, reconstruction, GPU
render/export or live scene revision was run. Segmentation/defaults, COLMAP/Brush, browser physics,
USD and the CoACD decomposition algorithm/configuration are unchanged.

## Audited data flow and calibration correction

1. Existing Gaussian membership binds immutable canonical metre source rows to object IDs. Dataset
   preparation retains their world coordinates, encodes explicit labels and writes calibrated PINHOLE
   cameras. Quaternion conversion writes world-to-camera COLMAP poses; no PCA/scene normalization
   is applied to these anchors. Camera extent is used by upstream for scale-dependent settings, not
   as permission to rescale canonical coordinates.
2. Pinned ObjectGS renderer uses `camera.fx/fy/cx/cy` and renders camera-Z depth. The existing adapter
   assigns categorical object masks to each camera's alpha mask. Bounded TSDF masks out other labels,
   uses depth_scale=1 and the explicitly configured metric voxel/depth range. Raw `fuse.ply` is used;
   upstream largest-N `fuse_post.ply` is never substituted.
3. Confirmed code mismatch: upstream `to_cam_open3d` rebuilt K from its FoV projection, placing the
   principal point at `(W-1)/2,(H-1)/2`. The renderer uses calibrated cx/cy. New export hooks use the
   renderer's exact K and existing world-view transform for TSDF. They reject non-rigid/nonfinite
   extrinsics and do not edit the pinned checkout. CPU tests include off-centre K and rotated poses.
   No claim is made that this mismatch caused the saved smoke mesh's holes.
4. Export also retains bounded support from the same masked rendered depths and calibrated cameras:
   at most 16 evenly selected views / 200,000 samples. This is an ObjectGS **rendered depth estimate**,
   not independent sensor geometry or ground truth. No visual inpainting enters fusion/support/repair.
5. Prepared producer verifies raw checksums/world-metre frame, converts vertices and support exactly
   once with the explicit world_from_object pose, compares surface bounds against that object's source
   membership anchors, and runs cleanup → controlled repair → QA. Final GLB is reloaded and validated
   again. Its checksum, source membership checksum and source pose bind the reports.

The hook adapter is explicitly requested by the producer using `--surface-support`. The pre-existing
mask-only export entry remains usable for old invocations, which do not gain support retroactively.
The hook was imported successfully in the actual isolated Python 3.8.19 runtime with CUDA hidden.
Actual ObjectGS TSDF execution through this new hook remains unverified on GPU.

## Cleanup and quality policy

`src/services/scene/surface_mesh.py` is NumPy/SciPy/Trimesh-only, reusable in worker and collider runtime.

- Weld exactly equal vertices, remove duplicate/degenerate/nonfinite faces and unused vertices. Never
  round/move vertices, smooth, decimate, select only the largest component, create a hull, or delete a
  finite closed component merely because it is small.
- Bake explicit rigid GLB child transforms once; reject non-rigid scale/reflection layouts. Keep every
  supported component and its relative location. No implicit canonical/display conversion occurs.
- Report finite geometry, bounds/dimensions/area, closed volume, components, per-component face counts,
  boundary edges/loops, nonmanifold edges, winding, Euler characteristic/genus and intersection checks.
  Genus/volume are not reported as valid closed-solid measurements for open surfaces.
- Require watertight, consistently oriented positive-volume components and valid closed topology. The
  bound comparison uses the existing TSDF truncation span of 5 voxels, without rescaling either mesh
  or anchors. Source-unit correctness still depends on canonical metric inputs; a mesh file alone
  cannot independently prove metres.
- Check nonadjacent/non-shared-vertex triangle intersections using a spatial broad phase and triangle
  SAT. Explicit pair budget: 250,000; exceeding it fails closed. The report names this coverage scope;
  it is not a mathematical proof covering all folds inside a shared-vertex one-ring.

## Controlled repair

Only simple convex planar boundary loops with at most 8 vertices and diameter at most 2 actual TSDF
voxels are candidates. Planarity residual must be within 0.1 voxel. Every sampled point over the proposed
cap needs depth support within half a voxel from at least two views, whose camera baseline exceeds a
voxel. Single-view, missing depth, unknown coordinate frame/resolution, coincident camera origins and
visual-inpainting support do not authorize repair. Large, branched, nonplanar or complex loops stay open.

Caps reverse existing boundary winding, add no displacement to observed vertices and never bridge
components. Inferred face indices/areas and supporting-data checksum are recorded. Full QA and GLB
round-trip QA must still pass afterwards. Partial repairs in an otherwise rejected mesh are retained only
as a rejected candidate with explicit inference labels, never an accepted physics surface.

A true through-hole in a closed surface has valid topology and no open boundary to cap. Tests preserve
an annulus, the spaces between disconnected components and the void under a connected four-leg table.
Size alone is never sufficient evidence to fill a boundary.

## Artifacts, failure behavior and CoACD

Before starting collider generation, production publishes raw object-local mesh, processed mesh, quality
JSON, repair JSON and optional rendered-depth support NPZ through the existing artifact store. Every
payload has SHA-256 and object provenance. The publisher verifies that reports bind object, raw/result
checksums and pass/fail status. Runtime/config/source-pose provenance is preserved.

- A passed mesh is `ObjectSurfaceMesh`; a rejected one is `ObjectSurfaceCandidateMesh`.
- Reports are `ObjectSurfaceQualityReport` / `ObjectSurfaceRepairReport`; raw/support artifacts remain
  distinct. Accepted SceneIR `ObjectSurfaceManifest.quality` and provenance reference the reports.
- ObjectGS emits `surface_quality` evidence including reasons/refs. Reports survive later collider failure
  or scratch deletion. A test verifies rejected reports after deleting the producer workspace.
- Failed quality prevents objectify from reaching accepted scene publication. Strict collider validation
  also rechecks actual surface topology/intersections. No Gaussian, convex-hull or OBB fallback is allowed.
- Downstream CoACD still decomposes separate components independently and rejects multipart budget
  overflow instead of merging gaps. Existing multipart policy and thresholds are not relaxed.
- Empty/nonfinite raw export or unsupported layout can fail before local surface processing; existing
  producer diagnostics/logs capture that earlier failure. They cannot manufacture a valid surface artifact.

Reports are available through stored refs/local artifact resolver and the saved JSON files; no report UI
or new artifact-download API was added in this task. Existing job retention/deletion governs artifacts.
Support compressed/uncompressed input is capped at 16 MiB. Repair loop detail is capped at 128 loops,
with omissions explicit; remaining boundaries still cause failure. Diagnostic byte quotas remain unchanged.

## Saved 8,000-iteration surface: real CPU inspection, rejected

Input: `data/pr05_objectgs_smoke_20261015/surface-masked-local.glb`. The saved export command records
iteration 8000, voxel size 0.03 m, depth truncation 8 m. Existing source SHA-256 was retained in the report.
No checkpoint was loaded on GPU, re-exported or trained.

```bash
.venv/bin/python scripts/scene/inspect_surface.py \
  --input data/pr05_objectgs_smoke_20261015/surface-masked-local.glb \
  --output-dir data/pr05_surface_quality_20261015/masked-final \
  --voxel-size-m .03 --coordinate-frame object_local --distance-unit m
```

The output directory must not already exist. Exit **2** means QA rejection; exit 0 means this CPU gate
passed, not real-scene acceptance. Optional expected-anchor bounds and checksum-bound world-frame depth
support/source pose can be supplied. CLI never invokes training, rendering or scene publication.

Result: **FAIL**, 7,497 vertices / 14,697 triangles / 11 components / 275 boundary edges / 7 boundary loops.
No saved depth support was available, so **zero holes were repaired**. Geometry dimensions remained
approximately 1.1214 × 1.1165 × 1.1700 m. The new camera correction is not retroactive to this mesh.
No fresh anchor-scale comparison was available to this offline inspection; it does not certify metric scale.

Checked-in evidence snapshots:

- [SAVED_SURFACE_QUALITY.json](SAVED_SURFACE_QUALITY.json)
- [SAVED_SURFACE_REPAIR.json](SAVED_SURFACE_REPAIR.json)
- [SAVED_SURFACE_STRICT_RESULT.json](SAVED_SURFACE_STRICT_RESULT.json)

The real isolated strict collider runner rejected it before decomposition: `parts=0`, `method=failed`,
`fallback_allowed=false`, `open_boundary` / `open_or_nonpositive_component`. No collider GLB was produced.
The large surface/checkpoint files remain local artifacts, not repository test fixtures.

## Test evidence and remaining limits

Fixtures cover asymmetric closed mesh, small missing patch, missing/incorrect support, large opening,
multiple components, annulus, noisy/duplicate/degenerate/nonfinite triangles, intersecting shells,
rotated/off-centre children, unsupported scale transforms, camera calibration and checksum bindings.
Actual isolated CPU CoACD processes the repaired patch, disconnected components and a four-leg table;
the tested under-table point remains outside all convex parts. GPU outputs in objectify flow tests are
explicit fixtures; the CoACD step is real. The publisher is exercised with the real filesystem store.

Known limits:

- Rendered depths can be consistently wrong. Two-view support is a conservative model-based criterion,
  not independent proof of physical shape. Semantic preservation needs annotated real-scene evaluation.
- Sampling may miss valid support and reject a safely repairable hole. Large/nonplanar/complex holes,
  nested inward cavity shells and budget-limited meshes remain rejected rather than weakened.
- Closed small floaters cannot be classified as noise by size alone. They are retained/reported; extra
  components can cause the unchanged CoACD part budget to reject the object.
- No raw measured depth, visual inpainting, unlabelled source cloud or fabricated collider is substituted
  for missing geometric evidence. No room-wide floor/wall repair was added.
- No new GPU TSDF run, browser physics or Isaac Sim acceptance. Old Room rev-100/paused processes and
  the original smoke artifacts were not modified. Thermal monitoring remains outside production code.

Local implementation commits: `3cad8e3c` (core QA/repair + TSDF hooks), `7971957a` (producer/artifact/strict
collider integration and CPU inspection CLI). Final regression results are recorded below.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: explored ObjectGS preparation/export/local-frame functions, surface contracts, collider
  surface_parts/build_one and objectify publication; inspected their callers. Read ignored pinned
  upstream renderer/camera/TSDF code directly because it is outside the index. Graphify query/update used.
- impact: ObjectGS surface producer and calibrated export adapter, isolated strict surface validation,
  early artifact publication and additive quality/provenance JSON. No segmentation or physics changes.
- understand: UNVERIFIED — understand-anything tools unavailable. Traced masks/camera K/E/depth units,
  world-to-local conversion, report/artifact binding, strict rejection and SceneIR publication directly.
- minimal-code: reused pinned TSDF, membership/SceneIR contracts, existing recorder/store, NumPy/SciPy/
  Trimesh and strict CoACD. No new dependency, replacement reconstruction method or service.
- checks: executable results below; ESLint/Vitest n/a — no frontend source changes. Frontend typecheck run.
- DevTools: n/a — no rendered UI change; browser/GPU/Isaac quality remains unverified.

## Final executable verification (2026-10-15)

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest \
  tests/test_scene tests/test_simulation tests/test_contracts \
  tests/test_orchestration/test_object_diagnostics.py \
  tests/test_orchestration/test_surface_evidence.py \
  tests/test_orchestration/test_scene_extraction.py \
  tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_orchestration/test_scene_editor.py \
  tests/test_orchestration/test_processing_presets_schema.py \
  tests/test_orchestration/test_collision_source_invalidation.py -q
```

- **755 passed in 56.25s**; log `/tmp/p087-surface-delivery-tests.log` (local temporary log).
- Earlier broad run: 750 PASS; newly added publication-binding tests are included in the final 755.
- Ruff check `src/ tests/ scripts/scene/inspect_surface.py scripts/scene/objectgs_export_entry.py`:
  **All checks passed**. Ruff format check: **653 files already formatted**.
- Contract mirror: **PASS**, 5 enums / 6 models. Frontend `npm run typecheck`: **PASS**, exit 0.
- TSDF support import in actual isolated Python **3.8.19**: **PASS**, CUDA hidden, no Torch/GPU probe.
- Saved masked surface checksum matches the pre-existing smoke `checksums.json`: **True**.
- Saved surface CPU inspection: **QA FAIL as expected**, exit 2, zero inferred faces. Strict runner
  emits a failed item without hull/OBB fallback. This is rejection evidence, not a successful real collider.
- `git diff --check`: **PASS**. Final `graphify update .`: **PASS**, 24,075 nodes / 74,731 edges /
  801 communities; 37 files without extracted symbols remain a graph-coverage limitation.

All implementation/tests are committed locally; documentation/evidence snapshots are committed separately.
Unrelated `BRAINSTORM.md` and `MASTER_PITCH.md` remain untouched and untracked.
