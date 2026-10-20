# CFG-11: Backend/API audit

Status: PASS - Ready for Frontend Layer.

## Evidence scope

Audit of current commits `7bfbe3dd`, `3f1f17ec` and `8b782762`. HTTP requests use the real FastAPI application through HTTPX ASGI transport and temporary persistent databases/artifacts. The executable backend prefix is `/api/v1`; no production deployment, new GPU reconstruction, Isaac simulation or browser acceptance is implied.

## Scenario matrix

The task says 12 combinations. Input type × environment × subject scope produces 12; testing all three capacity targets produces 36. Every valid combination returns HTTP 200 and a typed recommendation/evaluation. All 36 are covered in `test_suggestion_preserves_scenario_intent_and_evaluation`; malformed choices return 422 and inadequate known GPU capacity returns 409 as intended.

| Input | Environment | Subject | Preset | Matching |
| --- | --- | --- | --- | --- |
| Continuous video | Indoor | Object | video_single_object | sequential |
| Continuous video | Indoor | Room | video_indoor_walkthrough | sequential |
| Continuous video | Outdoor | Object | video_single_object | sequential |
| Continuous video | Outdoor | Room | video_outdoor_forward | sequential |
| Loop video | Indoor | Object | video_single_object | sequential_vocab_tree |
| Loop video | Indoor | Room | video_indoor_orbital_360 | sequential_vocab_tree |
| Loop video | Outdoor | Object | video_single_object | sequential_vocab_tree |
| Loop video | Outdoor | Room | video_outdoor_forward | sequential_vocab_tree |
| Photo set | Indoor | Object | photo_collection_indoor | exhaustive |
| Photo set | Indoor | Room | photo_collection_indoor | exhaustive |
| Photo set | Outdoor | Object | photo_collection_outdoor | exhaustive |
| Photo set | Outdoor | Room | photo_collection_outdoor | exhaustive |

Single-object scenarios retain max_objects=1. Indoor room scenarios select external fill 1.6 m; outdoor room scenarios select floor fill 1.6 m. Object scenarios disable both fill operations. Outdoor scenarios disable the exported ground plane. Resource estimates are heuristic and scale known SFM/3DGS drivers; they are not a guarantee of GPU fit or scene quality for all downstream providers.

## Options and dispatch

- Options expose 35 parameters across six groups, eight complete catalog presets and machine_maximum.
- All eight presets are sealed, loaded through checksum verification and resolved into the native tool dictionaries and sampling values.
- Pre-extension eleven-key job artifacts preserve their original tool controls and empty added groups.
- Real two-group legacy profile files remain dispatchable with sampling defaults; independent group factories prevent state sharing between resolves.
- Upload and idempotent input-assembly HTTP creation persist the selected groups into checksum-bound job artifacts. Existing shared builders required no new persistence path.
- Geometry reaches the captured finalize request and native voxel config. Objectify provider controls survive retries. Simulation ground-plane strings are normalized at the job boundary while native physics remains strict.

## Repair discovered by the audit

The initial full regression run had 1268 passes and one failed role inventory check. Its inventory omitted the new stateless suggestion endpoint and three earlier upload/camera routes. Actual router guards were inspected; the test inventory now classifies suggestion as public calculation, and upload/camera mutations as authenticated. All six role-matrix tests pass. No authentication guard was weakened.

## Verification

- Required six suites: 190 passed, no skips; `CFG11-REQUIRED-SUITES.log`.
- Additional explicit dispatch/legacy coverage: 13 passed; `CFG11-DISPATCH-VERIFICATION.log`.
- Role matrix after repair: 6 passed; `CFG11-ROLE-MATRIX.log`.
- Complete orchestration/API rerun: 1269 passed, no skips, 15 HTTPX cookie-deprecation warnings; `CFG11-BACKEND-REGRESSION.log`.
- `ruff check src/api/ src/services/orchestration/`: clean.
- `ruff format --check src/api/ src/services/orchestration/`: 142 files already formatted; `CFG11-STATIC-CHECKS.log`.
- Changed test files pass Ruff check and format check. `git diff --check` is clean.

## Gate conclusion

PASS - Ready for Frontend Layer. All named requirements, the 36-case HTTP matrix, options payload, both legacy dispatch paths and the complete API/orchestration regression suite have executable evidence. The new legacy-file case was added after the full suite collected tests and was verified separately in the 13-case dispatch run. Frontend implementation and browser acceptance remain later gates.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: inspected role inventory, current camera/upload guards, processing contracts and their consumers.
- impact: test-only route classification and dispatch regression coverage; production behavior unchanged.
- understand: n/a for test-only repair; authorization and configuration flows checked against current source.
- minimal-code: updated the existing role inventory and reused existing config/resolver/profile helpers for legacy coverage.
- checks: results above; TypeScript/eslint/vitest n/a for this backend audit.
- DevTools: n/a — no rendered UI change.
