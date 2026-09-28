/**
 * StageTimeline — hiển thị pipeline theo thứ tự stage thật của backend (PRODUCT-09).
 *
 * Bản cũ vẽ một pipeline tự chế gồm 11 ID trong đó **9 cái không tồn tại** ở
 * `src/models/contracts/manifests.py` (`ST-REC-DISPATCH`, `ST-REC-WAIT`,
 * `ST-SCENE-DISPATCH`, `ST-SCENE-WAIT`, `ST-SIM-DISPATCH`, `ST-SIM-WAIT`,
 * `ST-CANDIDATE-SEAL`, `ST-VALIDATION`, `ST-REVIEW-READY`), đồng thời thiếu 18
 * stage có thật — gồm cả `ST-FRAME-EXTRACT`, `ST-VISUAL-RECON`, `ST-RGB-GEOMETRY`.
 * Hậu quả: mọi stage thật rơi vào nhánh "PENDING", không dòng nào được đánh dấu là
 * đang chạy, và `ExecutionError` không bao giờ hiện dù code đã viết sẵn để hiện.
 *
 * Chỉ dựng các stage có trong execution records/current stage của job; enum
 * contract xác định ID hợp lệ, không phải execution plan cho mọi nhánh input.
 */

"use client";

import type { JobStatus, StageArtifact, StageId, StageStatus } from "@/lib/contracts/api";
import { STAGE_STATUSES } from "@/lib/contracts/api";

/** Nhãn tiếng Việt cho từng stage thật; stage chưa có nhãn hiển thị luôn ID gốc. */
const STAGE_LABEL: Partial<Record<StageId, string>> = {
  "ST-INPUT-VALIDATE": "Validate input",
  "ST-PRIVACY-GATE": "Privacy gate",
  "ST-FRAME-EXTRACT": "Trích frame",
  "ST-CAMERA-POSE": "Camera pose",
  "ST-VISUAL-RECON": "Dựng 3DGS",
  "ST-RGB-GEOMETRY": "Voxel collision",
  "ST-LIDAR-INGEST": "Nạp LiDAR",
  "ST-RGB-LIDAR-ALIGN": "Căn RGB↔LiDAR",
  "ST-METRIC-CANONICALIZE": "Chốt metric",
  "ST-OBJECT-EXTRACT": "Trích vật thể",
  "ST-OBJECT-ASSOC": "Ghép vật thể",
  "ST-OBJECT-CONFIRM": "Xác nhận vật thể",
  "ST-SCENE-DECOMPOSE": "Phân rã scene",
  "ST-COLLIDER": "Sinh collider",
  "ST-EDIT": "Chỉnh sửa scene",
  "ST-PREFLIGHT": "Preflight",
  "ST-CANDIDATE-BUILD": "Dựng candidate",
  "ST-ISAAC-VALIDATE": "Isaac validate",
  "ST-REVIEW": "Review",
  "ST-RELEASE": "Release",
};

/**
 * `CANCELLED` phải có nhãn riêng — thiếu nó thì một stage bị hủy hiện thành
 * "Pending", tức trông như chưa chạy. `SKIPPED` không phải `StageStatus` nên không
 * có ở đây.
 */
const STATUS_DOT: Record<StageStatus, { color: string; bg: string; label: string }> = {
  QUEUED: { color: "text-slate-500", bg: "bg-slate-700", label: "Queued" },
  RUNNING: { color: "text-sky-400", bg: "bg-sky-500", label: "Running" },
  SUCCEEDED: { color: "text-emerald-400", bg: "bg-emerald-600", label: "OK" },
  FAILED: { color: "text-rose-400", bg: "bg-rose-600", label: "Failed" },
  CANCELLED: { color: "text-slate-400", bg: "bg-slate-600", label: "Cancelled" },
};

/** Stage backend chưa gửi về coi như chưa chạy — không được bịa "Running". */
const NOT_REPORTED = STATUS_DOT.QUEUED;

export function StageTimeline({
  stages,
  currentStage,
  jobStatus,
}: {
  stages: StageArtifact[];
  currentStage?: StageId;
  jobStatus?: JobStatus;
}) {
  const byStage = new Map<StageId, StageArtifact>(stages.map((stage) => [stage.stage_id, stage]));
  // Enum là tập ID hợp lệ, không phải execution plan của mọi nhánh RGB/LiDAR.
  const orderedStages = [...byStage.keys()];
  if (currentStage && !byStage.has(currentStage)) orderedStages.push(currentStage);

  return (
    <ol className="flex flex-col gap-2" data-testid="stage-timeline">
      {orderedStages.map((stageId) => {
        const artifact = byStage.get(stageId);
        const status = artifact?.status;
        const dot = status ? STATUS_DOT[status] : { ...NOT_REPORTED, label: "Chưa có stage report" };
        const isCurrent = stageId === currentStage && status === "RUNNING" && (!jobStatus || jobStatus === "RUNNING");
        return (
          <li
            key={stageId}
            className="flex items-start gap-2 text-xs"
            data-stage-id={stageId}
            data-status={status ?? "UNREPORTED"}
            data-current={isCurrent}
          >
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${dot.bg} ${dot.color}`} />
            <span className={isCurrent ? "font-semibold text-slate-200" : "text-slate-400"}>
              {STAGE_LABEL[stageId] ?? stageId}
            </span>
            {isCurrent ? <span className="text-sky-400">← đang chạy</span> : null}
            <span className="ml-auto shrink-0 text-slate-500">{dot.label}</span>
            {artifact?.error ? (
              <details className="w-full">
                <summary className="cursor-pointer list-none text-rose-400">
                  {artifact.error.error_code}
                  {artifact.error.retryable ? <span className="ml-1 text-amber-400">(retryable)</span> : null}
                </summary>
                <p className="mt-1 text-[10px] text-slate-400">{artifact.error.human_message}</p>
              </details>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export { STAGE_STATUSES };
