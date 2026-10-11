/** ADAPT SuperSplat command-queue.ts/edit-history.ts (MIT, xem THIRD_PARTY_NOTICES.md).
 * Chỉ giữ lịch sử inspection tạm thời; không thay backend revision hoặc approval.
 */
export class InspectionHistory<T> {
  private states: T[];
  private cursor = 0;
  private tail: Promise<void> = Promise.resolve();

  constructor(initial: T, private readonly apply: (value: T) => void) {
    this.states = [initial];
  }

  get current(): T { return this.states[this.cursor]; }
  get canUndo(): boolean { return this.cursor > 0; }
  get canRedo(): boolean { return this.cursor + 1 < this.states.length; }

  /** FIFO: GPU pick và undo/redo không được hoàn tất sai thứ tự người dùng. */
  enqueue<R>(operation: () => R | Promise<R>): Promise<R> {
    const next = this.tail.then(operation);
    // Caller vẫn nhận rejection, nhưng một lỗi không làm hỏng toàn bộ queue.
    this.tail = next.then(() => undefined, () => undefined);
    return next;
  }

  commit(value: T): void {
    this.apply(value);
    this.states = [...this.states.slice(0, this.cursor + 1), value].slice(-100);
    this.cursor = this.states.length - 1;
  }

  undo(): void {
    if (!this.canUndo) return;
    this.apply(this.states[this.cursor - 1]);
    this.cursor -= 1;
  }

  redo(): void {
    if (!this.canRedo) return;
    this.apply(this.states[this.cursor + 1]);
    this.cursor += 1;
  }

  idle(): Promise<void> { return this.tail; }
}

export type InspectionPoint = readonly [number, number, number];

export interface InspectionState {
  measuring: boolean;
  points: readonly InspectionPoint[];
  canUndo: boolean;
  canRedo: boolean;
  busy: boolean;
  error: string | null;
}

export const EMPTY_INSPECTION: InspectionState = {
  measuring: false, points: [], canUndo: false, canRedo: false, busy: false, error: null,
};

export function pointDistance(points: readonly InspectionPoint[]): number | null {
  if (points.length !== 2 || !points.every((point) => point.every(Number.isFinite))) return null;
  const [a, b] = points;
  const distance = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  return Number.isFinite(distance) ? distance : null;
}

export function proposedMetricScale(distance: number | null, realMeters: number): number | null {
  if (distance === null || distance <= 0 || !Number.isFinite(realMeters) || realMeters <= 0) return null;
  const factor = realMeters / distance;
  return Number.isFinite(factor) && factor > 0 ? factor : null;
}
