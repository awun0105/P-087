"use client";

import { errorMessage } from "@/lib/ui-error";

import { useEffect, useState } from "react";

import { Badge, Button, Card, Notice } from "@/components/studio/primitives";
import type { SaveState } from "@/features/studio/ObjectReviewView";
import { ReviewPanel } from "@/features/studio/ReviewPanel";
import { ValidationRunsPanel } from "@/features/studio/ValidationRunsPanel";
import { SimulationPackagePanel } from "@/features/studio/SimulationPackagePanel";
import { HelpDetails } from "@/components/studio/feedback";
import { floorFitDiagnostic } from "@/features/studio/scene/floorFitDiagnostic";
import { EvaluationCard } from "@/features/studio/evaluation/EvaluationCard";
import { ValueCard } from "@/features/studio/value/ValueCard";
import { ValidationReportCard } from "@/features/studio/ValidationReportCard";
import { getJobScene, type ReviewStateView } from "@/lib/api/studio";
import { GEOMETRY_NOT_READY_REASON, objectGeometryState } from "@/lib/scene/geometry-state";
import { RegistrationPanel } from "@/features/studio/scene/RegistrationPanel";

export function ReviewTab({ jobId, canMutateJob, onSaveState }: { jobId: string; canMutateJob: boolean; onSaveState: (state: SaveState) => void }) {
  const [revision, setRevision] = useState<string | null>(null);
  const [geometryLocked, setGeometryLocked] = useState(false);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [floorFit, setFloorFit] = useState<ReturnType<typeof floorFitDiagnostic>>(null);
  const [reviewRefresh, setReviewRefresh] = useState(0);
  // Trạng thái duyệt do ReviewPanel tải; ở đây chỉ dùng lại để vẽ báo cáo chi tiết của đúng revision.
  const [review, setReview] = useState<ReviewStateView | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getJobScene(jobId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setError(null);
        setRevision(result.data.scene.scene_revision);
        setGeometryLocked(objectGeometryState(result.data.scene) === "awaiting_review");
        setFloorFit(floorFitDiagnostic(result.data.scene.provenance));
        // Tạo gói ghi một revision mới (collider vật đã xác nhận) → header phải theo revision đó.
        onSaveState({ status: "saved", revision: result.data.scene.scene_revision });
      } else {
        setFloorFit(null);
        setError(errorMessage(result.error));
      }
    });
    return () => controller.abort();
  }, [jobId, reload, onSaveState]);
  if (error) return <Notice tone="rust" className="m-4">{error} <Button size="sm" variant="secondary" onClick={() => setReload((value) => value + 1)}>Thử lại</Button></Notice>;
  if (!revision) return <p className="p-6 text-sm text-ink-muted" role="status">Đang tải scene…</p>;
  return (
    <div className="mx-auto grid max-w-5xl gap-4 px-4 py-6 sm:px-6 lg:grid-cols-2">
      <div className="lg:col-span-2">
        <h2 className="flex flex-wrap items-center gap-2 text-xl font-bold tracking-tight">Kiểm tra & duyệt <Badge tone="neutral">{revision}</Badge></h2>
        <p className="mt-1 text-sm text-ink-muted">Tạo gói và đọc preflight trước; validation cùng quyết định Reviewer áp dụng cho đúng gói của revision này.</p>
      </div>
      {floorFit && <div className="lg:col-span-2">
        <Notice tone={floorFit.tone}>
          <div className="space-y-1">
            <p className="font-semibold">{floorFit.title}</p>
            <p>{floorFit.message}</p>
            {floorFit.evidenceArtifactUri && <details className="pt-1 text-xs">
              <summary className="cursor-pointer font-medium">Mã báo cáo floor fit</summary>
              <code className="mt-1 block break-all font-mono">{floorFit.evidenceArtifactUri}</code>
            </details>}
          </div>
        </Notice>
      </div>}
      <Card className="overflow-hidden lg:col-span-2">
        <RegistrationPanel jobId={jobId} sceneRevision={revision} canMutateJob={canMutateJob} />
      </Card>
      <Card className="overflow-hidden">
        <SimulationPackagePanel
          jobId={jobId}
          sceneRevision={revision}
          canCreate={canMutateJob}
          lockedReason={geometryLocked ? GEOMETRY_NOT_READY_REASON : null}
          onSceneChanged={() => setReload((value) => value + 1)}
        />
      </Card>
      <Card className="overflow-hidden">
        <ReviewPanel jobId={jobId} sceneRevision={revision} refreshToken={reviewRefresh} onState={setReview} />
      </Card>
      {review?.record.scene_revision === revision && (
        <Card className="overflow-hidden lg:col-span-2">
          <ValidationRunsPanel
            jobId={jobId}
            sceneRevision={revision}
            candidateChecksum={review.record.candidate_checksum}
            canMutateJob={canMutateJob}
            onSelected={() => setReviewRefresh((value) => value + 1)}
          />
        </Card>
      )}
      {review?.validation && review.record.scene_revision === revision && (
        <Card className="overflow-hidden lg:col-span-2">
          <ValidationReportCard state={review} />
        </Card>
      )}
      <Card className="overflow-hidden lg:col-span-2">
        <ValueCard jobId={jobId} revision={revision} />
      </Card>
      <details className="lg:col-span-2">
        <summary className="cursor-pointer select-none px-1 py-2 text-sm font-semibold text-ink-muted hover:text-ink">
          Chi tiết kỹ thuật
        </summary>
        <Card className="mt-2 overflow-hidden">
          <EvaluationCard jobId={jobId} revision={revision} />
        </Card>
      </details>
      <div className="lg:col-span-2"><HelpDetails title="Gói và quyết định duyệt gắn với revision nào?">
        Mọi thay đổi vật thể sau khi tạo gói sẽ sinh revision mới: gói, báo cáo validation và quyết định duyệt cũ không còn áp dụng
        cho revision đó.
      </HelpDetails></div>
    </div>
  );
}
