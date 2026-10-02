/**
 * Thứ tự điểm của bước xác nhận tỉ lệ mét: A, B (đoạn biết độ dài thật), C, D (đoạn
 * kiểm độc lập, owner chốt 2026-09-29) rồi 3 điểm trên mặt sàn. Backend (REC-06) dùng
 * sàn làm z=0, A→B làm trục X, A làm gốc, và đo lại C–D để kiểm tỉ lệ.
 */
import type { InspectionPoint } from "@/features/viewer/inspection-history";
import type { DistanceSource, MetricInput, MetricPoint, MetricProposal } from "@/lib/contracts/studio";

export const METRIC_POINT_COUNT = 7;

export const METRIC_POINT_LABELS = ["A", "B", "C", "D", "Sàn 1", "Sàn 2", "Sàn 3"] as const;

/** Độ dài tối thiểu mỗi đoạn, khớp `MIN_SEGMENT_M` của backend. */
export const MIN_SEGMENT_M = 0.5;

/**
 * Bảy điểm của đề xuất tự động theo đúng thứ tự A, B, C, D, sàn 1–3; null khi đề xuất chỉ có tỉ lệ
 * (không tìm được mặt sàn) — khi đó người dùng tự chọn điểm và chỉ khoảng cách được điền.
 */
export function proposalPoints(proposal: MetricProposal): MetricPoint[] | null {
  if (!proposal.floor || !proposal.segments) return null;
  const { point_a, point_b, check_a, check_b } = proposal.segments;
  return [point_a, point_b, check_a, check_b, ...proposal.floor.points];
}

/**
 * Khoảng cách A–B và C–D theo tỉ lệ đề xuất: độ dài trong scene × tỉ lệ. Backend chỉ nhận nguồn
 * `ai_estimated` khi hai số này đúng bằng phép tính đó, nên luôn tính lại từ điểm đang chọn.
 */
export function estimatedDistances(
  pairs: [[MetricPoint, MetricPoint], [MetricPoint, MetricPoint]],
  scale: number,
): [number, number] {
  const length = ([a, b]: [MetricPoint, MetricPoint]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * scale;
  return [length(pairs[0]), length(pairs[1])];
}

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
