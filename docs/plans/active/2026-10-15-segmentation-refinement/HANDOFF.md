# Segmentation and Gaussian membership refinement

Branch: `mvp-pipeline-v2`. Local commits only; no push/merge/PR. Production defaults and processing
presets remain `legacy`. The new `multiview_v1` mode is explicitly opt-in because the quality evidence
below is synthetic. No reconstruction, SAM2 GPU inference, ObjectGS training or live scene mutation
was executed. COLMAP, Brush, ObjectGS, CoACD, browser physics, surface repair and USD producers are unchanged.

## Audit: established behavior versus unverified causes

Established from current source and executable annotated fixtures:

- Same-frame NMS across different prompts can leave each prompt fewer than two views when the highest
  score alternates. An entire consistently masked object then disappears.
- Requiring each point to have two visible observations removes a genuinely occluded appendage even
  though its object track has multiple views. Keeping only the largest connected component removes
  disconnected, repeatedly observed parts.
- Threshold-inclusive 50% votes and transitive prompt union can merge nearby objects through fused masks.
- Small-mask-over-large-mask painting assigns overlap by area/order. Lifting can discard trusted seeds
  or assign them to another object. Equal per-object normalized scores select the first object by argmax.
- The floor band is a protection heuristic, not semantic ownership. It removes low object points too.
  The fixed footprint lower bound can reject a volumetric small object with stable multiview membership.

Not established for Room: which of these accounts for any particular real missing part or merge.
Both inspected Room attempt directories contain `points.npz`, `request.json` and `sam2.log`, but no
completed `result.npz`. The stopped recovery predates diagnostic instrumentation. No new sealed
real-scene diagnostic attempt or annotated Room membership was available in the inspected artifact roots.
The existing ObjectGS smoke artifacts do not supply independent segmentation ground truth.

## Algorithm changes, only under multiview_v1

1. Keep separate prompt tracks during NMS. Deduplicate observations within each prompt/view; duplicated
   records cannot manufacture multiview support. Require the existing track support/view/fraction limits.
2. Vote relative to actual point visibility; unseen points add no negative vote. A 50% tie is not a
   positive majority. Accept singly visible appendage points only when their connected component has
   repeated mask support and the existing minimum component/instance support. This is not extrapolation
   of unobserved geometry.
3. Merge only with aggregate support overlap and consistent overlap in every shared accepted view,
   with at least the existing minimum number of shared views. Use complete-link groups so an A–bridge–B
   chain cannot imply A=B. Resolve equal group maxima by agreement across the group's tracks, then
   abstain if still tied. An adversarial regression caught and fixed the initial implementation's loss
   of B when rejecting a bridge merge.
4. Retain every sufficiently large repeatedly supported component rather than only the largest one.
5. In lifting, conflicting masks produce an internal `-2` abstention region. Exclude it from both positive
   and negative gradient evidence. Persist ObjectGS observations with valid categorical `-1` background,
   never `-2`. Pin exclusive multiview seed owners; reject duplicate seed ownership. Non-seed score ties
   abstain. Existing contribution/box/majority thresholds remain unchanged.
6. For near-floor membership, require positive distance outside the existing measured noise interval
   (`noise_sigma_multiplier * robust_noise_sigma_m`). A prior-only fallback keeps its original band.
   Within the original band also require Gaussian variance along the fitted normal to be at least the
   mean tangential variance, using its quaternion. This blocks planar floor splats with positive noisy
   centres. Uncertain floors fail closed. The roundoff allowance is machine epsilon, not a quality threshold.
7. Small-footprint candidates may pass only with already validated multiview support and 3D spatial
   spread above measured floor noise in every direction. Planar small clutter does not pass this alternate
   condition. The footprint upper bound, height bound, object cap, working-set opacity gate and final
   minimum 50 Gaussians are unchanged. No numeric production threshold was relaxed.

Rows remain in original source order. Membership remains one exclusive little-endian int32 label per
Gaussian, `-1` background, with the existing label-to-object map. Candidate ordering is deterministic
by size/source index; this does not promise identical candidate IDs across different extraction revisions.
Existing immutable revision/checksum and membership correction contracts are preserved.

## Annotated before/after evidence

Run from the repository root, without GPU/runtime providers:

```bash
.venv/bin/python -m eval.object.segmentation_quality --output /tmp/segmentation-quality.json
```

The checked-in [QUALITY_RESULTS.json](QUALITY_RESULTS.json) was generated by that command. It includes
per-case input checksums, both full configurations and metrics. Each pair uses identical points, mask
memberships, visibility and annotated ownership. The floor is fitted to annotated floor samples to isolate
filtering from floor-estimation error. This is a controlled CPU consolidation benchmark, not SAM2 accuracy
on real images or a full pipeline acceptance benchmark.

Completeness and purity use one-to-one IoU matching, macro averaging and penalties for unmatched objects
or predictions. Split/merge errors count nonzero cross-owner overlaps; background leakage and lost object
points are reported separately. Candidate count is not the quality measure.

| Case | Completeness before → after | Purity before → after | Split errors | Merge errors |
|---|---:|---:|---:|---:|
| Prompt winner changes across views | 0.500 → 1.000 | 1.000 → 1.000 | 0 → 0 | 0 → 0 |
| Occluded appendage | 0.833 → 1.000 | 1.000 → 1.000 | 0 → 0 | 0 → 0 |
| Disconnected observed part | 0.833 → 1.000 | 1.000 → 1.000 | 0 → 0 | 0 → 0 |
| Nearby objects with fused views | 0.500 → 1.000 | 0.500 → 1.000 | 0 → 0 | 1 → 0 |
| Complementary prompts on one object | 1.000 → 1.000 | 1.000 → 1.000 | 0 → 0 | 0 → 0 |
| Broad mask bridges two objects | 0.500 → 1.000 | 0.500 → 1.000 | 0 → 0 | 1 → 0 |
| Disjoint fragments without identity evidence | 0.750 → 0.750 | 0.667 → 0.667 | 1 → 1 | 0 → 0 |
| Near-floor object | 0.750 → 1.000 | 1.000 → 1.000 | 0 → 0 | 0 → 0 |

Background leakage is zero before/after in these fixtures. Near-floor point completeness is 0 → 1.
Additional annotated ownership tests check seed theft, occlusion, non-seed ties, overlap abstention,
rotated Gaussian covariance and tilted floor normals. A separate test passes a low 50-Gaussian object
through prompt selection, candidate filtering, floor filtering, split and existing membership encoding.
Planar floor, below-plane, invalid-quaternion and untrusted-floor counterexamples remain excluded.

The isolated CPU runner test executes actual SAM2/lift orchestration with fake SAM2 and rasterization,
CUDA disabled. It compares legacy output arrays exactly with/without instrumentation, then exercises
refined overlap/seed ownership and checks persisted ObjectGS label encoding. It does not prove GPU behavior.

## Activation and diagnostic evidence

No UI/preset was changed. For a future explicitly authorized scene operation, the existing CLI accepts
`--refinement multiview_v1` alongside `--expected-revision` and the existing geometry choice. Do not run
this command as a read-only quality check: it invokes GPU providers and publishes a new scene revision.
Nothing in this task has resumed the thermally stopped Room process.

The operation-level override is validated, merges with sealed job controls and preserves other providers'
configuration. `objectify(..., scene_config={"scene": {"refinement": "multiview_v1"}})` is the corresponding
internal entry point. Omit it or select `legacy` to retain current production algorithm behavior.

Existing diagnostic artifacts retain mask/prompt decisions, visibility-conditioned votes, merge acceptance
and rejection reasons, group tie resolution, component retention, small-candidate qualification,
floor-shape removals, overlap abstention and anchored owner counts. Per-object diagnostic reports now
include merge decisions linked by the prompt list. Final provenance records `segmentation_refinement`;
lifting's method metadata distinguishes the opt-in path. All diagnostic quotas/failure behavior remain
as documented in the [evidence handoff](../2026-10-15-object-pipeline-evidence/HANDOFF.md).

## Remaining limits and real-scene gates

- No independently annotated real-scene comparison or new SAM2 inference was run. Do not enable this
  mode by default based on these fixture scores. Evaluate same-input baseline/refinement on annotated
  held-out scenes before making that decision.
- Fragments without overlapping identity evidence remain split. Distance alone cannot prove they are
  one object; the benchmark explicitly reports this unresolved case.
- A consistently wrong seed/mask can still be preserved incorrectly. Seed pinning assumes reliable
  multiview ownership; it cannot establish semantic identity from nothing.
- Anisotropic covariance is an imperfect floor cue. Flat legitimate feet may still be removed; thick
  floor artifacts can pass. Points inside the measured noise interval remain protected. Wall ownership
  outside the floor band is not solved by this floor-only model.
- Small 3D clutter can satisfy volumetric/noise tests. The unchanged opacity/crop and minimum point-count
  limits can still miss tiny or transparent objects. No class-specific semantic recognition was added.
- Conflict abstention can reduce usable ObjectGS observations; its existing validation may reject an
  insufficient dataset. No permissive ObjectGS fallback or fabricated mask/collider was added.
- Keeping prompt tracks/components increases CPU/memory work at high prompt counts. Real-scene runtime,
  camera inconsistency, heavy occlusion and quality at contact boundaries still need measurement.
- No browser, physics quality or Isaac Sim acceptance. No scene/GPU artifact was modified in this task.

## Verification and commits

- `3f547b79`: annotated baseline characterization and ownership metrics — 7 PASS at that milestone.
- `3a7a2669`: opt-in multiview, floor/candidate/ownership refinement and diagnostic integration — focused
  54 PASS, including isolated CPU runner, before the extra adversarial fixtures.
- `7ce1125d`: bridge-mask regression, unresolved identity holdout, benchmark command, downstream checks.
- Broad regression: **730 PASS in 76.08s** across scene, simulation, contracts, object diagnostics,
  scene extraction/queue/editor, processing presets and collision-source invalidation tests.
  Command/output: `/tmp/p087-refinement-regression.log` (temporary local log).
- After the final method/provenance metadata addition, related quality/ObjectGS/CPU runner tests:
  **23 PASS in 10.47s**, `/tmp/p087-refinement-final-metadata.log`.
- Ruff check `src/ tests/` plus changed eval/CLI files: **PASS**. Ruff format check: **648 files formatted**.
- Contract mirror: **PASS**. Frontend `npm run typecheck`: **PASS** (route generation + tsc).
- `git diff --check`: **PASS**. Graphify AST update: **PASS**; reports 37 files with no extracted symbols,
  which limits graph coverage and is not a runtime failure.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: explored SAMPro3D proposal/vote/merge/component functions, prompt selection/runtime pipeline,
  lifting, Gaussian split/floor helpers, geometric candidate gates, objectify controls/retries and reports;
  checked callers of changed shared functions and affected orchestration entry points.
- impact: opt-in seed generation/lifting/floor/candidate membership, operation CLI and diagnostic reports.
  Legacy algorithm/defaults and downstream producer implementations are preserved.
- understand: UNVERIFIED — understand-anything tools unavailable. Flow was traced directly through current
  request serialization, isolated runtime, membership bytes, ObjectGS handoff, revision/provenance and correction tests.
- minimal-code: reused existing Proposal/configs, evidence recorder, floor uncertainty, NumPy/SciPy and
  membership encoding. No new model, database, service, browser control or external dependency.
- checks: results above. ESLint/Vitest n/a — no frontend source changes. Typecheck passed.
- DevTools: n/a — no rendered UI changes. Browser/GPU/Isaac acceptance remains unverified.

The checked-in quality JSON was regenerated and byte-compared with a second independent invocation:
**identical**. `scripts/scene/reobjectify.py --help` was checked; only argument parsing ran, no scene operation.
Final Graphify refresh after code changes completed successfully: 24,003 nodes, 74,451 edges, 795 communities.
