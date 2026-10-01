"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import { Badge, Button, Card, Notice, buttonVariants } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import { SceneWorkspace } from "@/features/studio/SceneWorkspace";
import { usePolling } from "@/features/studio/usePolling";
import { getImport, importContentUrl } from "@/lib/api/studio";
import type { ImportedScene } from "@/lib/contracts/studio";

/**
 * Scene import từ file 3DGS: chờ máy chủ nén PLY → SOG, rồi mở editor. Chỉ xem/chỉnh sửa
 * (ADR 0004 §3): không có camera nên không qua xác nhận tỉ lệ hay dựng collision.
 */
export function ImportScenePage({ importId }: { importId: string }) {
  const [scene, setScene] = useState<ImportedScene | null>(null);
  const [error, setError] = useState<string | null>(null);
  usePageTitle(scene?.name ?? null);

  const poll = useCallback(
    async (signal: AbortSignal) => {
      const result = await getImport(importId, signal);
      if (!result.ok) {
        setError(result.error.status === 404 ? "Không tìm thấy scene import này." : result.error.detail);
        return;
      }
      setError(null);
      setScene(result.data);
    },
    [importId],
  );
  usePolling(poll, 2000, scene?.status !== "READY" && scene?.status !== "FAILED");

  if (error) return <main className="mx-auto max-w-3xl space-y-4 px-4 py-10">
    <Notice tone="rust">{error}</Notice>
    <div className="flex gap-2"><Button size="sm" onClick={() => void poll(new AbortController().signal)}>Thử tải lại</Button><Link href="/scenes" className={buttonVariants({ variant: "secondary", size: "sm" })}>Về Scenes</Link></div>
  </main>;
  if (scene?.status === "READY") {
    return (
      <SceneWorkspace
        title={scene.name}
        backHref="/scenes"
        contentUrl={importContentUrl(importId)}
        filename="scene.sog"
        badges={
          <Badge tone="neutral" title="File 3DGS tải lên không có camera: không xác nhận tỉ lệ mét hay dựng collision">
            Scene import · chỉ xem/chỉnh sửa
          </Badge>
        }
      />
    );
  }
  if (scene?.status === "FAILED") {
    return (
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-10">
        <h1 className="text-2xl font-semibold">{scene.name}</h1>
        <Notice tone="rust">{scene.error ?? "Không nén được scene 3DGS."}</Notice>
        <Link href="/new" className={buttonVariants({ variant: "secondary" })}>Chọn file khác</Link>
      </main>
    );
  }
  return (
    <main className="mx-auto max-w-3xl space-y-5 px-4 py-10">
      <h1 className="text-2xl font-semibold">{scene?.name ?? "Đang mở scene import…"}</h1>
      <Card className="space-y-3 p-6">
        <p className="flex items-center gap-2 text-sm" role="status"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />Máy chủ đang chuẩn bị bản xem SOG…</p>
        <p className="text-sm text-ink-muted">File 3DGS chỉ được chuyển sang định dạng xem nhẹ, không chạy reconstruction. Có thể rời trang và mở lại từ Scenes khi xong.</p>
      </Card>
      <Link href="/scenes" className={buttonVariants({ variant: "secondary" })}>Về Scenes</Link>
    </main>
  );
}
