# REC-02A — Deterministic Frame Extraction

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | `@awun0105` |
| Stage | `ST-FRAME-EXTRACT` |
| Target milestone | `M1` |

## 2. Goal

Extract a deterministic normalized RGB frame artifact from input that has passed
REC-02 validation/privacy gates.

## 3. Why This Task Exists

COLMAP, Brush and downstream fixture/producer contracts need immutable frame IDs,
timestamps, checksums and provenance. Frame extraction must not be hidden inside
REC-03 or confused with REC-07 LiDAR prefusion.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md),
[Contract](../../../TEAM_EXECUTION_CONTRACT.md),
[Integration Playbook](../../../INTEGRATION_PLAYBOOK.md),
[Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-02 successful input validation and acceptable PrivacyValidationReport.
- FFmpeg availability/version recorded by the worker runtime manifest.

## 5. Input Contract

- Checksummed RGB input ref from InputManifest.
- REC-02 validation/privacy evidence.
- Explicit extraction configuration with deterministic sampling/timestamp policy.

No evaluation-only artifact or TorWIC ZIP-layout assumption is allowed.

## 6. Output Contract

- Immutable normalized frame-set artifact under logical artifact URI.
- Ordered frame IDs, timestamps and per-frame or set checksum inventory.
- Extraction config/version and source-input provenance.
- Structured stage success/error record for `ST-FRAME-EXTRACT`.

## 7. Code Ownership

Create/modify only within:

- `src/services/reconstruction/`
- `tests/test_reconstruction/`
- task-local fixture/evidence paths when needed

Do not modify scene, simulation or product internals. Shared contract change
requires producer + consumer review.

## 8. Tool / Repository Strategy

Use FFmpeg via one project adapter/process boundary. Reuse decoding/extraction;
self-code deterministic command construction, frame inventory, artifact publish,
provenance and errors. Do not implement a video decoder.

## 9. Implementation Plan

2026-09-24 audit: FR-04 and the Track Guide require an explicit frame extraction
stage. The shared contract supplies `ArtifactRef`, `StageArtifact` and privacy
report, but no shared frame-set schema; keep the frame-set inventory internal to
EX-REC. `Aisle_CW` already has 1092 normalized PNGs; the REC-02 quality mask
selects 954 of the frozen 983 reconstruction IDs. Do not duplicate or delete
those PNGs. The video path decodes via FFmpeg 6.1.1 with explicit no-resampling
policy, preserves decoded PTS, and publishes only quality-accepted frames.

- Add `src/services/reconstruction/rgb/frames/frame_set.py` for a versioned ordered
  frame inventory, checksum validation and a direct REC-03 resolution interface.
- Add `src/services/reconstruction/rgb/frames/frame_extraction.py` for privacy/quality
  gates, source-byte verification, deterministic FFmpeg command, immutable
  publication and structured `ST-FRAME-EXTRACT` result/error.
- Add `src/services/reconstruction/adapters/torwic_frame_source.py` only at the
  dataset boundary to resolve the canonical normalized PNGs from the checksummed
  REC-02 inventory; generic extraction core remains dataset-agnostic.
- Add focused `tests/test_reconstruction/test_rec02a_frame_extraction.py` with
  synthetic frame/video, negative, resolver and real FFmpeg smoke cases.
- Audit source: installed FFmpeg 6.1.1; `Nannigalaxy/video-3d-reconstruction-gsplat`
  commit `9fae0190345a7080f680d20d1a0c2f45b1354a16`, MIT,
  `video_to_gsplat.sh` lines 61-69. Use FFmpeg CLI; treat the upstream shell
  as reference only. Its pre-extraction `rm -f` is unsuitable for immutable
  artifact publication. No upstream source copied.
- Run focused test, full suite, Ruff and a real Aisle_CW inventory/resolution
  smoke. REC-03 input adapter consumes the exact published frame-set and
  materializes COLMAP's temporary image directory automatically.

The real REC-02 quality report is bound to the REC-01 preparation manifest,
while the later rights-attested `InputManifest` has a different checksum. The
adapter accepts this only when `InputManifest.preparation_provenance` declares
the exact preparation and split checksums, and verifies every selected source
frame ID/checksum/timestamp. An undeclared lineage is rejected.

## 10. Tests

- Command/config determinism unit test.
- Stable frame ordering/timestamp/checksum test on tiny synthetic input.
- Invalid/unreadable input and privacy-gate negative tests.
- Artifact resolver/checksum contract test.
- Real FFmpeg smoke only when runtime is available; fixture proof is labeled separately.

## 11. Definition of Done

- [x] REC-02-cleared input produces a deterministic normalized frame artifact.
- [x] REC-03 consumes the artifact directly without manual conversion.
- [x] Logical URI, SHA-256, stage ID, config and provenance validate.
- [x] Failure is structured and no partial output is published as success.
- [x] Focused tests and observed evidence/limitations are recorded.

## 12. Result / Evidence

Producer and REC-03 input-consumer boundary complete.
Image-ref mode publishes a 954-frame inventory without copying PNGs; video mode
uses real FFmpeg decoding and source PTS with no FPS resampling. The source
repository is referenced only; no upstream code was copied.

- Real `Aisle_CW`: 983 REC-01 reconstruction IDs, REC-02 excluded 29 for blur,
  frame-set 954; first ID `0`, last `1091`; zero held-out overlap. All 954
  source PNGs and the frame-set envelope were re-resolved and byte checksummed
  through `TorwicFrameSource` + `FrameSetResolver`.
- Frame-set URI:
  `artifact://jobs/torwic-aisle-cw-rec02a/rec02a/frame_set.json`; byte SHA-256
  `sha256:08201a6075a2b3b7d6e530744eaaf7798b0d2f3dddd89bf53971d565267fde66`;
  logical content checksum
  `sha256:549abc1fd1d872d30a8c77c42345b3ba22104ac7abdae9376f06dc8f1d7bf7d8`.
  Local artifact under ignored `data/torwic_slam/derived/aisle_cw/rec02a_artifacts/`.
- `.venv/bin/pytest tests/test_reconstruction/test_rec02a_frame_extraction.py -q`:
  5 passed, including a real 3-frame FFmpeg 6.1.1 video smoke, checksum
  resolver, privacy/timestamp negative, declared-lineage and COLMAP input
  consumer tests.
- Real REC-03 input smoke called `ColmapInputAdapter.prepare` with the exact
  954-frame published artifact and TorWIC source adapter: 954 workspace PNGs,
  first/last IDs `000000`/`001091`, matching checksum and independent inode.
  Workspace copies are temporary and cannot mutate canonical normalized PNGs.
- `.venv/bin/pytest tests/ -q`: 193 passed. `.venv/bin/ruff check src/ tests/
  scripts/torwic` and `.venv/bin/ruff format --check src/ tests/ scripts/torwic`:
  pass. New source functions meet the 30-line/3-parameter rule (excluding
  `self`). `git diff --check`: pass.
- Limitation: the REC-03 input consumer is proven; COLMAP feature/match/mapper
  execution and camera pose artifact remain REC-03 work.
