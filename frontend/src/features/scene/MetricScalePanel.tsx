"use client";

/**
 * Metric Scale panel — dùng dữ liệu thật từ `SceneIR.metric_scale`.
 *
 * Phần alignment cần tương tác chọn 2 điểm / nhập khoảng cách thật nằm ngoài
 * contract hiện tại, nên hiển thị read-only với nhãn mock.
 */

import { Badge } from "@/components/ui/badge";
import { Banner } from "@/components/ui/banner";
import { Panel, PanelHeader } from "@/components/ui/panel";
import type { SceneIR } from "@/lib/contracts/api";

interface MetricScalePanelProps {
  metricScale: SceneIR["metric_scale"];
}

export function MetricScalePanel({ metricScale }: MetricScalePanelProps) {
  return (
    <Panel>
      <div className="p-3">
        <PanelHeader
          title="Metric Scale"
          subtitle={`status: ${metricScale.status}`}
        />
        <div className="mt-2 flex items-center gap-2">
          <Badge tone={metricScale.status === "CONFIRMED" ? "ok" : "warn"}>
            {metricScale.status}
          </Badge>
          <span className="font-mono text-sm text-slate-200">
            {metricScale.meters_per_unit ?? "chưa xác định"}
          </span>
          <span className="text-[10px] text-slate-500">meters / unit</span>
        </div>
        <Banner tone="mock" title="Alignment chưa có backend">
          REC-06 đã có xử lý metric, nhưng thao tác chọn anchor và xác nhận từ UI chưa được nối.
          Hiện chỉ hiển thị giá trị metric_scale từ SceneIR; đây không phải form xác nhận metric.
        </Banner>
      </div>
    </Panel>
  );
}
