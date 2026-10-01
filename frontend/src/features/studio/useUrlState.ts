"use client";

import { useCallback, useEffect, useState } from "react";

/** Native history được Next hỗ trợ; giữ component/GPU sống khi đổi query. */
export function useUrlState() {
  // Server và lần hydrate đầu phải cùng snapshot; đọc query sau mount tránh mismatch.
  const [query, setQuery] = useState("");
  useEffect(() => {
    const sync = () => setQuery(window.location.search);
    window.addEventListener("popstate", sync);
    window.addEventListener("studio:url", sync);
    sync();
    return () => { window.removeEventListener("popstate", sync); window.removeEventListener("studio:url", sync); };
  }, []);
  const update = useCallback((values: Record<string, string | null>, replace = false) => {
    const url = new URL(window.location.href);
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === "") url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    }
    window.history[replace ? "replaceState" : "pushState"](null, "", url.pathname + url.search + url.hash);
    window.dispatchEvent(new Event("studio:url"));
  }, []);
  return { params: new URLSearchParams(query), update };
}
