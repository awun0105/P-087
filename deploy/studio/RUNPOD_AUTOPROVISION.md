# RunPod lifecycle controller

## Current boundary

The implementation uses the existing PostgreSQL queues and immutable R2 publishers. It does not deploy a Pod merely because somebody opens Studio. Provisioning is disabled in the example environment. No live GPU acceptance is implied by the local tests.

Run the controller as a supervised CPU process in the Railway API container. `GPU_CONTROLLER_RUN=true` enables supervision independently of HTTP traffic. Disable Railway App Sleeping/Serverless for that service before relying on polling. The supervisor exits if a child dies so Railway can restart the process group. The controller and its state do not live on the GPU Pod.

Keep one deployment ID for the project, across API replicas and releases. Do not run the Vast autoscaler against the same deployment. Stop the previous manually managed worker before enabling managed claiming. Do not delete or manage unrelated Pods.

## Release preparation

1. Build the worker image containing this revision and its pinned native dependencies on a builder with enough disk. Publish an immutable image digest through the existing authorized release process.
2. Qualify CUDA, Vulkan, COLMAP, Brush, SAM/scene geometry and ObjectGS on the intended GPU/resource envelope. Record the evidence reference. The reconstruction image does not install Isaac: validation may only be advertised by an image that has a qualified Isaac launcher, runtime/resource profiles and required dependencies.
3. Generate the runtime manifest and input qualification registry using the existing native scripts. Record `ExecutionProfile.load(config_path, runtime_path, seed)` from that actual release. Do not copy a fixture checksum or mark absent capabilities qualified.
4. Create metadata JSON with `profiles` and optional `input_registry`. Each profile requires:

   - `name`: unique, stable release-profile identifier. Prefer a versioned name.
   - `image`: immutable `registry/image@sha256:<64 lowercase hex>`.
   - `execution`: exact `ExecutionProfile` with config/runtime/software checksums and seed.
   - `kinds`: supported subset of `pipeline`, `scene`, `registration`, `validation`, `import`.
   - `gpu_types`: approved compatible RunPod GPU IDs, including permitted fallbacks.
   - `cuda_versions`: acceptable provider CUDA/driver capabilities for the qualified image, passed to `allowedCudaVersions`.
   - `scene_boxes_require_gpu`: actual selected box candidate path; true when it uses SAM2. The API host lacking SAM2 does not prove the remote path is CPU-only.
   - `min_vram_gb`, `min_ram_gb`, `min_cpus`, `scratch_gb`: qualified floors with boot/model/cache headroom.
   - `qualification_reference`: evidence for that image and resource envelope.
   - `storage_hourly_usd`: explicit conservative storage estimate in addition to the GPU quote. It is not an invoice guarantee.

5. Seal and validate it without renting anything:

   ```bash
   python -m scripts.cloud.gpu_catalog /secure/release-metadata.json --out /secure/release-catalog.json
   ```

   Output creation is exclusive: publish a new release file rather than overwrite a pinned catalog. The optional `input_registry` must itself have a valid existing qualification checksum. Unsupported input adapters remain unavailable.

6. Make the catalog accessible on the API/control service. Set both `PRODUCT_GPU_RELEASE_CATALOG` and `GPU_RELEASE_CATALOG` to the same path. Keep `PRODUCT_RUNTIME_FROM_WORKERS=true` and the matching `PRODUCT_PROCESSING_CONFIG`. This allows a first job before any worker has ever published a heartbeat. A configured catalog does not silently fall back to an unrelated historic runtime.

## Environment

Use `deploy/studio/production.env.example` and regenerate with `scripts.studio.deploy_env`. Provider credentials belong in the API section, never shared/web/worker sections. Production secrets remain outside Git. The actual project bucket is `real2sim`; examples keep storage credentials empty. Verify that bucket when deployment is authorized.

| Variable | Policy |
| --- | --- |
| `GPU_CONTROLLER_RUN` | Default false; supervise controller with API when true |
| `GPU_AUTOPROVISION_ENABLED` | Default false; permits new create requests |
| `GPU_AUTOPROVISION_DRY_RUN` | Default true; prevents provider create/delete |
| `GPU_DEPLOYMENT_ID` | Explicit stable project identifier, same on all replicas |
| `RUNPOD_API_KEY` | Controller only; never forwarded to worker |
| `GPU_RELEASE_CATALOG` / `PRODUCT_GPU_RELEASE_CATALOG` | Same pinned catalog file |
| `GPU_WORKER_ENV_FILE` | Private rendered worker env file in the controller container |
| `GPU_MAX_PODS` | Exactly 1 in this implementation |
| `STUDIO_WORKERS` | Worker launch overrides to exactly 1 |
| `GPU_MAX_HOURLY_USD` / `GPU_PROJECT_BUDGET_USD` | Explicit approved positive values; no money default |
| `GPU_IDLE_SECONDS` | 240 |
| `GPU_POLL_SECONDS` | 15 |
| `GPU_STARTUP_TIMEOUT_SECONDS` | 1200; tune for measured image boot/preflight duration |
| `GPU_MAX_LIFETIME_SECONDS` | 43200; soft drain, never a healthy-job kill deadline |
| `GPU_MAX_PROVISION_ATTEMPTS` | 3 until operator review/resume |
| `GPU_CONTAINER_DISK_GB` | 100, or qualified scratch floor if larger |
| `GPU_REGISTRY_AUTH_ID` | Optional provider-side registry credential ID |
| `GPU_CLOUD_TYPE` | SECURE or COMMUNITY |
| `GPU_OUTAGE_POLICY` | Default blocked; alternatives operator_accepted or external_watchdog |
| `GPU_OUTAGE_POLICY_REFERENCE` | Required for live provisioning: approved operating procedure/evidence |
| `GPU_CPU_LANE_ENABLED` | Default false |
| `GPU_CPU_LANE_QUALIFICATION_REFERENCE` | Required before CPU lane can start |
| `GPU_CPU_LANE_RAM_GB` | Default 2 GiB task address-space budget plus 1 GiB API headroom |

The worker env file must contain the shared PostgreSQL/R2 settings and correct worker paths. Only an explicit allowlist is forwarded. The image supplies its installed native runtime paths. No RunPod API credential is passed into the Pod. The controller creates no network volume and requests `volumeInGb=0`; `/data` is temporary scratch. Confirm the resulting storage behavior in P8.

The API, controller and managed workers require a main PostgreSQL schema named `public`. Demo workers retain their validated `r2s_demo_<id>` search path for jobs, but lifecycle state always comes from `public.r2s_gpu_control` in the same claim transaction.

## Lifecycle and safety

- Queues are scanned for runnable pipeline phases, scene requests, registration, validation and imports. Registered demo schemas are scanned independently. Closed sessions still contribute active leases/publication until teardown is complete. Merely open demo sessions do not count as GPU demand.
- CPU registration and CPU imports do not start a GPU Pod. Persisted resource waits exclude undersized profiles; provide qualified larger resource profiles if requests can exceed the initial envelope. A profile must cover every enabled preset/operation it advertises. Box extraction classification comes from the release capability and the actual worker classifier. GPU-only methods are never claimed by the CPU lane.
- A durable intent and ownership token are committed before create. A database leader lease serializes controllers; an unresolved create is never posted again automatically. A response lost after provider allocation is reconciled by the persisted intent/name/token/image, not by a name prefix alone.
- A Pod becomes usable only after allocation and actual worker runtime/resource/R2 preflight. The managed worker probes R2 write, HEAD checksum and read checksum, then deletes only its own unique probe object.
- Every durable claim locks the main control row before claiming work. The actual claim transaction sets the worker busy marker. Empty polling does not keep a Pod alive. The marker lasts through the synchronous operation, including artifact publication and final state persistence.
- Idle starts after no runnable compatible GPU demand and no live execution remain. After the grace period, draining closes the claim gate. A second complete scan checks leases, reservations and worker publication markers before transitioning to termination.
- Work arriving before irreversible termination can reopen draining. Work arriving after the terminating transition remains durably queued until deletion is confirmed and the next Pod starts. A replacement is never created while the previous managed Pod is unresolved.
- Cancellation, CAS, source revisions, baseline immutability and the existing queue-specific retry policies remain authoritative. Recovery may mark a job FAILED/retryable; that does not mean the pipeline was automatically rerun or resumed from an arbitrary checkpoint.
- Image changes retain the old Pod's pinned profile for ownership verification. Existing active work completes before retiring that Pod. Incompatible staged jobs are reported blocked; they are not rebound by rewriting immutable artifacts.

## Cost controls

The controller reads a current inventory price before create, filters approved GPU types/resources against the hourly cap, and checks accumulated project estimates plus startup/idle reservation against the project budget. Allocation price is checked again before allowing claims. Native resource and software checks run on the worker itself.

REST create has no atomic maximum-price field in the verified v1 contract. Price can change between quote and allocation. An overprice allocation is drained before claiming work; small startup charges can still occur. A local estimate is not a provider-enforced hard cap. Storage estimates and conservative elapsed time may differ from invoices.

A budget or lifetime limit stops new claims and provisioning. It does not kill healthy current work. Thus a long job may exceed the estimated budget. Confirmed-deleted Pod histories retain their estimated cost; restarting the controller does not reset it. Do not change deployment ID to bypass the budget.

State durations, estimated expenditure, current intent/Pod, errors and leader expiry are persisted. Status output is explicitly redacted and does not print the ownership token, env or database URL.

## Operations

Load the private service environment using the deployment secret mechanism. Commands do not take keys as command-line arguments:

```bash
python -m scripts.cloud.runpod_controller status
python -m scripts.cloud.runpod_controller once
python -m scripts.cloud.runpod_controller drain
python -m scripts.cloud.runpod_controller resume
```

`drain` prevents new claims and permits existing work/publication to finish. `resume` clears the provisioning incident counter and operator drain. Disabling `GPU_AUTOPROVISION_ENABLED` prevents new resources but still allows cleanup of known managed resources; keep the controller process running. Dry run suppresses create and delete, so do not enable dry run as a substitute for terminating an already paid Pod.

An unknown create response with no discoverable owned Pod remains blocked. Inspect the recorded intent and the provider before resolving it operationally. Do not clear the intent or change deployment ID merely to retry: a delayed successful create could otherwise become an orphan. Ambiguous ownership or multiple matching Pods requires operator reconciliation; unrelated resources are never deleted automatically.

## Control-plane outage

The controller is external to the Pod and handles a dead worker while Railway is running. It cannot execute if the entire Railway control plane is down. This implementation does not pretend the RunPod CLI terminate-after flag is a verified REST expiry contract.

Live provisioning is blocked unless an operator-approved outage procedure or independent watchdog is recorded. For the trial, that approval must explicitly cover how an operator detects an orphan, checks leases/publication, reconciles the exact intent/Pod and confirms termination. A configuration reference records that approval; it is not proof somebody deployed a watchdog.

A compatible independent host/scheduler can run:

```bash
python -m scripts.cloud.runpod_controller watchdog
```

This performs one reconciliation pass with new provisioning disabled. It uses the same leader lease and safety gates. Schedule repeated passes outside Railway; allow at least the 120-second leader lease plus scan/drain intervals after a failed leader. Keep the matching catalog, worker metadata and least necessary server credentials there. Installation and live outage acceptance are not performed by merely adding this command. A PostgreSQL outage or an unexpired job lease still prevents unsafe deletion; operator intervention may be necessary. There is no unconditional hard spending guarantee under a total control-plane outage.

## CPU lane acceptance

The opt-in CPU subprocess checks native Python imports, Node availability and RAM headroom, pins itself to one CPU, sets a task address-space limit and keeps existing operation admission/leases. Scene CPU work is enabled only for a catalog that declares box extraction CPU-only. CPU and GPU consumers can coexist without claiming the same operation.

A source preflight is not Railway capacity acceptance. Before enabling, measure real registration and CPU import runtime/peak RAM/API latency in the deployed image and validate subprocess termination under memory pressure. The address-space cap also applies to native/Node children and may require a different qualified budget. If the combined service cannot meet those limits, use the same CPU module as a separate qualified worker rather than enabling it on an undersized API service. No paid CPU service is created automatically.

## Acceptance and remaining release gates

Automated tests cover the lifecycle/provider state, lost responses, restart/adoption, soft limits, publication protection and real local PostgreSQL concurrency/schema isolation. Live acceptance still needs a built/qualified digest, approved money limits and outage procedure, then an isolated real small GPU stage, R2 verification, confirmed deletion and a second automatic provisioning cycle.

The previous demo bundle predates these source changes. Rebuild the source release after finalizing implementation; do not deploy its stale source ZIP as this implementation. The separate demo-library bootstrap issue remains: the current code downloads ZIP and extracts on the same persistent volume. Move staging to an appropriate disk or otherwise solve capacity in its own P0 change, and measure actual peak space before deploying all samples. Do not assume scale-to-zero fixes storage capacity.

GPU compute at idle is expected to be zero only after provider-confirmed termination. Railway CPU/RAM, PostgreSQL, R2 storage/requests and registries may still have recurring charges.

## Verified provider references

- [RunPod REST create](https://docs.runpod.io/api-reference/pods/POST/pods)
- [RunPod REST list](https://docs.runpod.io/api-reference/pods/GET/pods)
- [RunPod REST terminate](https://docs.runpod.io/api-reference/pods/DELETE/pods/podId)
- [RunPod official inventory quote examples](https://github.com/runpod/docs/blob/main/sdks/graphql/manage-pods.mdx)
- [Current official CLI create flags](https://github.com/runpod/runpodctl/blob/main/docs/runpodctl_pod_create.md)
