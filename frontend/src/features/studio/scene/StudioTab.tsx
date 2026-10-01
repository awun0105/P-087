"use client";

import { Notice } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";
import { MetricConfirmView } from "@/features/studio/MetricConfirmView";
import { ObjectReviewView, type SaveState } from "@/features/studio/ObjectReviewView";
import type { Preview, StageState, StudioMode } from "@/features/studio/scene/state";

export function StudioTab({
  jobId,
  title,
  preview,
  mode,
  geometry,
  sceneReady,
  revision,
  onSaveState,
  onMetricClose,
  onMetricConfirmed,
}: {
  jobId: string;
  title: string;
  preview: Preview;
  mode: StudioMode;
  geometry: StageState;
  sceneReady: boolean;
  /** Revision mới nhất header biết (vd. sau khi tạo gói); Studio giữ sống dùng để tự tải lại. */
  revision: string | null;
  onSaveState: (state: SaveState) => void;
  onMetricClose: () => void;
  onMetricConfirmed: () => void;
}) {
  if (mode === "metric") {
    return (
      <MetricConfirmView jobId={jobId} contentUrl={preview.url} filename={preview.filename} onClose={onMetricClose} onConfirmed={onMetricConfirmed} />
    );
  }
  if (mode === "gaussian") {
    return (
      <div className="flex h-full flex-col">
        <p className="border-b border-line bg-paper px-4 py-1.5 text-xs text-ink-muted">
          Chỉnh Gaussian trong SuperSplat: thay đổi chỉ nằm trong phiên editor và xuất ra file (File › Export PLY/SOG); không lưu vào scene, không qua duyệt.
        </p>
        <div className="min-h-0 flex-1">
          <EditorFrame contentUrl={preview.url} filename={preview.filename} homeHref="/scenes" title={`Editor 3D: ${title}`} />
        </div>
      </div>
    );
  }
  if (sceneReady) return <ObjectReviewView jobId={jobId} revision={revision} onSaveState={onSaveState} />;
  return (
    <div className="flex h-full flex-col">
      <Notice tone={geometry === "failed" ? "rust" : "ochre"} className="m-3">
        {geometry === "running"
          ? "Đang dựng collision và tách vật thể; Studio vật thể mở khi xong. Tạm thời xem bản 3DGS bên dưới."
          : geometry === "failed"
            ? "Bước dựng collision lỗi — xem tab Tiến trình và bấm Thử lại."
            : "Bản xem 3DGS (chưa quy đổi mét). Studio vật thể mở sau khi xác nhận tỉ lệ và dựng collision."}
      </Notice>
      <div className="min-h-0 flex-1">
        <EditorFrame contentUrl={preview.url} filename={preview.filename} homeHref="/scenes" title={`Editor 3D: ${title}`} />
      </div>
    </div>
  );
}
