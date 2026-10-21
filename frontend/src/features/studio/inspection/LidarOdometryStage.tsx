"use client";

import { useEffect, useState } from "react";

import { Badge, Card, Notice } from "@/components/studio/primitives";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { ProductArtifactRef } from "@/lib/contracts/api";
import { LIDAR_ODOMETRY_STAGE } from "@/features/studio/stages";

const CHECKSUM = /^sha256:[0-9a-f]{64}$/;

interface TrajectoryDiagnostics {
  scan_count: number;
  valid_pose_count: number;
  coverage_ratio: number;
  timestamp_gap_threshold_seconds: number;
  timestamp_gap_count: number;
  maximum_timestamp_gap_seconds: number;
  absolute_drift_status: "not_measured";
}

interface LidarOdometryEvidence {
  artifact_type: "EstimatedTrajectoryConsumerEvidence";
  job_id: string;
  recipe_group: "R5" | "R6";
  ingest_binding: { source_scan_file_ids: string[] };
  trajectory_ref: ProductArtifactRef;
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

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNonNegativeFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function parseTrajectoryRef(value: unknown, jobId: string): ProductArtifactRef {
  if (
    !isRecord(value) ||
    value.artifact_type !== "EstimatedTrajectoryArtifact" ||
    value.job_id !== jobId ||
    value.data_class !== "derived" ||
    value.producer_stage !== LIDAR_ODOMETRY_STAGE.id ||
    typeof value.artifact_uri !== "string" ||
    !value.artifact_uri.startsWith(`artifact://jobs/${jobId}/attempts/`) ||
    typeof value.artifact_checksum !== "string" ||
    !CHECKSUM.test(value.artifact_checksum)
  ) {
    throw new Error("Dữ liệu quỹ đạo không khớp scene này.");
  }
  return value as unknown as ProductArtifactRef;
}

function parseEvidence(value: unknown, jobId: string): LidarOdometryEvidence {
  if (!isRecord(value)) throw new Error("Dữ liệu quỹ đạo không hợp lệ.");
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
      throw new Error("Bản đồ quỹ đạo không khớp scene này.");
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
      throw new Error("Bản đồ đã ghép thiếu số liệu.");
    }
  } else if (value.artifact_type !== "EstimatedTrajectoryConsumerEvidence") {
    throw new Error("Dữ liệu quỹ đạo không khớp scene này.");
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
    throw new Error("Dữ liệu quỹ đạo không khớp scene này.");
  }
  return {
    ...record,
    trajectory_ref: parseTrajectoryRef(record.trajectory_ref, jobId),
    map_evidence: mapEvidence,
  } as unknown as LidarOdometryEvidence;
}

function parseTrajectoryDiagnostics(
  value: unknown,
  jobId: string,
  runtimeStatus: LidarOdometryEvidence["runtime_qualification_status"],
  expectedScanCount: number,
): TrajectoryDiagnostics {
  if (
    !isRecord(value) ||
    value.artifact_type !== "EstimatedTrajectoryArtifact" ||
    value.job_id !== jobId ||
    value.trajectory_origin !== "estimated" ||
    value.runtime_qualification_status !== runtimeStatus ||
    !isRecord(value.diagnostics)
  ) {
    throw new Error("Dữ liệu quỹ đạo không khớp scene này.");
  }
  const diagnostics = value.diagnostics;
  const {
    scan_count,
    valid_pose_count,
    coverage_ratio,
    timestamp_gap_threshold_seconds,
    timestamp_gap_count,
    maximum_timestamp_gap_seconds,
    absolute_drift_status,
  } = diagnostics;
  if (
    !isCount(scan_count) ||
    scan_count < 2 ||
    scan_count !== expectedScanCount ||
    !isCount(valid_pose_count) ||
    valid_pose_count > scan_count ||
    typeof coverage_ratio !== "number" ||
    !Number.isFinite(coverage_ratio) ||
    coverage_ratio < 0 ||
    coverage_ratio > 1 ||
    Math.abs(coverage_ratio - valid_pose_count / scan_count) > 1e-6 ||
    !isNonNegativeFinite(timestamp_gap_threshold_seconds) ||
    timestamp_gap_threshold_seconds === 0 ||
    !isCount(timestamp_gap_count) ||
    timestamp_gap_count > scan_count - 1 ||
    !isNonNegativeFinite(maximum_timestamp_gap_seconds) ||
    absolute_drift_status !== "not_measured" ||
    (timestamp_gap_count === 0 && maximum_timestamp_gap_seconds > timestamp_gap_threshold_seconds) ||
    (timestamp_gap_count > 0 && maximum_timestamp_gap_seconds <= timestamp_gap_threshold_seconds)
  ) {
    throw new Error("Số liệu chất lượng quỹ đạo không hợp lệ.");
  }
  return {
    scan_count,
    valid_pose_count,
    coverage_ratio,
    timestamp_gap_threshold_seconds,
    timestamp_gap_count,
    maximum_timestamp_gap_seconds,
    absolute_drift_status,
  };
}

export function LidarOdometryStage({ jobId, artifacts }: { jobId: string; artifacts: ProductArtifactRef[] }) {
  const evidenceRef = artifacts.find((ref) => ref.artifact_type === "EstimatedTrajectoryProductEvidence")
    ?? artifacts.find((ref) => ref.artifact_type === "EstimatedTrajectoryConsumerEvidence");
  const evidenceContentUrl = evidenceRef ? jobArtifactContentUrl(jobId, evidenceRef) : null;
  const [loaded, setLoaded] = useState<{
    key: string;
    evidence: LidarOdometryEvidence | null;
    diagnostics: TrajectoryDiagnostics | null;
    diagnosticsError: string | null;
    error: string | null;
  } | null>(null);
  const current = loaded?.key === evidenceContentUrl ? loaded : null;
  const evidence = current?.evidence ?? null;
  const diagnostics = current?.diagnostics ?? null;

  useEffect(() => {
    if (!evidenceContentUrl) return;
    const controller = new AbortController();
    const key = evidenceContentUrl;
    void (async () => {
      let parsedEvidence: LidarOdometryEvidence | null = null;
      try {
        const response = await fetch(evidenceContentUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        parsedEvidence = parseEvidence(await response.json(), jobId);
        if (controller.signal.aborted) return;
        setLoaded({ key, evidence: parsedEvidence, diagnostics: null, diagnosticsError: null, error: null });
        const trajectoryResponse = await fetch(jobArtifactContentUrl(jobId, parsedEvidence.trajectory_ref), {
          signal: controller.signal,
        });
        if (!trajectoryResponse.ok) throw new Error(`HTTP ${trajectoryResponse.status}`);
        const parsedDiagnostics = parseTrajectoryDiagnostics(
          await trajectoryResponse.json(),
          jobId,
          parsedEvidence.runtime_qualification_status,
          parsedEvidence.ingest_binding.source_scan_file_ids.length,
        );
        if (!controller.signal.aborted) {
          setLoaded({ key, evidence: parsedEvidence, diagnostics: parsedDiagnostics, diagnosticsError: null, error: null });
        }
      } catch (cause) {
        if (controller.signal.aborted) return;
        const message = cause instanceof Error ? cause.message : "Không đọc được dữ liệu quỹ đạo.";
        if (parsedEvidence) {
          setLoaded({ key, evidence: parsedEvidence, diagnostics: null, diagnosticsError: message, error: null });
        } else {
          setLoaded({ key, evidence: null, diagnostics: null, diagnosticsError: null, error: message });
        }
      }
    })();
    return () => controller.abort();
  }, [jobId, evidenceContentUrl]);

  if (!evidenceRef) {
    return <Notice tone="ochre" className="m-4">Scene này chưa có quỹ đạo LiDAR ước lượng.</Notice>;
  }
  if (current?.error) return <Notice tone="rust" className="m-4">Không đọc được quỹ đạo LiDAR: {current.error}</Notice>;
  if (!evidence) return <p role="status" className="p-6 text-sm text-ink-muted">Đang tải quỹ đạo LiDAR…</p>;

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
        <p className="mt-3">Đây là quỹ đạo ước lượng, chưa căn với scene và mặt sàn nên chưa dùng để dựng va chạm.</p>
      </Notice>

      <Card className="p-5">
        <h2 className="text-lg font-bold">Nguồn dữ liệu và trạng thái</h2>
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
        <h3 className="mt-5 font-semibold">Chất lượng quỹ đạo</h3>
        {diagnostics ? (
          <>
            <dl className="mt-2 divide-y divide-line">
              <Row
                label="Pose coverage"
                value={`${diagnostics.valid_pose_count}/${diagnostics.scan_count} · ${new Intl.NumberFormat("vi-VN", { style: "percent", maximumFractionDigits: 1 }).format(diagnostics.coverage_ratio)}`}
              />
              <Row
                label="Timestamp gaps"
                value={`${diagnostics.timestamp_gap_count} · ngưỡng ${formatSeconds(diagnostics.timestamp_gap_threshold_seconds)} · lớn nhất ${formatSeconds(diagnostics.maximum_timestamp_gap_seconds)}`}
              />
              <Row label="Absolute drift" value={diagnostics.absolute_drift_status} />
            </dl>
            {diagnostics.timestamp_gap_count > 0 && (
              <Notice tone="ochre" className="mt-3">
                Có khoảng thời gian bị hở quá lớn. Kiểm tra thứ tự và đơn vị thời điểm của các lượt quét.
              </Notice>
            )}
            {diagnostics.valid_pose_count < diagnostics.scan_count && (
              <Notice tone="ochre" className="mt-3">
                Một số lượt quét chưa ước lượng được vị trí. Kiểm tra các lượt bị bỏ qua.
              </Notice>
            )}
          </>
        ) : current?.diagnosticsError ? (
          <Notice tone="ochre" className="mt-3">Không tải được số liệu chất lượng quỹ đạo: {current.diagnosticsError}</Notice>
        ) : (
          <p role="status" className="mt-3 text-sm text-ink-muted">Đang tải số liệu chất lượng quỹ đạo…</p>
        )}
        <p className="mt-4 text-sm text-ink-muted">Cần thêm một bước xác nhận và kiểm tra trước khi dùng quỹ đạo này để căn với scene.</p>
      </Card>
    </div>
  );
}

function formatSeconds(value: number): string {
  return `${new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 3 }).format(value)} s`;
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="grid gap-1 py-3 sm:grid-cols-[13rem_1fr]"><dt className="text-sm text-ink-muted">{label}</dt><dd className="break-all font-mono text-xs">{value}</dd></div>;
}
