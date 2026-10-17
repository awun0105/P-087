import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GaussianMembershipEditor } from "@/features/studio/GaussianMembershipEditor";
import * as api from "@/lib/api/studio";
import type { SceneIR } from "@/lib/contracts/api";

vi.mock("@/lib/api/studio", () => ({ previewMembership: vi.fn(), regenerateMembership: vi.fn(), getObjectifyState: vi.fn(), cancelObjectify: vi.fn() }));
const checksum = "sha256:" + "a".repeat(64);
const reference = { artifact_type: "GaussianPLY", artifact_uri: "artifact://jobs/job-a/source.ply", artifact_checksum: checksum };
// This component reads only membership/owner identity, never poses for selection.
const scene = { scene_revision: "rev-012", environment: { membership: {
  source_visual_ref: reference, gaussian_count: 5, labels_ref: { artifact_checksum: checksum },
  label_to_object_id: { "0": "object-a", "1": "object-b" },
} }, objects: [{ id: "object-a", name: "Bàn", provenance: {} }, { id: "object-b", name: "Ghế", provenance: {} }] } as unknown as SceneIR;
const preview = { scene_revision: "rev-012", source_visual_checksum: checksum, membership_checksum: checksum, source_object_id: "object-a", target_object_id: null, affected_object_ids: ["object-a"], gaussian_count: 1, source_gaussian_indices: [2], protected_count: 1, wrong_owner_count: 0, remaining_gaussians: { "object-a": 100 } };
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers(); });
async function select() {
  const iframe = screen.getByTitle("SuperSplat chọn Gaussian nguồn") as HTMLIFrameElement;
  const post = vi.spyOn(iframe.contentWindow!, "postMessage");
  fireEvent.click(screen.getByText("Xem trước vùng chọn"));
  const request = post.mock.calls.at(-1)![0] as { requestId: number };
  await act(async () => { window.dispatchEvent(new MessageEvent("message", {
    source: iframe.contentWindow, origin: window.location.origin,
    data: { type: "supersplat:source-selection", requestId: request.requestId, checksum, rows: [1, 2] },
  })); });
  return iframe;
}
describe("Gaussian membership preview/apply", () => {
  it("previews source rows without mutation, then queues the exact reviewed command", async () => {
    vi.mocked(api.previewMembership).mockResolvedValue(preview);
    vi.mocked(api.regenerateMembership).mockResolvedValue({ status: "queued", mode: "membership", base_revision: "rev-012" } as api.ObjectifyState);
    render(<GaussianMembershipEditor jobId="job-a" scene={scene} objectId="object-a" onClose={vi.fn()} onPublished={vi.fn()} />);
    const iframe = await select();
    expect(api.previewMembership).toHaveBeenCalledWith("job-a", expect.objectContaining({ expected_scene_revision: "rev-012", source_gaussian_indices: [1, 2], source_visual_checksum: checksum }));
    expect(api.regenerateMembership).not.toHaveBeenCalled();
    expect(iframe.style.pointerEvents).toBe("none");
    expect(screen.getByText(/1 Gaussian: object-a/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Apply và tái tạo"));
    await waitFor(() => expect(api.regenerateMembership).toHaveBeenCalledWith("job-a", vi.mocked(api.previewMembership).mock.calls[0][1]));
    vi.mocked(api.cancelObjectify).mockResolvedValue({ status: "cancelled" } as api.ObjectifyState);
    fireEvent.click(await screen.findByText("Hủy tái tạo"));
    await waitFor(() => expect(api.cancelObjectify).toHaveBeenCalledWith("job-a", undefined));
  });
  it("keeps Apply unavailable when preview fails; foreign iframe messages are ignored", async () => {
    vi.mocked(api.previewMembership).mockRejectedValue(new Error("stale revision"));
    render(<GaussianMembershipEditor jobId="job-a" scene={scene} objectId="object-a" onClose={vi.fn()} onPublished={vi.fn()} />);
    window.dispatchEvent(new MessageEvent("message", { origin: "https://foreign.example", data: { type: "supersplat:source-selection", rows: [0] } }));
    expect(api.previewMembership).not.toHaveBeenCalled();
    await select();
    expect(screen.getByRole("alert")).toHaveTextContent("stale revision");
    expect(screen.queryByText("Apply và tái tạo")).not.toBeInTheDocument();
    expect(api.regenerateMembership).not.toHaveBeenCalled();
  });
  it("invalidates the preview when ownership changes", async () => {
    vi.mocked(api.previewMembership).mockResolvedValue(preview);
    render(<GaussianMembershipEditor jobId="job-a" scene={scene} objectId="object-a" onClose={vi.fn()} onPublished={vi.fn()} />);
    const iframe = await select();
    fireEvent.change(screen.getByLabelText("Đích Gaussian trực quan"), { target: { value: "object-b" } });
    expect(screen.queryByText("Apply và tái tạo")).not.toBeInTheDocument();
    expect(iframe.style.pointerEvents).toBe("auto");
  });
  it("loads the published revision only after the worker reports success", async () => {
    vi.mocked(api.previewMembership).mockResolvedValue(preview);
    vi.mocked(api.regenerateMembership).mockResolvedValue({ status: "queued", mode: "membership", base_revision: "rev-012" } as api.ObjectifyState);
    vi.mocked(api.getObjectifyState).mockResolvedValue({ status: "done", mode: "membership", base_revision: "rev-012", result_revision: "rev-013" } as api.ObjectifyState);
    const published = vi.fn();
    render(<GaussianMembershipEditor jobId="job-a" scene={scene} objectId="object-a" onClose={vi.fn()} onPublished={published} />);
    await select();
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByText("Apply và tái tạo")); });
    expect(published).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(published).toHaveBeenCalledOnce();
    expect(screen.getByText(/done.*rev-013/)).toBeInTheDocument();
  });

});
