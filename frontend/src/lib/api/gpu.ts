import { apiFetch } from "@/lib/api/client";

/** `src/services/orchestration/gpu/status.py` GpuCapacity — read-only state of the managed GPU. */
export type GpuCapacityState = "unmanaged" | "off" | "starting" | "ready" | "draining" | "blocked";

export interface GpuCapacity {
  state: GpuCapacityState;
  /** ISO time the current state began; for `starting`, when the GPU was requested. */
  since: string | null;
  elapsed_seconds: number | null;
  /** Typical cold start (image pull + worker check) for this deployment, in seconds. */
  expected_startup_seconds: number;
  remaining_seconds: number | null;
  /** Measured cold starts behind the estimate; 0 means the built-in default. */
  sample_count: number;
  /** T-073: pipeline steps waiting for a worker, by the resource they need; absent on older servers. */
  pending_gpu_steps?: number;
  pending_cpu_steps?: number;
}

export function getGpuCapacity(signal?: AbortSignal): Promise<GpuCapacity> {
  return apiFetch<GpuCapacity>("/api/v1/gpu/status", { signal });
}
