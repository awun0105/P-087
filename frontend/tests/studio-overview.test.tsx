/** Tổng quan chỉ đọc dữ liệu thật của API; proof component bằng fixture có kiểu. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OverviewPage } from "@/features/studio/OverviewPage";
import { ScenesHome } from "@/features/studio/ScenesHome";
import { ApiError } from "@/lib/api/client";
import type { Me } from "@/lib/api/auth";
import { listImports, listSamples, listScenes } from "@/lib/api/studio";
import type { JobManifest } from "@/lib/contracts/api";
import type { ImportedScene, SceneSummary } from "@/lib/contracts/studio";

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
  it("số liệu từ API; nút chính là Tạo scene mới; việc chờ bạn nằm trên cùng", async () => {
    render(<OverviewPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tổng quan");
    expect(screen.getByRole("link", { name: /Tạo scene mới/ })).toHaveAttribute("href", "/new");
    expect(screen.getByRole("link", { name: "Tất cả scene" })).toHaveAttribute("href", "/scenes");
    await waitFor(() => expect(within(screen.getByText("Scene từ video").parentElement!).getByText("3")).toBeInTheDocument());
    expect(within(screen.getByText("Đang xử lý").parentElement!).getByText("1")).toBeInTheDocument();
    expect(within(screen.getByText("Cần bạn xử lý", { selector: "dt" }).parentElement!).getByText("1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kho job-b/ })).toHaveAttribute("href", "/scenes/job-b");
    expect(screen.queryByText(/Một hành trình/)).toBeNull();
  });

  it("job chờ xem bản đã che được tính là cần xử lý, không phải đang chạy", async () => {
    const reviewing = { ...scene("job-r", "RUNNING"), awaiting_anonymization_review: true };
    vi.mocked(listScenes).mockResolvedValue({ ok: true, data: { scenes: [reviewing] } });
    render(<OverviewPage />);
    expect(await screen.findByRole("link", { name: /Kho job-r/ })).toHaveTextContent("Cần xem bản đã che");
    expect(within(screen.getByText("Đang xử lý").parentElement!).getByText("0")).toBeInTheDocument();
    expect(within(screen.getByText("Cần bạn xử lý", { selector: "dt" }).parentElement!).getByText("1")).toBeInTheDocument();
  });

  it("guest chỉ thấy giới thiệu và đường đăng nhập, không gọi API private", () => {
    auth.me = { auth_required: true, user: null };
    render(<OverviewPage />);
    expect(screen.getByText("Đăng nhập để xem công việc của nhóm")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Thử với mẫu/ })).toHaveAttribute("href", "/new/try-demo");
    expect(screen.getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("href", "/login?next=%2Foverview");
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

  it("scene import hiển thị đúng nguồn và trạng thái persisted, kể cả cancellation", async () => {
    auth.me = {
      auth_required: true,
      user: {
        user_id: "user-editor",
        email: "editor@example.test",
        display_name: "Editor Test",
        role: "editor",
        active: true,
        daily_job_quota: 10,
      },
    };
    const imported = (overrides: Partial<ImportedScene>): ImportedScene => ({
      import_id: "import-default",
      upload_id: "upload-1",
      name: "Default import",
      input_kind: "gaussian_ply",
      status: "PACKAGING",
      operation: {
        operation_id: "operation-default",
        status: "QUEUED",
        attempt: 0,
        attempt_history: [],
        error: null,
        created_at: "2026-10-08T00:00:00Z",
        updated_at: "2026-10-08T00:00:00Z",
      },
      delivery_ref: null,
      error: null,
      created_at: "2026-10-08T00:00:00Z",
      ...overrides,
    });
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [
          imported({ import_id: "sog-ready", name: "SOG import", input_kind: "gaussian_sog", status: "READY" }),
          imported({ import_id: "ply-waiting", name: "PLY waiting", operation: {
            operation_id: "operation-waiting",
            status: "WAITING",
            attempt: 0,
            attempt_history: [],
            error: "Worker đang chờ RAM",
            created_at: "2026-10-08T00:00:00Z",
            updated_at: "2026-10-08T00:00:00Z",
          } }),
          imported({ import_id: "ply-cancelled", name: "PLY cancelled", status: "CANCELLED", operation: {
            operation_id: "operation-cancelled",
            status: "CANCELLED",
            attempt: 0,
            attempt_history: [],
            error: "Đã hủy theo yêu cầu.",
            created_at: "2026-10-08T00:00:00Z",
            updated_at: "2026-10-08T00:00:00Z",
          } }),
        ],
      },
    });

    render(<ScenesHome />);

    const sog = await screen.findByRole("link", { name: /SOG import/ });
    const waiting = screen.getByRole("link", { name: /PLY waiting/ });
    const cancelled = screen.getByRole("link", { name: /PLY cancelled/ });
    expect(sog).toHaveTextContent("SOG");
    // Chỉnh Gaussian đang tạm ẩn: scene import chỉ mời xem.
    expect(sog).toHaveTextContent("Mở xem");
    expect(sog).not.toHaveTextContent("chỉnh");
    expect(waiting).toHaveTextContent("PLY");
    expect(waiting).toHaveTextContent("Đang chờ tài nguyên");
    expect(cancelled).toHaveTextContent("Đã hủy");
    expect(cancelled).not.toHaveTextContent("Đang nén");
  });
});

describe("trạng thái scene chờ xem bản đã che", () => {
  it("được tính là cần xử lý, không active, và ưu tiên hơn trạng thái worker", async () => {
    const { sceneStatus } = await import("@/features/studio/sceneStatus");
    const job = scene("job-r", "RUNNING").latest_job!;
    expect(sceneStatus(job, false, true)).toMatchObject({ label: "Cần xem bản đã che", group: "action", active: false });
    expect(sceneStatus(job, false, false)).toMatchObject({ group: "running", active: true });
  });

  it("nút tạo scene không nháy ra lúc chưa biết người dùng là ai", () => {
    auth.me = null;
    render(<OverviewPage />);
    expect(screen.queryByRole("link", { name: /Thử với mẫu/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Tạo scene mới/ })).toBeNull();
  });
});
