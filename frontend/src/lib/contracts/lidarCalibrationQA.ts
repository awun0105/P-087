import type { ProductArtifactRef } from "@/lib/contracts/api";

export type LidarCalibrationQAResult = "PASS" | "FAIL" | "INCONCLUSIVE";

export interface LidarCalibrationQAFinding {
  code: string;
  severity: "fail" | "inconclusive";
  detail: string;
  remediation: string;
}

export interface LidarCalibrationQAReport {
  schema_version: "1.0";
  package_ref: ProductArtifactRef;
  result: LidarCalibrationQAResult;
  observability: "UNAVAILABLE" | "INSUFFICIENT" | "READY_FOR_SCORING";
  sampled_frame_count: number;
  matched_frame_count: number;
  observable_frame_count: number;
  projected_point_count: number;
  overlap_point_count: number;
  overlap_fraction: number | null;
  maximum_timestamp_residual_sec: number | null;
  findings: LidarCalibrationQAFinding[];
  overlay_refs: ProductArtifactRef[];
  diagnostic_projection_ref: ProductArtifactRef | null;
  report_checksum: string;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function artifactRef(value: unknown, jobId: string, expectedType?: string): value is ProductArtifactRef {
  return record(value) && value.job_id === jobId &&
    (expectedType === undefined || value.artifact_type === expectedType) &&
    typeof value.artifact_uri === "string" && value.artifact_uri.startsWith(`artifact://jobs/${jobId}/`) &&
    typeof value.artifact_checksum === "string" && /^sha256:[a-f0-9]{64}$/.test(value.artifact_checksum) &&
    value.data_class === "derived";
}

export function parseLidarCalibrationQAReport(value: unknown, jobId: string): LidarCalibrationQAReport {
  if (!record(value) || value.schema_version !== "1.0" ||
      !["PASS", "FAIL", "INCONCLUSIVE"].includes(String(value.result)) ||
      !["UNAVAILABLE", "INSUFFICIENT", "READY_FOR_SCORING"].includes(String(value.observability)) ||
      !artifactRef(value.package_ref, jobId, "LidarPackageRecord") ||
      !Array.isArray(value.findings) || !Array.isArray(value.overlay_refs) ||
      !value.overlay_refs.every((item) => artifactRef(item, jobId, "LidarCalibrationQAOverlay")) ||
      !(value.diagnostic_projection_ref === null || artifactRef(value.diagnostic_projection_ref, jobId, "LidarCalibrationProjectionEvidence")) ||
      !Number.isInteger(value.sampled_frame_count) || !Number.isInteger(value.matched_frame_count) ||
      !Number.isInteger(value.observable_frame_count) || !Number.isInteger(value.projected_point_count) ||
      !Number.isInteger(value.overlap_point_count) || typeof value.report_checksum !== "string" ||
      !/^sha256:[a-f0-9]{64}$/.test(value.report_checksum)) {
    throw new Error("Báo cáo căn chỉnh LiDAR không hợp lệ hoặc thuộc scene khác.");
  }
  const findings = value.findings.filter((item): item is LidarCalibrationQAFinding =>
    record(item) && typeof item.code === "string" &&
    (item.severity === "fail" || item.severity === "inconclusive") &&
    typeof item.detail === "string" && typeof item.remediation === "string"
  );
  if (findings.length !== value.findings.length) throw new Error("Mục phát hiện trong báo cáo căn chỉnh không hợp lệ.");
  const numeric = [value.sampled_frame_count, value.matched_frame_count, value.observable_frame_count,
    value.projected_point_count, value.overlap_point_count];
  if (numeric.some((item) => (item as number) < 0) ||
      (value.overlap_fraction !== null && typeof value.overlap_fraction !== "number") ||
      (value.maximum_timestamp_residual_sec !== null && typeof value.maximum_timestamp_residual_sec !== "number")) {
    throw new Error("Số liệu căn chỉnh LiDAR không hợp lệ.");
  }
  return value as unknown as LidarCalibrationQAReport;
}
