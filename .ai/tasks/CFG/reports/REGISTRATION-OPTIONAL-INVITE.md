# Registration without an invitation

## Outcome

Owner request: leaving the invitation blank on the standard registration form creates a Guest account. Previously the form and request schema required a code, while guest signup was disabled by default.

The standard endpoint now delegates omitted, null, empty, or whitespace-only codes to the existing guest registration flow. Role assignment remains server-side. Nonblank invalid invitations still fail; valid invitations retain their assigned role. The existing guest flow preserves session cookies, rate limiting, quota and ownership rules.

Guest signup defaults to enabled in Settings, the environment example and Compose configurations. Explicit `AUTH_GUEST_SIGNUP_ENABLED=false` still supports invitation-only installations. ADR-0021 records the current owner policy without claiming cloud acceptance.

## Changed files

- Backend: `src/api/auth.py`, `src/config.py`.
- Frontend: `frontend/src/features/studio/auth/AuthForms.tsx`, `frontend/src/lib/api/auth.ts`.
- Configuration: `.env.example`, `docker-compose.yml`, `docker-compose.gpu.yml`.
- Tests: `tests/test_config.py`, `tests/test_api/test_auth_routes.py`, `frontend/tests/ux-account-auth.test.tsx`.
- Policy: `docs/decisions/0021-guest-identity-and-ownership.md`.

## Verification

- Focused backend suite: configuration, auth routes, role matrix, guest ownership, guest quota, and auth service — **97 passed**.
- Frontend auth suites: `ux-account-auth`, `auth-ui`, `auth-provider` — **17 passed**.
- Ruff lint/format checks on changed Python files, ESLint on changed frontend files, `tsc --noEmit`, and `git diff --check` passed.
- Local API restarted with guest signup enabled; `/api/v1/auth/me` advertises `guest_signup_enabled=true`.
- Chrome isolated browser context at `http://localhost:3010/register`: optional invitation explanation visible; invitation field `required=false`; completed identity fields with a blank invitation produce a valid form. No throwaway account was submitted to the live database. Account creation, role, session and quota were verified in isolated backend tests.
- `graphify update .` completed successfully.

## Gate report

- **codegraph:** explored registration routes, `AuthService.register_guest`, `RegisterForm`, and callers before changing source. Graphify query was used for navigation and the graph was refreshed after changes. Understand-anything tooling was unavailable.
- **minimal-code:** reused the existing guest flow; no new role, signup service, or privilege bypass.
- **checks:** results above are local executable evidence; no production or shared PostgreSQL acceptance is claimed.
- **report:** this document records scope, behavior and verification limits.
