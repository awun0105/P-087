"use client";

import { useCallback, useEffect, useState } from "react";

const PREFIX = "studio:draft:";
export function clearStudioDrafts(): void {
  try { for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key); } catch { /* Storage bị chặn: draft trong bộ nhớ vẫn dùng được. */ }
}
export function readDraft<T>(key: string, parse: (value: unknown) => T | null): T | null {
  try {
    const stored = sessionStorage.getItem(PREFIX + key);
    return stored ? parse(JSON.parse(stored)) : null;
  } catch { return null; }
}

/** Draft chỉ tồn tại trong tab; parser bắt buộc tại boundary storage. */
export function useSessionDraft<T>(key: string, initial: T, parse: (value: unknown) => T | null) {
  const [value, setValue] = useState<T>(initial);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const ready = loadedKey === key;
  useEffect(() => {
    const timer = setTimeout(() => {
      setValue(readDraft(key, parse) ?? initial);
      setLoadedKey(key);
    }, 0);
    return () => clearTimeout(timer);
    // Key phải đổi theo người dùng/nguồn; initial/parser là giá trị bootstrap.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    if (!ready) return;
    try { sessionStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch { /* Không chặn form khi storage hết/chặn. */ }
  }, [key, ready, value]);
  const clear = useCallback(() => {
    try { sessionStorage.removeItem(PREFIX + key); } catch { /* Memory draft sẽ mất khi rời form. */ }
  }, [key]);
  return { value, setValue, ready, clear };
}
