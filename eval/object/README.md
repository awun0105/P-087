# Object evaluation

`segmentation_quality.py` evaluates exclusive Gaussian/point ownership against annotations. It uses
one-to-one IoU matching and reports macro completeness, macro purity, split/merge errors, background
leakage and object points returned to background. Unmatched objects/predictions are penalized; merely
adding candidates cannot raise every score. Any nonzero cross-object overlap counts as a split/merge
association in these small fixtures; this is not a calibrated real-dataset noise tolerance.

Run the deterministic CPU benchmark from the repository root:

```bash
.venv/bin/python -m eval.object.segmentation_quality --output /tmp/segmentation-quality.json
```

Each comparison replays exactly the same points, annotated ownership, masks and visibility through
`legacy` and `multiview_v1` consolidation. Inputs have checksums. The floor is fitted to the annotated
floor samples to isolate filtering from floor-estimation error. The report evaluates consolidation,
not SAM2 image accuracy, GPU training, full scene quality or physics. The unresolved disjoint-fragment
case is retained in the report instead of silently omitted from acceptance.

`ownership_metrics(truth, predicted)` also accepts aligned annotation/prediction arrays from an external
benchmark; labels are exclusive integer IDs and `-1` is background. Real-scene annotation remains needed.
See the segmentation refinement handoff under `docs/plans/active/2026-10-15-segmentation-refinement/`.

`collision_quality.py` evaluates separate collision-quality protocols. Segmentation scores do not
constitute collision/browser/Isaac acceptance.
