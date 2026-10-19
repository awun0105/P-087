/**
 * Gửi sự kiện giá trị lên máy chủ (architecture §15.3): thời gian thao tác của người dùng và phiên Walk.
 *
 * Lỗi không bao giờ làm phiền người dùng: hàm không ném lỗi. Lỗi mạng hoặc 5xx được thử lại đúng một lần;
 * lỗi 4xx (lô vi phạm luật máy chủ) bỏ qua ngay. Các lô cùng phiên được gửi tuần tự để máy chủ nhận đúng thứ tự,
 * vì máy chủ từ chối lô chồng lên lô trước của cùng `session_key`.
 */

import { apiFetch } from "@/lib/api/client";
import { demoApiPath } from "@/lib/api/demo-session";

const API = "/api/v1/jobs";

export type OperatorTimeSurface = "studio" | "progress" | "evaluation" | "other";

export interface OperatorTimeBatch {
  session_key: string;
  surface: OperatorTimeSurface;
  started_at: string;
  ended_at: string;
  active_seconds: number;
}

export interface WalkSessionBatch {
  scene_revision: string;
  started_at: string;
  ended_at: string;
  outcome: "completed" | "aborted";
}

export interface SendOptions {
  /** `keepalive` giữ request sống khi trang đóng hoặc tab ẩn. */
  keepalive?: boolean;
}

class SendError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

/** Hàng đợi chung: mọi lô gửi lần lượt, lô sau không vượt lô trước. Không bao giờ reject. */
let queue: Promise<void> = Promise.resolve();

function retryable(error: unknown): boolean {
  if (!(error instanceof SendError)) return true; // lỗi mạng: fetch ném TypeError
  return error.status === 0 || error.status >= 500;
}

async function sendOnce(path: string, body: unknown, options: SendOptions): Promise<void> {
  let response: Response;
  try {
    response = await fetch(demoApiPath(`${API}${path}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      keepalive: options.keepalive ?? false,
    });
  } catch {
    throw new SendError(0);
  }
  if (!response.ok) throw new SendError(response.status);
}

async function sendWithOneRetry(path: string, body: unknown, options: SendOptions): Promise<void> {
  try {
    await sendOnce(path, body, options);
  } catch (error) {
    if (!retryable(error)) return;
    try {
      await sendOnce(path, body, options);
    } catch {
      // Bỏ qua lô: không thử lại thêm, không báo lỗi cho người dùng.
    }
  }
}

function enqueue(path: string, body: unknown, options: SendOptions): Promise<void> {
  const next = queue.then(() => sendWithOneRetry(path, body, options));
  queue = next;
  return next;
}

export function postOperatorTime(jobId: string, batch: OperatorTimeBatch, options: SendOptions = {}): Promise<void> {
  return enqueue(`/${encodeURIComponent(jobId)}/value-events/operator-time`, batch, options);
}

export function postWalkSession(jobId: string, session: WalkSessionBatch, options: SendOptions = {}): Promise<void> {
  return enqueue(`/${encodeURIComponent(jobId)}/value-events/walk-session`, session, options);
}

/* ---------------------------------------------------------------------------------------------
 * Ground truth benchmark (T-030, architecture §15.2): route `/api/v1/jobs/{job_id}/benchmark-truth`.
 * Toạ độ là hệ canonical của scene (mét, Z-up, sàn z = 0). Máy chủ đặt `tagged_at` của layout.
 * ------------------------------------------------------------------------------------------- */

export type Vec3 = [number, number, number];
export type Layout = "A" | "B";

export interface RobotProfile {
  width_m: number;
  safety_margin_m: number;
  height_min_m: number;
  height_max_m: number;
}

export interface MeasuredDistance {
  id: string;
  label: string;
  a: Vec3;
  b: Vec3;
  real_m: number;
}

export interface GapCheck {
  id: string;
  label: string;
  layout: Layout;
  a: Vec3;
  b: Vec3;
  real_width_m: number | null;
  real_passable: boolean;
}

export interface LayoutRef {
  scene_revision: string;
  tagged_at: string;
}

export interface L4Declaration {
  layout_a_passed: boolean;
  layout_b_passed: boolean;
  matches_reality: boolean;
  evidence: string;
}

export interface BenchmarkTruth {
  schema_version: "1.0";
  include_in_benchmark: boolean;
  data_source: "self_capture" | "hf_room" | "synthetic";
  robot: RobotProfile | null;
  distances: MeasuredDistance[];
  gaps: GapCheck[];
  key_obstacle_ids: string[];
  layouts: Partial<Record<Layout, LayoutRef>>;
  manual_baseline_minutes: number | null;
  l4: L4Declaration | null;
  notes: string;
}

export interface BenchmarkTruthResponse {
  version: number;
  truth: BenchmarkTruth;
  updated_at: string | null;
}

const truthPath = (jobId: string) => `/api/v1/jobs/${encodeURIComponent(jobId)}/benchmark-truth`;

/** Job chưa có tài liệu thì máy chủ trả version 0 và giá trị mặc định (không 404). */
export function getBenchmarkTruth(jobId: string, signal?: AbortSignal): Promise<BenchmarkTruthResponse> {
  return apiFetch<BenchmarkTruthResponse>(truthPath(jobId), { signal });
}

/** Ghi CAS: lệch `expectedVersion` thì máy chủ trả 409 (ApiError.status), sai tham chiếu thì 422. */
export function putBenchmarkTruth(
  jobId: string,
  expectedVersion: number,
  truth: BenchmarkTruth,
): Promise<BenchmarkTruthResponse> {
  return apiFetch<BenchmarkTruthResponse>(truthPath(jobId), {
    method: "PUT",
    body: JSON.stringify({ expected_version: expectedVersion, truth }),
  });
}

/* ---------------------------------------------------------------------------------------------
 * Bảng metric giá trị (T-032, architecture §15.1): `/api/v1/jobs/{id}/value-metrics` và benchmark.
 * Mọi số thiếu dữ liệu là `provenance: "unavailable"` kèm `note`; không bao giờ là 0 giả.
 * ------------------------------------------------------------------------------------------- */

export type Provenance = "measured" | "declared" | "unavailable";

export interface Figure {
  value: number | string | null;
  unit: string | null;
  provenance: Provenance;
  note: string | null;
}

export interface GapResult {
  gap_id: string;
  sim_width_m: number;
  sim_passable: boolean;
  real_passable: boolean;
  agree: boolean;
  kind: "ok" | "missed_obstacle" | "false_obstacle";
  heights_checked: number;
}

export interface MoveResult {
  object_id: string;
  old_cleared: boolean;
  new_present: boolean;
  passed: boolean;
}

export interface NorthStar {
  hands_on_minutes: Figure;
  hands_on_before_ready_minutes: Figure;
  hands_on_after_ready_minutes: Figure;
  machine_minutes: Figure;
  hardware: Record<string, string | number | null>;
  gpu_hours: Figure;
  cost_usd: Figure;
  interventions: Record<string, number>;
  interventions_total: Figure;
}

export interface ScorecardP2 {
  gaps_checked: number;
  gaps_agree: number;
  missed_obstacles: number;
  false_obstacles: number;
  gap_results: GapResult[];
  max_distance_error_cm: Figure;
  key_obstacles_with_collider: string;
  unavailable_reason: string | null;
}

export interface ScorecardP3 {
  edit_to_retest_minutes: Figure;
  moves: MoveResult[];
  consistent: boolean | null;
  unavailable_reason: string | null;
}

export interface ScorecardP4 {
  level: 0 | 1 | 2 | 3 | 4;
  reasons: string[];
}

export interface ValueScorecard {
  job_id: string;
  scene_name: string;
  generated_at: string;
  scene_revision: string | null;
  data_source: string;
  notes: string;
  north_star: NorthStar;
  p2: ScorecardP2;
  p3: ScorecardP3;
  p4: ScorecardP4;
  manual_baseline_minutes: Figure;
}

export interface BenchmarkSummary {
  scenes: number;
  hands_on_median_minutes: number | null;
  hands_on_n: number;
  machine_median_minutes_by_gpu: Record<string, number | null>;
  machine_n_by_gpu: Record<string, number>;
  gaps_agree_total: number;
  gaps_total: number;
  missed_total: number;
  false_total: number;
  scenes_at_least_l2: number;
  scenes_at_least_l3: number;
  manual_median_minutes: number | null;
  manual_n: number;
}

export interface BenchmarkResponse {
  rows: ValueScorecard[];
  summary: BenchmarkSummary;
}

const VALUE_API = "/api/v1";

export function getValueMetrics(jobId: string, signal?: AbortSignal): Promise<ValueScorecard> {
  return apiFetch<ValueScorecard>(`/api/v1/jobs/${encodeURIComponent(jobId)}/value-metrics`, { signal });
}

export function getBenchmarkMetrics(signal?: AbortSignal): Promise<BenchmarkResponse> {
  return apiFetch<BenchmarkResponse>(`${VALUE_API}/value-metrics/benchmark`, { signal });
}

/** Đường dẫn tải thật tới API (không tạo file ở phía client). */
export function valueMetricsUrl(jobId: string, format: "md" | "csv"): string {
  return demoApiPath(`${VALUE_API}/jobs/${encodeURIComponent(jobId)}/value-metrics.${format}`);
}

export function benchmarkMetricsUrl(format: "md" | "csv"): string {
  return demoApiPath(`${VALUE_API}/value-metrics/benchmark.${format}`);
}
