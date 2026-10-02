"use client";

import { errorMessage } from "@/lib/ui-error";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Notice } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import { SceneWorkspace } from "@/features/studio/SceneWorkspace";
import { getSample, sampleFileUrl } from "@/lib/api/studio";
import type { DemoManifest } from "@/lib/contracts/studio";

/** Editor cho scene của video mẫu (file 3DGS trong bundle đã xử lý sẵn). */
export function SampleScene({ sampleId }: { sampleId: string }) {
  const [demo, setDemo] = useState<DemoManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  usePageTitle(demo?.title ?? null);
  useEffect(() => {
    let alive = true;
    void getSample(sampleId).then((result) => {
      if (!alive) return;
      if (result.ok) setDemo(result.data);
      else setError(errorMessage(result.error));
    });
    return () => {
      alive = false;
    };
  }, [sampleId]);

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <Notice tone="rust">Không mở được scene mẫu: {error}</Notice>
      </main>
    );
  }
  if (!demo) {
    return (
      <main className="grid h-[calc(100dvh-3rem)] place-items-center text-sm text-ink-muted" role="status">
        <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden />
      </main>
    );
  }
  return (
    <SceneWorkspace
      title={demo.title}
      backHref={`/new/try-demo?sample=${encodeURIComponent(sampleId)}`}
      contentUrl={sampleFileUrl(sampleId, demo.splat.name)}
      filename={demo.splat.name}
      badges={<Badge tone="ember">Video mẫu · xử lý sẵn</Badge>}
    />
  );
}
