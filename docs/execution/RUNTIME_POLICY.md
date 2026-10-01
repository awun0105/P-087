# Runtime Standardization & Dependency Isolation Policy

## 1. Core Python Policy
- **Supported Versions**: `>=3.12, <3.13`
- **Reference Environment**: exactly `3.12.14`
- **CI Validation**: `3.12.14`

The `make doctor` script ensures environments are compliant. Patch versions other than `3.12.14` will emit a warning but will pass local checks. CI is strict and requires the reference runtime.

## 2. Dependency Layers and Ownership
Dependencies are grouped into logical, isolated environments. We do NOT use one huge `.venv` for the whole system (including providers).

### Core Dependencies
- Managed centrally for the Core Foundation.
- Resolver & Lock Tool: `uv` (version 0.9.4). `uv` is environment tooling and not a core runtime dependency.
- Sources: `requirements.in` (runtime) and `requirements-dev.in` (tooling).
- Environment: `.venv` in the repository root.
- Lockfiles: `requirements.lock.txt` and `requirements-dev.lock.txt`.
- Workflow: Lock with `uv pip compile --generate-hashes --python-version 3.12.14`, sync with `uv pip sync`.

### External Provider Dependencies (e.g. 3DGS, Isaac, SAM2)
- Must be isolated from the Core.
- Permitted mechanisms: dedicated virtualenv, vendor containers, or separate processes.
- Do NOT merge external requirements (e.g., specific PyTorch versions, CUDA toolkits) into the Core `requirements.lock.txt`.
- Provider integrations must pin external source revisions (e.g. strict commit SHA or tag, NEVER `main`).
- Actual virtual environments for providers should not be committed to Git. Store configurations logically (e.g. `external/providers/<provider>/runtime.yaml`) and ignore the virtualenv directory.

## 3. Communication Boundary
External providers interact with the Core strictly via Canonical Artifacts (e.g., `InputManifest`, `ReconstructionBundle`, `SceneIR`). The Core process never imports arbitrary, incompatible code directly from providers via `sys.path`.

## 4. Runtime Diagnostics
- **Doctor / Preflight**: `make doctor` verifies Python versions, lockfile availability, and crucial dependency sanity before long-running tasks. This catches environment mismatch.
- **Smoke Test**: `make smoke` executes Foundation logic (contract parsing, identity checksums, handoff) to confirm application sanity. Catching software logic bugs.
- **Environment Fingerprint**: Core context captures Python, OS, and Lockfile hash (via `src/services/orchestration/environment.py`). Provider contexts should additionally capture Provider ID, Source Revision, CUDA/Torch versions if relevant. This metadata goes into execution logs/provenance, NOT directly inside Core schemas like `SceneIR`.

## 5. Compatibility Matrix
| Component | Runtime mode | Python | Torch | CUDA | Source revision | Dependency lock | Status |
|---|---|---|---|---|---|---|---|
| Core / Foundation | native | 3.12.x | - | - | Foundation SHA | requirements.lock.txt | SUPPORTED |
| REC GPU tools (Studio) | separate processes | - | - | driver 580.178.04 | COLMAP image `sha256:b8498ebe…`, Brush 0.3.0, splat-transform 3.6.6, FFmpeg 6.1.1 | `runtime_manifest.json` (gitignored, sinh bằng `scripts/gpu/make_runtime_manifest.py`) | Verified local Quadro T2000 (29/09); image GPU trên Vast.ai/RunPod UNVERIFIED (ADR 0003) |
| Scene runtime (SAMPro3D + SAM2, LPIPS, usd-core) | dedicated virtualenv `data/scene_runtime` (gitignored), gọi qua subprocess | 3.12.3 | 2.7.1+cu126 | 12.6 | SAM2 source `private/sam2` @ `2b90b9f` (sam2.1 hiera tiny); usd-core 26.8; lpips 0.1.4 | `scripts/gpu/setup_scene_runtime.sh` | Verified local T2000 (30/09, ADR 0006) |
| Pipeline v2 providers (cùng venv `data/scene_runtime`) | dedicated virtualenv, gọi qua subprocess | 3.12.x | 2.7.1+cu126 | 12.6 (nvcc 12.x để biên dịch gsplat) | gsplat 1.5.3, coacd 1.0.14, scikit-image 0.26.0, opencv-python-headless 5.0.0.93, trimesh 5.1.0, usd-core 26.8; LaMa `big-lama.pt` sha256 `7ba7aa7a…` | `scripts/gpu/setup_scene_runtime.sh` (ghim phiên bản; chưa có lockfile có hash) | Verified local T2000 (01/10, ADR 0007); cần header Python 3.12 khi cài; GPU thuê UNVERIFIED |
