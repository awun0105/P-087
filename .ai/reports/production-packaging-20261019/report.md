# Production packaging audit — 2026-10-19

## Outcome

Audited executable packaging/install recipes and their actual runtime consumers.
Fixed the missing build inputs, installer detection, dependency packaging and demo
bootstrap disk layout described below. Created an updated source/demo bundle.

**Native production readiness remains unverified.** No Docker image was built,
no GPU/Isaac job was run, no cloud infrastructure was changed and no test suite
was rerun, following the user's instruction. The development filesystem had
approximately 2.2 GiB free; a full CUDA/ObjectGS/Isaac build cannot fit there.

## Findings and fixes

| Finding from source | Change |
| --- | --- |
| Root Docker ignore matched public `configs/runtime/pins.env` | Allow that exact file; private env files remain excluded |
| GPU build ran ObjectGS verification before copying its Python imports | Copy `scripts/kaggle/preflight.py` and `src/runtime_env.py` before installation |
| Source ZIP omitted `requirements.in`, Compose recipes and other build inputs | Include root `.in`/lock files, Compose, tests and public env template |
| Frontend `npm ci` ran postinstall before its patch script existed | Copy the patch before npm installation |
| Frontend final image omitted Next runtime configuration | Copy `next.config.ts` into the runner |
| Native build prerequisites absent from apt list | Include Python headers, compiler/build tools, Ninja and pkg-config |
| Runtime with changed installer recipe could be re-stamped without installing | Adoption only when no stamp exists; changed recipe triggers installation |
| ObjectGS outer recipe ignored setup/lock/pin changes, and inner setup skipped changed conda roots | Include those inputs in recipe identity; reconcile conda specifications on update |
| Interrupted first ObjectGS installation could never resume | Owned in-progress marker permits retry; foreign directories remain rejected |
| Scene detection accepted only Python + two existing checkpoint paths | Check SAM2/LaMa/MoGe SHA-256, VGG cache and actual required imports |
| LPIPS download failure silently produced an incomplete runtime | Require successful VGG initialization during installation; package cache at TORCH_HOME |
| splat-transform transitives resolved independently on API/GPU builds | Shared npm lock with 8 integrity-protected dependency entries; use npm ci |
| KISS-ICP depended on system pip and ad-hoc Python environment | Isolated uv environment, hashed lock sync and dependency check |
| Downloads could leave corrupt files at the final destination | Shared retrying downloader checks temporary bytes before atomic rename |
| Binary COLMAP image omitted redistribution license files | Installer fetches pinned license files even when binaries were copied from a build stage |
| GPU runtime accepted missing scene/ObjectGS as optional | Production image requests strict full-runtime preflight |
| Runtime manifest hardcoded OpenUSD/Isaac as unused | Query installed USD and configured Isaac launcher; normalize Isaac version to evaluator convention |
| Isaac had no installation recipe in GPU image | Optional `isaac` build target, isolated Python 3.11 installer, licensed launcher, workflow target selection |
| Controller dropped required Isaac acceptance variable | Allow server-side OMNI_KIT_ACCEPT_EULA through worker configuration |
| GPU Compose passed no required COLMAP build argument | Require exported COLMAP_IMAGE; document pin extraction |
| ZIP and extracted demo occupied the same persistent volume | Download ZIP on ephemeral disk, extract beside destination, check capacity with 256 MiB reserve and retain atomic publication |
| Existing demo archive had to be repacked for every source change | Verify and reuse via hardlink on the same filesystem; preserve data release identity |
| Source hash could be calculated from different bytes than the ZIP write | Hash the actual streamed ZIP member bytes and preserve file mode |
| General setup installed dev tools unconditionally and uv inside the environment it syncs | Add production/core-only mode; isolate temporary installer; resolve repo working directory |

## Files modified in this task

- `.dockerignore`, `Dockerfile`, `Dockerfile.gpu`, `frontend/Dockerfile`, `docker-compose.gpu.yml`.
- `configs/runtime/apt-packages.txt`, `configs/runtime/pins.env`, new `configs/runtime/splat/package.json` and `package-lock.json`.
- `scripts/setup.sh`, `scripts/gpu/install.sh`.
- `scripts/gpu/install.d/{_lib,colmap,lidar_odometry,objectgs,scene,splat}.sh`.
- `scripts/gpu/setup_scene_runtime.sh`, `scripts/gpu/setup_objectgs_runtime.sh`.
- New `scripts/gpu/setup_isaac_runtime.sh`, `scripts/gpu/isaac_python.sh`.
- `scripts/gpu/make_runtime_manifest.py`, `scripts/kaggle/preflight.py`.
- `scripts/studio/build_demo_release.py`.
- `src/config.py`, `src/services/orchestration/samples/release.py`, `src/services/orchestration/gpu/controller.py`.
- `.github/workflows/release-studio.yml`.
- `deploy/studio/{api.env.example,production.env.example,worker.env.example,DEMO_RUNBOOK.md}`.
- New `deploy/studio/PACKAGING.md`, this report and two JSON evidence files.

Earlier unrelated/work-in-progress changes were preserved. No commit or push.

## Actual verification

- `.venv/bin/ruff check src/ scripts/ tests/`: passed.
- `.venv/bin/ruff format --check` on the six edited Python files: passed after formatting two files.
- `bash -n` independently on 14 installer/entrypoint shell files: passed.
- Python AST parse of six edited Python files: passed.
- YAML parse of workflow and two Compose files: passed.
- JSON parse of frontend/package locks, shared splat locks and Railway config: passed.
- Shared npm lock generated with `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`: completed; 8 entries all have versions and integrity.
- Source bundle inspection: all 1,553 members matched size/hash, their current workspace bytes and manifest inventory; executable installer mode retained.
- Required build inputs: 13 explicitly checked inputs present; all 25 non-stage Docker COPY inputs present in the bundle.
- Demo archive: all 2,497 member checksums verified by `verify_archive` during packaging. Data archive SHA-256 unchanged.
- No non-example private env filenames entered the source archive; this filename check is not a general-purpose secret-content scanner.
- `git diff --check`: passed.
- `graphify update .`: completed, 28,426 nodes and 89,110 edges; AST update only.
- No pytest, frontend test, native pipeline, Docker build or cloud smoke test was executed.

Evidence: `static-checks.json`, `bundle-inspection.json`, and the bundle manifests.

## Updated bundle

Canonical output for this task:
`dist/studio-production-packaging-20261019-v2/`.

- Source ZIP: **7,542,131 bytes**, SHA-256 `f2f4c89e6714093f892969537e1617a02027461a6c6a5e96cc7ec11700636324`.
- Demo ZIP: **3,373,872,210 bytes**, SHA-256 `956dbc22addff4ef3436cc2c796192ad4fb8580f0e381f82f70a4e9286bcddce`.
- Demo remains release `demo-20261019`, three samples, 2,497 files.
- Source base commit: `45cd6f43d9a5276b3287975b403edc2ad213d2df`, dirty workspace explicitly recorded, DB schema 25.
- Demo archive is hardlinked to the earlier verified archive; no second 3.37 GB payload was allocated.
- The earlier non-v2 directory is an intermediate candidate. Use v2.
- API/GPU/Isaac image digests remain null. This is a source/data bundle, not a prebuilt image release or offline wheelhouse.

## Remaining production gates

1. Build API/frontend/GPU images on an amd64 builder with adequate scratch disk. Actual compiler, shared-library and CUDA compatibility remains unverified by static checks.
2. Use the immutable built image digest and regenerate/qualify the matching software capability catalog. New USD/Isaac inventory changes software identity; do not reuse old catalog checksums.
3. Enable Isaac only after explicit license acceptance, actual native startup, qualified validation config/profile/resources and robot/candidate assets. Its installation recipe follows [NVIDIA's versioned Python 3.11 / Isaac 5.1 instructions](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/install_python.html). Root container execution follows the [official build workflow's OMNI_KIT_ALLOW_ROOT convention](https://github.com/isaac-sim/IsaacSim/blob/main/.github/workflows/build-and-test.yml).
4. Correction after checking the configured local path: both EgoBlur weights already exist in `/home/lqaq/PROJECT/AI20K/private/`; `.env` and `scripts/gpu/studio.env` point there. Each file is approximately 401 MiB. SHA-256 matches both pins in `scripts/gpu/egoblur_weights.py` exactly: face `2ba183ff74a66752f6457846efb4379b351727d1c9eaef461ed4be8db18cc2e8`, plate `1d6b3fc37fce4158d3b7d4a364290cfeeccc86a9cd84a376c443d560f11497f4`. No new download or provision of these files is needed. Availability through the production R2 prefix/worker configuration has not been checked; this is distinct from local file availability. No model upload was performed here. The earlier request to supply the weights was inaccurate.
5. Scene/Isaac transitives, conda transitives, apt repositories and base image tags are not a fully frozen offline dependency graph. Treat the built image digest as deployment identity; installed-version receipts do not replace hashed wheelhouses.
6. A 5 GB persistent volume avoids the old ZIP+extraction double footprint after this fix, but ~3.964 GB demo data still leaves limited space for DB/cache/session data. No peak production disk/RAM/CPU measurement was performed.
7. Retain the existing RunPod budget/outage-policy and CPU-lane qualification gates. No paid provisioning or deployment was authorized by this task.

## Pre-flight gates

- codegraph: explored preflight/ObjectGS, manifest generation, bundle/bootstrap and caller relationships; graphify queried runtime packaging and Isaac.
- impact: GPU image/installers, API bootstrap, frontend Docker build and source release; no landing/auth/UI behavior edit.
- understand: traced source packaging → Docker inputs → isolated native runtimes → worker preflight → R2/bootstrap publication.
- minimal-code: reused existing install components, version pins, checksum helpers, Python stdlib and existing release CLI.
- checks: static results above; automated tests deliberately not rerun per user instruction.
- DevTools: n/a, no rendered UI change.
