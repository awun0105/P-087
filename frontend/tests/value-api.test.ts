/** Client sự kiện giá trị: không bao giờ reject, thử lại đúng một lần khi lỗi mạng/5xx, lô gửi theo thứ tự. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { postOperatorTime, postWalkSession, type OperatorTimeBatch } from "@/lib/api/value";

const batch: OperatorTimeBatch = {
  session_key: "session-abcdef12",
  surface: "studio",
  started_at: "2026-10-16T09:00:00.000Z",
  ended_at: "2026-10-16T09:00:30.000Z",
  active_seconds: 12.5,
};

function response(status: number): Response {
  return new Response(status === 204 ? null : "{}", { status });
}

describe("value event client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => response(204));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the operator batch as JSON with keepalive and accepts 204", async () => {
    await postOperatorTime("job-1", batch, { keepalive: true });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/jobs/job-1/value-events/operator-time");
    expect(init.method).toBe("POST");
    expect(init.keepalive).toBe(true);
    expect(JSON.parse(String(init.body))).toEqual(batch);
  });

  it("retries a network failure once and then gives up silently", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(postWalkSession("job-1", { scene_revision: "rev-001", started_at: batch.started_at, ended_at: batch.ended_at, outcome: "completed" })).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries a 5xx once and does not retry a 422 batch", async () => {
    fetchMock.mockResolvedValueOnce(response(500)).mockResolvedValueOnce(response(204));
    await postOperatorTime("job-1", batch);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(response(422));
    await expect(postOperatorTime("job-1", batch)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends batches one after another, never overlapping in flight", async () => {
    const order: string[] = [];
    let release: () => void = () => {};
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      const name = JSON.parse(String(init.body)).ended_at;
      order.push(`start ${name}`);
      if (name === batch.ended_at) await new Promise<void>((resolve) => (release = resolve));
      order.push(`end ${name}`);
      return response(204);
    });

    const first = postOperatorTime("job-1", batch);
    const second = postOperatorTime("job-1", { ...batch, started_at: batch.ended_at, ended_at: "2026-10-16T09:01:00.000Z" });
    await Promise.resolve();
    expect(order).toEqual([`start ${batch.ended_at}`]);
    release();
    await Promise.all([first, second]);
    expect(order).toEqual([
      `start ${batch.ended_at}`,
      `end ${batch.ended_at}`,
      "start 2026-10-16T09:01:00.000Z",
      "end 2026-10-16T09:01:00.000Z",
    ]);
  });
});
