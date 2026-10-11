export interface FloorFitDiagnostic {
  status: "confirmed_prior_fallback" | "uncertain";
  tone: "ochre" | "rust";
  title: string;
  message: string;
  evidenceArtifactUri: string | null;
}

const REASONS: Record<string, string> = {
  missing_floor_prior: "chưa có mốc sàn đã xác nhận",
  invalid_point_shape: "dữ liệu điểm không đúng định dạng",
  non_finite_points: "dữ liệu điểm có giá trị không hữu hạn",
  insufficient_points: "chưa đủ điểm để đo mặt sàn",
  degenerate_points: "các điểm sàn chưa phân bố đủ rộng",
  no_floor_near_prior: "chưa tìm được mặt sàn gần mốc đã xác nhận",
  insufficient_inliers: "chưa đủ điểm nhất quán trên mặt sàn",
  low_inlier_ratio: "tỉ lệ điểm nhất quán trên mặt sàn còn thấp",
  insufficient_coverage: "vùng quan sát mặt sàn còn hẹp",
  excessive_noise: "nhiễu đo mặt sàn vượt ngưỡng",
  ambiguous_multiple_planes: "có nhiều mặt phẳng cạnh tranh",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Read optional SceneIR provenance without rejecting legacy revisions. */
export function floorFitDiagnostic(provenance: unknown): FloorFitDiagnostic | null {
  if (!isRecord(provenance) || !isRecord(provenance.floor_fit)) return null;
  const fit = provenance.floor_fit;
  if (fit.status !== "confirmed_prior_fallback" && fit.status !== "uncertain") return null;
  const reason = typeof fit.fallback_reason === "string" ? REASONS[fit.fallback_reason] ?? "cần kiểm tra dữ liệu sàn" : "cần kiểm tra dữ liệu sàn";
  const evidenceRef = isRecord(fit.artifact_ref) ? fit.artifact_ref : null;
  const evidenceArtifactUri = evidenceRef && typeof evidenceRef.artifact_uri === "string" ? evidenceRef.artifact_uri : null;

  if (fit.status === "confirmed_prior_fallback") {
    const band = typeof fit.floor_band_m === "number" && Number.isFinite(fit.floor_band_m)
      ? ` Dải bảo vệ sàn hiện dùng ${fit.floor_band_m.toFixed(3)} m.`
      : "";
    return {
      status: fit.status,
      tone: "ochre",
      title: "Mặt sàn đang dùng mốc REC-06 đã xác nhận",
      message: `Bộ fit ${reason}; kết quả đang dùng mốc sàn đã xác nhận. Hãy kiểm tra scale và vị trí sàn nếu vật sát sàn bị phân loại sai.${band}`,
      evidenceArtifactUri,
    };
  }

  return {
    status: fit.status,
    tone: "rust",
    title: "Chưa xác nhận được mặt sàn",
    message: `Bộ fit ${reason}.${typeof fit.robust_noise_sigma_m === "number" && Number.isFinite(fit.robust_noise_sigma_m)
      && typeof fit.max_noise_sigma_m === "number" && Number.isFinite(fit.max_noise_sigma_m)
      ? ` Độ nhiễu ${(fit.robust_noise_sigma_m * 100).toFixed(2)} cm; ngưỡng ${(fit.max_noise_sigma_m * 100).toFixed(2)} cm.` : ""} Cần kiểm tra dữ liệu hình học, tỉ lệ và mốc sàn trước khi tách vật hoặc dùng scene cho mô phỏng.`,
    evidenceArtifactUri,
  };
}
