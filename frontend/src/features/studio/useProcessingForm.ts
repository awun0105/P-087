"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { PresetKey } from "@/features/studio/ProcessingSettings";
import { evaluateProcessing, getProcessingOptions } from "@/lib/api/studio";
import type { ParamValue, ProcessingEvaluation, ProcessingOptions } from "@/lib/contracts/studio";

const EVALUATE_DELAY_MS = 300;

function samePreset(values: Record<string, ParamValue>, preset: Record<string, ParamValue>): boolean {
  return Object.keys(preset).every((key) => values[key] === preset[key]);
}

/**
 * State của bảng thông số: nạp options từ backend, bắt đầu ở preset tối thiểu,
 * gọi ước lượng tài nguyên (debounce, hủy request cũ) mỗi khi giá trị đổi.
 * Giá trị chỉ là state form tạm thời; nguồn sự thật là config backend của job.
 */
export function useProcessingForm(enabled: boolean) {
  const [options, setOptions] = useState<ProcessingOptions | null>(null);
  const [values, setValues] = useState<Record<string, ParamValue> | null>(null);
  const [evaluation, setEvaluation] = useState<ProcessingEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    void getProcessingOptions().then((result) => {
      if (!alive) return;
      if (!result.ok) {
        setError(result.error.detail);
        return;
      }
      setOptions(result.data);
      setValues({ ...result.data.presets.minimum_quality });
      setEvaluation(result.data.default_evaluation);
    });
    return () => {
      alive = false;
    };
  }, [enabled]);

  useEffect(() => {
    if (!values || !options) return;
    const timer = setTimeout(() => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;
      setEvaluating(true);
      void evaluateProcessing(values, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        setEvaluating(false);
        if (result.ok) setEvaluation(result.data);
      });
    }, EVALUATE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [values, options]);

  useEffect(() => () => pending.current?.abort(), []);

  const setValue = useCallback((key: string, value: ParamValue) => {
    setValues((current) => (current ? { ...current, [key]: value } : current));
  }, []);

  const applyPreset = useCallback(
    (preset: PresetKey) => {
      if (options) setValues({ ...options.presets[preset] });
    },
    [options],
  );

  let activePreset: PresetKey | null = null;
  if (options && values) {
    if (samePreset(values, options.presets.minimum_quality)) activePreset = "minimum_quality";
    else if (samePreset(values, options.presets.machine_maximum)) activePreset = "machine_maximum";
  }

  return { options, values, evaluation, error, evaluating, activePreset, setValue, applyPreset };
}
