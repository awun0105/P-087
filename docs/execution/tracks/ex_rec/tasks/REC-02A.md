# REC-02A — Deterministic Frame Extraction

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
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

Assignee fills exact files, command shape, timestamp policy and proof after
inspecting the real manifest/tool environment. Do not change task scope.

## 10. Tests

- Command/config determinism unit test.
- Stable frame ordering/timestamp/checksum test on tiny synthetic input.
- Invalid/unreadable input and privacy-gate negative tests.
- Artifact resolver/checksum contract test.
- Real FFmpeg smoke only when runtime is available; fixture proof is labeled separately.

## 11. Definition of Done

- [ ] REC-02-cleared input produces a deterministic normalized frame artifact.
- [ ] REC-03 consumes the artifact directly without manual conversion.
- [ ] Logical URI, SHA-256, stage ID, config and provenance validate.
- [ ] Failure is structured and no partial output is published as success.
- [ ] Focused tests and observed evidence/limitations are recorded.

## 12. Result / Evidence

Pending implementation.

Expected evidence: focused test command/output, representative frame inventory,
artifact URI/checksum and runtime/tool version status.
