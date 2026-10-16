/**
 * Gửi sự kiện giá trị lên máy chủ (architecture §15.3): thời gian thao tác của người dùng và phiên Walk.
 *
 * Lỗi không bao giờ làm phiền người dùng: hàm không ném lỗi. Lỗi mạng hoặc 5xx được thử lại đúng một lần;
 * lỗi 4xx (lô vi phạm luật máy chủ) bỏ qua ngay. Các lô cùng phiên được gửi tuần tự để máy chủ nhận đúng thứ tự,
 * vì máy chủ từ chối lô chồng lên lô trước của cùng `session_key`.
 */

const API = "/api/v1/jobs";

export type OperatorTimeSurface = "studio" | "progress" | "evaluation" | "other";

export interface OperatorTimeBatch {
  session_key: string;
  surface: OperatorTimeSurface;
  started_at: string;
  ended_at: string;
  active_seconds: number;
}

export interface WalkSessionBatch {
  scene_revision: string;
  started_at: string;
  ended_at: string;
  outcome: "completed" | "aborted";
}

export interface SendOptions {
  /** `keepalive` giữ request sống khi trang đóng hoặc tab ẩn. */
  keepalive?: boolean;
}

class SendError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

/** Hàng đợi chung: mọi lô gửi lần lượt, lô sau không vượt lô trước. Không bao giờ reject. */
let queue: Promise<void> = Promise.resolve();

function retryable(error: unknown): boolean {
  if (!(error instanceof SendError)) return true; // lỗi mạng: fetch ném TypeError
  return error.status === 0 || error.status >= 500;
}

async function sendOnce(path: string, body: unknown, options: SendOptions): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      keepalive: options.keepalive ?? false,
    });
  } catch {
    throw new SendError(0);
  }
  if (!response.ok) throw new SendError(response.status);
}

async function sendWithOneRetry(path: string, body: unknown, options: SendOptions): Promise<void> {
  try {
    await sendOnce(path, body, options);
  } catch (error) {
    if (!retryable(error)) return;
    try {
      await sendOnce(path, body, options);
    } catch {
      // Bỏ qua lô: không thử lại thêm, không báo lỗi cho người dùng.
    }
  }
}

function enqueue(path: string, body: unknown, options: SendOptions): Promise<void> {
  const next = queue.then(() => sendWithOneRetry(path, body, options));
  queue = next;
  return next;
}

export function postOperatorTime(jobId: string, batch: OperatorTimeBatch, options: SendOptions = {}): Promise<void> {
  return enqueue(`/${encodeURIComponent(jobId)}/value-events/operator-time`, batch, options);
}

export function postWalkSession(jobId: string, session: WalkSessionBatch, options: SendOptions = {}): Promise<void> {
  return enqueue(`/${encodeURIComponent(jobId)}/value-events/walk-session`, session, options);
}
