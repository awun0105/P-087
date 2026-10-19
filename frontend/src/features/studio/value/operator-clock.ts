/**
 * Đồng hồ phút công người (architecture §15.3 quy tắc 1). Thuần: mọi thời điểm truyền từ ngoài vào (ms epoch),
 * nên test chạy được với thời gian giả. Máy chủ kiểm lại mọi luật; lô đây luôn thoả trước để không bị từ chối.
 */

import type { OperatorTimeBatch, OperatorTimeSurface } from "@/lib/api/value";

/** Không có thao tác trong khoảng này thì thời gian không được tính. */
export const IDLE_LIMIT_MS = 60_000;
/** Mỗi lô đóng sau khoảng này; luôn nhỏ hơn giới hạn 300 s của máy chủ. */
export const BATCH_WINDOW_MS = 30_000;
/** Giới hạn cứng của một lô theo máy chủ. */
export const MAX_BATCH_MS = 300_000;
/** Một nhịp tối đa được cộng; chặn trường hợp tab bị khựng rồi cộng dồn cả khoảng dài. */
export const MAX_TICK_MS = 2_000;

export class OperatorClock {
  private startedAt: number | null = null;
  private lastTick = 0;
  private activeMs = 0;
  private lastActivity = Number.NEGATIVE_INFINITY;

  constructor(
    private readonly sessionKey: string,
    private readonly surface: OperatorTimeSurface,
  ) {}

  get running(): boolean {
    return this.startedAt !== null;
  }

  start(now: number): void {
    this.startedAt = now;
    this.lastTick = now;
    this.activeMs = 0;
  }

  activity(now: number): void {
    this.lastActivity = now;
  }

  /** Cộng thời gian của nhịp vừa qua nếu người dùng có thao tác trong 60 s gần nhất. */
  tick(now: number): void {
    if (this.startedAt === null) return;
    const elapsed = Math.min(Math.max(now - this.lastTick, 0), MAX_TICK_MS);
    this.lastTick = now;
    if (now - this.lastActivity <= IDLE_LIMIT_MS) this.activeMs += elapsed;
  }

  due(now: number): boolean {
    return this.startedAt !== null && now - this.startedAt >= BATCH_WINDOW_MS;
  }

  /** Đóng cửa sổ tại `now` và mở cửa sổ kế tiếp ngay từ thời điểm kết thúc, nên các lô không chồng nhau. */
  cut(now: number): OperatorTimeBatch | null {
    if (this.startedAt === null) return null;
    const started = this.startedAt;
    const ended = Math.min(now, started + MAX_BATCH_MS);
    const duration = ended - started;
    const active = Math.min(this.activeMs, duration);
    this.startedAt = ended;
    this.lastTick = now;
    this.activeMs = 0;
    if (active <= 0) return null;
    return {
      session_key: this.sessionKey,
      surface: this.surface,
      started_at: new Date(started).toISOString(),
      ended_at: new Date(ended).toISOString(),
      active_seconds: active / 1000,
    };
  }

  /** Đóng hẳn đồng hồ (tab ẩn, rời trang, đổi tab): trả lô cuối rồi ngừng đếm. */
  close(now: number): OperatorTimeBatch | null {
    const batch = this.cut(now);
    this.startedAt = null;
    return batch;
  }
}
