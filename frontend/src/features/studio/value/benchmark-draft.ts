/**
 * Nháp của panel Benchmark (T-033): đổi từ `BenchmarkTruth` của máy chủ sang trạng thái form và ngược lại.
 * Không có React ở đây để test được bằng hàm thuần.
 */

import type {
  BenchmarkTruth,
  GapCheck,
  L4Declaration,
  Layout,
  LayoutRef,
  MeasuredDistance,
  RobotProfile,
  Vec3,
} from "@/lib/api/value";

/** Mặc định của kế hoạch T-033: robot 0,6 m, khoảng an toàn 0,05 m, dải độ cao 0,05–1,2 m. */
export const DEFAULT_ROBOT: RobotProfile = { width_m: 0.6, safety_margin_m: 0.05, height_min_m: 0.05, height_max_m: 1.2 };

export interface BenchmarkDraft {
  robot: RobotProfile;
  distances: MeasuredDistance[];
  gaps: GapCheck[];
  keyObstacleIds: string[];
  layouts: Partial<Record<Layout, LayoutRef>>;
  dataSource: BenchmarkTruth["data_source"];
  includeInBenchmark: boolean;
  /** Giữ chuỗi người dùng gõ; đổi sang số khi gửi. */
  manualBaselineMinutes: string;
  l4: L4Declaration | null;
  notes: string;
}

export function draftFromTruth(truth: BenchmarkTruth): BenchmarkDraft {
  return {
    robot: truth.robot ?? DEFAULT_ROBOT,
    distances: truth.distances.map((item) => ({ ...item, a: [...item.a] as Vec3, b: [...item.b] as Vec3 })),
    gaps: truth.gaps.map((item) => ({ ...item, a: [...item.a] as Vec3, b: [...item.b] as Vec3 })),
    keyObstacleIds: [...truth.key_obstacle_ids],
    layouts: { ...truth.layouts },
    dataSource: truth.data_source,
    includeInBenchmark: truth.include_in_benchmark,
    manualBaselineMinutes: truth.manual_baseline_minutes === null ? "" : String(truth.manual_baseline_minutes),
    l4: truth.l4 ? { ...truth.l4 } : null,
    notes: truth.notes,
  };
}

/** Chuỗi phút → số không âm; rỗng hoặc không hợp lệ thì null (nghĩa là chưa khai báo). */
export function parseMinutes(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/**
 * Tài liệu sẽ gửi. `tagged_at` của layout lấy từ nháp nhưng máy chủ luôn đặt lại; client không cần sửa.
 */
export function truthFromDraft(draft: BenchmarkDraft): BenchmarkTruth {
  return {
    schema_version: "1.0",
    include_in_benchmark: draft.includeInBenchmark,
    data_source: draft.dataSource,
    robot: draft.robot,
    distances: draft.distances,
    gaps: draft.gaps,
    key_obstacle_ids: draft.keyObstacleIds,
    layouts: draft.layouts,
    manual_baseline_minutes: parseMinutes(draft.manualBaselineMinutes),
    l4: draft.l4,
    notes: draft.notes,
  };
}

/** Nháp khác tài liệu đã lưu: hiện cảnh báo rời panel và bật nút Lưu. */
export function isDirty(draft: BenchmarkDraft, saved: BenchmarkDraft): boolean {
  return JSON.stringify(truthFromDraft(draft)) !== JSON.stringify(truthFromDraft(saved));
}

/** Vật cản chính đã chọn nhưng không còn trong scene hiện tại (vd vật bị xoá); panel phải báo để bỏ chọn. */
export function missingObstacleIds(keyObstacleIds: readonly string[], sceneObjectIds: ReadonlySet<string>): string[] {
  return keyObstacleIds.filter((id) => !sceneObjectIds.has(id));
}

/** Id nhỏ nhất còn trống trong dãy `d1`, `d2`... hoặc `g1`, `g2`... (id đã xoá được dùng lại). */
export function nextId(prefix: "d" | "g", existing: readonly { id: string }[]): string {
  const taken = new Set(existing.map((item) => item.id));
  let index = 1;
  while (taken.has(`${prefix}${index}`)) index += 1;
  return `${prefix}${index}`;
}

/** Khoảng cách giữa hai điểm (m), để so với số đo thật. */
export function distanceBetween(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** Robot hợp lệ theo cùng biên với máy chủ; ô trống (NaN) là không hợp lệ. */
export function robotProblem(robot: RobotProfile): string | null {
  if (![robot.width_m, robot.safety_margin_m, robot.height_min_m, robot.height_max_m].every(Number.isFinite)) {
    return "Thông số robot phải là số";
  }
  if (!(robot.width_m > 0.05 && robot.width_m <= 3)) return "Bề rộng robot nằm trong (0,05; 3] m";
  if (!(robot.safety_margin_m >= 0 && robot.safety_margin_m <= 1)) return "Khoảng an toàn nằm trong [0; 1] m";
  if (!(robot.height_min_m >= 0 && robot.height_min_m <= 2)) return "Độ cao thấp nhất nằm trong [0; 2] m";
  if (!(robot.height_max_m > 0 && robot.height_max_m <= 3)) return "Độ cao cao nhất nằm trong (0; 3] m";
  if (robot.height_min_m >= robot.height_max_m) return "Độ cao thấp nhất phải nhỏ hơn độ cao cao nhất";
  return null;
}
