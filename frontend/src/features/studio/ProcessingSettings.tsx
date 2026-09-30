"use client";

import { AlertTriangle, Cpu, Gauge, HardDrive, Lock, MemoryStick, Sparkles } from "lucide-react";
import { useId } from "react";

import { Badge, Card } from "@/components/studio/primitives";
import { cn } from "@/lib/cn";
import type {
  MachineCapability,
  ParamValue,
  ParameterSpec,
  ProcessingEvaluation,
  ResourceEstimate,
  ResourceStatus,
} from "@/lib/contracts/studio";

const GROUPS: { key: ParameterSpec["group"]; title: string; hint: string }[] = [
  { key: "sampling", title: "Lấy mẫu khung hình", hint: "Video → ảnh đưa vào dựng 3D" },
  { key: "colmap", title: "Ước lượng camera · COLMAP", hint: "Vị trí và hướng camera của từng ảnh" },
  { key: "brush", title: "Dựng 3D Gaussian Splatting · Brush", hint: "Huấn luyện scene trên GPU" },
];

export type PresetKey = "minimum_quality" | "machine_maximum";

const PRESET_LABEL: Record<PresetKey, { title: string; hint: string }> = {
  minimum_quality: { title: "Tối thiểu · chất lượng tốt", hint: "Khuyến nghị, nhanh và ổn định" },
  machine_maximum: { title: "Tối đa cho máy này", hint: "Cao nhất mà máy xử lý chịu được" },
};

/**
 * Bảng thông số xử lý theo file cấu hình chung.
 *
 * `editable=false` (video mẫu): hiện đúng thông số đã chạy, khóa sửa.
 * `editable=true` (người dùng thật): preset + chỉnh từng ô; ô gây nguy cơ crash
 * tô đỏ kèm lý do theo ước lượng tài nguyên của máy worker.
 */
export function ProcessingSettings({
  parameters,
  values,
  editable,
  evaluation,
  capability,
  machineLabel,
  activePreset,
  onPreset,
  onChange,
  note,
}: {
  parameters: ParameterSpec[];
  values: Record<string, ParamValue>;
  editable: boolean;
  evaluation?: ProcessingEvaluation | null;
  capability?: MachineCapability | null;
  machineLabel?: string | null;
  activePreset?: PresetKey | null;
  onPreset?: (preset: PresetKey) => void;
  onChange?: (key: string, value: ParamValue) => void;
  note?: string;
}) {
  const statusOf = (key: string) => evaluation?.parameters.find((item) => item.key === key);
  const flagged = evaluation?.parameters.some((item) => item.status !== "ok") ?? false;
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Gauge className="size-4 text-ember-strong" aria-hidden />
            Thông số xử lý
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            {editable
              ? "Mặc định là cấu hình tối thiểu cho chất lượng tốt. Tăng dần tới mức tối đa mà máy xử lý chịu được."
              : "Thông số thật đã dùng khi xử lý sẵn video mẫu này — chỉ để xem."}
          </p>
        </div>
        {!editable && (
          <Badge tone="neutral">
            <Lock aria-hidden />
            Chỉ đọc
          </Badge>
        )}
      </div>

      {editable && onPreset && (
        <div role="radiogroup" aria-label="Preset thông số" className="mt-5 grid gap-2 sm:grid-cols-2">
          {(Object.keys(PRESET_LABEL) as PresetKey[]).map((key) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={activePreset === key}
              onClick={() => onPreset(key)}
              className={cn(
                "cursor-pointer rounded-xl border p-3 text-left transition-colors duration-200",
                activePreset === key ? "border-ember bg-ember-soft/60" : "border-line hover:border-line-strong",
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
                {key === "machine_maximum" && <Sparkles className="size-3.5 text-ember-strong" aria-hidden />}
                {PRESET_LABEL[key].title}
              </span>
              <span className="mt-0.5 block text-xs text-ink-muted">{PRESET_LABEL[key].hint}</span>
            </button>
          ))}
        </div>
      )}
      {editable && activePreset === null && <p className="mt-2 text-xs text-ink-subtle">Đang dùng thông số tùy chỉnh.</p>}

      <MachinePanel capability={capability} machineLabel={machineLabel} evaluation={evaluation} editable={editable} />

      {/* Thông số chi tiết thu gọn khi đang dùng preset và không có ô cảnh báo (PRODUCT.md P3). */}
      <details className="group mt-6" open={!editable || activePreset === null || flagged}>
        <summary className="cursor-pointer text-sm font-medium text-ink-muted select-none hover:text-ink">
          Thông số chi tiết ({parameters.length} tham số)
        </summary>
      <div className="mt-4 space-y-6">
        {GROUPS.map((group) => {
          const specs = parameters.filter((spec) => spec.group === group.key);
          if (specs.length === 0) return null;
          return (
            <fieldset key={group.key} disabled={!editable}>
              <legend className="text-sm font-semibold text-ink">{group.title}</legend>
              <p className="text-xs text-ink-subtle">{group.hint}</p>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                {specs.map((spec) => {
                  const status = statusOf(spec.key);
                  return (
                    <ParameterField
                      key={spec.key}
                      spec={spec}
                      value={values[spec.key]}
                      editable={editable}
                      status={status?.status ?? "ok"}
                      message={status?.message ?? null}
                      onChange={(value) => onChange?.(spec.key, value)}
                    />
                  );
                })}
              </div>
            </fieldset>
          );
        })}
      </div>
      </details>
      {note && <p className="mt-5 text-xs leading-relaxed text-ink-subtle">{note}</p>}
    </Card>
  );
}

const RESOURCE_META: Record<ResourceEstimate["resource"], { label: string; icon: typeof Cpu }> = {
  vram: { label: "VRAM GPU", icon: Gauge },
  ram: { label: "RAM", icon: MemoryStick },
  disk: { label: "Ổ đĩa trống", icon: HardDrive },
};

const STATUS_BAR: Record<ResourceStatus, string> = {
  ok: "bg-sage",
  warn: "bg-ochre",
  danger: "bg-rust",
  unknown: "bg-line-strong",
};

function MachinePanel({
  capability,
  machineLabel,
  evaluation,
  editable,
}: {
  capability?: MachineCapability | null;
  machineLabel?: string | null;
  evaluation?: ProcessingEvaluation | null;
  editable: boolean;
}) {
  const header = capability
    ? `${capability.gpu_name ?? "Không có GPU NVIDIA"} · ${capability.cpu_count} CPU · ${capability.ram_total_gb.toFixed(0)} GB RAM`
    : machineLabel;
  return (
    <div className="mt-5 rounded-xl bg-paper-sunken p-4">
      <p className="flex items-center gap-2 text-sm font-medium text-ink">
        <Cpu className="size-4 text-ink-muted" aria-hidden />
        {editable ? "Máy xử lý (GPU server)" : "Máy đã xử lý"}
      </p>
      <p className="mt-1 text-sm text-ink-muted">
        {header ?? "Chưa có số đo — worker chưa chạy hoặc chưa báo cấu hình. Không kiểm được nguy cơ crash."}
      </p>
      {editable && evaluation && (
        <ul className="mt-4 grid gap-3 sm:grid-cols-3">
          {evaluation.resources.map((item) => {
            const meta = RESOURCE_META[item.resource];
            const Icon = meta.icon;
            const ratio = item.available_gb ? Math.min(1, item.required_gb / item.available_gb) : 0;
            return (
              <li key={item.resource} className="min-w-0">
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="flex items-center gap-1 font-medium text-ink">
                    <Icon className="size-3.5 text-ink-muted" aria-hidden />
                    {meta.label}
                  </span>
                  <span className={cn("tabular-nums", item.status === "danger" ? "text-rust" : "text-ink-subtle")}>
                    {item.required_gb.toFixed(1)}
                    {item.available_gb !== null ? ` / ${item.available_gb.toFixed(1)} GB` : " GB"}
                  </span>
                </div>
                <div
                  className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-paper"
                  role="meter"
                  aria-label={`${meta.label} ước lượng`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(ratio * 100)}
                >
                  <div className={cn("h-full rounded-full transition-[width] duration-300", STATUS_BAR[item.status])} style={{ width: `${ratio * 100}%` }} />
                </div>
                {item.status === "danger" && <p className="mt-1 text-xs text-rust">{item.message}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ParameterField({
  spec,
  value,
  editable,
  status,
  message,
  onChange,
}: {
  spec: ParameterSpec;
  value: ParamValue | undefined;
  editable: boolean;
  status: ResourceStatus;
  message: string | null;
  onChange: (value: ParamValue) => void;
}) {
  const id = useId();
  const tone =
    status === "danger"
      ? "border-rust bg-rust-soft/60"
      : status === "warn"
        ? "border-ochre/60 bg-ochre-soft/50"
        : "border-line bg-paper-raised";
  return (
    <div className={cn("rounded-xl border p-3 transition-colors duration-200", tone)}>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {spec.label}
        </label>
        {spec.kind !== "choice" && (
          <span className="shrink-0 text-xs tabular-nums text-ink-subtle">
            {formatValue(spec, spec.min)}–{formatValue(spec, spec.max)} {spec.unit}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{spec.description}</p>
      <div className="mt-2.5">
        {spec.kind === "choice" ? (
          <select
            id={id}
            value={String(value ?? "")}
            disabled={!editable}
            onChange={(event) => onChange(event.target.value)}
            className="h-9 w-full rounded-lg border border-line-strong bg-paper-raised px-2.5 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30 disabled:opacity-80"
          >
            {spec.choices?.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        ) : (
          <div className="flex items-center gap-3">
            <input
              type="range"
              aria-label={spec.label}
              min={spec.min ?? 0}
              max={spec.max ?? 0}
              step={spec.step ?? 1}
              value={Number(value ?? spec.min ?? 0)}
              disabled={!editable}
              onChange={(event) => onChange(Number(event.target.value))}
              className="h-2 min-w-0 flex-1 cursor-pointer accent-ember-strong disabled:cursor-default"
            />
            <input
              id={id}
              type="number"
              inputMode={spec.kind === "integer" ? "numeric" : "decimal"}
              min={spec.min ?? undefined}
              max={spec.max ?? undefined}
              step={spec.step ?? 1}
              value={Number(value ?? spec.min ?? 0)}
              disabled={!editable}
              onChange={(event) => {
                const next = Number(event.target.value);
                if (Number.isFinite(next)) onChange(spec.kind === "integer" ? Math.round(next) : next);
              }}
              className="h-9 w-28 rounded-lg border border-line-strong bg-paper-raised px-2.5 text-right text-sm tabular-nums outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30 disabled:opacity-80"
            />
          </div>
        )}
      </div>
      {message && status !== "ok" && (
        <p className={cn("mt-2 flex gap-1.5 text-xs", status === "danger" ? "text-rust" : "text-ochre")} role={status === "danger" ? "alert" : undefined}>
          <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden />
          {message}
        </p>
      )}
    </div>
  );
}

function formatValue(spec: ParameterSpec, value: number | null): string {
  if (value === null) return "";
  return value >= 100000 ? new Intl.NumberFormat("vi-VN", { notation: "compact" }).format(value) : String(value);
}
