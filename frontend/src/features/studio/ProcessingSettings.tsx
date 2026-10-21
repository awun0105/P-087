"use client";

import { AlertTriangle, Box, Camera, Cpu, Gauge, HardDrive, Home, Lock, MemoryStick, Sparkles } from "lucide-react";
import { useId, useState } from "react";

import { Badge, Card } from "@/components/studio/primitives";
import { cn } from "@/lib/cn";
import type {
  MachineCapability,
  ParamValue,
  ParameterSpec,
  ProcessingEvaluation,
  ResourceEstimate,
  ResourceStatus,
  ScenarioPreferences,
} from "@/lib/contracts/studio";

const GROUPS: { key: ParameterSpec["group"]; title: string; hint: string }[] = [
  { key: "sampling", title: "Lấy mẫu khung hình", hint: "Video → ảnh đưa vào dựng 3D" },
  { key: "colmap", title: "Ước lượng camera · COLMAP", hint: "Vị trí và hướng camera của từng ảnh" },
  { key: "brush", title: "Dựng 3D Gaussian Splatting · Brush", hint: "Huấn luyện scene trên GPU" },
  { key: "geometry", title: "Lưới va chạm Voxel", hint: "Chọn kiểu lưới, độ phân giải và cách lấp vùng trống" },
  { key: "scene", title: "Tách vật thể · CoACD", hint: "Nhận diện vật thể, tạo collider và vá nền" },
  { key: "simulation", title: "Mô phỏng · OpenUSD", hint: "Sàn và vật liệu vật lý mặc định khi xuất gói" },
];

export type PresetKey = "minimum_quality" | "machine_maximum";

const PRESET_LABEL: Record<PresetKey, { title: string; hint: string }> = {
  minimum_quality: { title: "Tối thiểu · chất lượng tốt", hint: "Khuyến nghị, nhanh và ổn định" },
  machine_maximum: { title: "Tối đa cho máy này", hint: "Cao nhất mà máy xử lý chịu được" },
};

/** Lựa chọn duyệt tách vật là radio riêng, đặt ngay dưới preset; không nằm trong danh sách nâng cao. */
export const GEOMETRY_REVIEW_KEY = "scene.geometry_review";
const REVIEW_CHOICES: { value: string; title: string; hint?: string }[] = [
  { value: "required", title: "Dừng để duyệt và chỉnh vùng vật (khuyên dùng)" },
  {
    value: "auto",
    title: "Tạo mesh ngay, không duyệt",
    hint: "Nhanh hơn. Vật tách sai vẫn sửa được sau nhưng phải dựng lại.",
  },
];

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
  onScenario,
  scenarioPreset,
  scenarioPreferences,
  suggesting = false,
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
  onScenario?: (preferences: ScenarioPreferences) => Promise<void>;
  scenarioPreset?: string | null;
  scenarioPreferences?: ScenarioPreferences | null;
  suggesting?: boolean;
}) {
  const statusOf = (key: string) => evaluation?.parameters.find((item) => item.key === key);
  const flagged = evaluation?.parameters.some((item) => item.status !== "ok") ?? false;
  const reviewSpec = parameters.find((spec) => spec.key === GEOMETRY_REVIEW_KEY);
  const detailParameters = parameters.filter((spec) => spec.key !== GEOMETRY_REVIEW_KEY);
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-bold">
            <Gauge className="size-4 text-ember-strong" aria-hidden />
            Thông số xử lý
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            {editable
              ? "Chọn kịch bản để nhận cấu hình phù hợp. Có thể chỉnh thêm ở phần chi tiết."
              : "Thông số đã dùng cho video mẫu này, chỉ để xem."}
          </p>
        </div>
        {!editable && (
          <Badge tone="neutral">
            <Lock aria-hidden />
            Chỉ đọc
          </Badge>
        )}
      </div>

      {editable && onScenario && <ScenarioWizard onChange={onScenario} suggesting={suggesting} initialPreferences={scenarioPreferences} />}
      {scenarioPreset && <p className="mt-3 text-sm" role="status">Đã áp dụng: <Badge tone="neutral">{scenarioLabel(scenarioPreset, scenarioPreferences)}</Badge></p>}
      {editable && onPreset && !onScenario && (
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
      {editable && activePreset === null && !scenarioPreset && <p className="mt-2 text-xs text-ink-subtle">Đang dùng thông số tùy chỉnh.</p>}

      {reviewSpec && (
        <ReviewChoice
          spec={reviewSpec}
          value={values[GEOMETRY_REVIEW_KEY]}
          editable={editable}
          onChange={(value) => onChange?.(GEOMETRY_REVIEW_KEY, value)}
        />
      )}

      <MachinePanel capability={capability} machineLabel={machineLabel} evaluation={evaluation} editable={editable} />

      {/* Thông số chi tiết thu gọn khi đang dùng preset và không có ô cảnh báo. */}
      <details className="group mt-6" open={!editable || (activePreset === null && !scenarioPreset) || flagged}>
        <summary className="cursor-pointer text-sm font-medium text-ink-muted select-none hover:text-ink">
          Thông số chi tiết ({detailParameters.length} tham số)
        </summary>
      <div className="mt-4 space-y-6">
        {GROUPS.map((group) => {
          const specs = detailParameters.filter((spec) => spec.group === group.key);
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

export const SCENARIO_LABELS: Record<string, string> = {
  video_indoor_walkthrough: "Video trong nhà", video_indoor_orbital_360: "Video quay vòng trong nhà",
  video_single_object: "Quét một vật thể", video_outdoor_forward: "Video ngoài trời",
  photo_collection_indoor: "Bộ ảnh trong nhà", photo_collection_outdoor: "Bộ ảnh ngoài trời",
};

export function scenarioLabel(preset: string, preferences?: ScenarioPreferences | null): string {
  const target = preferences ? { minimum_quality: "Tối thiểu cho máy này", balanced: "Cân bằng", machine_maximum: "Tối đa cho máy này" }[preferences.target_capacity] : null;
  return [SCENARIO_LABELS[preset] ?? preset, target].filter(Boolean).join(" · ");
}

const SCENARIO_QUESTIONS = [
  { key: "input_type", label: "Kiểu quay", icon: Camera, choices: [
    { value: "video_continuous", label: "Video đi bộ liên tục" }, { value: "video_loop_360", label: "Video quay vòng 360°" }, { value: "photo_set", label: "Tập ảnh rời" },
  ] },
  { key: "environment", label: "Không gian", icon: Home, choices: [
    { value: "indoor", label: "Trong nhà" }, { value: "outdoor", label: "Ngoài trời" },
  ] },
  { key: "subject_scope", label: "Phạm vi", icon: Box, choices: [
    { value: "single_object", label: "Một vật thể" }, { value: "full_room", label: "Toàn bộ căn phòng" },
  ] },
  { key: "target_capacity", label: "Mức xử lý", icon: Sparkles, choices: [
    { value: "minimum_quality", label: "Tối thiểu cho máy này" }, { value: "balanced", label: "Cân bằng" }, { value: "machine_maximum", label: "Tối đa cho máy này" },
  ] },
] as const;

function ScenarioWizard({ onChange, suggesting, initialPreferences }: { onChange: (preferences: ScenarioPreferences) => Promise<void>; suggesting: boolean; initialPreferences?: ScenarioPreferences | null }) {
  const id = useId();
  const [preferences, setPreferences] = useState<ScenarioPreferences | null>(initialPreferences ?? null);
  const choose = (key: keyof ScenarioPreferences, value: ScenarioPreferences[keyof ScenarioPreferences]) => {
    const next = { ...(preferences ?? { input_type: "video_continuous", environment: "indoor", subject_scope: "full_room", target_capacity: "balanced" } as ScenarioPreferences), [key]: value };
    setPreferences(next);
    void onChange(next);
  };
  return <section aria-label="Chọn nhanh kịch bản" className="mt-5 space-y-4">
    <h3 className="text-sm font-semibold">Chọn nhanh kịch bản</h3>
    <p className="text-xs text-ink-muted">Chọn để áp dụng gợi ý. Chỉ đổi thông số, không đổi file đã tải lên.</p>
    {SCENARIO_QUESTIONS.map((question) => <fieldset key={question.key}>
      <legend className="mb-2 flex items-center gap-1.5 text-sm font-medium"><question.icon className="size-4" aria-hidden />{question.label}</legend>
      <div className="flex flex-wrap gap-2">{question.choices.map((choice) => <label key={choice.value} className={cn(
        "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm focus-within:ring-2 focus-within:ring-ember",
        preferences?.[question.key] === choice.value ? "border-ember bg-ember-soft/60" : "border-line hover:border-line-strong",
      )}>
        <input type="radio" name={`${id}-${question.key}`} checked={preferences?.[question.key] === choice.value} className="accent-ember-strong"
          onClick={() => { if (preferences?.[question.key] === choice.value) choose(question.key, choice.value); }}
          onChange={() => choose(question.key, choice.value)} />{choice.label}
      </label>)}</div>
    </fieldset>)}
    {suggesting && <p role="status" className="text-xs text-ink-muted">Đang gợi ý cấu hình…</p>}
  </section>;
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
        {editable ? "Máy xử lý" : "Máy đã xử lý"}
      </p>
      <p className="mt-1 text-sm text-ink-muted">
        {header ?? "Chưa có số đo của máy xử lý nên chưa kiểm được cấu hình có vừa máy không."}
      </p>
      {editable && capability?.headroom_measured && <p className="mt-2 text-xs text-ink-subtle">
        Đo lúc {new Date(capability.measured_at).toLocaleTimeString("vi-VN")}. Khi đến lượt, máy đo lại và chờ nếu thiếu tài nguyên.
      </p>}
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
                  <span className={cn("value-tech", item.status === "danger" ? "text-rust" : "text-ink-subtle")}>
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
                  <div
                    className={cn("h-full w-full origin-left rounded-full transition-transform duration-300", STATUS_BAR[item.status])}
                    style={{ transform: `scaleX(${ratio})` }}
                  />
                </div>
                {item.status === "danger" && (
                  <div className="mt-1 space-y-1">
                    <p className="text-xs text-rust">{item.message}</p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ReviewChoice({
  spec,
  value,
  editable,
  onChange,
}: {
  spec: ParameterSpec;
  value: ParamValue | undefined;
  editable: boolean;
  onChange: (value: ParamValue) => void;
}) {
  const name = useId();
  if (!editable && value === undefined) {
    return (
      <fieldset className="mt-5">
        <legend className="text-sm font-semibold text-ink">Sau khi tách vật</legend>
        <p className="mt-2 text-xs text-ink-subtle">Scene này tạo trước khi có lựa chọn này nên không dừng để duyệt.</p>
      </fieldset>
    );
  }
  const offered = REVIEW_CHOICES.filter((choice) => spec.choices?.some((item) => item.value === choice.value));
  return (
    <fieldset disabled={!editable} className="mt-5">
      <legend className="text-sm font-semibold text-ink">Sau khi tách vật</legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {offered.map((choice) => (
          <label
            key={choice.value}
            className={cn(
              "flex items-start gap-2.5 rounded-xl border p-3 transition-colors duration-200",
              editable ? "cursor-pointer" : "cursor-default",
              value === choice.value ? "border-ember bg-ember-soft/60" : "border-line hover:border-line-strong",
            )}
          >
            <input
              type="radio"
              name={name}
              value={choice.value}
              checked={value === choice.value}
              disabled={!editable}
              onChange={() => onChange(choice.value)}
              className="mt-0.5 accent-ember-strong"
            />
            <span className="min-w-0">
              <span className="block text-sm font-medium text-ink">{choice.title}</span>
              {choice.hint && <span className="mt-0.5 block text-xs leading-relaxed text-ink-muted">{choice.hint}</span>}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
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
  if (!editable && value === undefined) return (
    <div className="rounded-xl border border-line bg-paper-raised p-3">
      <p className="text-sm font-medium">{spec.label}</p>
      <p className="mt-1 text-xs text-ink-muted">Không được ghi lại trong video mẫu.</p>
    </div>
  );
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
          <span className="shrink-0 text-xs value-tech text-ink-subtle">
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
              className="h-9 w-28 rounded-lg border border-line-strong bg-paper-raised px-2.5 text-right text-sm value-tech outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30 disabled:opacity-80"
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
