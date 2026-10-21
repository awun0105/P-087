import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportedScenesHome } from "@/features/studio/ImportedScenesHome";
import type { Me } from "@/lib/api/auth";
import { listImports } from "@/lib/api/studio";
import type { ImportedScene } from "@/lib/contracts/studio";

const auth = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me | null }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  listImports: vi.fn(),
  moveImportToTrash: vi.fn(),
}));

const mockImport = (overrides: Partial<ImportedScene>): ImportedScene => ({
  import_id: "import-default",
  upload_id: "upload-1",
  name: "Default import",
  input_kind: "gaussian_ply",
  status: "READY",
  operation: null,
  delivery_ref: null,
  error: null,
  created_at: "2026-10-08T00:00:00Z",
  capabilities: { can_delete: true },
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  auth.me = { auth_required: false, user: null };
  vi.mocked(listImports).mockResolvedValue({ ok: true, data: { imports: [] } });
});

describe("ImportedScenesHome", () => {
  it("hiển thị tiêu đề và trạng thái rỗng khi chưa có scene import", async () => {
    render(<ImportedScenesHome />);
    expect(screen.getByRole("heading", { level: 1, name: "Scenes đã import" })).toBeInTheDocument();
    expect(await screen.findByText("Chưa có scene 3DGS nào")).toBeInTheDocument();
  });

  it("scene import hiển thị creator và role dưới dạng text thuần (chống XSS)", async () => {
    const hostileName = '<img src="x" onerror="alert(1)">';
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [
          mockImport({
            import_id: "import-1",
            name: "PLY an toàn",
            created_by_name: hostileName,
            created_by_role: "reviewer",
          }),
        ],
      },
    });

    render(<ImportedScenesHome />);

    await screen.findByRole("heading", { name: "PLY an toàn" });
    expect(screen.getByText(hostileName)).toBeInTheDocument();
    expect(screen.getByText("Reviewer")).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });

  it("scene import hiển thị đúng nguồn và trạng thái persisted", async () => {
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
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [
          mockImport({ import_id: "sog-ready", name: "SOG import", input_kind: "gaussian_sog", status: "READY" }),
          mockImport({
            import_id: "ply-waiting",
            name: "PLY waiting",
            status: "PACKAGING",
            operation: {
              operation_id: "op-1",
              status: "WAITING",
              attempt: 0,
              attempt_history: [],
              error: "Worker đang chờ RAM",
              created_at: "2026-10-08T00:00:00Z",
              updated_at: "2026-10-08T00:00:00Z",
            },
          }),
          mockImport({
            import_id: "ply-cancelled",
            name: "PLY cancelled",
            status: "CANCELLED",
            operation: {
              operation_id: "op-2",
              status: "CANCELLED",
              attempt: 0,
              attempt_history: [],
              error: "Đã hủy theo yêu cầu.",
              created_at: "2026-10-08T00:00:00Z",
              updated_at: "2026-10-08T00:00:00Z",
            },
          }),
        ],
      },
    });

    render(<ImportedScenesHome />);

    const sogTitle = await screen.findByRole("heading", { name: "SOG import" });
    const sogCard = sogTitle.closest("section")!;
    expect(sogCard).toHaveTextContent("SOG");
    expect(sogCard).toHaveTextContent("Mở xem");

    const waitingTitle = screen.getByRole("heading", { name: "PLY waiting" });
    const waitingCard = waitingTitle.closest("section")!;
    expect(waitingCard).toHaveTextContent("PLY");
    expect(waitingCard).toHaveTextContent("Đang chờ tài nguyên");

    const cancelledTitle = screen.getByRole("heading", { name: "PLY cancelled" });
    const cancelledCard = cancelledTitle.closest("section")!;
    expect(cancelledCard).toHaveTextContent("Đã hủy");
  });

  it.each([
    { role: "guest" as const, own: true, foreign: false },
    { role: "editor" as const, own: true, foreign: true },
    { role: "reviewer" as const, own: true, foreign: true },
  ])("$role chỉ hiện thao tác xoá theo capability của server ở cả lưới và danh sách", async ({ role, own, foreign }) => {
    auth.me = {
      auth_required: true,
      user: {
        user_id: "user-test",
        email: "test@example.test",
        display_name: "Test User",
        role,
        active: true,
        daily_job_quota: 10,
      },
    };
    vi.mocked(listImports).mockResolvedValue({
      ok: true,
      data: {
        imports: [
          mockImport({
            import_id: "import-mine",
            name: "PLY của tôi",
            capabilities: { can_delete: own },
          }),
          mockImport({
            import_id: "import-other",
            name: "PLY của nhóm",
            capabilities: { can_delete: foreign },
          }),
        ],
      },
    });

    render(<ImportedScenesHome />);

    await screen.findByText("PLY của tôi");
    expect(screen.queryByRole("button", { name: "Chuyển PLY của tôi vào thùng rác" }) !== null).toBe(own);
    expect(screen.queryByRole("button", { name: "Chuyển PLY của nhóm vào thùng rác" }) !== null).toBe(foreign);

    fireEvent.click(screen.getByRole("radio", { name: "Danh sách" }));
    const ownRow = await screen.findByRole("row", { name: /PLY của tôi/ });
    const foreignRow = screen.getByRole("row", { name: /PLY của nhóm/ });
    expect(within(ownRow).queryByRole("button", { name: "Chuyển PLY của tôi vào thùng rác" }) !== null).toBe(own);
    expect(within(foreignRow).queryByRole("button", { name: "Chuyển PLY của nhóm vào thùng rác" }) !== null).toBe(foreign);
  });
});
