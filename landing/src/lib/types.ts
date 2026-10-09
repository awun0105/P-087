export interface SampleSummary {
  sample_id: string;
  title: string;
  description: string;
  origin: "pipeline_job" | "smoke_run";
  source: { dataset: string; sequence: string; note: string };
  cover: string | null;
  video: { path: string; media_type: string; size_bytes: number } | null;
  frame_count: number | null;
  total_seconds: number | null;
  has_processing: boolean;
  machine: Record<string, string>;
}

export interface MachineCapability {
  gpu_name: string | null;
  vram_total_gb: number | null;
  cpu_count?: number;
  ram_total_gb?: number;
  disk_free_gb?: number;
  [key: string]: unknown;
}

export interface ProcessingOptions {
  capability: MachineCapability | null;
}
