"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { PresetKey } from "@/features/studio/ProcessingSettings";
import { evaluateProcessing, getProcessingOptions, suggestProcessingPreset } from "@/lib/api/studio";
import type { ParamValue, ProcessingEvaluation, ProcessingOptions, ScenarioPreferences } from "@/lib/contracts/studio";
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

function samePreset(values: Record<string, ParamValue>, preset: Record<string, ParamValue>): boolean {
  return Object.keys(preset).every((key) => values[key] === preset[key]);
}

/**
 * State của bảng thông số: nạp options từ backend, bắt đầu ở preset tối thiểu,
 * gọi ước lượng tài nguyên (debounce, hủy request cũ) mỗi khi giá trị đổi.
 * Giá trị chỉ là state form tạm thời; nguồn sự thật là config backend của job.
 */
export function useProcessingForm(enabled: boolean, restored?: Record<string, ParamValue> | null, draftReady = true) {
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
    if (suggestedKey.current === JSON.stringify(values)) return;
    const timer = setTimeout(() => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;
      setEvaluating(true);
      void evaluateProcessing(values, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        setEvaluating(false);
        if (result.ok) { setEvaluation(result.data); setEvaluatedKey(JSON.stringify(values)); setError(null); }
        else { setEvaluation(null); setError(errorMessage(result.error)); }
      });
    }, EVALUATE_DELAY_MS);
    return () => { clearTimeout(timer); pending.current?.abort(); };
  }, [values, options, retryKey]);

  useEffect(() => () => { pending.current?.abort(); pendingSuggestion.current?.abort(); }, []);

  const [selectedPreset, setSelectedPreset] = useState<PresetKey | null>(null);

  const setValue = useCallback((key: string, value: ParamValue) => {
    suggestedKey.current = null;
    pendingSuggestion.current?.abort();
    setSuggesting(false);
    setScenarioPreset(null);
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
        setError(null); 
        setSelectedPreset(preset);
        setValues({ ...options.presets[preset] }); 
      }
    },
    [options],
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
    const result = await suggestProcessingPreset(preferences, controller.signal);
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
    suggestedKey.current = JSON.stringify(normalized);
    setValues(normalized);
    setEvaluation(result.data.evaluation);
    setEvaluatedKey(JSON.stringify(normalized));
  }, [options]);

  let activePreset: PresetKey | null = null;
  if (options && values) {
    if (selectedPreset && samePreset(values, options.presets[selectedPreset])) {
      activePreset = selectedPreset;
    } else if (samePreset(values, options.presets.minimum_quality)) {
      activePreset = "minimum_quality";
    } else if (samePreset(values, options.presets.machine_maximum)) {
      activePreset = "machine_maximum";
    }
  }

  const retry = () => { suggestedKey.current = null; setError(null); setRetryKey((key) => key + 1); };
  return { options, values, evaluation: values && JSON.stringify(values) === evaluatedKey ? evaluation : null, error, loading: !options && !error, evaluating: suggesting || evaluating || !!(options && values && JSON.stringify(values) !== evaluatedKey && !error), suggesting, scenarioPreset, scenarioPreferences, activePreset, setValue, applyPreset, applyScenario, retry };
}
