"use client";

import { Loader2, Plus, Save, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Button, Notice } from "@/components/studio/primitives";
import {
  distanceBetween,
  draftFromTruth,
  isDirty,
  missingObstacleIds,
  nextId,
  parseMinutes,
  robotProblem,
  truthFromDraft,
  type BenchmarkDraft,
} from "@/features/studio/value/benchmark-draft";
import { ApiError } from "@/lib/api/client";
import {
  getBenchmarkTruth,
  putBenchmarkTruth,
  type BenchmarkTruth,
  type GapCheck,
  type Layout,
  type MeasuredDistance,
  type Vec3,
} from "@/lib/api/value";
import { errorMessage } from "@/lib/ui-error";

/** Điểm chọn trên viewer, hệ nguồn của scene (`z_up` = canonical). */
export interface BenchmarkPickerApi {
  points: readonly (readonly [number, number, number])[];
  /** Bật chọn điểm và xoá điểm cũ. */
  start(): void;
  /** Tắt chọn điểm. */
  stop(): void;
}

export interface BenchmarkPanelProps {
  jobId: string;
  /** Revision hiện tại của scene, dùng khi gắn bố trí A/B. */
  sceneRevision: string;
  /** Vật của scene hiện tại; checklist vật cản lấy từ đây. */
  objects: readonly { id: string; name: string }[];
  /** Có quyền ghi không; false thì chỉ xem. */
  canEdit: boolean;
  /** Chọn điểm trên viewer; null khi viewer chưa sẵn sàng. */
  picker?: BenchmarkPickerApi | null;
  onClose: () => void;
}

type PickPurpose = "distance" | "gap";

const DATA_SOURCES: { value: BenchmarkTruth["data_source"]; label: string }[] = [
  { value: "self_capture", label: "Tự quay" },
  { value: "hf_room", label: "Phòng Hugging Face" },
  { value: "synthetic", label: "Tổng hợp" },
];

const SECTION = "space-y-2 border-t border-line-dark pt-3";
const FIELD = "h-8 w-full rounded-md border border-line-dark bg-viewport-deep px-2 text-sm text-on-dark disabled:opacity-60";
const TEXTAREA = "w-full rounded-md border border-line-dark bg-viewport-deep px-2 py-1 text-sm text-on-dark disabled:opacity-60";

function formatPoint(point: Vec3): string {
  return `(${point.map((value) => value.toFixed(2)).join(", ")})`;
}

/** Số trong ô nhập; ô trống là NaN để kiểm tra được chưa nhập. */
function numberOrNaN(text: string): number {
  return text.trim() === "" ? Number.NaN : Number(text);
}

function shownNumber(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "" : String(value);
}

/** Lỗi kiểm ở phía client, trùng biên của máy chủ; máy chủ vẫn kiểm lại khi lưu. */
function draftProblems(draft: BenchmarkDraft): string[] {
  const problems: string[] = [];
  const robot = robotProblem(draft.robot);
  if (robot) problems.push(robot);
  for (const item of draft.distances) {
    if (!(Number.isFinite(item.real_m) && item.real_m > 0 && item.real_m <= 100)) {
      problems.push(`Đoạn "${item.label}": nhập mét thật trong (0; 100]`);
    }
  }
  for (const gap of draft.gaps) {
    const span = distanceBetween(gap.a, gap.b);
    if (!(span >= 0.1 && span <= 10)) problems.push(`Khe "${gap.label}": khoảng cách hai điểm nằm ngoài [0,1; 10] m`);
    if (gap.real_width_m !== null && !(gap.real_width_m > 0 && gap.real_width_m <= 10)) {
      problems.push(`Khe "${gap.label}": bề rộng thật nằm trong (0; 10] m`);
    }
  }
  if (draft.layouts.A && draft.layouts.B && draft.layouts.A.scene_revision === draft.layouts.B.scene_revision) {
    problems.push("Bố trí A và B phải là hai revision khác nhau");
  }
  if (draft.l4 && draft.l4.evidence.trim() === "") problems.push("L4: cần ghi bằng chứng");
  if (draft.manualBaselineMinutes.trim() !== "" && parseMinutes(draft.manualBaselineMinutes) === null) {
    problems.push("Mốc làm tay phải là số phút ≥ 0 (dùng dấu chấm cho phần thập phân)");
  }
  return problems;
}

export function BenchmarkPanel({ jobId, sceneRevision, objects, canEdit, picker = null, onClose }: BenchmarkPanelProps) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [saved, setSaved] = useState<BenchmarkDraft | null>(null);
  const [draft, setDraft] = useState<BenchmarkDraft | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "rust" | "ember"; text: string } | null>(null);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<PickPurpose | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  // Bộ điểm của viewer lúc bắt đầu chọn. `picker.start()` xoá điểm cũ bất đồng bộ, nên chỉ nhận bộ điểm MỚI so với bộ này.
  const pickBaseline = useRef<BenchmarkPickerApi["points"] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getBenchmarkTruth(jobId, controller.signal)
      .then((response) => {
        const next = draftFromTruth(response.truth);
        setVersion(response.version);
        setSaved(next);
        setDraft(next);
        setUpdatedAt(response.updated_at);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [jobId]);

  // Chọn đủ hai điểm thì đưa vào đoạn đo hoặc khe, rồi tắt chế độ chọn. Viewer là hệ bên ngoài React nên đồng bộ bằng effect.
  useEffect(() => {
    if (!pending || !picker || picker.points.length < 2 || picker.points === pickBaseline.current) return;
    const [a, b] = picker.points;
    picker.stop();
    setPending(null);
    const point = (value: readonly [number, number, number]): Vec3 => [value[0], value[1], value[2]];
    setDraft((current) => {
      if (!current) return current;
      if (pending === "distance") {
        const item: MeasuredDistance = {
          id: nextId("d", current.distances),
          label: `Đoạn ${current.distances.length + 1}`,
          a: point(a),
          b: point(b),
          real_m: Number.NaN,
        };
        return { ...current, distances: [...current.distances, item] };
      }
      const item: GapCheck = {
        id: nextId("g", current.gaps),
        label: `Khe ${current.gaps.length + 1}`,
        layout: "A",
        a: point(a),
        b: point(b),
        real_width_m: null,
        real_passable: false,
      };
      return { ...current, gaps: [...current.gaps, item] };
    });
  }, [pending, picker, picker?.points]);

  const sceneIds = useMemo(() => new Set(objects.map((item) => item.id)), [objects]);

  if (loading) {
    return (
      <Shell onClose={onClose}>
        <p className="flex items-center gap-2 text-sm text-on-dark/70" role="status">
          <Loader2 className="size-4 animate-spin" /> Đang tải ground truth…
        </p>
      </Shell>
    );
  }
  if (loadError || !draft || !saved) {
    return (
      <Shell onClose={onClose}>
        <Notice tone="rust">{loadError ?? "Chưa đọc được số đo thật của scene."}</Notice>
      </Shell>
    );
  }

  const current = draft;
  const l4 = current.l4;
  const dirty = isDirty(current, saved);
  const problems = draftProblems(current);
  const missing = missingObstacleIds(current.keyObstacleIds, sceneIds);
  const editable = canEdit && !busy;
  const pickAvailable = Boolean(picker) && canEdit;

  const update = (change: Partial<BenchmarkDraft>) => setDraft({ ...current, ...change });
  const updateDistance = (id: string, change: Partial<MeasuredDistance>) =>
    update({ distances: current.distances.map((item) => (item.id === id ? { ...item, ...change } : item)) });
  const updateGap = (id: string, change: Partial<GapCheck>) =>
    update({ gaps: current.gaps.map((item) => (item.id === id ? { ...item, ...change } : item)) });

  const startPick = (purpose: PickPurpose) => {
    if (!picker) return;
    pickBaseline.current = picker.points;
    setPending(purpose);
    picker.start();
  };
  const cancelPick = () => {
    picker?.stop();
    setPending(null);
  };

  const tagLayout = (layout: Layout) =>
    update({ layouts: { ...current.layouts, [layout]: { scene_revision: sceneRevision, tagged_at: new Date().toISOString() } } });

  const save = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const response = await putBenchmarkTruth(jobId, version, truthFromDraft(current));
      const next = draftFromTruth(response.truth);
      setVersion(response.version);
      setSaved(next);
      setDraft(next);
      setUpdatedAt(response.updated_at);
      setConflict(false);
      setNotice({ tone: "ember", text: `Đã lưu (phiên bản ${response.version}).` });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true);
      } else {
        setNotice({ tone: "rust", text: error instanceof ApiError ? error.detail : errorMessage(error) });
      }
    } finally {
      setBusy(false);
    }
  };

  const reloadServer = async () => {
    setBusy(true);
    try {
      const response = await getBenchmarkTruth(jobId);
      // Chỉ cập nhật phiên bản và bản đã lưu; nhập liệu của người dùng được giữ nguyên.
      setVersion(response.version);
      setSaved(draftFromTruth(response.truth));
      setUpdatedAt(response.updated_at);
      setConflict(false);
      setNotice({ tone: "ember", text: "Đã tải bản mới nhất. Nhập liệu của bạn vẫn còn; Lưu sẽ ghi đè bản trên máy chủ." });
    } catch (error) {
      setNotice({ tone: "rust", text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  const requestClose = () => {
    if (dirty) setConfirmClose(true);
    else onClose();
  };

  return (
    <Shell onClose={requestClose} title="Benchmark · ground truth" subtitle={`phiên bản ${version}${updatedAt ? ` · lưu lúc ${new Date(updatedAt).toLocaleString("vi-VN")}` : ""}`}>
      {!canEdit && <Notice>Bạn chỉ có quyền xem ground truth; cần đăng nhập để sửa.</Notice>}
      {pending && (
        <div role="status" className="flex items-center justify-between gap-2 rounded-md border border-ember/40 bg-ember-soft/20 px-3 py-2 text-xs">
          <span>Bấm hai điểm trên scene cho {pending === "distance" ? "đoạn đo" : "khe kiểm"} ({picker?.points.length ?? 0}/2)</span>
          <Button size="sm" variant="ghost" onClick={cancelPick}>Huỷ chọn</Button>
        </div>
      )}

      <section aria-label="Robot" className={SECTION}>
        <h3 className="text-sm font-semibold">Robot</h3>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <Field label="Bề rộng (m)" value={current.robot.width_m} disabled={!editable} onChange={(value) => update({ robot: { ...current.robot, width_m: value } })} />
          <Field label="Khoảng an toàn (m)" value={current.robot.safety_margin_m} disabled={!editable} onChange={(value) => update({ robot: { ...current.robot, safety_margin_m: value } })} />
          <Field label="Độ cao thấp nhất (m)" value={current.robot.height_min_m} disabled={!editable} onChange={(value) => update({ robot: { ...current.robot, height_min_m: value } })} />
          <Field label="Độ cao cao nhất (m)" value={current.robot.height_max_m} disabled={!editable} onChange={(value) => update({ robot: { ...current.robot, height_max_m: value } })} />
        </div>
      </section>

      <section aria-label="Đoạn đo" className={SECTION}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Đoạn đo</h3>
          <Button size="sm" variant="ghost" disabled={!editable || !pickAvailable || pending !== null} onClick={() => startPick("distance")}>
            <Plus className="size-3.5" /> Thêm đoạn
          </Button>
        </div>
        {!picker && canEdit && <p className="text-[11px] text-on-dark/60">Chọn điểm cần viewer sẵn sàng.</p>}
        {current.distances.length === 0 && <p className="text-xs text-on-dark/60">Chưa có đoạn đo.</p>}
        {current.distances.map((item) => {
          const simulated = distanceBetween(item.a, item.b);
          const hasReal = Number.isFinite(item.real_m) && item.real_m > 0;
          const error = hasReal ? simulated - item.real_m : null;
          return (
            <div key={item.id} className="space-y-1 rounded-md border border-line-dark p-2 text-xs">
              <div className="flex items-center gap-2">
                <input aria-label={`Tên đoạn ${item.id}`} className={FIELD} maxLength={80} value={item.label} disabled={!editable} onChange={(event) => updateDistance(item.id, { label: event.target.value })} />
                <button type="button" aria-label={`Xoá đoạn ${item.label}`} disabled={!editable} onClick={() => update({ distances: current.distances.filter((other) => other.id !== item.id) })} className="text-on-dark/70 hover:text-on-dark disabled:opacity-50">
                  <X className="size-4" />
                </button>
              </div>
              <p className="text-on-dark/60">A {formatPoint(item.a)} → B {formatPoint(item.b)}</p>
              <label className="flex items-center gap-2">
                <span className="shrink-0">Mét thật</span>
                <input aria-label={`Mét thật ${item.label}`} type="number" step="any" className={FIELD} value={shownNumber(item.real_m)} disabled={!editable} onChange={(event) => updateDistance(item.id, { real_m: numberOrNaN(event.target.value) })} />
              </label>
              <p>
                Trên scene: {simulated.toFixed(3)} m
                {error !== null && <> · sai số {error >= 0 ? "+" : ""}{error.toFixed(3)} m ({((error / item.real_m) * 100).toFixed(1)}%)</>}
              </p>
            </div>
          );
        })}
      </section>

      <section aria-label="Khe kiểm" className={SECTION}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Khe kiểm</h3>
          <Button size="sm" variant="ghost" disabled={!editable || !pickAvailable || pending !== null} onClick={() => startPick("gap")}>
            <Plus className="size-3.5" /> Thêm khe
          </Button>
        </div>
        {current.gaps.length === 0 && <p className="text-xs text-on-dark/60">Chưa có khe kiểm.</p>}
        {current.gaps.map((gap) => (
          <div key={gap.id} className="space-y-1 rounded-md border border-line-dark p-2 text-xs">
            <div className="flex items-center gap-2">
              <input aria-label={`Tên khe ${gap.id}`} className={FIELD} maxLength={80} value={gap.label} disabled={!editable} onChange={(event) => updateGap(gap.id, { label: event.target.value })} />
              <button type="button" aria-label={`Xoá khe ${gap.label}`} disabled={!editable} onClick={() => update({ gaps: current.gaps.filter((other) => other.id !== gap.id) })} className="text-on-dark/70 hover:text-on-dark disabled:opacity-50">
                <X className="size-4" />
              </button>
            </div>
            <p className="text-on-dark/60">Khoảng hai điểm: {distanceBetween(gap.a, gap.b).toFixed(3)} m</p>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex items-center gap-2">
                <span className="shrink-0">Bố trí</span>
                <select aria-label={`Bố trí của ${gap.label}`} className={FIELD} value={gap.layout} disabled={!editable} onChange={(event) => updateGap(gap.id, { layout: event.target.value as Layout })}>
                  <option value="A">A</option>
                  <option value="B">B</option>
                </select>
              </label>
              <label className="flex items-center gap-2">
                <span className="shrink-0">Bề rộng thật (m)</span>
                <input aria-label={`Bề rộng thật ${gap.label}`} type="number" step="any" className={FIELD} value={shownNumber(gap.real_width_m)} disabled={!editable} onChange={(event) => updateGap(gap.id, { real_width_m: event.target.value.trim() === "" ? null : numberOrNaN(event.target.value) })} />
              </label>
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" aria-label={`Ngoài đời robot qua được ${gap.label}`} checked={gap.real_passable} disabled={!editable} onChange={(event) => updateGap(gap.id, { real_passable: event.target.checked })} />
              Ngoài đời robot qua được
            </label>
          </div>
        ))}
      </section>

      <section aria-label="Vật cản chính" className={SECTION}>
        <h3 className="text-sm font-semibold">Vật cản chính</h3>
        {objects.length === 0 && <p className="text-xs text-on-dark/60">Scene chưa có vật nào.</p>}
        <ul className="space-y-1 text-xs">
          {objects.map((object) => (
            <li key={object.id}>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  aria-label={`Vật cản chính ${object.name}`}
                  checked={current.keyObstacleIds.includes(object.id)}
                  disabled={!editable}
                  onChange={(event) =>
                    update({
                      keyObstacleIds: event.target.checked
                        ? [...current.keyObstacleIds, object.id]
                        : current.keyObstacleIds.filter((id) => id !== object.id),
                    })
                  }
                />
                {object.name}
              </label>
            </li>
          ))}
        </ul>
        {missing.length > 0 && (
          <div role="alert" className="space-y-1 rounded-md border border-ochre/40 p-2 text-xs">
            <p>Đã chọn nhưng không còn trong scene: {missing.join(", ")}</p>
            {missing.map((id) => (
              <Button key={id} size="sm" variant="ghost" disabled={!editable} aria-label={`Bỏ chọn vật đã xoá (${id})`} onClick={() => update({ keyObstacleIds: current.keyObstacleIds.filter((other) => other !== id) })}>
                Bỏ chọn vật đã xoá ({id})
              </Button>
            ))}
          </div>
        )}
      </section>

      <section aria-label="Bố trí" className={SECTION}>
        <h3 className="text-sm font-semibold">Bố trí</h3>
        {(["A", "B"] as const).map((layout) => {
          const tagged = current.layouts[layout];
          const savedTag = saved.layouts[layout];
          const unsaved = JSON.stringify(tagged) !== JSON.stringify(savedTag);
          return (
            <div key={layout} className="flex items-center justify-between gap-2 text-xs">
              <span>
                {layout}: {tagged ? `revision ${tagged.scene_revision}` : "chưa gắn"}
                {tagged && savedTag && !unsaved && <> · máy chủ đặt lúc {new Date(savedTag.tagged_at).toLocaleString("vi-VN")}</>}
                {unsaved && <em className="text-ochre"> (chưa lưu)</em>}
              </span>
              <Button size="sm" variant="ghost" disabled={!editable} onClick={() => tagLayout(layout)}>
                Gắn revision hiện tại là {layout}
              </Button>
            </div>
          );
        })}
      </section>

      <section aria-label="Khác" className={SECTION}>
        <h3 className="text-sm font-semibold">Khác</h3>
        <label className="flex items-center gap-2 text-xs">
          Nguồn dữ liệu
          <select aria-label="Nguồn dữ liệu" className={FIELD} value={current.dataSource} disabled={!editable} onChange={(event) => update({ dataSource: event.target.value as BenchmarkTruth["data_source"] })}>
            {DATA_SOURCES.map((source) => (
              <option key={source.value} value={source.value}>{source.label}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={current.includeInBenchmark} disabled={!editable} onChange={(event) => update({ includeInBenchmark: event.target.checked })} />
          Đưa vào benchmark
        </label>
        <label className="flex items-center gap-2 text-xs">
          Mốc làm tay (phút)
          <input aria-label="Mốc làm tay (phút)" type="number" min={0} step="any" className={FIELD} value={current.manualBaselineMinutes} disabled={!editable} onChange={(event) => update({ manualBaselineMinutes: event.target.value })} />
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            aria-label="Khai báo L4"
            checked={current.l4 !== null}
            disabled={!editable}
            onChange={(event) => update({ l4: event.target.checked ? { layout_a_passed: false, layout_b_passed: false, matches_reality: false, evidence: "" } : null })}
          />
          Khai báo L4
        </label>
        {l4 && (
          <div className="space-y-1 rounded-md border border-line-dark p-2 text-xs">
            <label className="flex items-center gap-2"><input type="checkbox" checked={l4.layout_a_passed} disabled={!editable} onChange={(event) => update({ l4: { ...l4, layout_a_passed: event.target.checked } })} /> Bàn thử A: robot qua được</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={l4.layout_b_passed} disabled={!editable} onChange={(event) => update({ l4: { ...l4, layout_b_passed: event.target.checked } })} /> Bàn thử B: robot qua được</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={l4.matches_reality} disabled={!editable} onChange={(event) => update({ l4: { ...l4, matches_reality: event.target.checked } })} /> Khớp với thực tế</label>
            <textarea aria-label="Bằng chứng L4" className={TEXTAREA} rows={2} maxLength={600} value={l4.evidence} disabled={!editable} onChange={(event) => update({ l4: { ...l4, evidence: event.target.value } })} />
          </div>
        )}
        <label className="block text-xs">
          Ghi chú
          <textarea aria-label="Ghi chú" className={TEXTAREA} rows={2} maxLength={2000} value={current.notes} disabled={!editable} onChange={(event) => update({ notes: event.target.value })} />
        </label>
      </section>

      {conflict && (
        <Notice tone="rust">
          <span>Người khác vừa sửa ground truth. Nhập liệu của bạn vẫn còn.</span>{" "}
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void reloadServer()}>Tải lại</Button>
        </Notice>
      )}
      {problems.length > 0 && (
        <ul role="alert" className="list-disc space-y-0.5 pl-4 text-xs text-rust">
          {problems.map((problem) => <li key={problem}>{problem}</li>)}
        </ul>
      )}
      {notice && <Notice tone={notice.tone === "rust" ? "rust" : "neutral"}>{notice.text}</Notice>}

      {confirmClose && (
        <div role="alertdialog" aria-label="Thay đổi chưa lưu" className="space-y-2 rounded-md border border-ochre/40 p-2 text-xs">
          <p>Còn thay đổi chưa lưu. Rời panel sẽ bỏ các thay đổi đó.</p>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => setConfirmClose(false)}>Ở lại</Button>
            <Button size="sm" variant="danger" onClick={onClose}>Bỏ thay đổi</Button>
          </div>
        </div>
      )}

      <div className="sticky bottom-0 flex items-center justify-between gap-2 border-t border-line-dark bg-viewport-deep/95 pt-3 text-xs">
        <span className="text-on-dark/60">{dirty ? "Có thay đổi chưa lưu" : "Đã khớp bản trên máy chủ"}</span>
        <Button size="sm" disabled={!canEdit || busy || !dirty || problems.length > 0} onClick={() => void save()}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Lưu
        </Button>
      </div>
    </Shell>
  );
}

function Shell({ children, onClose, title = "Benchmark", subtitle }: { children: ReactNode; onClose: () => void; title?: string; subtitle?: string }) {
  return (
    <section
      aria-label="Panel Benchmark"
      className="pointer-events-auto flex max-h-[calc(100vh-6rem)] w-96 max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-lg border border-line-dark bg-viewport-deep/90 text-on-dark shadow-2xl backdrop-blur-md"
    >
      <header className="flex items-start justify-between gap-2 border-b border-line-dark px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {subtitle && <p className="text-[11px] text-on-dark/60">{subtitle}</p>}
        </div>
        <button type="button" aria-label="Đóng panel Benchmark" onClick={onClose} className="text-on-dark/70 hover:text-on-dark">
          <X className="size-4" />
        </button>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">{children}</div>
    </section>
  );
}

function Field({ label, value, disabled, onChange }: { label: string; value: number; disabled: boolean; onChange: (value: number) => void }) {
  return (
    <label className="space-y-1">
      <span className="block text-on-dark/70">{label}</span>
      <input aria-label={label} type="number" step="any" className={FIELD} value={shownNumber(value)} disabled={disabled} onChange={(event) => onChange(numberOrNaN(event.target.value))} />
    </label>
  );
}
