## 1. Think before coding

State your assumptions. If a request has more than one interpretation, list them — don't pick silently.
If a simpler approach exists, say so and push back. Ask only when the answer changes what gets built
and you can't find it in the code, the task, or the rules (product behaviour, architecture, public API).
Otherwise pick the most reasonable reading, state it as an assumption, and keep going.

## 2. Simplicity first

Minimum code that solves the problem. No speculative features, single-use abstractions,
unrequested configurability, or error handling for impossible cases.
If 200 lines could be 50, rewrite it. Would a senior engineer call it overcomplicated? Then simplify.

## 3. Surgical changes

Touch only what the request needs. Don't "improve" adjacent code, comments, or formatting,
and don't refactor what isn't broken. Mention unrelated dead code — don't delete it.
Remove only the imports/variables/functions that YOUR change orphaned.
Every changed line should trace to the request.

## 4. Goal-driven execution

Turn each task into a verifiable goal ("fix the bug" → "a test reproduces it, then passes"; for a
UI-only bug, state how you reproduced and verified it). For multi-step tasks, state a short plan with
a verify step per item, and loop until verified.

## 5. Surface conflicts, don't average them

If two existing patterns contradict, don't blend them. Pick the more recent / more tested one,
say why, and flag the other for cleanup.

## 6. Read before you write

Before adding code to a file, read its exports, its immediate caller, and the obvious shared utilities.
If you don't understand why existing code is structured the way it is, find out (callers, git history,
understand-anything); ask only if that doesn't answer it.
"Looks orthogonal to me" is the most dangerous phrase in this codebase.

## 7. Tests verify intent

Each test encodes WHY the behavior matters. A good test fails when the business logic it protects changes.

## 8. Checkpoint after every significant step

Summarize what was done, what's verified, what's left. If you lose track, stop and restate.

## 9. Match the codebase's conventions

Conformance beats taste: follow the nearby pattern even if you'd do it differently.
If a convention looks harmful, raise it — don't fork it silently.

## 10. Fail loud

If you can't be sure something worked, say so. "Tests pass" is wrong if you skipped any;
"feature works" is wrong if you didn't verify the edge case asked about.

## 11. Use codegraph first

Navigate **code** with codegraph — symbols, callers, callees (`codegraph_explore` is usually the only
call you need). Use `grep` / `git grep` only where codegraph can't see: string literals, i18n keys,
JSON / CSS / config / markdown, code on another ref (`git grep <ref>`, `git show <ref>:<path>`), or
when the index returns nothing or is stale. If codegraph is down, say so once
(`UNVERIFIED: codegraph — <reason>`) and continue with search.

## 12. Understand the business

Before refactoring, or changing old, unfamiliar, or business-critical code, build the business context
first (Rule 13, Gate 3). A small, local change in code you have just read doesn't need it.

## 13. Pre-flight gates

A task that changes code runs the gates that apply and ends its summary — and the PR description —
with the gate report below. No code change → no report. A gate that cannot run is reported as
`UNVERIFIED: <gate> — <reason>` — never silently skipped, never reported as passing.
**Small change** (a few lines, no shared/exported symbol, e.g. a typo, a translation, a style tweak):
one line is enough — `Pre-flight: small change — <what you verified>`.

**Pre-code**

1. **codegraph** (Rule 11) — start with `codegraph_explore`; use `codegraph_node` /
   `codegraph_callers` for a dependent you're unsure about. _State_ what you read.
2. **Blast radius** — run `codegraph_callers` on every shared/exported symbol you change
   (component, hook, slice/thunk, selector, service method, util); repeat on exported callers.
   _State_ who is affected, or "no external callers".
3. **Business context** (Rule 12) — only for old, unfamiliar, or business-critical code: run
   `understand-anything:understand-explain` (or `understand-domain` for a flow). _State_ the flows.
4. **Minimal code** (Rule 2) — after you understand the flow, before non-trivial code, stop at the
   first rung that holds: (1) does it need to exist? (2) already in this codebase — helper, hook,
   wrapper, MUI default (`components.md` → Reuse before building)? (3) stdlib / lodash? (4) native
   platform or MUI feature? (5) an installed dependency? (6) one line? (7) only then, minimum code.
   A bug fix fixes the shared function once (check its callers), not only the path the ticket names.
   A deliberate simplification with a known ceiling gets a `ponytail:` comment naming the ceiling.
   Never cut input validation, data-loss error handling, security, or accessibility. _State_ the rung.
   (Ladder from [ponytail](https://github.com/DietrichGebert/ponytail), MIT — no plugin needed.)

**Post-code**

5. **Checks** — `npx tsc --noEmit`, `npx eslint <changed files>`, `npx vitest related <changed files> --run`.
   _State_ the results. Report new errors you introduced; note pre-existing ones, don't fix them unless asked.
6. **DevTools** — required when rendered UI or runtime behaviour changes (not for types, tests,
   UI-free services, docs, constants, config). The teammate runs `npm start` → picks tenant → logs in;
   the agent attaches via the `chrome-devtools` MCP, opens the screen, takes a snapshot, and lists
   console messages (plus network requests if a request changed). No session →
   `UNVERIFIED: DevTools — no logged-in session`. MCP not connected →
   `UNVERIFIED: DevTools — MCP not connected` and ask the teammate to restart it (`/mcp`).
   Never claim the UI works, and never swap in another browser tool without saying so.

**Gate report**

```
Pre-flight (GUIDE.md Rule 13)
- codegraph:    <files/symbols read>
- impact:       <affected callers, or "no external callers">
- understand:   <flows involved, or "n/a — trivial/net-new code">
- minimal-code: <ladder rung, e.g. "rung 2 — reused X">
- checks:       tsc <clean | N new errors>, eslint <…>, vitest <N passed / N failed | no related tests>
- DevTools:     <screen> renders, console clean | UNVERIFIED: <reason> | n/a — no UI change
```
