# Production packaging

## Images and environments

| Component | Recipe | Included runtime |
| --- | --- | --- |
| API/controller | root `Dockerfile` | Python 3.12.14 core lock, psycopg, boto3, FFmpeg, Node, locked splat-transform; separate USD environment |
| Studio | `frontend/Dockerfile`, context `frontend/` | Node, locked Next/PlayCanvas dependencies, patched viewer, compiled vendored SuperSplat editor |
| GPU pipeline | `Dockerfile.gpu`, target `production` | CUDA 12.6, pinned COLMAP binary, Brush, Node/splat-transform, KISS-ICP, SAM2, gsplat, MoGe, LaMa, CoACD, scikit-image, trimesh, USD, LPIPS/VGG, ObjectGS |
| GPU pipeline + validation | `Dockerfile.gpu`, target `isaac` | All pipeline components plus Isaac Sim 5.1 in isolated Python 3.11 |

App Python, scene Python, ObjectGS Python 3.8/CUDA 11.8 and Isaac Python
3.11 remain separate. Do not merge their pip environments. The fixed build
architecture list is `7.5;8.0;8.6;8.9`; qualify another architecture before
advertising it in a RunPod release profile. Host NVIDIA drivers and graphics/Vulkan
capability are external requirements, and cannot be installed into the image.

## Build on a host with enough disk

These commands build local images. They do not push or provision cloud resources.
Use a dedicated amd64 build host; the development host has insufficient free disk.
For a non-container core installation, `bash scripts/setup.sh --production`
installs only the core hashed lock. The default setup mode includes developer
tools. Neither mode substitutes for the GPU or USD runtime installation recipes.

```bash
docker build --platform linux/amd64 -f Dockerfile -t real2sim-api:release .
docker build --platform linux/amd64 -f frontend/Dockerfile -t real2sim-web:release \
  --build-arg REAL2SIM_API_URL=https://YOUR-API-HOST frontend
docker build --platform linux/amd64 -f Dockerfile.gpu --target production \
  --build-arg COLMAP_IMAGE="$(sed -n 's/^COLMAP_IMAGE=//p' configs/runtime/pins.env)" \
  -t real2sim-gpu:release .
```

For Isaac, review and accept the NVIDIA license first, then select
`--target isaac --build-arg ISAAC_ACCEPT_EULA=YES`. Runtime execution also requires
`OMNI_KIT_ACCEPT_EULA=YES`. The installer follows NVIDIA's
[Python 3.11 / Isaac 5.1 installation recipe](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/install_python.html).
Configure actual validation config/profile/resource files and robot assets;
installing Isaac does not invent or qualify those contracts. Do not advertise a
`validation` release profile before measuring and qualifying that image.

For the local GPU Compose override, export the pinned image first:

```bash
export COLMAP_IMAGE="$(sed -n 's/^COLMAP_IMAGE=//p' configs/runtime/pins.env)"
```

The manual release workflow supports either GPU target. It publishes only when
explicitly dispatched by an authorized operator; this audit did not dispatch it.
Use the resulting immutable image digest in the release catalog. Changing runtime
versions changes software identity: regenerate the catalog from the built image.

## Model files and optional data

- SAM2, LaMa and MoGe are downloaded and SHA-256 checked while building.
- LPIPS VGG weights must download successfully during installation. Their cache
  is included at `TORCH_HOME=/opt/real2sim/torch_cache` in the GPU image.
- EgoBlur's package is included. Its two licensed `.jit` files require the
  operator's download/acceptance and one-time `scripts.gpu.egoblur_weights upload`.
  Workers fetch and verify them from private R2 when `PRODUCT_EGOBLUR_WEIGHTS`
  is configured. Keep anonymization unavailable until they exist.
- Demo baselines are separate checksummed ZIP/R2 data, not Docker image layers.
- Asset previews and Rerun recordings are optional data. No Rerun recording
  generator is implied by including the browser viewer.
- `scripts/torwic/` offline dataset preparation uses the separate hashed
  `requirements-offline.lock.txt` (Open3D). Install it into its own environment
  when doing offline preparation; it is not called by the production worker.

## Bundle and reproducibility limits

`scripts.studio.build_demo_release` includes root requirements inputs and locks,
Docker/Compose recipes, backend, frontend/vendor, scripts, configs and tests.
ZIP source records hash the exact bytes written and retain Unix executable modes.
When reusing demo data, pass `--demo-archive <verified-library.zip>`; the data release
identity remains separate from the source release identity.

Python core/USD/KISS-ICP/ObjectGS pip locks and npm locks have hashes/integrity.
Scene and Isaac installers still resolve some transitive Python dependencies,
and conda resolves transitives within pinned root specifications. Scene/Isaac
installation receipts record installed versions; these are not wheelhouse locks.
Base image tags and apt repositories are not fully frozen snapshots. The final
image digest is the deployable immutable unit. This source bundle requires network
access to build; it is not a complete offline installer or prebuilt image release.

Before enabling paid provisioning, build the selected image, perform native
qualification, publish its digest and matching capability catalog, configure
approved budget/outage policy, and confirm required model/validation data exists.
Until then, keep provisioning disabled. No native build or cloud qualification
was performed during this packaging audit.
