"use client";

import { errorMessage } from "@/lib/ui-error";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import { SceneWorkspace } from "@/features/studio/SceneWorkspace";
import { getSample, sampleFileUrl } from "@/lib/api/studio";
import type { DemoManifest } from "@/lib/contracts/studio";
import { apiFetch } from "@/lib/api/client";

interface DemoSession {
  session_id: string;
  job_id: string;
  source_revision: string;
  expires_at: string;
}

function closeSession(session: DemoSession): void {
  void fetch(`/api/v1/demo-sessions/${encodeURIComponent(session.session_id)}`, {
    method: "DELETE", keepalive: true,
  }).catch(() => undefined); // Server also expires orphaned sessions when the browser cannot send cleanup.
}

/** A fresh private workspace per visit; the source sample and real job remain immutable. */
export function SampleScene({ sampleId }: { sampleId: string }) {
  const [demo, setDemo] = useState<DemoManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [loaded, setLoaded] = useState<{ generation: number; session: DemoSession } | null>(null);
  const [previewOnly, setPreviewOnly] = useState(false);
  const [expiredGeneration, setExpiredGeneration] = useState<number | null>(null);
  const session = loaded?.generation === generation && expiredGeneration !== generation ? loaded.session : null;
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

  useEffect(() => {
    let alive = true;
    let created: DemoSession | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    const end = () => { if (created) closeSession(created); };
    const restored = (event: PageTransitionEvent) => { if (event.persisted) window.location.reload(); };
    window.addEventListener("pagehide", end);
    window.addEventListener("pageshow", restored);
    void apiFetch<DemoSession>(`/api/v1/samples/${encodeURIComponent(sampleId)}/sessions`, { method: "POST" })
      .then((value) => {
        created = value;
        if (!alive) { closeSession(value); return; }
        setLoaded({ generation, session: value });
        heartbeat = setInterval(() => {
          void fetch(`/api/v1/demo-sessions/${value.session_id}/heartbeat`, { method: "POST" }).then((response) => {
            if (alive && response.status === 410) {
              setExpiredGeneration(generation);
              setError("Phiên demo đã kết thúc. Mở lại để trở về trạng thái mẫu.");
            }
          }).catch(() => undefined);
        }, 25_000);
      })
      .catch((cause: unknown) => { if (alive) setError(errorMessage(cause)); });
    return () => {
      alive = false;
      window.removeEventListener("pagehide", end);
      window.removeEventListener("pageshow", restored);
      if (heartbeat) clearInterval(heartbeat);
      end();
    };
  }, [sampleId, generation]);

  const restart = () => { setError(null); setPreviewOnly(false); setGeneration((value) => value + 1); };

  if (session && !previewOnly) return (
    <section className="flex h-[calc(100dvh-3rem)] min-h-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-2">
        <Badge tone="ember">Demo tương tác</Badge>
        <p className="min-w-0 flex-1 text-sm text-ink-muted">{demo?.title ?? sampleId} · Thay đổi chỉ có trong phiên này. Thoát rồi mở lại sẽ trở về mẫu.</p>
        <Button size="sm" variant="secondary" onClick={restart}>Khôi phục mẫu</Button>
      </header>
      <iframe key={session.session_id} title={`Workspace demo: ${demo?.title ?? sampleId}`}
        src={`/demo-workspace/${session.session_id}?job=${encodeURIComponent(session.job_id)}&tab=progress`}
        className="min-h-0 w-full flex-1 border-0" allow="fullscreen; gamepad; xr-spatial-tracking"
        sandbox="allow-scripts allow-same-origin allow-downloads allow-forms allow-pointer-lock allow-top-navigation-by-user-activation"
        referrerPolicy="no-referrer" allowFullScreen />
    </section>
  );

  if (error && !previewOnly) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <Notice tone="rust">Không mở được workspace mẫu: {error}</Notice>
        <div className="mt-4 flex gap-2"><Button onClick={restart}>Thử lại</Button>
          {demo && <Button variant="secondary" onClick={() => setPreviewOnly(true)}>Xem file 3DGS của mẫu</Button>}</div>
      </main>
    );
  }
  if (!demo || !previewOnly) {
    return (
      <main className="grid h-[calc(100dvh-3rem)] place-items-center text-sm text-ink-muted" role="status">
        <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tạo phiên demo riêng…
      </main>
    );
  }
  return (
    <SceneWorkspace
      title={demo.title}
      contentUrl={sampleFileUrl(sampleId, demo.splat.name)}
      filename={demo.splat.name}
      badges={<Badge tone="ember">Video mẫu · xử lý sẵn</Badge>}
      cameras={demo.cameras}
      displayRotation={demo.display_rotation_xyzw ?? undefined}
    />
  );
}
