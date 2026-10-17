"use client";

import { Notice } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";
import { MetricConfirmView } from "@/features/studio/MetricConfirmView";
import { ObjectReviewView, type SaveState } from "@/features/studio/ObjectReviewView";
import type { Preview, StageState, StudioMode } from "@/features/studio/scene/state";
import { PreviewScene } from "@/features/studio/scene/PreviewScene";
import { DemoControls } from "@/features/studio/scene/DemoControls";
import type { MetricDraft } from "@/features/studio/MetricConfirmView";

export function StudioTab({
  jobId,
  title,
  canMutate,
  preview,
  mode,
  geometry,
  sceneReady,
  revision,
  onSaveState,
  onMetricClose,
  onMetricConfirmed,
  metricDraft,
  onMetricDraft,
}: {
  jobId: string;
  title: string;
  canMutate: boolean;
  preview: Preview;
  mode: StudioMode;
  geometry: StageState;
  sceneReady: boolean;
  /** Revision mới nhất header biết (vd. sau khi tạo gói); Studio giữ sống dùng để tự tải lại. */
  revision: string | null;
  onSaveState: (state: SaveState) => void;
  onMetricClose: () => void;
  onMetricConfirmed: () => void;
  metricDraft?: MetricDraft;
  onMetricDraft?: (draft: MetricDraft) => void;
}) {
  if (!canMutate) {
    return (
      <div className="flex h-full flex-col">
        <Notice className="m-3">Bạn đang xem scene của người khác. Scene này ở chế độ chỉ xem.</Notice>
        <div className="min-h-0 flex-1">
          <PreviewScene jobId={jobId} contentUrl={preview.url} filename={preview.filename} title={`Viewer 3DGS: ${title}`} />
        </div>
      </div>
    );
  }
  if (mode === "metric") {
    return (
      <MetricConfirmView jobId={jobId} contentUrl={preview.url} filename={preview.filename} onClose={onMetricClose} onConfirmed={onMetricConfirmed} draft={metricDraft} onDraft={onMetricDraft} />
    );
  }
  if (mode === "gaussian") {
    return (
      <div className="flex h-full flex-col">
        <div className="min-h-0 flex-1">
          <EditorFrame contentUrl={preview.url} filename={preview.filename} homeHref="/scenes" title={`Editor 3D: ${title}`} />
        </div>
      </div>
    );
  }
  if (sceneReady) return <ObjectReviewView jobId={jobId} revision={revision} onSaveState={onSaveState} canMutateJob={canMutate}
    sceneStateControls={<DemoControls scope="state" jobId={jobId} revision={revision} sceneReady
      onRestored={(next) => onSaveState({ status: "saved", revision: next })} />} />;
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
        <PreviewScene jobId={jobId} contentUrl={preview.url} filename={preview.filename} title={`Viewer 3DGS: ${title}`} />
      </div>
    </div>
  );
}
