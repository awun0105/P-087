/** Tổng quan chỉ đọc dữ liệu thật của API; proof component bằng fixture có kiểu. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OverviewPage } from "@/features/studio/OverviewPage";
import { ScenesHome } from "@/features/studio/ScenesHome";
import { ApiError } from "@/lib/api/client";
import type { Me } from "@/lib/api/auth";
import { listImports, listSamples, listScenes } from "@/lib/api/studio";
import type { JobManifest } from "@/lib/contracts/api";
import type { SceneSummary } from "@/lib/contracts/studio";

const auth = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me | null }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  listScenes: vi.fn(), listImports: vi.fn(), listSamples: vi.fn(),
}));

const sha = `sha256:${"a".repeat(64)}`;
function scene(id: string, status: JobManifest["status"], waiting = false): SceneSummary {
  return {
    project: { project_id: `project-${id}`, name: `Kho ${id}`, source_type: "upload", privacy: { result: "VERIFIED_ANONYMIZED", dispatch_allowed: true, block_reason: null, privacy_mode: "qa_verified" }, input_video: null, created_at: "2026-10-01T00:00:00Z" },
    latest_job: { schema_version: "1.0", job_id: id, project_id: `project-${id}`, status, current_stage: waiting ? "ST-METRIC-CANONICALIZE" : "ST-VISUAL-RECON", seed: 1, scene_revision: "rev-001", stage_artifacts: [], input_manifest_checksum: sha, config_checksum: sha, runtime_manifest_checksum: sha, job_manifest_checksum: sha, started_at: "2026-10-01T00:00:00Z", completed_at: null },
    preview_ready: waiting,
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  auth.me = { auth_required: false, user: null };
  vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [scene("job-a", "QUEUED"), scene("job-b", "RUNNING", true), scene("job-c", "SUCCEEDED")] } });
  vi.mocked(listImports).mockResolvedValue({ ok: true, data: { imports: [] } });
  vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [] } });
});

describe("Tổng quan và thư viện riêng", () => {
  it("giới thiệu và số liệu từ API; không có nút tạo scene trên Tổng quan", async () => {
    render(<OverviewPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Từ dữ liệu thực");
    expect(screen.getByRole("link", { name: "Mở Scenes" })).toHaveAttribute("href", "/scenes");
    await waitFor(() => expect(within(screen.getByText("Scene từ video").parentElement!).getByText("3")).toBeInTheDocument());
    expect(within(screen.getByText("Đang xử lý").parentElement!).getByText("1")).toBeInTheDocument();
    expect(within(screen.getByText("Cần xác nhận tỉ lệ", { selector: "dt" }).parentElement!).getByText("1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kho job-b/ })).toHaveAttribute("href", "/scenes/job-b");
    expect(document.querySelector('a[href="/new"]')).toBeNull();
  });

  it("guest chỉ thấy giới thiệu và đường đăng nhập, không gọi API private", () => {
    auth.me = { auth_required: true, user: null };
    render(<OverviewPage />);
    expect(screen.getByText("Khám phá Studio với mẫu đã xử lý sẵn")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Đăng nhập để xem tổng hợp" })).toHaveAttribute("href", "/login?next=/");
    expect(listScenes).not.toHaveBeenCalled();
    expect(listImports).not.toHaveBeenCalled();
  });

  it("lỗi nguồn không biến thành số 0 và có đường thử lại", async () => {
    vi.mocked(listScenes).mockResolvedValueOnce({ ok: false, error: new ApiError(503, "Mất kết nối") });
    render(<OverviewPage />);
    expect(await screen.findByText(/Chưa tải đủ dữ liệu tổng hợp/)).toBeInTheDocument();
    expect(within(screen.getByText("Scene từ video").parentElement!).getByText("—")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(within(screen.getByText("Scene từ video").parentElement!).getByText("3")).toBeInTheDocument());
    expect(screen.queryByText(/Chưa tải đủ dữ liệu tổng hợp/)).toBeNull();
  });

  it("Scenes rỗng vẫn chỉ có một nút tạo scene ở đầu trang", async () => {
    vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [] } });
    render(<ScenesHome />);
    expect(await screen.findByText("Chưa có scene nào")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Scene mới" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Scene mới" })).toHaveAttribute("href", "/new");
    expect(document.querySelectorAll('a[href="/new"]')).toHaveLength(1);
  });
});
