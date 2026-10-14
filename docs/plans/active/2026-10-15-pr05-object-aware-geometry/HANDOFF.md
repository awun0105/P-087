# PR-05 implementation in progress — NOT accepted

## Baseline and delivery

Branch: codex/pr05-object-aware-geometry, created directly from local PR-04 ee6b69f05f5af40696b1d09a438601c93a6ae27d.
User explicitly authorized pushing the existing PR-04 work before branching. That exact SHA was pushed to
origin/codex/pr04-browser-physics and verified with git ls-remote. PR-05 commits must remain local;
no GitHub PR or merge is authorized by this task. Unrelated BRAINSTORM.md and MASTER_PITCH.md are left untouched.

PR-04 closure evidence: backend 410 PASS; full frontend 629 PASS in 73 files (65.44 s), tsc, scoped ESLint,
Ruff lint/format and diff checks PASS. PR-04 still rejects Room's unrepairable preview cuts; it does NOT
constitute Room acceptance. See PLANAR_CUT_REPAIR_HANDOFF.md in the PR-04 plan directory.

## Verified compatibility findings

ObjectGS pinned commit: 0f6842b0fa80b9bfe151c31b70c306cbc5eab788,
https://github.com/RuijieZhu94/ObjectGS/tree/0f6842b0fa80b9bfe151c31b70c306cbc5eab788.

- train.py reads YAML and creates outputs/<dataset_name>/<exp_name>/<timestamp> itself. No CLI -m output
  argument exists for training. Export takes -m and reloads config, point_cloud.ply AND MLP checkpoints.
- export_object_mesh.py selects label_ids == query_label_id directly. It does NOT implement the README's
  claimed -1 iteration over objects. Invoke explicit numeric labels, reserving 0 for background in this adapter.
- Export overwrites scene_name with model_path.split('/')[-2] and appends it to source_path.
  Adapter layout must account for this exact behavior.
- cameras.py always opens object_mask/<image stem>.png, even when add_mask is false. Categorical masks
  are uint8 with nearest-neighbor resizing. Labels must be remapped explicitly, not reused implicitly.
- ObjectGS anchors are labelled RGB point clouds, not Brush Gaussian PLY/checkpoints.
- ObjectGS requires its custom gsplat-object. The application/SAM2/Brush environment must not be modified.
- Upstream environment.yml targets Python 3.8.19, PyTorch 2.1.2, CUDA 11.8. It omits several imported mesh
  dependencies (e.g. open3d). Local host has Quadro T2000 4 GB and nvcc 12.8; these are observations,
  not evidence of ObjectGS success or failure. No ObjectGS train/export has run.
- Existing render-lift computes useful per-view instance masks but only persists aggregate Gaussian labels.
  A producer integration must preserve calibrated undistorted images/masks and their object-ID map.
- Existing convex runner silently falls back to one hull and merges excess parts; the surface-mesh path
  must explicitly disallow these fallbacks rather than claiming multipart correctness.

License inspection: ObjectGS root LICENSE says MIT. train.py/scene/__init__.py/dataset_readers.py retain
Inria non-commercial/research headers referring to LICENSE.md, which is not present at root. Do not describe
all included code as unambiguously MIT. No upstream source is vendored into this repository.
Custom gsplat revision/license/dependency inspection is in progress.

## Implementation checkpoints

Contracts: optional SceneObject.surface_mesh_ref separates surface mesh from ColliderSpec.geometry_ref.
Optional SceneEnvironment.object_aware_collision_ref identifies a separately authored environment manifest;
requires membership + active collider and forbids simultaneous legacy source selection. Absent optional
fields are excluded from serialization to preserve legacy SceneIR checksums. TypeScript mirror updated.
ObjectSurfaceManifest binds checkpoint, explicit label, source membership, frame/units, upstream commit,
counts and quality. ObjectAwareEnvironmentManifest retains original geometry and source membership.
These contracts alone do not enable the producer or prove integration.

## Verification and gates

Contracts checkpoint: focused 30 tests PASS; contract mirror PASS (5 enums, 6 models); frontend tsc and
scoped ESLint PASS. Full contract suite results and later checkpoints recorded below.
Pre-flight: CodeGraph scene contracts, objectify/lift/correction/convex and effective-environment call
paths inspected; callers of SceneObject/SceneEnvironment/ColliderSpec inspected. Minimal reuse: existing
ProductArtifactRef, membership contract, Transform and process cancellation runner. No rendered UI changes
at this checkpoint. Browser/Isaac/ObjectGS GPU E2E UNVERIFIED. Graphify update required after source changes.

## Acceptance status

AC-01–AC-14: NOT COMPLETE. Contracts and compatibility audit are preliminary work, not a working ObjectGS
pipeline. Room smoke, real train/checkpoint -> mesh, CoACD mesh path, voxel ownership, producer publication,
consumer integration, correction invalidation and full regressions remain outstanding.

## Checkpoint: strict surface mesh -> CoACD

Existing convex_runner accepts an explicit object-local metre surface input + checksum, validates finite
triangles and closed components, then invokes actual CoACD separately per connected component.
No Gaussian voxelization, hull fallback, dropping invalid parts or merging parts to meet a budget is
allowed on this path. Exceeding the total part budget fails. Failed regeneration removes stale output.
Legacy Gaussian input retains prior behavior. Trimesh split explicitly uses repair=False; the first
negative test exposed that its default silently fills small holes, and that behavior was disabled.

Real isolated data/scene_runtime CoACD tests: 6 PASS (4.12 s), no skips. Two 0.3 x 0.5 x 2 m legs at
x=-1/+1 yield two distinct watertight convex parts, exact off-center bounds and 0.6 m3 total volume;
no part crosses the gap. Failure injection, wrong checksum/frame, open mesh and budget overflow all
reject without stale/fallback GLB. This is real CPU CoACD evidence on a synthetic surface, NOT ObjectGS
train/export or browser/Isaac evidence. Initial test import failed because the standalone runtime does
not install application/Pydantic dependencies; the test now loads the same standalone runner file directly.
Full contract suite: 238 PASS. Contract mirror, frontend tsc/scoped lint PASS.

Pre-flight: CodeGraph convex_parts/build_one callers inspected; source change affects only explicit
surface_mesh requests and reuses existing CoACD/GLB serialization. Ruff scoped lint/format PASS.

## Checkpoint: ObjectGS prepared-input adapter and runner

- `src/services/scene/objectgs.py` writes labelled RGB anchors, calibrated undistorted COLMAP text cameras,
  explicit 0-background / 1..255 object mapping, and categorical PNG observations. No scale is applied.
  Invalid IDs, camera quaternions, dimensions and missing source/visible labels fail before training.
- Both ObjectGS and custom gsplat revisions are pinned and tracked source modifications are rejected.
  Custom gsplat pinned SHA is 68a61a4485cfc2967703391a3e1cfb59981f8fc7 (package version 1.4.0; Apache-2.0).
- The process runner invokes actual upstream training and numeric-label mesh export, checks anchors plus
  opacity/cov/color MLP checkpoint files, validates nonempty finite raw exports and reports checksums.
  It reuses run_cancellable_process for timeout/cancellation and records per-stage logs/progress.
- `scripts/scene/objectgs_entry.py` removes only the exact pinned import-time GPU auto-selection prelude
  in memory. Source files are not patched; the host's selected CUDA_VISIBLE_DEVICES remains effective.
- `scripts/scene/run_objectgs.py --request ... --result ...` verifies immutable PLY/membership checksums,
  prepares inputs, calls the real runner, archives checkpoint files, and converts canonical world surface
  vertices to each immutable object-local frame exactly once. It does not publish SceneIR or claim that
  the normal worker already calls it. Source poses must be explicitly supplied/bound by its caller.
- Resume is unsupported because pinned upstream capture()/restore() tuple layouts disagree (11 vs 13).

Nine CPU adapter tests PASS, including rotated/off-center 1x2x3 m world-to-object conversion. Runner
command/checkpoint/export tests use explicit fixtures/mocks and are NOT real ObjectGS evidence.
The real entry was attempted in existing scene_runtime and failed with ModuleNotFoundError: wandb
(/tmp/p087-objectgs-runtime-probe.log). Existing scene runtime is unchanged and is not an ObjectGS runtime.
A separate Python 3.8.19 Conda environment was created at /tmp/p087-objectgs-env; dependencies are being
installed there only, not into application, Brush or SAM2 environments. GPU train/export remains UNVERIFIED.

Pre-flight: new adapter reuses canonical membership decode, Gaussian reader, Transform and cancellation
runner. Ruff lint/format PASS; 9 focused tests PASS. UI unchanged. No PR-05 push.

## Checkpoint: ownership-aware occupancy and shared consumers

`object_aware_geometry.build_background_collision` separates source occupancy before meshing. Object-only
cells are excluded; background/shared/unknown cells remain conservative; measured free-space conflicts
fail. Optional authored support points are counted separately as inferred. Exposed voxel faces are
extracted directly with no exterior fill, smoothing or global triangle carving. Grid extent is bounded.
This block surface is intentionally at the configured voxel resolution, not a reconstructed smooth mesh.

The shared effective compositor recognizes the checksum-bound ObjectAwareEnvironmentManifest and reads
its separately authored collider, without applying legacy triangle removal a second time. The baseline
separates all source objects; formal Pending/Ignored source representations restore their verified object
colliders at immutable extraction poses. Studio Pending preview uses the independent current-pose collider
instead. Confirmed/inactive/deleted representations reuse existing lifecycle rules. Move does not move
source restoration geometry or change the authored background. Changed membership/map or corrupt artifacts
reject rather than falling back to global geometry. Existing browser and USD consumers call this compositor.

Tests: occupancy 3 PASS; mode composition 2 PASS; including legacy effective collision, 13 PASS.
Fixture global floor/table/legs/wall/unselected geometry is connected. Independent triangle-ray probes
verify floor and wall remain, old tabletop no longer blocks, unselected object remains and shared floor
contact cells survive. This does not establish real Room or unseen support recovery acceptance.
Source map integrity, stale/corrupt rejection, Pending/Ignore and Confirm->Move composition are tested.
Ruff lint/format and diff checks PASS; Graphify AST update in progress. No PR-05 push.
