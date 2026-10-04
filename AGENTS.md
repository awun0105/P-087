# Real2Sim Studio Coding Agent Harness

This file is the entrypoint for every AI coding agent working in the AI20K RAV-01 (Real2Sim Studio) repository.

---

## Always-on Instructions & Sub-rules

Reference and adhere to the following core documents:
- @GUIDE.md (13 technical rules, coding mindset, and pre-flight gates)
- @plain-prose.md (Concise, direct, fluff-free communication, respectful tone)

### Pre-flight Gates (Summary from GUIDE.md Rule 13)
All code changes must be executed with an attached summary report:
1. **codegraph**: Use `codegraph_explore` / `codegraph_callers` before modifying source code to understand links and blast radius.
2. **minimal-code**: Write only the minimum amount of code to solve the problem, do not add abstractions or speculative features.
3. **checks**: Run static checks and related test suites (`ruff check`, `ruff format --check`, `pytest <focused paths>`).
4. **report**: Provide a concise report following the pre-flight gate format.

---

## 1. Non-Negotiable Core Rules

1. **Repository is System of Record:** Chat memory and conversational inferences do not create product policy.
2. **Strict Scope:** Only implement the outcome requested by the user. Do not expand the scope or modify code when only asked to review/diagnose.
3. **Preserve Scaffold & Source:** Do not rename, move, or delete source scaffolds without permission; do not modify outside the task boundary.
4. **Evidence-based:** Do not claim `DONE` or "pass" without executable evidence.
5. **Conflict Protocol:** When documents or requirements conflict, stop at that boundary, state the conflict, and ask the user. Do not guess.
6. **Security:** Absolutely no hardcoded secrets, API keys, credentials, or sensitive paths. Use `.env` and `Settings`.
7. **Git Safety:** Do not commit, push, create PRs, change branches, or perform destructive git operations (force-push, reset --hard) unless explicitly requested.

---

## 2. Authority Map

Technical decisions follow specific authorities:

| Decision | Authoritative Source |
| --- | --- |
| Product scope, priority, user behavior, acceptance | `docs/PRD.md` |
| Dataset preparation, split, evaluation protocol | `docs/DATASET_PLAYBOOK.md` |
| Shared contracts, schemas, runtime rules | `docs/execution/TEAM_EXECUTION_CONTRACT.md` |
| Canonical repository placement & architecture | `ARCHITECTURE.md` |
| Studio Web UX / Viewer interaction | `docs/STUDIO_UX_SPEC.md` |
| Integration strategy & reusable baseline | `docs/execution/INTEGRATION_PLAYBOOK.md` |
| Task-local scope, I/O, DoD | assigned `tasks/<TASK-ID>.md` |
| Current executable behavior | Code + Tests + Runtime Evidence |

---

## 3. Canonical Ownership Boundaries

- `src/models/contracts/`: Shared artifact contracts (no track internals).
- `src/services/reconstruction/`: `EX-REC` pipeline (Brush/3DGS/Colmap/SuperSplat).
- `src/services/scene/`: `EX-SCENE` pipeline (Physics/Asset/Scene Composition).
- `src/services/simulation/`: `EX-SIM` pipeline (Isaac Gym/Sim runtime).
- `src/services/orchestration/`, `src/api/`, `frontend/`: `EX-PRODUCT` (Web Studio, REST/WS APIs, Background jobs).
- `tests/`: Corresponds to each boundary (unit, contract, integration, e2e).

---

## 4. Code Quality & Standards

### Python (Backend)
- Full type hints for function/method signatures.
- Pydantic models for Data Transfer Objects (FastAPI I/O, schemas).
- Catch specific exceptions; no bare `except` or silent swallowing of errors.
- Linter/Formatter: `ruff check` and `ruff format`.

### TypeScript / Frontend
- Typed domain models, do not abuse `any`.
- Clear separation: Render state, API state, Domain commands.
- GPU/PlayCanvas/3DGS Lifecycle Management: Must cleanup listeners, frame callbacks, and GPU buffers on unmount to prevent memory leaks.

---

## 5. Verification & Testing Baseline

Before concluding changes, run the appropriate checks:

```bash
# Linting & Formatting
ruff check src/ tests/
ruff format --check src/ tests/

# Testing
pytest <focused_test_path> -v
```

---

## 6. Handoff Summary Format

Follow the spirit of `plain-prose`: concise and focused:

1. **Outcome:** Achieved result (or blocker if any).
2. **Changed Files:** List of files actually modified.
3. **Verification:** Commands run and actual verification output.
4. **Gate Report:** Pre-flight gates report if there are code changes.
