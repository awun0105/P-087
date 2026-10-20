import type { PlayCanvasRuntime } from "@/features/viewer/PlayCanvasScene";

/** Trường đổi liên tục (mỗi khung khi phát quỹ đạo hoặc đang tải): báo cho giao diện theo nhịp, không theo từng khung. */
const FAST_FIELDS = new Set<keyof PlayCanvasRuntime>(["animationTime", "progress"]);

export interface RuntimePublisher {
  (next: PlayCanvasRuntime): void;
  dispose(): void;
}

/**
 * T-064: gói `emit` để `animationTime`/`progress` báo tối đa một lần mỗi `intervalMs` (mặc định 250 ms = 4 lần/giây), luôn kết
 * thúc ở giá trị cuối; trường khác (loaded, cameraMode, walkAllowed…) đổi thì báo ngay kèm giá trị mới nhất.
 */
export function createRuntimePublisher(emit: (next: PlayCanvasRuntime) => void, intervalMs = 250): RuntimePublisher {
  let last: PlayCanvasRuntime | null = null;
  let pending: PlayCanvasRuntime | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastEmitAt = -Infinity;

  const flush = () => {
    timer = undefined;
    if (!pending) return;
    const value = pending;
    pending = null;
    last = value;
    lastEmitAt = Date.now();
    emit(value);
  };

  const publish = ((next: PlayCanvasRuntime) => {
    const onlyFast = last !== null
      && (Object.keys(next) as (keyof PlayCanvasRuntime)[]).every((key) => FAST_FIELDS.has(key) || next[key] === last![key]);
    pending = next;
    if (!onlyFast) {
      if (timer !== undefined) clearTimeout(timer);
      flush();
      return;
    }
    if (timer !== undefined) return;
    timer = setTimeout(flush, Math.max(0, lastEmitAt + intervalMs - Date.now()));
  }) as RuntimePublisher;
  publish.dispose = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    pending = null;
  };
  return publish;
}
