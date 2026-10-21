"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DEFAULT_SCENARIO, GEOMETRY_REVIEW_KEY, type PresetKey } from "@/features/studio/ProcessingSettings";
import { evaluateProcessing, getProcessingOptions, suggestProcessingPreset } from "@/lib/api/studio";
import type { ParamValue, ProcessingEvaluation, ProcessingOptions, ScenarioPreferences, VideoFacts } from "@/lib/contracts/studio";
import type { VideoStreamMetadata } from "@/lib/contracts/videoPreparation";
import { errorMessage } from "@/lib/ui-error";

/** Đối chiếu draft với schema hiện hành trước khi gửi evaluate/create. */
export function restoreProcessing(options: ProcessingOptions, draft: Record<string, ParamValue>): Record<string, ParamValue> {
  const values = { ...options.presets.minimum_quality };
  for (const parameter of options.parameters) {
    const value = draft[parameter.key];
    if (parameter.kind === "choice") {
      if (typeof value === "string" && parameter.choices?.some((choice) => choice.value === value)) values[parameter.key] = value;
    } else if (typeof value === "number" && Number.isFinite(value) && (parameter.kind !== "integer" || Number.isInteger(value)) &&
      (parameter.min === null || value >= parameter.min) && (parameter.max === null || value <= parameter.max)) values[parameter.key] = value;
  }
  return values;
}

const EVALUATE_DELAY_MS = 300;

/** Thời lượng và độ phân giải từ `observed_video` do server đo; số không hợp lệ thì không gửi (null). */
export function videoFactsFromObserved(video: VideoStreamMetadata | null | undefined): VideoFacts | null {
  if (!video || !video.time_base?.denominator) return null;
  const duration = video.duration_ticks * video.time_base.numerator / video.time_base.denominator;
  if (!Number.isFinite(duration) || duration <= 0 || video.display_width < 16 || video.display_height < 16) return null;
  const rate = video.frame_rate && video.frame_rate.denominator ? video.frame_rate.numerator / video.frame_rate.denominator : null;
  return {
    duration_seconds: duration,
    display_width: video.display_width,
    display_height: video.display_height,
    frame_rate: rate !== null && Number.isFinite(rate) && rate > 0 ? rate : null,
  };
}

function samePreset(values: Record<string, ParamValue>, preset: Record<string, ParamValue>): boolean {
  return Object.keys(preset).every((key) => values[key] === preset[key]);
}

/** Khớp preset theo thông số chất lượng. Lựa chọn duyệt tách vật là radio riêng nên không tính. */
function matchesPreset(values: Record<string, ParamValue>, preset: Record<string, ParamValue>): boolean {
  return Object.keys(preset).every((key) => key === GEOMETRY_REVIEW_KEY || values[key] === preset[key]);
}

/** Preset và kịch bản không ghi đè lựa chọn duyệt tách vật người dùng đang giữ. */
function keepReviewChoice(next: Record<string, ParamValue>, current: Record<string, ParamValue> | null): Record<string, ParamValue> {
  const choice = current?.[GEOMETRY_REVIEW_KEY];
  return choice === undefined || !(GEOMETRY_REVIEW_KEY in next) ? next : { ...next, [GEOMETRY_REVIEW_KEY]: choice };
}

/**
 * State của bảng thông số: nạp options từ backend, bắt đầu ở preset tối thiểu,
 * gọi ước lượng tài nguyên (debounce, hủy request cũ) mỗi khi giá trị đổi.
 * Giá trị chỉ là state form tạm thời; nguồn sự thật là config backend của job.
 *
 * `auto.suggest` (bước cấu hình đang mở với tuyến video): tự gọi gợi ý với kịch bản mặc định và `auto.video`, nên
 * giá trị khởi đầu là gợi ý theo video thật chứ không phải preset tối thiểu. Có draft khôi phục thì giữ draft;
 * mọi lần đổi kịch bản vẫn gửi `auto.video`.
 */
export function useProcessingForm(
  enabled: boolean,
  restored?: Record<string, ParamValue> | null,
  draftReady = true,
  auto?: { video?: VideoFacts | null; suggest?: boolean },
) {
  const [options, setOptions] = useState<ProcessingOptions | null>(null);
  const [values, setValues] = useState<Record<string, ParamValue> | null>(null);
  const [evaluation, setEvaluation] = useState<ProcessingEvaluation | null>(null);
  const [evaluatedKey, setEvaluatedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const pending = useRef<AbortController | null>(null);
  const pendingSuggestion = useRef<AbortController | null>(null);
  const suggestedKey = useRef<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [scenarioPreset, setScenarioPreset] = useState<string | null>(null);
  const [scenarioPreferences, setScenarioPreferences] = useState<ScenarioPreferences | null>(null);
  const [scenarioNotes, setScenarioNotes] = useState<string[]>([]);
  const video = auto?.video ?? null;
  const videoKey = JSON.stringify(video);
  const videoRef = useRef<VideoFacts | null>(video);
  const autoKey = useRef<string | null>(null);
  useEffect(() => { videoRef.current = video; });
  const applied = useRef(false);
  useEffect(() => {
    if (!options || !draftReady || applied.current) return;
    // Chỉ công bố values sau khi đối chiếu draft; tránh parent ghi preset mặc định đè draft.
    const timer = setTimeout(() => {
      applied.current = true;
      const next = restored ? restoreProcessing(options, restored) : { ...options.presets.minimum_quality };
      setValues(next);
      if (samePreset(next, options.presets.minimum_quality)) {
        setEvaluation(options.default_evaluation);
        setEvaluatedKey(JSON.stringify(next));
      }
    }, 0);
    return () => clearTimeout(timer);
  }, [options, restored, draftReady]);

  useEffect(() => {
    if (!enabled || options) return;
    let alive = true;
    void getProcessingOptions().then((result) => {
      if (!alive) return;
      if (!result.ok) {
        setError(errorMessage(result.error));
        return;
      }
      setOptions(result.data);
    });
    return () => {
      alive = false;
    };
  }, [enabled, options, retryKey]);

  useEffect(() => {
    if (!values || !options) return;
    // Đã có ước lượng đúng cho bộ giá trị này (gợi ý hoặc ước lượng mặc định của options): không gọi lại.
    if (suggestedKey.current === JSON.stringify(values) || evaluatedKey === JSON.stringify(values)) return;
    const timer = setTimeout(() => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;
      setEvaluating(true);
      void evaluateProcessing(values, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        setEvaluating(false);
        if (result.ok) { setEvaluation(result.data); setEvaluatedKey(JSON.stringify(values)); setError(null); }
        else { setEvaluation(null); setEvaluatedKey(null); setError(errorMessage(result.error)); }
      });
    }, EVALUATE_DELAY_MS);
    return () => { clearTimeout(timer); pending.current?.abort(); };
  }, [values, options, retryKey, evaluatedKey]);

  useEffect(() => () => { pending.current?.abort(); pendingSuggestion.current?.abort(); }, []);

  const [selectedPreset, setSelectedPreset] = useState<PresetKey | null>(null);

  const setValue = useCallback((key: string, value: ParamValue) => {
    suggestedKey.current = null;
    pendingSuggestion.current?.abort();
    setSuggesting(false);
    setScenarioPreset(null);
    setScenarioNotes([]);
    setError(null);
    setSelectedPreset(null);
    setValues((current) => (current ? { ...current, [key]: value } : current));
  }, []);

  const applyPreset = useCallback(
    (preset: PresetKey) => {
      if (options) { 
        suggestedKey.current = null;
        pendingSuggestion.current?.abort();
        setSuggesting(false);
        setScenarioPreset(null);
        setScenarioNotes([]);
        setError(null); 
        setSelectedPreset(preset);
        setValues(keepReviewChoice({ ...options.presets[preset] }, values)); 
      }
    },
    [options, values],
  );

  const applyScenario = useCallback(async (preferences: ScenarioPreferences) => {
    if (!options) return;
    pendingSuggestion.current?.abort();
    pending.current?.abort();
    setEvaluating(false);
    const controller = new AbortController();
    pendingSuggestion.current = controller;
    setSuggesting(true);
    setScenarioPreferences(preferences);
    setError(null);
    // Bộ ảnh không có video; video thì luôn gửi thời lượng/độ phân giải thật để bộ gợi ý không đoán.
    const request: ScenarioPreferences = preferences.input_type === "photo_set"
      ? { ...preferences, video: null, photo_count: preferences.photo_count ?? null }
      : { ...preferences, video: videoRef.current };
    const result = await suggestProcessingPreset(request, controller.signal);
    if (controller.signal.aborted) return;
    setSuggesting(false);
    if (!result.ok) { setError(errorMessage(result.error)); return; }
    const normalized = restoreProcessing(options, result.data.params);
    if (Object.keys(result.data.params).length !== options.parameters.length ||
        options.parameters.some((spec) => normalized[spec.key] !== result.data.params[spec.key])) {
      setError("Gợi ý cấu hình không khớp thông số hiện hành. Hãy tải lại trang.");
      return;
    }
    setSelectedPreset(null);
    setScenarioPreset(result.data.preset_name);
    setScenarioNotes(result.data.notes ?? []);
    // Ước lượng tài nguyên không đọc lựa chọn duyệt tách vật (processing/resources.py), nên dùng lại ước lượng của kịch bản.
    const next = keepReviewChoice(normalized, values);
    suggestedKey.current = JSON.stringify(next);
    setValues(next);
    setEvaluation(result.data.evaluation);
    setEvaluatedKey(JSON.stringify(next));
  }, [options, values]);

  useEffect(() => {
    if (!auto?.suggest || !options || !values || restored || autoKey.current === videoKey) return;
    // Đổi video sau khi người dùng đã tự chỉnh thông số thì không ghi đè phần đã chỉnh.
    if (autoKey.current !== null && scenarioPreset === null) return;
    autoKey.current = videoKey;
    void applyScenario(scenarioPreferences ?? DEFAULT_SCENARIO);
  }, [auto?.suggest, options, values, restored, videoKey, scenarioPreset, scenarioPreferences, applyScenario]);

  let activePreset: PresetKey | null = null;
  if (options && values) {
    if (selectedPreset && matchesPreset(values, options.presets[selectedPreset])) {
      activePreset = selectedPreset;
    } else if (matchesPreset(values, options.presets.minimum_quality)) {
      activePreset = "minimum_quality";
    } else if (matchesPreset(values, options.presets.machine_maximum)) {
      activePreset = "machine_maximum";
    }
  }

  const retry = () => { suggestedKey.current = null; setError(null); setRetryKey((key) => key + 1); };
  return { options, values, evaluation: values && JSON.stringify(values) === evaluatedKey ? evaluation : null, error, loading: !options && !error, evaluating: suggesting || evaluating || !!(options && values && JSON.stringify(values) !== evaluatedKey && !error), suggesting, scenarioPreset, scenarioPreferences, scenarioNotes, activePreset, setValue, applyPreset, applyScenario, retry };
}
