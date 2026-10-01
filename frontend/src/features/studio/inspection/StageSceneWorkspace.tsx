"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { Button, Notice } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";
import { progressHref } from "@/features/studio/inspection";
import { getPreview, jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { StageId } from "@/lib/contracts/api";
import type { ReconstructionPreview } from "@/lib/contracts/preview";

const StageViewer = dynamic(() => import("@/features/studio/StageViewer").then((m) => m.StageViewer), { ssr: false });
const ObjectReview = dynamic(() => import("@/features/studio/ObjectReviewView").then((m) => m.ObjectReviewView), { ssr: false });
const Comparison = dynamic(() => import("@/features/studio/ModeComparisonView").then((m) => m.ModeComparisonView), { ssr: false });

/** Workspace scene chung cho 5–8; công cụ hiện có giữ nguyên hệ tọa độ và biên lưu. */
export function StageSceneWorkspace({ jobId, stageId, title }: { jobId: string; stageId: StageId; title: string }) {
  const [mode, setMode] = useState<"scene" | "comparison">("scene");
  return <div className="flex h-full min-h-[24rem] flex-col">
    <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-2">
      <p className="min-w-0 flex-1 text-xs text-ink-muted">{stageId === "ST-VISUAL-RECON" ? "Gaussian gốc · chưa quy đổi mét · chỉnh trong phiên, File › Export PLY/SOG"
        : stageId === "ST-METRIC-CANONICALIZE" ? "Kết quả hệ mét · xác nhận đã publish, không đo lại hoặc ghi đè bản xác nhận"
          : stageId === "ST-RGB-GEOMETRY" ? "Scene hệ mét + collision · bật/tắt lớp để kiểm tra hình học"
            : "SceneObject hiện tại · chọn vật thể trong 3D, xác nhận/loại, chỉnh inspector; thao tác lưu revision mới"}</p>
      {stageId === "ST-METRIC-CANONICALIZE" && <div role="group" aria-label="Công cụ hệ mét"><Button size="sm" variant={mode === "scene" ? "secondary" : "ghost"} onClick={() => setMode("scene")}>Scene 3D</Button><Button size="sm" variant={mode === "comparison" ? "secondary" : "ghost"} onClick={() => setMode("comparison")}>Xem số đo & so sánh</Button></div>}
    </div>
    <div className="relative min-h-0 flex-1">
      {stageId === "ST-VISUAL-RECON" ? <GaussianWorkspace jobId={jobId} title={title} />
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
      else setError(result.error.detail);
    });
    return () => { alive = false; };
  }, [jobId, reload]);
  if (error) return <Notice tone="rust" className="m-4">Không mở được bản 3DGS: {error} <Button size="sm" variant="secondary" onClick={() => setReload((value) => value + 1)}>Thử lại</Button></Notice>;
  if (!preview) return <p role="status" className="p-6 text-sm text-ink-muted">Đang tải bản 3DGS…</p>;
  return <EditorFrame contentUrl={jobArtifactContentUrl(jobId, preview.delivery_ref)} filename={preview.delivery_ref.artifact_uri.split("/").pop() ?? "scene.sog"} homeHref={progressHref(jobId)} title={`5. 3DGS: ${title}`} />;
}
