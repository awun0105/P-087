"use client";

import { useEffect, useState } from "react";

import { Badge, Card, Notice } from "@/components/studio/primitives";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { ProductArtifactRef } from "@/lib/contracts/api";

interface LidarOdometryEvidence {
  artifact_type: "EstimatedTrajectoryConsumerEvidence";
  job_id: string;
  recipe_group: "R5" | "R6";
  ingest_binding: { source_scan_file_ids: string[] };
  odometry_runtime_id: string;
  odometry_runtime_version: string;
  odometry_profile_checksum: string;
  runtime_qualification_status: "qualified" | "wired_unqualified";
  world_frame_status: "pending_world_from_map_confirmation";
  floor_status: "pending_floor_and_up_axis_evidence";
  alignment_status: "not_registered";
  map_evidence?: {
    map_frame_id: string;
    map_status: "ready" | "blocked";
    point_count: number | null;
    diagnostic_code: "MAP_FUSION_FAILED" | null;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseEvidence(value: unknown, jobId: string): LidarOdometryEvidence {
  if (!isRecord(value)) throw new Error("Artifact odometry phải là JSON object.");
  let record = value;
  let mapEvidence: LidarOdometryEvidence["map_evidence"];
  if (value.artifact_type === "EstimatedTrajectoryProductEvidence") {
    const consumer = value.consumer_evidence;
    const map = value.map_evidence;
    if (
      value.job_id !== jobId ||
      !isRecord(consumer) ||
      !isRecord(map) ||
      map.artifact_type !== "EstimatedTrajectoryMapEvidence" ||
      map.job_id !== jobId ||
      typeof map.map_frame_id !== "string" ||
      (map.map_status !== "ready" && map.map_status !== "blocked") ||
      (map.point_count !== null &&
        (typeof map.point_count !== "number" || !Number.isSafeInteger(map.point_count) || map.point_count < 1)) ||
      (map.diagnostic_code !== null && map.diagnostic_code !== "MAP_FUSION_FAILED")
    ) {
      throw new Error("Artifact map odometry không khớp contract hoặc job hiện tại.");
    }
    record = consumer;
    mapEvidence = {
      map_frame_id: map.map_frame_id,
      map_status: map.map_status as "ready" | "blocked",
      point_count: map.point_count as number | null,
      diagnostic_code: map.diagnostic_code as "MAP_FUSION_FAILED" | null,
    };
    if ((map.map_status === "ready") !== (map.point_count !== null) ||
      (map.map_status === "blocked") !== (map.diagnostic_code === "MAP_FUSION_FAILED")) {
      throw new Error("Trạng thái fused map thiếu point count hoặc diagnostic tương ứng.");
    }
  } else if (value.artifact_type !== "EstimatedTrajectoryConsumerEvidence") {
    throw new Error("Artifact odometry không khớp contract hoặc job hiện tại.");
  }
  const binding = record.ingest_binding as Record<string, unknown> | undefined;
  if (
    record.artifact_type !== "EstimatedTrajectoryConsumerEvidence" ||
    record.job_id !== jobId ||
    (record.recipe_group !== "R5" && record.recipe_group !== "R6") ||
    !binding ||
    !Array.isArray(binding.source_scan_file_ids) ||
    !binding.source_scan_file_ids.every((id) => typeof id === "string") ||
    typeof record.odometry_runtime_id !== "string" ||
    typeof record.odometry_runtime_version !== "string" ||
    typeof record.odometry_profile_checksum !== "string" ||
    (record.runtime_qualification_status !== "qualified" && record.runtime_qualification_status !== "wired_unqualified") ||
    record.world_frame_status !== "pending_world_from_map_confirmation" ||
    record.floor_status !== "pending_floor_and_up_axis_evidence" ||
    record.alignment_status !== "not_registered"
  ) {
    throw new Error("Artifact odometry không khớp contract hoặc job hiện tại.");
  }
  return { ...record, map_evidence: mapEvidence } as unknown as LidarOdometryEvidence;
}

export function LidarOdometryStage({ jobId, artifacts }: { jobId: string; artifacts: ProductArtifactRef[] }) {
  const evidenceRef = artifacts.find((ref) =>
    ref.artifact_type === "EstimatedTrajectoryProductEvidence" || ref.artifact_type === "EstimatedTrajectoryConsumerEvidence",
  );
  const evidenceContentUrl = evidenceRef ? jobArtifactContentUrl(jobId, evidenceRef) : null;
  const [evidence, setEvidence] = useState<LidarOdometryEvidence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!evidenceContentUrl) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(evidenceContentUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const parsed = parseEvidence(await response.json(), jobId);
        if (!controller.signal.aborted) setEvidence(parsed);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Không đọc được bằng chứng odometry.");
      }
    })();
    return () => controller.abort();
  }, [jobId, evidenceContentUrl]);

  if (!evidenceRef) {
    return <Notice tone="ochre" className="m-4">Job này chưa có artifact bằng chứng quỹ đạo LiDAR ước lượng.</Notice>;
  }
  if (error) return <Notice tone="rust" className="m-4">Không thể xác minh bằng chứng odometry: {error}</Notice>;
  if (!evidence) return <p role="status" className="p-6 text-sm text-ink-muted">Đang tải bằng chứng quỹ đạo LiDAR…</p>;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <Notice tone="ochre">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">{evidence.recipe_group}</Badge>
          <Badge tone="sage">Runtime {evidence.runtime_qualification_status}</Badge>
          <Badge tone="neutral">{evidence.ingest_binding.source_scan_file_ids.length} scan</Badge>
          {evidence.map_evidence && (
            <Badge tone={evidence.map_evidence.map_status === "ready" ? "sage" : "ochre"}>
              Map {evidence.map_evidence.map_status}
            </Badge>
          )}
        </div>
        <p className="mt-3">Quỹ đạo này là ước lượng trong local odometry map. Nó chưa được biến đổi vào world, chưa có bằng chứng mặt sàn/trục lên và chưa đăng ký với scene RGB; không dùng làm LiDAR canonical hoặc collision source.</p>
      </Notice>

      <Card className="p-5">
        <h2 className="text-lg font-bold">Bằng chứng nguồn và trạng thái consumer</h2>
        <dl className="mt-3 divide-y divide-line">
          <Row label="R5 runtime" value={`${evidence.odometry_runtime_id} · ${evidence.odometry_runtime_version}`} />
          <Row label="Profile checksum" value={evidence.odometry_profile_checksum} />
          {evidence.map_evidence && (
            <Row
              label="Fused map (local frame)"
              value={evidence.map_evidence.map_status === "ready"
                ? `${evidence.map_evidence.point_count?.toLocaleString("vi-VN")} points · ${evidence.map_evidence.map_frame_id}`
                : `${evidence.map_evidence.diagnostic_code} · ${evidence.map_evidence.map_frame_id}`}
            />
          )}
          <Row label="World frame" value={evidence.world_frame_status} />
          <Row label="Mặt sàn và trục lên" value={evidence.floor_status} />
          <Row label="RGB–LiDAR alignment" value={evidence.alignment_status} />
        </dl>
        <p className="mt-4 text-sm text-ink-muted">Calibration và RGB/LiDAR timestamp được giữ theo checksum trong artifact. Trước khi ingest hoặc alignment, hệ thống cần bước xác nhận riêng và QA tương ứng.</p>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="grid gap-1 py-3 sm:grid-cols-[13rem_1fr]"><dt className="text-sm text-ink-muted">{label}</dt><dd className="break-all font-mono text-xs">{value}</dd></div>;
}
