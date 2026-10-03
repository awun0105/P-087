# Real2Sim Studio deployment handoff

This directory contains reviewable production configuration templates.  It
does not contain credentials and it does not deploy an account or mutate
Railway, Supabase, Cloudflare, Vast.ai, RunPod, or Vercel.  The accepted
topology is Vercel for the Next.js UI, Railway for the FastAPI control server,
Supabase PostgreSQL for RuntimeDatabase, Cloudflare R2 for immutable artifact
objects, and an ephemeral GPU worker on Vast.ai with RunPod as fallback.

## Service split

Use [`api.env.example`](api.env.example) for the Railway API service,
[`worker.env.example`](worker.env.example) for `Dockerfile.gpu`, and
[`web.env.example`](web.env.example) for the Vercel project.  Empty values in
these files are intentional required inputs.  They must be filled in the
provider secret stores; they are not production defaults.

Railway injects `PORT`; the API image `Dockerfile` listens on that port
and includes the pinned API-side `splat-transform` runtime.  It exposes
`/health`.  The manifest starts the repository-owned
`python -m scripts.studio.container_entrypoint serve`, which performs the data/auth checks
and then resolves Railway's `PORT` before exec'ing Uvicorn.  Do not replace it
with a bare `uvicorn ... --port $PORT` command: a custom Railway command
overrides the Docker image entrypoint and an exec-form command does not expand
`$PORT`.  [`railway-api.json`](railway-api.json) is an operator manifest
because it lives below `deploy/studio/` and Railway discovers `railway.json` or
`railway.toml` from the service source root.  When creating the API service,
copy the manifest to the selected repository root or enter the same build and
deploy settings in the service configuration.  The service source root must
contain `Dockerfile` and the rest of the repository build context.
Railway's current documentation marks
this config-as-code format as transitional, so confirm the provider's IaC
format before a long-lived rollout.

The Vercel project root is `frontend/`.  Set `REAL2SIM_API_URL` to the public
Railway origin at build time, run `npm ci`, and use the editor-aware build
command:

```text
npm run build:editor && npm run build
```

The first command creates `public/editor`, which `EditorFrame` serves.  Set
Vercel Build and Deployment **Node.js Version** to `24.x`; this matches the
repository CI baseline.  Do not put `DATABASE_URL`, R2 keys, worker tokens, or
an LLM key in Vercel variables or browser-exposed variables.

## Supabase and R2 inputs

`DATABASE_URL` must be the Supabase **shared pooler, session mode** connection
string copied from the Dashboard Connect dialog.  Use port `5432` and append
`?sslmode=require` (or configure `verify-full` with Supabase's CA certificate).
Do not guess the pooler host or rewrite the username; the shared session pooler
uses a project-qualified username.  Keep Railway, Supabase, and R2 in the same
region where possible.  The API and worker use the standard PostgreSQL wire
connection; they do not use Supabase Auth, the Supabase Storage API, or browser
direct database access.

This application does not use the Supabase Data API.  Disable the Data API for
the project if it is not needed.  If the Data API must remain enabled, expose
no `r2s_*` tables to `anon` or `authenticated`, revoke their table/sequence/
routine grants, and enable RLS with deny-by-default policies before importing
data.  The FastAPI service connects through PostgreSQL and needs its own
database role grants; do not make the tables public merely to make the app
work.  Verify the effective grants and exposed schema in the Supabase
Dashboard/SQL editor before accepting a deployment.

For R2, set one bucket and one shared `ARTIFACT_S3_PREFIX` (for example
`prod`) in both API and worker.  Configure R2 CORS with the exact Vercel origin
and `GET`, `HEAD`, and `PUT`; expose `ETag`.  Keep the lifecycle rule that aborts
incomplete multipart uploads after one day.  Artifact keys remain logical
`jobs/<namespace>/<path>` under that prefix; the bucket name and credentials
never enter a contract or database payload.

## Importing a verified package into production

The SQLite package is a staging input, not a production database.  It must be
created from a quiescent workstation state and a valid account policy.  The
publisher refuses active jobs, active scene requests, sessions, invites,
worker leases, reservations, invalid account credentials outside the explicit
two-user keep policy, corrupt archives, path traversal, missing artifact
references, and checksum mismatches.

First set `DATABASE_URL` in the operator shell.  For the default non-mutating
check, run the command below.  The publisher reads all credentials only from
environment variables; it does not accept a database URL on the command line.

```bash
python -m scripts.cloud.package_publish \
  --package /secure/inbox/r2s-studio-data.zip \
  --report /secure/out/package-publish.json
```

The default command verifies the ZIP with `scripts/studio/data_package.py`,
checks that all imported product and attribution tables are empty, and exits
without creating a schema or writing either target.  To perform the actual
handoff, supply the R2 variables and add the explicit mutation switch:

```bash
export ARTIFACT_S3_BUCKET=...
export ARTIFACT_S3_ENDPOINT=...
export ARTIFACT_S3_ACCESS_KEY_ID=...
export ARTIFACT_S3_SECRET_ACCESS_KEY=...
export ARTIFACT_S3_PREFIX=prod
python -m scripts.cloud.package_publish \
  --package /secure/inbox/r2s-studio-data.zip \
  --apply \
  --report /secure/out/package-publish.json
```

The same operator command can use the built API image without installing
Python dependencies on the host. Put the database/R2 variables in an operator
secret env file, mount the verified ZIP read-only, and explicitly override the
web server entrypoint:

```bash
docker run --rm --entrypoint python --env-file /secure/publish.env \
  --mount type=bind,src=/secure/inbox/r2s-studio-data.zip,dst=/package/r2s-studio-data.zip,readonly \
  real2sim-studio-api -m scripts.cloud.package_publish \
  --package /package/r2s-studio-data.zip
```

This remains a dry-run; add `--apply` to the publisher arguments only for the
actual import. The entrypoint override is required because the normal API
entrypoint bootstraps auth, while the publisher must inspect an empty target
before any users are written. This command needs local temporary disk space for
the full unpacked package. Use a writable staging mount and `TMPDIR` if the
operator's Docker storage is too small.

With `--apply`, the tool runs the repository's canonical RuntimeDatabase
migrations on the target, checks that all imported product, audit/history, and
attribution tables are empty, uploads each logical artifact with its exact
SHA-256 metadata, verifies the remote object after upload, and only then
inserts rows in one database transaction.  It never drops, replaces, or
truncates an existing database.  Retrying after a network interruption is
safe for already verified object keys; a key with a different checksum is
refused.  If the row transaction fails after uploads, the database remains
uncommitted and the same package can be retried after the cause is fixed;
orphaned immutable objects must be reviewed by an operator.

The command emits counts and package commit metadata only; it does not print
credentials.  Historical resource usage and audit rows are migrated with the
product rows so the jobs view keeps requester/reviewer context and telemetry;
sessions, invites, worker leases, and resource waits are never migrated.

After importing a `scrub-all` package, create the first production Reviewer with
the repository-owned CLI. The current two-seed package already has an active
Reviewer, so skip this step unless the owner wants an additional account.
Supply the password through the environment or an interactive prompt;
the command never prints it:

```bash
export R2S_BOOTSTRAP_PASSWORD='use-a-secret-manager-value'
python -m src.services.orchestration.auth.cli create-user \
  --email reviewer@your-domain.example \
  --name 'Production Reviewer' \
  --role reviewer
unset R2S_BOOTSTRAP_PASSWORD
```

The package manifest records an explicit account policy.  In the default
`scrub-all` mode, imported users are disabled attribution records with the
literal password marker `disabled-in-data-package`; no reusable password is
migrated.  The `keep-seed-accounts` or `keep-selected-passwords` mode is an
explicit exception that must name exactly two source users.  Those two users
retain their email, role, active state, and existing password hash, so they can
log in with the same credentials after import.  The publisher never prints
password hashes or plaintext passwords.  Sessions and invites are always
empty in the package, so preserved accounts must sign in again and subsequent
Editors are created through the Reviewer invite flow.  If the package uses
`scrub-all`, create the first production Reviewer with the CLI above.

## Optional demo, preview, and Rerun data

`data/studio_local/artifacts` is the only local data family currently covered
by the production publisher.  `data/demo/library`, `data/asset_previews`, and
`data/rerun_recordings` are optional local paths in `Settings`, not logical
artifact references.  They are therefore **not mirrored by the publish/apply
step into shared R2 state** and must not be described as shared production
state.

The source now includes all 34 CC0/procedural catalog previews under
`configs/product/catalog_previews/` (ADR 0010 section 3). They travel with the
source/image and take priority in every environment. Converted Isaac GLB files
are only a fallback when no CC0 preview exists and the deployment permits it;
`PRODUCT_ISAAC_ASSET_PREVIEWS` disables that fallback by default in
staging/production. Provisioning the old data does not override this boundary.

For a single Railway API service that must retain the current optional views,
provision one Railway volume mounted at exactly **`/app/data`**.  This is the
same path used by `Dockerfile` for the portable data boundary.  Set the
following API variables before the first deploy:

```text
PRODUCT_DEMO_DIR=/app/data/demo/library
PRODUCT_ASSET_PREVIEW_DIR=/app/data/asset_previews
PRODUCT_RERUN_RECORDING_DIR=/app/data/rerun_recordings
ARTIFACT_ROOT=/app/data/studio_local/artifacts
PRODUCT_WORKER_ROOT=/app/data/studio_local/workers
PRODUCT_TRASH_ROOT=/app/data/studio_local/trash
CHROMA_PERSIST_DIR=/app/data/studio_local/chroma
RAILWAY_RUN_UID=0
R2S_PREPARE_VOLUME=true
```

Railway mounts volumes as root and does not mount them during pre-deploy.
The container entrypoint prepares the fixed data directories when
`R2S_PREPARE_VOLUME=true`, then drops to `appuser` UID 1000 before serving the
API. Do not move provisioning to a pre-deploy hook. The sibling
`studio_local/thumbnail_cache` path then matches the packaged thumbnail cache.
See [Railway volume availability and permissions](https://docs.railway.com/volumes).

Create the subdirectories with the same names shown above and keep the volume
outside the container image.  To seed only these optional families from a
verified ZIP without touching the production database or R2 artifacts, run the
publisher's explicit `provision` command inside the API service (or an
equivalent one-shot Railway shell) after the volume is mounted:

```bash
PACKAGE=/app/data/r2s-studio-data.zip
TMPDIR=/app/data python -m scripts.studio.container_entrypoint serve \
  python -m scripts.cloud.package_publish provision \
  --package "$PACKAGE" \
  --target-root /app/data
```

One concrete way to transfer the ZIP is `railway volume files upload` to the
attached volume, then run `provision` through the linked service's shell. For
example, uploading it as `/r2s-studio-data.zip` makes the package available to
the container as `/app/data/r2s-studio-data.zip`. Supply that actual path to
`--package`; `/secure/inbox` above is only an operator example. Keep the package
out of the Git/Docker build context.

The command verifies and unpacks the ZIP into a temporary empty root through
the shared package verifier, then merges only `demo/library`, `asset_previews`,
`rerun_recordings`, and `studio_local/thumbnail_cache`.  Existing equal files
are skipped; a different checksum aborts before copying.  It deliberately does
not copy `runtime.db` or `studio_local/artifacts`; those are handled by the
Postgres/R2 publisher.  It also does not set `R2S_DATA_ARCHIVE` or
`R2S_RESTORE_DATA` on the production service, because automatic full-package
restore could replace the wrong database.  This volume makes the paths survive
a Railway image redeploy, but it is a single-service cache: it is not visible
to a GPU worker, does not provide cross-region replication, and Railway volume
deployments can have downtime during replacement.  Back up the volume
separately and do not run multiple API replicas while these views depend on it.
The durable multi-host solution remains to publish these files under a versioned
R2 prefix and add an artifact-backed resolver contract; until that is
implemented, this `/app/data` volume procedure is the concrete production
choice for one Railway instance.

Run that command with the API environment after importing metadata and ensuring
an active Reviewer exists. The entrypoint applies the documented root-volume
preparation and drops to `appuser`, so provisioned files remain owned by the API
user. The uploaded ZIP must be readable by that user. `TMPDIR=/app/data` puts
temporary extraction on the mounted volume rather than the provider's small
ephemeral `/tmp`. The shared unpacker currently extracts the full package even
for optional provisioning: allow free space for the approximately 2.97 GB
unpacked payload plus the copied auxiliary files, in addition to the ZIP already
on the volume. The temporary extraction is removed when the command exits.

## Worker and runtime-manifest boundary

`Dockerfile.gpu` contains native COLMAP and the pinned Brush/splat-transform
tools; it does not require nested Docker.  The worker host still needs a real
NVIDIA runtime and Vulkan ICD.  Before accepting a worker, run its image
preflight and record the actual COLMAP/Brush/scene-runtime identity.  The API's
`PRODUCT_PROCESSING_CONFIG` and `PRODUCT_RUNTIME_MANIFEST` must be supplied as
a matched pair from an accepted worker baseline.  A manifest copied from the
laptop or fabricated from defaults does not prove that the rented worker can
execute the pipeline.

Use a new empty state directory on the actual NVIDIA worker host for each
accepted runtime baseline. After filling the worker environment in the host
secret store, this command runs the image preflight and writes its real
`runtime_manifest.json` into that state directory:

```bash
docker run --rm --gpus all --env-file /secure/worker.env \
  --mount type=bind,src=/secure/worker-state,dst=/data \
  your-registry/real2sim-gpu:accepted-tag preflight
```

The image entrypoint calls `scripts.gpu.make_runtime_manifest` from actual
worker probes before preflight. The source state directory must already exist
and contain no previous manifest. Keep the preflight output and use the
repository-owned `ExecutionProfile.load` to verify the matched preset and
canonical manifest checksum. Upload only the accepted worker manifest into the
Railway volume at `/studio_local/runtime_manifest.json` using
`railway volume files upload`; the API then sees
`/app/data/studio_local/runtime_manifest.json`. Set both commented profile paths
in `api.env.example` and redeploy the API. The API and worker must use the same
preset contents and manifest checksum; this transfer publishes the worker's
identity to its control API, rather than reusing a laptop manifest on a worker.

Operational acceptance from ADR 0003 also requires configured Sentry coverage,
an external `/health` monitor, the agreed database keep-alive schedule, and a
nightly `pg_dump` backup to R2 retaining seven snapshots. These provider jobs
and monitoring integrations require operator setup and observed restore proof;
the data ZIP and image builds do not establish that they are running.

The current worker implementation receives the shared Postgres and R2
credentials directly.  That is a known production blocker for an untrusted
rental host: the worker API/token boundary and least-privilege worker role have
not been implemented or verified.  Do not turn on autonomous Vast.ai/RunPod
autoscaling with live credentials until that boundary is reviewed.  A provider
deployment and a browser/GPU end-to-end run remain external proof requirements;
these templates do not claim them.

The production templates retain `PRODUCT_PRIVACY_MODE=qa_verified`. The current
new-video route in `src/api/studio/scenes.py` accepts only `self_attested`, so
that route remains closed under this production policy. Imported, previously
published data can still be restored; enabling new production video processing
needs an approved QA upload flow or an explicit owner policy decision. The
packaging tool does not weaken the production gate to match the local MVP.

The current GPU entrypoint also has a non-secret local fallback for the selected
LLM key when the environment value is empty.  The template intentionally leaves
the value blank, but production acceptance still requires an operator-approved
real key or an explicit code/config decision to remove that dependency; the
fallback must not be treated as a production credential.

References used for provider fields:

- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles),
  [Railway start commands](https://docs.railway.com/deployments/start-command),
  and [Railway healthchecks](https://docs.railway.com/deployments/healthchecks)
- [Railway config as code reference](https://docs.railway.com/config-as-code/reference)
- [Supabase PostgreSQL connections and SSL](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase API security](https://supabase.com/docs/guides/api/securing-your-api)
- [Vercel Node.js versions](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions)
- [Vercel project configuration](https://vercel.com/docs/project-configuration/vercel-json)
