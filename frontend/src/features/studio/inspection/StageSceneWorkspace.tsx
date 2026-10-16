"use client";

import { errorMessage } from "@/lib/ui-error";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { Button, Notice } from "@/components/studio/primitives";
import { PreviewScene } from "@/features/studio/scene/PreviewScene";
import { useUrlState } from "@/features/studio/useUrlState";
import { getPreview, jobArtifactContentUrl } from "@/lib/api/endpoints";
import { getTrainingRecording } from "@/lib/api/studio";
import type { StageId } from "@/lib/contracts/api";
import type { ReconstructionPreview } from "@/lib/contracts/preview";

const StageViewer = dynamic(() => import("@/features/studio/StageViewer").then((m) => m.StageViewer), { ssr: false });
const ObjectReview = dynamic(() => import("@/features/studio/ObjectReviewView").then((m) => m.ObjectReviewView), { ssr: false });
const RerunTraining = dynamic(() => import("@/features/studio/inspection/RerunTrainingView").then((m) => m.RerunTrainingView), { ssr: false });
const Comparison = dynamic(() => import("@/features/studio/ModeComparisonView").then((m) => m.ModeComparisonView), { ssr: false });

/** Workspace scene chung cho 5–8; công cụ hiện có giữ nguyên hệ tọa độ và biên lưu. */
export function StageSceneWorkspace({ jobId, stageId, title }: { jobId: string; stageId: StageId; title: string }) {
  const { params, update } = useUrlState();
  // Bản ghi Rerun là dữ liệu tuỳ chọn: không có thì bước 3DGS giữ nguyên một chế độ xem như trước.
  const [recordingJob, setRecordingJob] = useState<string | null>(null);
  useEffect(() => {
    if (stageId !== "ST-VISUAL-RECON") return;
    const controller = new AbortController();
    void getTrainingRecording(jobId, controller.signal).then((recording) => {
      if (!controller.signal.aborted && recording.available) setRecordingJob(jobId);
    });
    return () => controller.abort();
  }, [jobId, stageId]);
  const hasRecording = stageId === "ST-VISUAL-RECON" && recordingJob === jobId;
  const view = params.get("view");
  const mode = view === "comparison" ? "comparison" : view === "training" && hasRecording ? "training" : "scene";
  const setMode = (next: string) => update({ view: next });
  return <div className="flex h-full min-h-[24rem] flex-col">
    {(hasRecording || stageId === "ST-METRIC-CANONICALIZE") && <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-2">
      {hasRecording && <div role="group" aria-label="Chế độ xem 3DGS"><Button size="sm" variant={mode === "scene" ? "secondary" : "ghost"} onClick={() => setMode("scene")}>Scene 3D</Button><Button size="sm" variant={mode === "training" ? "secondary" : "ghost"} onClick={() => setMode("training")}>Quá trình train (Rerun)</Button></div>}
      {stageId === "ST-METRIC-CANONICALIZE" && <div role="group" aria-label="Công cụ hệ mét"><Button size="sm" variant={mode === "scene" ? "secondary" : "ghost"} onClick={() => setMode("scene")}>Scene 3D</Button><Button size="sm" variant={mode === "comparison" ? "secondary" : "ghost"} onClick={() => setMode("comparison")}>Xem số đo & so sánh</Button></div>}
    </div>}
    <div className="relative min-h-0 flex-1">
      {mode === "training" ? <RerunTraining jobId={jobId} />
        : stageId === "ST-VISUAL-RECON" ? <GaussianWorkspace jobId={jobId} title={title} />
        : stageId === "ST-OBJECT-EXTRACT" ? <ObjectReview jobId={jobId} />
          : mode === "comparison" ? <Comparison jobId={jobId} />
            : <StageViewer jobId={jobId} stageId={stageId} fallbackStageId={stageId === "ST-METRIC-CANONICALIZE" ? "ST-VISUAL-RECON" : undefined} />}
    </div>
  </div>;
}

function GaussianWorkspace({ jobId, title }: { jobId: string; title: string }) {
  const [preview, setPreview] = useState<ReconstructionPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    void getPreview(jobId).then((result) => {
      if (!alive) return;
      if (result.ok) { setPreview(result.data); setError(null); }
      else setError(errorMessage(result.error));
    });
    return () => { alive = false; };
  }, [jobId, reload]);
  if (error) return <Notice tone="rust" className="m-4">Không mở được bản 3DGS: {error} <Button size="sm" variant="secondary" onClick={() => setReload((value) => value + 1)}>Thử lại</Button></Notice>;
  if (!preview) return <p role="status" className="p-6 text-sm text-ink-muted">Đang tải bản 3DGS…</p>;
  // `jobId` để viewer lấy quỹ đạo camera của job: mở đầu bên trong scene và có replay theo quỹ đạo quay.
  return <PreviewScene jobId={jobId} contentUrl={jobArtifactContentUrl(jobId, preview.delivery_ref)} filename={preview.delivery_ref.artifact_uri.split("/").pop() ?? "scene.sog"} title={`5. 3DGS: ${title}`} />;
}
