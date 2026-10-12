"use client";

import { errorMessage } from "@/lib/ui-error";

import { Loader2 } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useCallback, useMemo, useRef, useState } from "react";

import { Badge, Button, Card, Notice, buttonVariants } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import { SceneWorkspace } from "@/features/studio/SceneWorkspace";
import { usePolling } from "@/features/studio/usePolling";
import { cancelImport, clearImportCamera, getImport, importContentUrl, retryImport, updateImportCamera } from "@/lib/api/studio";
import type { ViewerControls } from "@/features/viewer/PlayCanvasScene";
import type { DisplayCameraPose } from "@/features/viewer/source-frame";
import type { ImportedScene } from "@/lib/contracts/studio";

function lifecycleStatus(scene: ImportedScene): string {
  return scene.operation?.status ?? scene.status;
}

function terminal(scene: ImportedScene): boolean {
  return scene.status === "READY" || scene.status === "FAILED" || scene.status === "CANCELLED";
}

function progressLabel(scene: ImportedScene | null): string {
  const operation = scene?.operation;
  if (operation?.cancel_requested) return "Đang dừng worker an toàn trước khi xác nhận hủy…";
  if (operation?.status === "QUEUED") return "Đang chờ worker nhận scene…";
  if (operation?.status === "WAITING") return operation.error ?? "Worker đang chờ tài nguyên…";
  if (operation?.status === "RUNNING") return "Máy chủ đang chuẩn bị bản xem SOG…";
  return "Đang kiểm tra trạng thái import…";
}

function attemptStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    RUNNING: "đang chạy",
    SUCCEEDED: "hoàn tất",
    FAILED: "thất bại",
    CANCELLED: "đã hủy",
    INTERRUPTED: "worker bị gián đoạn",
  };
  return labels[status] ?? status;
}

/**
 * Scene import từ file 3DGS: chờ worker publish bản xem SOG, rồi mở editor. Chỉ xem/chỉnh sửa
 * (ADR 0004 §3): không có camera nên không qua xác nhận tỉ lệ hay dựng collision.
 */
export function ImportScenePage({ importId }: { importId: string }) {
  return <ImportScenePageContent key={importId} importId={importId} />;
}

function ImportScenePageContent({ importId }: { importId: string }) {
  const [scene, setScene] = useState<ImportedScene | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"retry" | "cancel" | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const viewerControlsRef = useRef<ViewerControls | null>(null);
  const initialCameraRef = useRef<DisplayCameraPose | undefined>(undefined);
  const pollSequence = useRef(0);
  const latestApplied = useRef<{
    importId: string;
    sequence: number;
    attempt: number;
    status: string;
    parentStatus: ImportedScene["status"];
  } | null>(null);
  usePageTitle(scene?.name ?? null);

  // Giữ cố định camera khởi đầu để viewer không bị re-mount khi lưu hoặc gỡ bookmark
  if (!initialCameraRef.current) {
    const cam = scene?.default_camera ?? scene?.initial_camera;
    if (cam) {
      initialCameraRef.current = {
        position: cam.position,
        target: cam.target,
        fov: cam.fov ?? 60,
      };
    }
  }

  const fallbackInitialCamera = useMemo<DisplayCameraPose | undefined>(() => {
    if (!scene?.initial_camera) return undefined;
    return {
      position: scene.initial_camera.position,
      target: scene.initial_camera.target,
      fov: scene.initial_camera.fov ?? 60,
    };
  }, [scene?.initial_camera]);

  const currentBookmark = useMemo<DisplayCameraPose | null>(() => {
    if (!scene?.default_camera) return null;
    return {
      position: scene.default_camera.position,
      target: scene.default_camera.target,
      fov: scene.default_camera.fov ?? 60,
    };
  }, [scene?.default_camera]);

  const handleToggleBookmark = useCallback(
    async (active: boolean, controls?: ViewerControls | null) => {
      const activeControls = controls ?? viewerControlsRef.current;
      if (active) {
        // Lưu góc nhìn hiện tại làm bookmark
        const pose = activeControls?.getCameraPose();
        if (!pose) {
          console.warn("handleToggleBookmark: Không lấy được pose camera từ viewer controls", activeControls);
          setSaveStatus("error");
          setTimeout(() => {
            setSaveStatus((current) => (current === "error" ? "idle" : current));
          }, 3000);
          return;
        }
        setSaveStatus("saving");
        try {
          const updated = await updateImportCamera(importId, pose);
          setScene(updated);
          setSaveStatus("saved");
          setTimeout(() => {
            setSaveStatus((current) => (current === "saved" ? "idle" : current));
          }, 3000);
        } catch (err) {
          console.error("updateImportCamera error:", err);
          setSaveStatus("error");
          setTimeout(() => {
            setSaveStatus((current) => (current === "error" ? "idle" : current));
          }, 3000);
        }
      } else {
        // Gỡ bookmark -> quay lại vị trí mặc định ban đầu
        setSaveStatus("saving");
        try {
          const updated = await clearImportCamera(importId);
          setScene(updated);
          setSaveStatus("saved");
          setTimeout(() => {
            setSaveStatus((current) => (current === "saved" ? "idle" : current));
          }, 3000);
        } catch (err) {
          console.error("clearImportCamera error:", err);
          setSaveStatus("error");
          setTimeout(() => {
            setSaveStatus((current) => (current === "error" ? "idle" : current));
          }, 3000);
        }
      }
    },
    [importId],
  );

  const apply = useCallback((next: ImportedScene, sequence: number) => {
    latestApplied.current = {
      importId,
      sequence,
      attempt: next.operation?.attempt ?? 0,
      status: lifecycleStatus(next),
      parentStatus: next.status,
    };
    setError(null);
    setScene(next);
  }, [importId]);

  const poll = useCallback(
    async (signal: AbortSignal) => {
      const sequence = ++pollSequence.current;
      const result = await getImport(importId, signal);
      if (signal.aborted) return;
      const latest = latestApplied.current;
      if (latest?.importId === importId && sequence < latest.sequence) return;
      if (!result.ok) {
        setError(result.error.status === 404 ? "Không tìm thấy scene import này." : errorMessage(result.error));
        return;
      }
      const next = result.data;
      if (latest?.importId === importId) {
        const nextAttempt = next.operation?.attempt ?? 0;
        const latestTerminal = ["READY", "SUCCEEDED", "FAILED", "CANCELLED"].includes(latest.status)
          || ["READY", "FAILED", "CANCELLED"].includes(latest.parentStatus);
        const nextTerminal = terminal(next);
        if (nextAttempt < latest.attempt || (latestTerminal && !nextTerminal)) return;
      }
      apply(next, sequence);
    },
    [apply, importId],
  );
  const active = scene === null || !terminal(scene);
  usePolling(poll, 2000, active, importId);

  async function runAction(action: "retry" | "cancel") {
    setBusy(action);
    setActionError(null);
    try {
      const next = action === "retry" ? await retryImport(importId) : await cancelImport(importId);
      apply(next, ++pollSequence.current);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusy(null);
    }
  }

  if (error) return <main className="mx-auto max-w-3xl space-y-4 px-4 py-10">
    <Notice tone="rust">{error}</Notice>
    <div className="flex gap-2"><Button size="sm" onClick={() => void poll(new AbortController().signal)}>Thử tải lại</Button><Link href="/imports" className={buttonVariants({ variant: "secondary", size: "sm" })}>Về Scenes đã import</Link></div>
  </main>;
  if (scene?.status === "READY") {
    const sourceLabel = scene.input_kind === "gaussian_sog"
      ? "SOG tải lên · giữ nguyên bytes"
      : scene.input_kind === "gaussian_ply_colmap"
        ? "PLY + COLMAP → SOG"
        : "PLY → SOG";
    return (
      <SceneWorkspace
        title={scene.name}
        contentUrl={importContentUrl(importId)}
        filename="scene.sog"
        initialCamera={initialCameraRef.current}
        onControlsReady={(ctrl) => {
          viewerControlsRef.current = ctrl;
        }}
        currentBookmark={currentBookmark}
        fallbackInitialCamera={fallbackInitialCamera}
        onToggleBookmark={handleToggleBookmark}
        onSaveDefaultCamera={(controls) => handleToggleBookmark(true, controls)}
        bookmarkStatus={saveStatus}
        saveDefaultCameraStatus={saveStatus}
        badges={
          <Badge tone="neutral" title="File 3DGS tải lên không có camera: không xác nhận tỉ lệ mét hay dựng collision">
            Scene import · {sourceLabel}
          </Badge>
        }
      />
    );
  }
  if (scene?.status === "FAILED" || scene?.status === "CANCELLED") {
    return (
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-10">
        <h1 className="text-2xl font-extrabold tracking-tight">{scene.name}</h1>
        {scene.status === "FAILED" ? (
          <Notice tone="rust">{scene.operation?.error ?? scene.error ?? "Không nén được scene 3DGS."}</Notice>
        ) : (
          <Notice tone="neutral">{scene.operation?.error ?? scene.error ?? "Scene import đã được hủy."}</Notice>
        )}
        {scene.operation?.attempt_history && scene.operation.attempt_history.length > 0 && (
          <details className="rounded-xl border border-line bg-paper-raised p-4 text-sm">
            <summary className="cursor-pointer font-medium">Lịch sử xử lý · {scene.operation.attempt_history.length} lượt</summary>
            <ol className="mt-3 space-y-2 text-ink-muted">
              {scene.operation.attempt_history.map((attempt) => (
                <li key={attempt.attempt}>
                  Lượt {attempt.attempt} · {attemptStatusLabel(attempt.status)}{attempt.error ? ` · ${attempt.error}` : ""}
                </li>
              ))}
            </ol>
          </details>
        )}
        {actionError && <Notice tone="rust">{actionError}</Notice>}
        <div className="flex flex-wrap gap-2">
          {scene.capabilities?.can_retry && (
            <Button disabled={busy !== null} onClick={() => void runAction("retry")}>
              {busy === "retry" ? "Đang xếp lại…" : "Thử lại scene import"}
            </Button>
          )}
          <Link href="/new" className={buttonVariants({ variant: "secondary" })}>Chọn file khác</Link>
          <Link href="/imports" className={buttonVariants({ variant: "secondary" })}>Về Scenes đã import</Link>
        </div>
      </main>
    );
  }
  return (
    <main className="mx-auto max-w-3xl space-y-5 px-4 py-10">
      <h1 className="text-2xl font-extrabold tracking-tight">{scene?.name ?? "Đang mở scene import…"}</h1>
      <Card className="space-y-3 p-6">
        <p className="flex items-center gap-2 text-sm" role="status">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          {progressLabel(scene)}
        </p>
        <p className="text-sm text-ink-muted">PLY được chuyển sang SOG; SOG đã tải lên được giữ nguyên bytes. Cả hai chỉ vào scene viewer, không chạy reconstruction. Có thể rời trang và mở lại từ Scenes đã import khi xong.</p>
        {actionError && <Notice tone="rust">{actionError}</Notice>}
        {scene?.capabilities?.can_cancel && (
          <Button variant="secondary" disabled={busy !== null} onClick={() => void runAction("cancel")}>
            {busy === "cancel" ? "Đang yêu cầu hủy…" : "Hủy import"}
          </Button>
        )}
      </Card>
      <Link href="/imports" className={buttonVariants({ variant: "secondary" })}>Về Scenes đã import</Link>
    </main>
  );
}
