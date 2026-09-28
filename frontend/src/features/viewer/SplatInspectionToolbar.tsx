"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { pointDistance, proposedMetricScale, type InspectionState } from "./inspection-history";
import type { SplatInspection } from "./splat-inspection";

/** Inspection cục bộ rõ ràng; không có nút confirm/save giả khi REC-06 chưa nối. */
export function SplatInspectionToolbar({ controller, state, loaded }: {
  controller: SplatInspection | null; state: InspectionState; loaded: boolean;
}) {
  const [measurement, setMeasurement] = useState({ points: state.points, value: "" });
  const realDistance = measurement.points === state.points ? measurement.value : "";
  const distance = pointDistance(state.points);
  const scale = proposedMetricScale(distance, Number(realDistance));
  const disabled = !controller || !loaded || state.busy;

  return <section className="space-y-3 rounded-lg border border-slate-700 p-3" aria-label="Công cụ inspection 3DGS"
    onFocusCapture={() => controller?.setFormFocused(true)}
    onBlurCapture={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) controller?.setFormFocused(false);
    }}>
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" disabled={disabled} onClick={() => controller?.frameScene()}>Fit scene</Button>
      <Button variant="secondary" disabled={disabled} onClick={() => controller?.resetCamera()}>Reset camera</Button>
      <Button variant={state.measuring ? "primary" : "secondary"} disabled={disabled}
        onClick={() => controller?.setMeasuring(!state.measuring)}>
        {state.measuring ? "Thoát chọn điểm" : "Chọn 2 điểm / đo"}
      </Button>
      <Button variant="secondary" disabled={disabled || !state.canUndo} onClick={() => controller?.undo()}>Undo điểm</Button>
      <Button variant="secondary" disabled={disabled || !state.canRedo} onClick={() => controller?.redo()}>Redo điểm</Button>
      <Button variant="secondary" disabled={disabled || !state.points.length} onClick={() => controller?.clear()}>Xóa điểm đo</Button>
    </div>
    {state.measuring && <p className="text-sm text-sky-300">Click bề mặt để chọn A (xanh), B (vàng). Click thứ ba bắt đầu cặp mới. Thoát chọn điểm để orbit/pan.</p>}
    {state.busy && <p role="status" className="text-xs">Đang đọc điểm từ GPU…</p>}
    {state.error && <p role="alert" className="text-sm text-rose-400">{state.error}</p>}
    {state.points.length > 0 && <div className="space-y-1 text-xs text-slate-300">
      {state.points.map((point, index) => <p key={index}>{index === 0 ? "A" : "B"} — tọa độ nguồn: {point.map((value) => value.toFixed(5)).join(", ")}</p>)}
      {distance !== null && <p>Khoảng cách: {distance.toPrecision(7)} đơn vị nguồn — chưa phải mét.</p>}
    </div>}
    {distance !== null && <div className="space-y-2">
      <label className="flex flex-wrap items-center gap-2 text-sm">
        Khoảng cách thực bạn đã đo (m)
        <input type="number" inputMode="decimal" min="0" step="any" value={realDistance}
          className="w-36 rounded border border-slate-600 bg-slate-950 px-2 py-1"
          onChange={(event) => setMeasurement({ points: state.points, value: event.target.value })} />
      </label>
      <p className="text-xs text-amber-300">{scale === null ? "Cần hai điểm khác nhau và số đo dương hữu hạn." :
        `Scale đề xuất: ${scale.toPrecision(7)} m/đơn vị nguồn. Chỉ là bản nháp, chưa áp dụng hoặc xác nhận metric.`}</p>
    </div>}
    <p className="text-xs text-slate-400">Điểm lấy từ depth Gaussian, có thể lệch ở vùng trong suốt/floaters. Đây là inspection tạm thời, không sửa artifact hay collision. Dấu điểm hiển thị xuyên bề mặt để dễ nhận biết.</p>
  </section>;
}
