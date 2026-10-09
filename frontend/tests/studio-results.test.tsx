/** Candidate/release luôn gắn revision; fixture này chỉ chứng minh UI gate. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResultsTab } from "@/features/studio/scene/ResultsTab";
import { ApiError } from "@/lib/api/client";
import { getJobScene, getReviewState, getSimulationPackage, type ReviewStateView, type SimulationPackageView } from "@/lib/api/studio";

vi.mock("@/lib/api/studio", async (original) => ({ ...(await original<typeof import("@/lib/api/studio")>()), getReviewState: vi.fn(), getSimulationPackage: vi.fn(), getJobScene: vi.fn() }));
const pkg: SimulationPackageView = { scene_revision: "rev-1", source_scene_revision: "rev-0", created_at: "2026-10-01T00:00:00Z", confirmed_objects: 1, environment_triangles: 100, carved_triangles: 5, retained_shared_triangles: 0, retained_shared_object_ids: [], preflight: { blocking_result: "PASS", rules: [] }, export_capability: null, package_ref: { artifact_uri: "artifact://test/candidate", artifact_checksum: "sha256:test" } };
const review: ReviewStateView = { record: { scene_revision: "rev-1", status: "RELEASED", candidate_checksum: "sha256:candidate", validation_report_checksum: "sha256:report" }, validation: null, isaac_runtime_proof: null, warning_ids: [], approval: { reviewer_id: "user-reviewer", decision: "APPROVE", reason: null, decided_at: "2026-10-01T00:00:30Z", candidate_checksum: "sha256:candidate", validation_report_checksum: "sha256:report", record_checksum: "sha256:approval", accepted_warning_ids: [] }, release: { release_timestamp: "2026-10-01T00:01:00Z", release_manifest_checksum: "sha256:release", candidate_checksum: "sha256:candidate", validation_report_checksum: "sha256:report" }, release_archive: { artifact_uri: "artifact://test/release" }, release_seal_error: null, blockers: [] };
const preview = { url: "/preview.sog", filename: "preview.sog" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSimulationPackage).mockResolvedValue(pkg);
  vi.mocked(getReviewState).mockResolvedValue(review);
});

describe("kết quả đúng revision", () => {
  it("có candidate và release hiện hành thì mở đúng download", async () => {
    render(<ResultsTab jobId="job-a" preview={preview} revision="rev-1" />);
    expect(await screen.findByRole("link", { name: "Tải gói" })).toHaveAttribute("href", "/api/v1/jobs/job-a/simulation-package/download");
    expect(screen.getByRole("link", { name: "Tải bản phát hành" })).toHaveAttribute("href", "/api/v1/jobs/job-a/release-download");
    // S12: bản phát hành truy vết được tới gói, báo cáo, người duyệt và manifest.
    expect(screen.getByText(/duyệt bởi user-reviewer/)).toBeInTheDocument();
    expect(screen.getByText("sha256:release")).toBeInTheDocument();
    expect(screen.getByText("sha256:report")).toBeInTheDocument();
  });
  it("revision đã đổi thì chỉ giữ download bản làm việc", async () => {
    render(<ResultsTab jobId="job-a" preview={preview} revision="rev-2" />);
    expect(await screen.findByText(/Scene đã đổi revision/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Tải gói" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Tải bản phát hành" })).toBeNull();
    expect(screen.getByRole("link", { name: "Tải preview.sog" })).toHaveAttribute("href", "/preview.sog");
  });
  it("release chưa có archive thì không mở tải; lỗi mạng có thể retry", async () => {
    vi.mocked(getReviewState).mockResolvedValue({ ...review, release_archive: null });
    vi.mocked(getSimulationPackage).mockRejectedValueOnce(new Error("Mất kết nối"));
    render(<ResultsTab jobId="job-a" preview={preview} revision="rev-1" />);
    expect(await screen.findByText(/Mất kết nối/)).toBeInTheDocument();
    expect(screen.getByText("Chưa đọc được gói")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Tải bản phát hành" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByRole("link", { name: "Tải gói" })).toBeInTheDocument();
  });
  it("chưa biết revision thì phải đọc SceneIR; lỗi đọc không được mở download", async () => {
    vi.mocked(getJobScene).mockResolvedValue({ ok: false, error: new ApiError(503, "Không đọc được revision") });
    render(<ResultsTab jobId="job-a" preview={preview} revision={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Máy chủ chưa xử lý được yêu cầu");
    expect(getJobScene).toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Tải gói" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Tải bản phát hành" })).toBeNull();
  });
  it("scene có artifact nhưng chưa có head (409): hiện lý do của backend, không coi là chưa có SceneIR", async () => {
    const notReady = new ApiError(409, "Scene này chưa được chuẩn bị để xem. Nhờ quản trị chuẩn bị scene.");
    vi.mocked(getJobScene).mockResolvedValue({ ok: false, error: notReady });
    vi.mocked(getSimulationPackage).mockRejectedValue(notReady);
    vi.mocked(getReviewState).mockRejectedValue(notReady);
    render(<ResultsTab jobId="job-a" preview={preview} revision={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Scene này chưa được chuẩn bị để xem. Nhờ quản trị chuẩn bị scene.");
    expect(screen.queryByRole("link", { name: "Tải gói" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Tải bản phát hành" })).toBeNull();
  });
});
