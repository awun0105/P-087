# Deployment checkpoint — 2026-10-19

Deployment remains incomplete. GPU provisioning remains disabled. No GPU Pod has been created in this deployment attempt; paid GPU usage so far is USD 0 of the approved USD 5 total.

## Changes captured

- Supply a User-Agent for RunPod API requests and accept nullable inventory fields without crashing. Availability and price still require live verification before provisioning.
- Install SuperSplat build dependencies explicitly in Vercel production builds.
- Use a production TypeScript project excluding vendor sources and tests that depend on fixtures outside the frontend deployment root. Keep the regular typecheck command unchanged.
- Publish demo members with four bounded network workers and serialize extraction from the shared ZIP. An earlier concurrent publication failed with `BadZipFile: Overlapped entries`; the corrected publication is being retried. Do not treat it as verified until all objects and the archive have completed publication.
- Remove an unsupported explicit Railway builder value. Railway now rejects legacy Config as Code updates; runtime deployment configuration still needs integration and validation through the supported service settings or Infrastructure as Code.

## Actual cloud evidence

- Vercel Studio project `real2sim-studio` was created separately from the landing page. Preview `https://real2sim-studio-k21gaaurv-promaxima1.vercel.app` reached READY. Backend wiring, public access and production acceptance remain unverified.
- Railway project `real2sim` has an API deployment submitted, a volume mounted at `/app/data`, and domain `https://api-production-c5570.up.railway.app`. Build/startup, bootstrap peak storage and application readiness remain unverified.
- R2 bucket is `real2sim`. Three-demo library publication is incomplete. Existing EgoBlur weights were uploaded; full remote checksum verification is still in progress.
- Supabase connection succeeded. Application migrations, queue operation and demo isolation on the deployed service remain unverified.
- RunPod API credentials work and the account lists no Pods. No image qualification or scale 0 → 1 → 0 verification has occurred.
- Organization GHCR denied package creation. Personal registry accepted authentication. No worker image has been published yet.

## Repository authorization

The organization repository remains private. The user explicitly authorized keeping `awun0105/P-087` public and pushing current changes to its `master` branch, in addition to `origin/develop`. Deployment may use the personal repository as fallback. Secrets remain outside Git.

## Verification

- Focused Ruff lint and formatting checks: passed.
- Frontend production TypeScript check and changed Next config ESLint: passed before this checkpoint.
- Actual Vercel preview build: READY.
- `git diff --check`: passed before staging.
- Automated tests were not rerun, following the user's instruction.
- No rendered browser, live pipeline, GPU qualification or scale-to-zero success is claimed.

## Pre-flight — GUIDE.md Rule 13

- codegraph: inspected `publish_library`, its CLI caller and artifact publication dependencies; prior provider call paths were inspected during deployment diagnosis.
- impact: demo release CLI, RunPod inventory/transport and frontend production builds.
- understand: existing immutable demo publication and deployment bootstrap; no queue or authentication redesign.
- minimal-code: standard library bounded executor and extraction lock; existing configuration and provider reused.
- checks: focused Ruff clean; production tsc and Next config ESLint clean; tests not rerun by user instruction.
- DevTools: unverified; production browser acceptance pending.
