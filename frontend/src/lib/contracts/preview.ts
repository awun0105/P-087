/** Mirror src/models/contracts/preview.py; raw SfM không giả thành canonical meter. */
import type { ProductArtifactRef } from "@/lib/contracts/api";

export interface ReconstructionPreview {
  schema_version: "1.0";
  artifact_type: "ReconstructionPreview";
  job_id: string;
  attempt_id: string;
  source_input_checksum: string;
  source_visual_ref: ProductArtifactRef;
  camera_pose_ref: ProductArtifactRef;
  delivery_ref: ProductArtifactRef;
  format: "gaussian_sog";
  producer: "brush";
  producer_version: string;
  metric_status: "UNCONFIRMED";
  coordinate_frame: "sfm_world";
  unit: "arbitrary";
}

const checksum = /^sha256:[a-f0-9]{64}$/;
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Validate boundary trước khi tạo URL hoặc gắn metric label. */
export function parsePreview(value: unknown, jobId: string): ReconstructionPreview {
  if (!record(value) || value.schema_version !== "1.0" || value.artifact_type !== "ReconstructionPreview" ||
      value.job_id !== jobId || typeof value.attempt_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value.attempt_id) ||
      value.format !== "gaussian_sog" || value.producer !== "brush" || typeof value.producer_version !== "string" ||
      value.metric_status !== "UNCONFIRMED" || value.coordinate_frame !== "sfm_world" || value.unit !== "arbitrary" ||
      typeof value.source_input_checksum !== "string" || !checksum.test(value.source_input_checksum)) {
    throw new Error("Preview schema/identity không hợp lệ");
  }
  const prefix = `artifact://jobs/${jobId}/attempts/${value.attempt_id}/`;
  for (const field of ["source_visual_ref", "camera_pose_ref", "delivery_ref"] as const) {
    const ref = value[field];
    if (!record(ref) || ref.job_id !== jobId || typeof ref.artifact_uri !== "string" || !ref.artifact_uri.startsWith(prefix) ||
        typeof ref.artifact_checksum !== "string" || !checksum.test(ref.artifact_checksum) ||
        !["derived", "product_input"].includes(String(ref.data_class)) || ref.schema_version !== "1.0" ||
        typeof ref.artifact_type !== "string" || typeof ref.producer_stage !== "string") {
      throw new Error("Preview artifact reference không hợp lệ");
    }
  }
  const delivery = value.delivery_ref as ProductArtifactRef;
  if (delivery.artifact_type !== "GaussianSOG" || !delivery.artifact_uri.endsWith(".sog")) {
    throw new Error("Preview cần SOG đóng gói một file");
  }
  return value as unknown as ReconstructionPreview;
}
