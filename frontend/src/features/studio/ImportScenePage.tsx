"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useState } from "react";

import { Badge, Notice } from "@/components/studio/primitives";
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

  if (error) return <Notice tone="rust" className="m-6">{error}</Notice>;
  if (scene?.status === "READY") {
    return (
      <SceneWorkspace
        title={scene.name}
        backHref="/"
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
      <Notice tone="rust" className="m-6">
        {scene.error ?? "Không nén được scene 3DGS."}
      </Notice>
    );
  }
  return (
    <p className="flex items-center gap-2 p-10 text-sm text-ink-muted" role="status">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
      Máy chủ đang nén file 3DGS sang định dạng xem nhẹ (SOG)…
    </p>
  );
}
