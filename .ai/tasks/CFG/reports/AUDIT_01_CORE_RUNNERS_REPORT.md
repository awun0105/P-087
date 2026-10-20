# Core runners audit — 2026-10-13

**PASS — Ready for Presets & API Layer.** CFG-02 through CFG-06 are implemented and committed. The user clarified that may-modify lists are examples; additional required files are recorded in CFG-04 and CFG-06.

| Boundary | Current evidence | Remaining requirement |
| --- | --- | --- |
| Vocabulary | CFG-02 verified pinned legacy FLANN and modern FAISS assets; asset tests pass | None at the asset boundary |
| COLMAP | Explicit sequential, sequential_vocab_tree and exhaustive CLI branches tested; CFG-03 native CPU loop matching on three valid frames recorded | No new full reconstruction/GPU acceptance claimed |
| Voxel | Mesh and fill command controls tested; old schema checksums pinned; request config reaches adapter | Adapter qualifies floor-fill support and checks both fill radii before voxel execution; oversized floor-only grid regression passes |
| Objectify | CFG-05 override dictionaries reach lift, convex and inpaint; retry propagation and seed truncation tested | Job processing artifact wiring belongs to CFG-09 |
| USD | Request validation, legacy candidate config and standalone hybrid material/ground controls verified; native USD inspection preserves per-object material precedence | Package service forwards checksum-bound job/default/explicit controls to carve and hybrid requests; v6 build/cache identity binds the same values |

## Executed regression verification

The complete mandatory pytest command from CFG-07 was executed as one suite, covering:

- Original COLMAP, voxel, scene queue/rush and collision-quality suites.
- New vocabulary asset, matching modes, geometry overrides, objectify overrides and simulation overrides suites.

Result: **172 passed in 11.33s**, no skips. Raw output: `tasks/reports/CFG-07-VERIFICATION.log`.

Additional CFG-06 run includes USD, carve and hybrid USD regression suites: **108 passed in 31.62s**, no skips. Native USD tests use the independent virtualenv executable without resolving its symlink to system Python. Raw output: `tasks/reports/CFG-06-VERIFICATION.log`.

Static checks executed:

```text
.venv/bin/ruff check src/services/ scripts/
All checks passed!
.venv/bin/ruff format --check src/services/ scripts/
357 files already formatted
git diff --check
exit 0
```

## Command and payload audit

| Tool | Effective command/payload | Proof |
| --- | --- | --- |
| COLMAP sequential | sequential_matcher; SequentialMatching.loop_detection=0; explicit CPU/GPU/thread controls | Original 36 cases plus mode tests |
| COLMAP loop | sequential_matcher; loop_detection=1; staged vocab_tree.bin; period/image count/min distance from config | Mode tests and CFG-03 native CPU evidence |
| COLMAP exhaustive | exhaustive_matcher; no SequentialMatching flags | Selected-command/help and adapter tests |
| splat-transform collision | --collision-mesh faces or smooth; --voxel-floor-fill radius and/or --voxel-external-fill radius | Command tests; adapter capability and capacity checks |
| splat-transform occupancy | Same configured fill flags before clearance/carve | Override fixture pipeline and fill-control tests |
| CoACD | convex request config: threshold, max_convex_hull, preprocess_resolution, voxel_m | Objectify orchestration request capture and validated defaults |
| LaMa/inpaint | inpaint request config: max_new_gaussians, behind_object_m | Request capture and invalid-input tests |
| SAM2/lift | lift config: min_score, max_area, box_margin_m, sam_batch; seed max_objects applied separately | Request, seed limit and retry tests |
| USD | Candidate build_config and hybrid request use ground/material/carve values; global material is weaker than object materials | Candidate byte checks, package/cache integration and native pxr inspection |

Legacy Colmap/Voxel serialized defaults retain checksum compatibility. Non-default configuration enters identity; changed material or carve values invalidate candidate cache. Vocabulary downloads remain explicit operator actions, never request-time side effects.

Remaining integration work is assigned to later tasks: expose/persist all groups in presets, worker resolution, API evaluation and wizard UI. This gate does not claim those later tasks are already delivered. Full backend/frontend verification remains CFG-15 scope.

Provider request tests mock GPU providers. USD authoring and reopening with pxr do not prove Isaac/PhysX behavior. No production job was rerun.
