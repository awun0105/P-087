"use client";

import { useState } from "react";

import type { RegistrationOverlayPreview } from "@/lib/api/registration";

const VIEW_WIDTH = 640;

function svgPoint(point: readonly [number, number], preview: RegistrationOverlayPreview, height: number): [number, number] {
  const [minX, minY] = preview.bounds_min_xy_m;
  const [maxX, maxY] = preview.bounds_max_xy_m;
  return [
    ((point[0] - minX) / (maxX - minX)) * VIEW_WIDTH,
    height - ((point[1] - minY) / (maxY - minY)) * height,
  ];
}

function metres(value: number): string {
  return `${value.toFixed(2)} m`;
}

export function RegistrationOverlay({
  previews,
  selectedCandidateId,
  onCandidateChange,
}: {
  previews: RegistrationOverlayPreview[];
  selectedCandidateId?: string | null;
  onCandidateChange?: (candidateId: string) => void;
}) {
  const [localCandidateId, setLocalCandidateId] = useState<string | null>(null);
  const candidateId = selectedCandidateId === undefined ? localCandidateId : selectedCandidateId;
  const preview = previews.find((item) => item.candidate_id === candidateId) ?? previews[0];
  if (!preview) return null;

  const extentX = preview.bounds_max_xy_m[0] - preview.bounds_min_xy_m[0];
  const extentY = preview.bounds_max_xy_m[1] - preview.bounds_min_xy_m[1];
  const height = VIEW_WIDTH * extentY / extentX;
  const sourcePoints = preview.source_points_xy_world_m.map((point, index) => {
    const [cx, cy] = svgPoint(point, preview, height);
    return <circle key={`lidar-${index}`} cx={cx} cy={cy} r="2.2" fill="var(--studio-marker-a)" fillOpacity="0.72" />;
  });
  const targetPoints = preview.target_points_xy_world_m.map((point, index) => {
    const [cx, cy] = svgPoint(point, preview, height);
    return <circle key={`rgb-${index}`} cx={cx} cy={cy} r="2.2" fill="var(--studio-marker-b)" fillOpacity="0.68" />;
  });

  return (
    <figure className="space-y-2 rounded-lg border border-line p-3" aria-label="Bản xem trước chồng chiếu registration">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <figcaption className="text-sm font-medium">Chồng chiếu BEV (chỉ để kiểm tra)</figcaption>
        {previews.length > 1 && (
          <label className="flex items-center gap-2 text-sm">
            <span>Phương án</span>
            <select
              aria-label="Phương án chồng chiếu"
              className="rounded-md border border-line bg-paper px-2 py-1 text-ink"
              value={preview.candidate_id}
              onChange={(event) => {
                setLocalCandidateId(event.target.value);
                onCandidateChange?.(event.target.value);
              }}
            >
              {previews.map((item) => <option key={item.candidate_id} value={item.candidate_id}>{item.candidate_id}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted" aria-label="Chú giải chồng chiếu">
        <span><span aria-hidden="true" className="mr-1 inline-block size-2 rounded-full bg-[var(--studio-marker-a)]" />LiDAR đã biến đổi</span>
        <span><span aria-hidden="true" className="mr-1 inline-block size-2 rounded-full bg-[var(--studio-marker-b)]" />RGB theo scale giả thuyết</span>
      </div>
      <svg
        role="img"
        aria-label={`Hình chiếu bằng LiDAR và RGB cho ${preview.candidate_id}`}
        viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
        className="h-auto max-h-96 w-full rounded-md border border-line bg-paper-sunken"
        preserveAspectRatio="xMidYMid meet"
      >
        <title>{`Hình chiếu bằng chẩn đoán ${preview.candidate_id}; không phải kết quả QA`}</title>
        {targetPoints}
        {sourcePoints}
      </svg>
      <p className="text-xs text-ink-muted">
        {preview.candidate_id}; scale RGB: {preview.rgb_scale_factor === null ? "1.00×" : `${preview.rgb_scale_factor.toFixed(3)}×`};
        {" "}hiển thị {preview.source_points_xy_world_m.length}/{preview.source_in_roi_point_count} điểm LiDAR và{" "}
        {preview.target_points_xy_world_m.length}/{preview.target_in_roi_point_count} điểm RGB trong vùng {metres(extentX)} × {metres(extentY)}.
        {" "}Mỗi lớp lấy mẫu tối đa {preview.sample_cap_per_cloud} điểm; hình chiếu này không thay thế QA hoặc kiểm chứng thực địa.
      </p>
    </figure>
  );
}
