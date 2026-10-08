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
    capabilities: { can_delete_project: true },
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
    expect(screen.getByRole("link", { name: "Đăng nhập để xem tổng hợp" })).toHaveAttribute("href", "/login?next=%2Foverview");
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

  it("Scenes rỗng hiển thị hướng dẫn tạo scene mới", async () => {
    vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [] } });
    render(<ScenesHome />);
    expect(await screen.findByText("Chưa có scene nào")).toBeInTheDocument();
    expect(screen.getByText(/Chọn “Tạo scene mới” từ thanh điều hướng/)).toBeInTheDocument();
  });

  it("thẻ scene ghi rõ ai tạo và ai chạy lại gần nhất; không biết thì không ghi", async () => {
    const mine = {
      ...scene("job-a", "RUNNING"),
      requested_by: { user_id: "u-2", display_name: "Bình", role: "reviewer" as const },
    };
    mine.project = {
      ...mine.project,
      name: "Kho có chủ",
      created_by: { user_id: "u-1", display_name: "An", role: "editor" },
    };
    const anonymous = scene("job-b", "QUEUED");
    anonymous.project = { ...anonymous.project, name: "Kho không rõ" };
    const legacy = scene("job-c", "FAILED");
    legacy.project = {
      ...legacy.project,
      name: "Kho thiếu role",
      created_by: { user_id: "u-3", display_name: "Chi" },
    };
    vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [mine, anonymous, legacy] } });
    render(<ScenesHome />);
    const owned = (await screen.findByRole("heading", { name: "Kho có chủ" })).closest("a")!;
    expect(owned).toHaveTextContent(/Tạo bởi:\s*An/i);
    expect(owned).toHaveTextContent(/Chạy bởi:\s*Bình/i);
    expect(owned).toHaveTextContent("Editor");
    expect(owned).toHaveTextContent("Reviewer");
    const unknown = screen.getByRole("heading", { name: "Kho không rõ" }).closest("a")!;
    expect(unknown).not.toHaveTextContent("tạo bởi");
    const old = screen.getByRole("heading", { name: "Kho thiếu role" }).closest("a")!;
    expect(old).toHaveTextContent("Vai trò chưa xác định");

    fireEvent.click(screen.getByRole("radio", { name: "Danh sách" }));
    const row = await screen.findByRole("row", { name: /Kho có chủ/ });
    expect(row).toHaveTextContent("Editor");
    expect(row).toHaveTextContent("Reviewer");
    expect(row).toHaveTextContent(/Chạy bởi:\s*Bình/i);
  });

  it.each([
    { role: "guest" as const, own: true, foreign: false },
    { role: "editor" as const, own: true, foreign: true },
    { role: "reviewer" as const, own: true, foreign: true },
  ])("$role chỉ hiện thao tác xoá theo capability của server ở cả lưới và danh sách", async ({ role, own, foreign }) => {
    auth.me = { auth_required: true, user: { user_id: "user-guest", email: "guest@example.test", display_name: "Guest Test", role, active: true, daily_job_quota: 10 } };
    const mine = {
      ...scene("mine", "SUCCEEDED"),
      project: { ...scene("mine", "SUCCEEDED").project, name: "Scene của tôi", created_by: { user_id: "user-guest", display_name: "Guest Test", role } },
      capabilities: { can_delete_project: own },
    };
    const other = {
      ...scene("other", "SUCCEEDED"),
      project: { ...scene("other", "SUCCEEDED").project, name: "Scene của nhóm" },
      capabilities: { can_delete_project: foreign },
    };
    vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [mine, other] } });
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [
          { import_id: "import-mine", upload_id: "upload-mine", name: "PLY của tôi", input_kind: "gaussian_ply", status: "READY", delivery_ref: null, error: null, created_at: "2026-10-01T00:00:00Z", capabilities: { can_delete: own } },
          { import_id: "import-other", upload_id: "upload-other", name: "PLY của nhóm", input_kind: "gaussian_ply", status: "READY", delivery_ref: null, error: null, created_at: "2026-10-01T00:00:00Z", capabilities: { can_delete: foreign } },
        ],
      },
    });
    render(<ScenesHome />);

    await screen.findByText("Scene của tôi");
    expect(screen.getByText(role === "guest" ? "Guest" : role === "editor" ? "Editor" : "Reviewer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Chuyển Scene của tôi vào thùng rác" }) !== null).toBe(own);
    expect(screen.queryByRole("button", { name: "Chuyển Scene của nhóm vào thùng rác" }) !== null).toBe(foreign);
    expect(screen.queryByRole("button", { name: "Chuyển PLY của tôi vào thùng rác" }) !== null).toBe(own);
    expect(screen.queryByRole("button", { name: "Chuyển PLY của nhóm vào thùng rác" }) !== null).toBe(foreign);

    fireEvent.click(screen.getByRole("radio", { name: "Danh sách" }));
    const ownRow = await screen.findByRole("row", { name: /Scene của tôi/ });
    const foreignRow = screen.getByRole("row", { name: /Scene của nhóm/ });
    expect(within(ownRow).queryByRole("button", { name: "Chuyển Scene của tôi vào thùng rác" }) !== null).toBe(own);
    expect(within(foreignRow).queryByRole("button", { name: "Chuyển Scene của nhóm vào thùng rác" }) !== null).toBe(foreign);
  });

  it.each(["guest", "editor", "reviewer"] as const)("legacy Scenes/import response fails closed for Guest and preserves %s access", async (role) => {
    auth.me = { auth_required: true, user: { user_id: "user-guest", email: "guest@example.test", display_name: "Guest Test", role, active: true, daily_job_quota: 10 } };
    const legacyScene = scene("legacy", "SUCCEEDED");
    Reflect.deleteProperty(legacyScene, "capabilities");
    vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [legacyScene] } });
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [{ import_id: "legacy-import", upload_id: "upload-1", name: "PLY cũ", input_kind: "gaussian_ply", status: "READY", delivery_ref: null, error: null, created_at: "2026-10-01T00:00:00Z" }],
      },
    });
    render(<ScenesHome />);

    await screen.findByText("Kho legacy");
    const allowed = role !== "guest";
    expect(screen.queryByRole("button", { name: "Chuyển Kho legacy vào thùng rác" }) !== null).toBe(allowed);
    expect(screen.queryByRole("button", { name: "Chuyển PLY cũ vào thùng rác" }) !== null).toBe(allowed);
  });

  it("scene import hiển thị creator và role dưới dạng text thuần", async () => {
    const hostileName = '<img src="x" onerror="alert(1)">';
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [{
          import_id: "import-1",
          upload_id: "upload-1",
          name: "PLY nhập",
          input_kind: "gaussian_ply",
          status: "READY",
          delivery_ref: null,
          error: null,
          created_at: "2026-10-01T00:00:00Z",
          created_by_name: hostileName,
          created_by_role: "reviewer",
          capabilities: { can_delete: true },
        }],
      },
    });

    render(<ScenesHome />);

    const imported = await screen.findByRole("link", { name: /PLY nhập/ });
    expect(imported).toHaveTextContent(hostileName);
    expect(imported).toHaveTextContent("Reviewer");
    expect(imported.querySelector('img[src="x"]')).toBeNull();
  });
});
