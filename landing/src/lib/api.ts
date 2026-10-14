import type { SampleSummary, ProcessingOptions } from "./types";

export const STUDIO_LOGIN_URL =
  process.env.NEXT_PUBLIC_STUDIO_LOGIN_URL ||
  (process.env.NEXT_PUBLIC_STUDIO_URL
    ? `${process.env.NEXT_PUBLIC_STUDIO_URL}/login?next=%2Foverview`
    : "/login?next=%2Foverview");

export const STUDIO_URL = process.env.NEXT_PUBLIC_STUDIO_URL || "";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export async function listSamples(): Promise<{ ok: boolean; data: { samples: SampleSummary[] } }> {
  if (!API_BASE) {
    return { ok: false, data: { samples: [] } };
  }
  try {
    const res = await fetch(`${API_BASE}/api/v1/samples`, { next: { revalidate: 60 } });
    if (!res.ok) return { ok: false, data: { samples: [] } };
    const json = await res.json();
    return { ok: true, data: json };
  } catch {
    return { ok: false, data: { samples: [] } };
  }
}

export async function getProcessingOptions(): Promise<{ ok: boolean; data: ProcessingOptions }> {
  if (!API_BASE) {
    return { ok: false, data: { capability: null } };
  }
  try {
    const res = await fetch(`${API_BASE}/api/v1/processing/options`, { next: { revalidate: 60 } });
    if (!res.ok) return { ok: false, data: { capability: null } };
    const json = await res.json();
    return { ok: true, data: json };
  } catch {
    return { ok: false, data: { capability: null } };
  }
}
