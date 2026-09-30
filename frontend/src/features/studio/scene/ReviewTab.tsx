"use client";

import { Info } from "lucide-react";
import { useEffect, useState } from "react";

import { Card, Notice } from "@/components/studio/primitives";
import type { SaveState } from "@/features/studio/ObjectReviewView";
import { ReviewPanel } from "@/features/studio/ReviewPanel";
import { SimulationPackagePanel } from "@/features/studio/SimulationPackagePanel";
import { getJobScene } from "@/lib/api/studio";

export function ReviewTab({ jobId, onSaveState }: { jobId: string; onSaveState: (state: SaveState) => void }) {
  const [revision, setRevision] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getJobScene(jobId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setRevision(result.data.scene.scene_revision);
        // Tạo gói ghi một revision mới (collider vật đã xác nhận) → header phải theo revision đó.
        onSaveState({ status: "saved", revision: result.data.scene.scene_revision });
      } else setError(result.error.detail);
    });
    return () => controller.abort();
  }, [jobId, reload, onSaveState]);
  if (error) return <Notice tone="rust" className="m-4">{error}</Notice>;
  if (!revision) return <p className="p-6 text-sm text-ink-muted" role="status">Đang tải scene…</p>;
  return (
    <div className="mx-auto grid max-w-5xl gap-4 px-4 py-6 sm:px-6 lg:grid-cols-2">
      <Card className="overflow-hidden">
        <SimulationPackagePanel jobId={jobId} sceneRevision={revision} onSceneChanged={() => setReload((value) => value + 1)} />
      </Card>
      <Card className="overflow-hidden">
        <ReviewPanel jobId={jobId} sceneRevision={revision} />
      </Card>
      <Notice icon={<Info aria-hidden />} className="lg:col-span-2">
        Mọi thay đổi vật thể sau khi tạo gói sẽ sinh revision mới: gói, báo cáo validation và quyết định duyệt cũ không còn áp dụng
        cho revision đó.
      </Notice>
    </div>
  );
}
