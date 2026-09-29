/**
 * Thứ tự điểm của bước xác nhận tỉ lệ mét: A, B (đoạn biết độ dài thật) rồi 3 điểm
 * trên mặt sàn. Backend (REC-06) dùng sàn làm z=0, A→B làm trục X, A làm gốc.
 */
import type { InspectionPoint } from "@/features/viewer/inspection-history";
import type { MetricInput, MetricPoint } from "@/lib/contracts/studio";

export const METRIC_POINT_COUNT = 5;

export const METRIC_POINT_LABELS = ["A", "B", "Sàn 1", "Sàn 2", "Sàn 3"] as const;

/** Hướng dẫn cho điểm kế tiếp cần chọn (null khi đã đủ). */
export function nextPointHint(count: number): string | null {
  if (count <= 0) return "Chọn điểm A: một đầu của vật bạn biết kích thước thật.";
  if (count === 1) return "Chọn điểm B: đầu còn lại của vật đó.";
  if (count < METRIC_POINT_COUNT) return `Chọn điểm sàn ${count - 1}/3: trải rộng trên mặt sàn phẳng.`;
  return null;
}

/** Khoảng cách người dùng nhập (mét): dương, hữu hạn, ≤ 1000 như backend. */
export function parseDistance(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d*\.?\d+$/.test(normalized)) return null;
  const distance = Number(normalized);
  return Number.isFinite(distance) && distance > 0 && distance <= 1000 ? distance : null;
}

/** Payload REC-06 khi đủ 5 điểm và khoảng cách hợp lệ; ngược lại null. */
export function metricInput(points: readonly InspectionPoint[], distance: string): MetricInput | null {
  const meters = parseDistance(distance);
  if (points.length !== METRIC_POINT_COUNT || meters === null) return null;
  const [a, b, f1, f2, f3] = points.map((point) => [point[0], point[1], point[2]] as MetricPoint);
  return { point_a: a, point_b: b, floor_points: [f1, f2, f3], distance_m: meters };
}
