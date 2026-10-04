import type { DataOrigin, ParamValue } from "@/lib/contracts/studio";

export interface SetupDraft {
  selected: string | null; name: string; owner: string; origin: DataOrigin; purpose: string;
  rights: boolean; anonymized: boolean; retention: boolean; processing: Record<string, ParamValue> | null;
}
export const EMPTY_SETUP: SetupDraft = { selected: null, name: "", owner: "", origin: "self_collected_no_pii", purpose: "Dựng scene mô phỏng kho cho robot AMR", rights: false, anonymized: false, retention: false, processing: null };
/** Chỉ nhận các field form cho phép; không giữ File, token hoặc dữ liệu ngoài schema. */
export function parseSetupDraft(value: unknown): SetupDraft | null {
  if (!value || typeof value !== "object") return null;
  const draft = value as Partial<SetupDraft>;
  if (!(draft.selected === null || typeof draft.selected === "string") || typeof draft.name !== "string" || typeof draft.owner !== "string" || typeof draft.purpose !== "string" ||
    !["self_collected_no_pii", "anonymized", "public_or_synthetic"].includes(draft.origin ?? "") ||
    typeof draft.rights !== "boolean" || typeof draft.anonymized !== "boolean" || typeof draft.retention !== "boolean") return null;
  const processing = draft.processing && typeof draft.processing === "object" && !Array.isArray(draft.processing) ?
    Object.fromEntries(Object.entries(draft.processing).filter(([, v]) => typeof v === "string" || typeof v === "number" && Number.isFinite(v))) : null;
  return { selected: draft.selected, name: draft.name.slice(0, 200), owner: draft.owner.slice(0, 200), purpose: draft.purpose.slice(0, 500), origin: draft.origin as DataOrigin,
    rights: draft.rights, anonymized: draft.anonymized, retention: draft.retention, processing };
}
