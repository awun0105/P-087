import { notFound } from "next/navigation";

import { inspectionStage } from "@/features/studio/inspection";
import { StageInspectionPage } from "@/features/studio/inspection/StageInspectionPage";

export default async function StageRoute({ params }: PageProps<"/scenes/[jobId]/stages/[stageId]">) {
  const { jobId, stageId } = await params;
  if (!inspectionStage(stageId)) notFound();
  return <StageInspectionPage key={`${jobId}:${stageId}`} jobId={jobId} stageId={stageId} />;
}
