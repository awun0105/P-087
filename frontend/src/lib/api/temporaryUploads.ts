import { apiFetch } from "@/lib/api/client";

export function temporaryUploads(action: "heartbeat" | "discard", uploadIds: string[], keepalive = false) {
  return apiFetch<{ deleted: string[] }>(`/api/v1/uploads/temporary/${action}`, {
    method: "POST",
    body: JSON.stringify({ upload_ids: uploadIds }),
    keepalive,
  });
}
