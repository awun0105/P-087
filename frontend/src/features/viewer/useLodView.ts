"use client";

import { useEffect, useState } from "react";

import { apiPathUrl } from "@/lib/api/client";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";

type Ref = { artifact_uri: string; artifact_checksum: string };

export interface LodView {
  /** URL khung 3D tải: file mục lục của bộ LOD khi có, không thì SOG gốc. */
  url: string;
  /** Tên file cho bộ đọc của thư viện (`lod-meta.json` chọn chế độ tải theo mức chi tiết). */
  filename: string;
  lod: boolean;
  /** Đã biết có bộ LOD hay không (kể cả lỗi). Viewer chỉ nên dựng sau đó để khỏi tải hai lần. */
  settled: boolean;
}

export function jobLodIndexUrl(jobId: string, checksum: string): string {
  return apiPathUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}/lod/${checksum.replace(/^sha256:/, "")}/lod-meta.json`);
}

/**
 * T-070: SOG lớn có bộ LOD (worker GPU tạo lúc rảnh) thì khung 3D hiện bản thô ngay rồi tự tải thêm chi tiết tới đủ
 * chất lượng gốc. Chưa có bộ LOD (scene nhỏ, đang tạo) hoặc hỏi lỗi thì mở SOG gốc như trước.
 */
export function useLodView(jobId: string, ref: Ref | null): LodView {
  const checksum = ref?.artifact_checksum ?? null;
  const key = `${jobId}\u0000${checksum ?? ""}`;
  const [status, setStatus] = useState<{ key: string; lod: boolean } | null>(null);

  useEffect(() => {
    if (checksum === null) return;
    const controller = new AbortController();
    // File mục lục nhỏ (vài KB) và được đệm bất biến: hỏi bằng chính nó, lần tải của viewer sau đó trúng đệm.
    fetch(jobLodIndexUrl(jobId, checksum), { signal: controller.signal, credentials: "include" }).then(
      (response) => {
        if (!controller.signal.aborted) setStatus({ key, lod: response.ok });
      },
      () => {
        if (!controller.signal.aborted) setStatus({ key, lod: false });
      },
    );
    return () => controller.abort();
  }, [jobId, checksum, key]);

  if (ref === null) return { url: "", filename: "", lod: false, settled: true };
  const settled = status?.key === key;
  const lod = settled && status.lod;
  return lod
    ? { url: jobLodIndexUrl(jobId, ref.artifact_checksum), filename: "lod-meta.json", lod, settled }
    : { url: jobArtifactContentUrl(jobId, ref), filename: ref.artifact_uri.split("/").pop() ?? "scene.sog", lod, settled };
}
