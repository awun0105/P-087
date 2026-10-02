/** Bridge same-origin; timeout/abort giữ trạng thái UNKNOWN thay vì giả sạch. */
export function queryEditorDirty(frame: Window, signal?: AbortSignal): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const finish = (value?: boolean) => {
      clearTimeout(timer);
      window.removeEventListener("message", receive);
      signal?.removeEventListener("abort", abort);
      if (value === undefined) reject(new Error("Chưa kiểm tra được trạng thái editor."));
      else resolve(value);
    };
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame) return;
      if (event.data?.type === "supersplat:is-scene-dirty" && typeof event.data.result === "boolean") finish(event.data.result);
    };
    const abort = () => finish();
    const timer = window.setTimeout(abort, 1500);
    window.addEventListener("message", receive);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    else {
      try { frame.postMessage({ type: "supersplat:is-scene-dirty" }, window.location.origin); }
      catch { finish(); }
    }
  });
}
