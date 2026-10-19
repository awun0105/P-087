import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { AnonymizationReviewPanel } from "@/features/studio/scene/AnonymizationReviewPanel";
import { progressSceneStatus } from "@/features/studio/sceneStatus";
import { isJobStale } from "@/features/studio/scene/state";
import { parseJobProgress, type JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/scene/AttemptHistory", () => ({ AttemptHistory: () => <div /> }));

const review = {
  state: "awaiting",
  frame_set_checksum: "sha256:" + "a".repeat(64),
  frame_count: 12,
  frames: [{ frame_name: "000004.png", width: 32, height: 24, regions: [{ kind: "face", box: [1, 1, 12, 12] }] }],
};

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AnonymizationReviewPanel", () => {
  it("shows the redacted frames and accepts exactly the frame set that was viewed", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return String(url).endsWith("/accept") ? respond({ acceptance: {} }) : respond(review);
    }));
    const onAccepted = vi.fn();
    render(<AnonymizationReviewPanel jobId="job-1" canAccept onAccepted={onAccepted} />);

    expect(await screen.findByText(/Đã che 1 trên 12 frame/)).toBeTruthy();
    expect(screen.getByRole("img").getAttribute("src")).toBe("/api/v1/jobs/job-1/anonymization/frames/000004.png");
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận và dựng 3D/ }));
    await waitFor(() => expect(onAccepted).toHaveBeenCalledTimes(1));
    const accept = calls.find((call) => call.url.endsWith("/accept"));
    expect(accept?.init?.method).toBe("POST");
    expect(JSON.parse(String(accept?.init?.body))).toEqual({ frame_set_checksum: review.frame_set_checksum });
  });

  it("offers no accept button to a viewer who cannot change the job, and reports a refused accept", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      String(url).endsWith("/accept") ? respond({ detail: "Bản đã che đã thay đổi" }, 409) : respond(review)));
    const { unmount } = render(<AnonymizationReviewPanel jobId="job-1" canAccept={false} onAccepted={() => undefined} />);
    await screen.findByText(/Đã che 1 trên 12 frame/);
    expect(screen.queryByRole("button", { name: /Xác nhận/ })).toBeNull();
    unmount();

    const onAccepted = vi.fn();
    render(<AnonymizationReviewPanel jobId="job-1" canAccept onAccepted={onAccepted} />);
    fireEvent.click(await screen.findByRole("button", { name: /Xác nhận và dựng 3D/ }));
    expect(await screen.findByText(/Bản đã che đã thay đổi/)).toBeTruthy();
    expect(onAccepted).not.toHaveBeenCalled();
  });
});

describe("anonymization review waiting state", () => {
  const waiting: JobProgress = {
    job_id: "job-1", status: "RUNNING", current_stage: "ST-FRAME-EXTRACT", attempt: 1,
    started_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", completed_at: null,
    preview_ready: false, error: null, waiting_for: "anonymization_review", stages: [],
  };

  it("is a user action, not a running or stale worker", () => {
    expect(progressSceneStatus(waiting)).toMatchObject({ label: "Cần xem bản đã che", active: false, group: "action" });
    expect(isJobStale(waiting, Date.parse("2026-01-02T00:00:00Z"))).toBe(false);
  });

  it("is accepted by the progress parser, which still rejects unknown reasons", () => {
    expect(parseJobProgress(waiting).waiting_for).toBe("anonymization_review");
    expect(() => parseJobProgress({ ...waiting, waiting_for: "something_else" })).toThrow();
  });

  it("replaces the queue message with the review panel and keeps cancel available", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(review)));
    const cancel = vi.fn();
    render(<ProgressTab jobId="job-1" progress={{ ...waiting, status: "QUEUED" }} info={null} busy={false} canCancel onCancel={cancel} />);
    expect(await screen.findByTestId("anonymization-review")).toBeTruthy();
    expect(screen.queryByText(/Job đã vào hàng đợi/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Huỷ xử lý" }));
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
