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
