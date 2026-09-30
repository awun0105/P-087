/**
 * Thứ tự điểm của bước xác nhận tỉ lệ mét: A, B (đoạn biết độ dài thật), C, D (đoạn
 * kiểm độc lập, owner chốt 2026-09-29) rồi 3 điểm trên mặt sàn. Backend (REC-06) dùng
 * sàn làm z=0, A→B làm trục X, A làm gốc, và đo lại C–D để kiểm tỉ lệ.
 */
import type { InspectionPoint } from "@/features/viewer/inspection-history";
import type { DistanceSource, MetricInput, MetricPoint } from "@/lib/contracts/studio";

export const METRIC_POINT_COUNT = 7;

export const METRIC_POINT_LABELS = ["A", "B", "C", "D", "Sàn 1", "Sàn 2", "Sàn 3"] as const;

/** Độ dài tối thiểu mỗi đoạn, khớp `MIN_SEGMENT_M` của backend. */
export const MIN_SEGMENT_M = 0.5;

/** Hướng dẫn cho điểm kế tiếp cần chọn (null khi đã đủ). */
export function nextPointHint(count: number): string | null {
  if (count <= 0) return "Chọn điểm A: một đầu của vật bạn biết kích thước thật (dài ≥ 0,5 m).";
  if (count === 1) return "Chọn điểm B: đầu còn lại của vật đó.";
  if (count === 2) return "Chọn điểm C: một đầu của vật thứ hai để kiểm tỉ lệ.";
  if (count === 3) return "Chọn điểm D: đầu còn lại của vật thứ hai.";
  if (count < METRIC_POINT_COUNT) return `Chọn điểm sàn ${count - 3}/3: trải rộng trên mặt sàn phẳng.`;
  return null;
}

/** Khoảng cách người dùng nhập (mét): dương, hữu hạn, ≤ 1000 như backend. */
export function parseDistance(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d*\.?\d+$/.test(normalized)) return null;
  const distance = Number(normalized);
  return Number.isFinite(distance) && distance > 0 && distance <= 1000 ? distance : null;
}

function point(value: InspectionPoint): MetricPoint {
  return [value[0], value[1], value[2]];
}

/** Hai đoạn A/B và C/D khi đã chọn đủ 4 điểm đầu (để đo trên LiDAR). */
export function segments(points: readonly InspectionPoint[]): [[MetricPoint, MetricPoint], [MetricPoint, MetricPoint]] | null {
  if (points.length < 4) return null;
  return [
    [point(points[0]), point(points[1])],
    [point(points[2]), point(points[3])],
  ];
}

/** Payload REC-06 khi đủ 7 điểm và hai số đo hợp lệ; ngược lại null. */
export function metricInput(
  points: readonly InspectionPoint[],
  distance: string,
  checkDistance: string,
  source: DistanceSource = "user_measured",
): MetricInput | null {
  const meters = parseDistance(distance);
  const checkMeters = parseDistance(checkDistance);
  if (points.length !== METRIC_POINT_COUNT || meters === null || checkMeters === null) return null;
  const [a, b, c, d, f1, f2, f3] = points.map(point);
  return {
    point_a: a,
    point_b: b,
    distance_m: meters,
    check_a: c,
    check_b: d,
    check_distance_m: checkMeters,
    floor_points: [f1, f2, f3],
    distance_source: source,
  };
}
