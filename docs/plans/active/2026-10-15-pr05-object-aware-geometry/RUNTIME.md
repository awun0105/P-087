# ObjectGS isolated runtime and executable smokes

This runtime is separate from the application `.venv`, Brush and SAM2. Do not install the custom gsplat
into those environments. The commands below require a CUDA-capable host and an appropriate C++ compiler.
They are deployment instructions, not a claim of successful GPU acceptance. See HANDOFF.md for actual runs.

## Pinned source

- ObjectGS: `RuijieZhu94/ObjectGS` at `0f6842b0fa80b9bfe151c31b70c306cbc5eab788`.
- Custom gsplat: `RuijieZhu94/gsplat-object` at `68a61a4485cfc2967703391a3e1cfb59981f8fc7`.
- GLM headers: `g-truc/glm` at `bf71a834948186f4097caa076cd2663c69a10e1e` (0.9.9.8).

Use clean checkouts; the adapter verifies exact revisions and rejects tracked source edits. See the license
caveat in HANDOFF.md before redistributing upstream code. No upstream implementation is vendored here.

## Environment

Choose persistent external directories for deployment. The local smoke used temporary prefixes only.
Create an isolated Conda Python 3.8.19 environment, then install torch 2.1.2+cu118, torchvision 0.16.2+cu118
and torchaudio 2.1.2+cu118 from the official PyTorch cu118 wheel index. Install torch-scatter 2.1.2+pt21cu118
from the PyG torch-2.1.0+cu118 wheel index. Do not substitute the normal PyPI gsplat package.

Other directly selected versions in the local environment:

```text
numpy==1.24.4
open3d-cpu==0.18.0
wandb==0.18.7
PyYAML==6.0.2
scipy==1.10.1
scikit-learn==1.3.2
lpips==0.1.4
einops==0.8.1
kornia==0.7.3
plyfile==1.0.3
rich==13.9.4
jaxtyping==0.2.19
ninja==1.11.1.3
opencv-python-headless==4.10.0.84
imageio==2.35.1
tensorboard==2.14.0
matplotlib==3.7.5
laspy==2.5.4
trimesh==4.5.3
mediapy==1.2.2
colorama==0.4.6
```

`open3d-cpu` supplies the CPU TSDF API used by upstream mesh export. The actual Gaussian rasterizer still
requires CUDA. `lpips` loads VGG16 weights through the normal Torch cache; allow their download or prefill
that cache. Upstream resume is disabled: capture/restore checkpoint tuple layouts are incompatible.

On this host, a separate CUDA 11.8.89 toolkit + gxx_linux-64=11 prefix was installed because the system
nvcc 12.8/GCC 13 do not match the selected Torch CUDA runtime. Supply `cuda_home`, `cxx` and pinned
`glm_repository` explicitly. Custom gsplat JIT needs toolkit version metadata beside `bin/`; the Conda
prefix lacked this, so `version.txt` was supplied from the installed nvcc version (`CUDA Version 11.8.0`).
The runner also adds the isolated Python environment include root to CPLUS_INCLUDE_PATH: Python 3.8
includes crypt.h from there, outside its python3.8 subdirectory. GLM is added explicitly alongside it.
No compiler or headers were changed in the system or application environment.

`runtime-packages.json` records installed package versions from the local probe; it is evidence, not a
universal GPU qualification. CUDA/compiler pins and source revisions remain separate requirements.

## Synthetic real-GPU smoke

Create runtime.json using absolute deployment paths:

```json
{
  "python": "/path/to/isolated-env/bin/python",
  "repository": "/path/to/ObjectGS",
  "gsplat_repository": "/path/to/gsplat-object",
  "cuda_home": "/path/to/cuda-11.8-prefix",
  "cxx": "/path/to/cuda-11.8-prefix/bin/x86_64-conda-linux-gnu-g++",
  "glm_repository": "/path/to/glm",
  "gpu_device": 0,
  "iterations": 100,
  "timeout_seconds": 1800,
  "voxel_size_m": 0.03,
  "depth_trunc_m": 8
}
```

From repository root:

```bash
.venv/bin/python scripts/scene/smoke_objectgs.py \
  --runtime-config /absolute/path/runtime.json \
  --workspace /absolute/path/fresh-synthetic-smoke
```

This generates eight calibrated 96x96 observations of a one-metre cube above a floor, explicit labels and
metric anchors, runs actual upstream training and each numeric-label mesh export, then writes result.json.
The workspace must not exist; retries require a fresh path. Logs are runtime/runtime-check.log, train.log,
and export-1.log. A 100-iteration smoke tests execution, not trained mesh quality or CoACD acceptance.
An optional `extension_cache_dir` in runtime.json reuses a completed CUDA extension for the same
pinned source, Python/Torch/CUDA/compiler environment. Keep distinct directories for different runtimes.
The default remains per-invocation scratch. A process-level lock rejects concurrent users of an explicitly
shared cache, including export subprocesses. Pinned upstream deletes an incomplete cache without its .so;
this option does not resume a failed compiler build or a neural checkpoint. The local 900-second cold build
timed out; use a sufficiently long timeout for first compilation (the example now uses 1800 seconds).
The production default remains 30,000 iterations. Empty exports fail; no fabricated result or fallback.

## Existing Room pipeline smoke (mutates the scene only when executed)

Use the normal Studio environment and fill the isolated-runtime settings before executing. Inspect the
current revision first; the guard rejects concurrent scene edits. This command replaces candidates and
creates a new revision, so preserve reviewed work before using it. It has NOT been run on the user's Room.

```bash
set -a
source scripts/gpu/studio.env
set +a
export PRODUCT_OBJECTGS_RUNTIME_PYTHON=/absolute/path/isolated-env/bin/python
export PRODUCT_OBJECTGS_REPOSITORY=/absolute/path/ObjectGS
export PRODUCT_OBJECTGS_GSPLAT_REPOSITORY=/absolute/path/gsplat-object
export PRODUCT_OBJECTGS_CUDA_HOME=/absolute/path/cuda-11.8-prefix
export PRODUCT_OBJECTGS_CXX=/absolute/path/cuda-11.8-prefix/bin/x86_64-conda-linux-gnu-g++
export PRODUCT_OBJECTGS_GLM_REPOSITORY=/absolute/path/glm
export PRODUCT_OBJECTGS_GPU_DEVICE=0
.venv/bin/python scripts/scene/reobjectify.py job-a14981f78f85 \
  --geometry-method objectgs --expected-revision rev-100 \
  --workspace /absolute/path/fresh-room-objectgs-smoke
```

This reuses the canonical ReconstructionBundle and reruns objectify/segmentation, ObjectGS training,
surface export, strict CoACD and background occupancy. It does not rerun COLMAP or Brush. It preserves
other sealed job controls. Missing runtime, invalid surfaces or failed CoACD abort instead of reporting a
successful legacy fallback. Use the normal simulation-package action to build USD from the accepted
revision; no Isaac Sim acceptance is implied. In Studio inspect diagnostics, Confirm/Move/Rotate,
Delete/Restore and Walk, and compare the exported stage's collision refs/transforms with that revision.
