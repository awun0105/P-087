/** Bind once per isolated demo document so late async work cannot fall back to real-job APIs. */
const frameSession = typeof window === "undefined" ? null
  : /^\/demo-workspace\/([a-f0-9]{32})\/?$/.exec(window.location.pathname)?.[1] ?? null;

export function demoSessionId(): string | null {
  return frameSession;
}

export function demoApiPath(path: string): string {
  const session = demoSessionId();
  return session && path.startsWith("/api/v1/") && !path.startsWith("/api/v1/demo-sessions/")
    ? `/api/v1/demo-sessions/${session}${path}` : path;
}

export function demoSceneHref(stage: string | null, tab = "progress"): string | null {
  if (!demoSessionId()) return null;
  const url = new URL(window.location.href);
  url.pathname = `/demo-workspace/${frameSession}`;
  if (stage) url.searchParams.set("stage", stage);
  else url.searchParams.delete("stage");
  url.searchParams.set("tab", tab);
  url.searchParams.delete("view");
  return url.pathname + url.search;
}
