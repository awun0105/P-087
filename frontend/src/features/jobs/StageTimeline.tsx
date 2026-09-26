/**
 * StageTimeline — hiển thị pipeline REC→SCENE→SIM theo dạng timeline (PRODUCT-09).
 *
 * Dùng dữ liệu stage_artifacts từ JobManifest để vẽ từng bước.
 * Không fake percentage — chỉ hiện trạng thái thật từ backend.
 */

"use client";

import type { StageArtifact } from "@/lib/contracts/api";

const STAGE_ORDER = [
  "ST-INPUT-VALIDATE",
  "ST-PRIVACY-GATE",
  "ST-REC-DISPATCH",
  "ST-REC-WAIT",
  "ST-SCENE-DISPATCH",
  "ST-SCENE-WAIT",
  "ST-SIM-DISPATCH",
  "ST-SIM-WAIT",
  "ST-CANDIDATE-SEAL",
  "ST-VALIDATION",
  "ST-REVIEW-READY",
];

const STAGE_LABEL: Record<string, string> = {
  "ST-INPUT-VALIDATE": "Validate input",
  "ST-PRIVACY-GATE": "Privacy gate",
  "ST-REC-DISPATCH": "Dispatch REC",
  "ST-REC-WAIT": "Reconstruction",
  "ST-SCENE-DISPATCH": "Dispatch SCENE",
  "ST-SCENE-WAIT": "Scene processing",
  "ST-SIM-DISPATCH": "Dispatch SIM",
  "ST-SIM-WAIT": "Simulation",
  "ST-CANDIDATE-SEAL": "Seal candidate",
  "ST-VALIDATION": "Validation",
  "ST-REVIEW-READY": "Ready for review",
};

const STATUS_DOT: Record<
  string,
  { color: string; bg: string; label: string }
> = {
  SUCCEEDED: { color: "text-emerald-400", bg: "bg-emerald-600", label: "OK" },
  RUNNING: { color: "text-sky-400", bg: "bg-sky-500", label: "Running" },
  FAILED: { color: "text-rose-400", bg: "bg-rose-600", label: "Failed" },
  PENDING: { color: "text-slate-500", bg: "bg-slate-700", label: "Pending" },
  SKIPPED: { color: "text-slate-600", bg: "bg-slate-800", label: "Skip" },
};

export function StageTimeline({
  stages,
  currentStage,
}: {
  stages: StageArtifact[];
  currentStage: string;
}) {
  // Map stage_id → artifact info
  const stageMap = new Map(stages.map((s) => [s.stage_id, s]));

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-slate-500">
        Pipeline REC → SCENE → SIM
      </h2>
      <ol className="relative ml-2 border-l border-slate-800">
        {STAGE_ORDER.map((stageId, idx) => {
          const artifact = stageMap.get(stageId);
          const status = artifact?.status ?? (stageId === currentStage ? "RUNNING" : "PENDING");
          const meta = STATUS_DOT[status] ?? STATUS_DOT.PENDING!;
          const isCurrent = stageId === currentStage;

          return (
            <li key={stageId} className="mb-3 ml-4 last:mb-0">
              {/* Dot */}
              <span
                className={`absolute -left-[5px] mt-0.5 h-2.5 w-2.5 rounded-full border-2 border-slate-950 ${meta.bg} ${isCurrent ? "ring-2 ring-sky-500/40" : ""}`}
              />

              <div className="flex items-start justify-between gap-2">
                <div>
                  <p
                    className={`text-xs font-medium ${isCurrent ? "text-sky-300" : status === "SUCCEEDED" ? "text-slate-300" : "text-slate-500"}`}
                  >
                    {STAGE_LABEL[stageId] ?? stageId}
                    {isCurrent && (
                      <span className="ml-1.5 text-[10px] text-sky-500">← current</span>
                    )}
                  </p>
                  {artifact?.error && (
                    <p className="mt-0.5 text-[10px] text-rose-400">
                      {artifact.error.error_code}: {artifact.error.human_message}
                      {artifact.error.retryable && (
                        <span className="ml-1 text-amber-400">(có thể retry)</span>
                      )}
                    </p>
                  )}
                  {artifact?.artifact_uri && (
                    <p className="mt-0.5 font-mono text-[10px] text-slate-600 truncate max-w-xs">
                      {artifact.artifact_uri}
                    </p>
                  )}
                </div>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.color} bg-slate-800/60`}
                >
                  {meta.label}
                </span>
              </div>

              {artifact?.started_at && (
                <p className="mt-0.5 text-[10px] text-slate-700">
                  {artifact.started_at}
                  {artifact.completed_at ? ` → ${artifact.completed_at}` : ""}
                </p>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-[10px] text-slate-700">
        Stage thực tế từ backend · không có percentage ước tính.
      </p>
    </div>
  );
}
