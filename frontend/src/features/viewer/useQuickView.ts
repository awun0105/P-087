"use client";

import { useEffect, useState } from "react";

import { getQuickViewStatus, jobArtifactContentUrl, jobQuickViewUrl } from "@/lib/api/endpoints";

type Ref = { artifact_uri: string; artifact_checksum: string };

export interface QuickView {
  /** URL viewer nên tải: bản xem nhanh khi đã có và người dùng chưa đòi bản đầy đủ, không thì bản gốc. */
  url: string;
  quick: boolean;
  /** Đã biết trạng thái (kể cả lỗi). Viewer chỉ nên dựng sau đó để khỏi tải hai lần. */
  settled: boolean;
  showFull: () => void;
}

/**
 * T-068: chọn giữa bản xem nhanh và bản gốc của một SOG. Lần đầu mở scene lớn, máy chủ mới bắt đầu tạo bản nhanh nên
 * vẫn xem bản gốc; các lần sau mở nhanh hơn. Lỗi hỏi trạng thái thì dùng bản gốc.
 */
export function useQuickView(jobId: string, ref: Ref | null): QuickView {
  const key = `${jobId}\u0000${ref?.artifact_uri ?? ""}\u0000${ref?.artifact_checksum ?? ""}`;
  const [status, setStatus] = useState<{ key: string; ready: boolean } | null>(null);
  const [fullFor, setFullFor] = useState<string | null>(null);
  const artifact_uri = ref?.artifact_uri ?? null;
  const artifact_checksum = ref?.artifact_checksum ?? null;

  useEffect(() => {
    if (artifact_uri === null || artifact_checksum === null) return;
    const controller = new AbortController();
    getQuickViewStatus(jobId, { artifact_uri, artifact_checksum }, controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) setStatus({ key, ready: result.ok && result.data.state === "ready" });
      },
      () => {
        if (!controller.signal.aborted) setStatus({ key, ready: false });
      },
    );
    return () => controller.abort();
  }, [jobId, artifact_uri, artifact_checksum, key]);

  if (ref === null) return { url: "", quick: false, settled: true, showFull: () => undefined };
  const settled = status?.key === key;
  const quick = settled && status.ready && fullFor !== key;
  return {
    url: quick ? jobQuickViewUrl(jobId, ref) : jobArtifactContentUrl(jobId, ref),
    quick,
    settled,
    showFull: () => setFullFor(key),
  };
}
