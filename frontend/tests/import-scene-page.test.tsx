import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportScenePage } from "@/features/studio/ImportScenePage";
import { cancelImport, clearImportCamera, getImport, retryImport, updateImportCamera } from "@/lib/api/studio";
import type { ImportedScene } from "@/lib/contracts/studio";

const pollingHarness = vi.hoisted(() => ({
  task: null as null | ((signal: AbortSignal) => Promise<void>),
}));

vi.mock("@/features/studio/usePolling", async () => {
  const React = await import("react");
  return {
    usePolling: (
      task: (signal: AbortSignal) => Promise<void>,
      _intervalMs: number,
      active: boolean,
      key?: unknown,
    ) => {
      React.useEffect(() => {
        if (!active) {
          pollingHarness.task = null;
          return;
        }
        pollingHarness.task = task;
        const controller = new AbortController();
        void task(controller.signal);
        return () => {
          controller.abort();
          if (pollingHarness.task === task) pollingHarness.task = null;
        };
      }, [task, active, key]);
    },
  };
});

vi.mock("@/features/shell/Breadcrumbs", () => ({ usePageTitle: () => undefined }));
vi.mock("@/features/shell/NavigationGuard", () => ({
  GuardedLink: ({ href, ...props }: React.ComponentProps<"a">) => <a href={href} {...props} />,
}));
vi.mock("@/features/studio/SceneWorkspace", () => ({
  SceneWorkspace: ({
    badges,
    initialCamera,
    onControlsReady,
    onToggleBookmark,
    bookmarkStatus,
    currentBookmark,
    fallbackInitialCamera,
  }: {
    badges?: import("react").ReactNode;
    initialCamera?: { position: number[]; target: number[]; fov?: number };
    onControlsReady?: (controls: unknown) => void;
    onToggleBookmark?: (active: boolean, controls?: unknown) => void;
    bookmarkStatus?: string;
    currentBookmark?: unknown;
    fallbackInitialCamera?: unknown;
  }) => (
    <div data-testid="scene-workspace">
      {badges}
      {initialCamera && <div data-testid="initial-camera">{JSON.stringify(initialCamera)}</div>}
      {onToggleBookmark && (
        <button
          type="button"
          onClick={() => {
            const mockControls = {
              getCameraPose: () => ({ position: [1.2, 3.4, 5.6], target: [0, 0, 0], fov: 60 }),
            };
            onControlsReady?.(mockControls);
            onToggleBookmark(true, mockControls);
          }}
        >
          Lưu góc nhìn
        </button>
      )}
      {onToggleBookmark && (
        <button
          type="button"
          onClick={() => {
            const mockControls = {
              getCameraPose: () => ({ position: [1.2, 3.4, 5.6], target: [0, 0, 0], fov: 60 }),
            };
            onControlsReady?.(mockControls);
            onToggleBookmark(false, mockControls);
          }}
        >
          Gỡ bookmark
        </button>
      )}
      <div data-testid="bookmark">{JSON.stringify(currentBookmark)}</div>
      <div data-testid="fallback-camera">{JSON.stringify(fallbackInitialCamera)}</div>
      <div data-testid="save-status">{bookmarkStatus}</div>
    </div>
  ),
}));
vi.mock("@/lib/api/studio", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/studio")>()),
  cancelImport: vi.fn(),
  clearImportCamera: vi.fn(),
  getImport: vi.fn(),
  retryImport: vi.fn(),
  updateImportCamera: vi.fn(),
}));

function importedScene(
  status: ImportedScene["status"],
  operationStatus: NonNullable<ImportedScene["operation"]>["status"],
  overrides: Partial<NonNullable<ImportedScene["operation"]>> = {},
): ImportedScene {
  const now = "2026-10-08T00:00:00Z";
  return {
    import_id: "import-1",
    upload_id: "upload-1",
    name: "Kho 3DGS",
    input_kind: "gaussian_ply",
    status,
    operation: {
      operation_id: "operation-1",
      status: operationStatus,
      attempt: 1,
      attempt_history: [],
      error: null,
      created_at: now,
      updated_at: now,
      ...overrides,
    },
    delivery_ref: null,
    error: null,
    created_at: now,
    capabilities: {
      can_delete: true,
      can_retry: operationStatus === "FAILED",
      can_cancel: operationStatus === "QUEUED" || operationStatus === "WAITING" || operationStatus === "RUNNING",
    },
  };
}

function ok(data: ImportedScene) {
  return { ok: true as const, data };
}

beforeEach(() => {
  vi.clearAllMocks();
  pollingHarness.task = null;
});

describe("ImportScenePage durable lifecycle", () => {
  it("shows the waiting reason and cancels an active import into a terminal state", async () => {
    const waiting = importedScene("PACKAGING", "WAITING", { error: "Worker đang chờ RAM (unmeasured)." });
    const queued = importedScene("PACKAGING", "QUEUED");
    const cancelled = importedScene("CANCELLED", "CANCELLED", {
      cancel_requested: true,
      error: "Đã hủy theo yêu cầu.",
    });
    vi.mocked(getImport).mockResolvedValueOnce(ok(waiting)).mockResolvedValue(ok(queued));
    vi.mocked(cancelImport).mockResolvedValue(cancelled);

    render(<ImportScenePage importId="import-1" />);

    expect(await screen.findByText("Worker đang chờ RAM (unmeasured).", { selector: "p" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Hủy import" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hủy import" }));

    expect(await screen.findByText("Đã hủy theo yêu cầu.")).toBeInTheDocument();
    expect(cancelImport).toHaveBeenCalledWith("import-1");
    expect(screen.queryByRole("button", { name: "Hủy import" })).toBeNull();
  });

  it("retries only the failed scene and returns to worker progress", async () => {
    const failed = importedScene("FAILED", "FAILED", {
      error: "Chưa lưu được bản xem scene.",
      failure_code: "publication_failure",
      retryable: true,
      attempt_history: [{ attempt: 1, status: "FAILED", started_at: "2026-10-08T00:00:00Z", error: "publish failed" }],
    });
    const queued = importedScene("PACKAGING", "QUEUED", {
      attempt_history: [{ attempt: 1, status: "FAILED", started_at: "2026-10-08T00:00:00Z", error: "publish failed" }],
    });
    vi.mocked(getImport).mockResolvedValueOnce(ok(failed)).mockResolvedValue(ok(queued));
    vi.mocked(retryImport).mockResolvedValue(queued);

    render(<ImportScenePage importId="import-1" />);

    expect(await screen.findByText("Chưa lưu được bản xem scene.")).toBeInTheDocument();
    expect(screen.getByText(/Lịch sử xử lý · 1 lượt/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại scene import" }));

    expect(await screen.findByText("Đang chờ worker nhận scene…")).toBeInTheDocument();
    expect(retryImport).toHaveBeenCalledWith("import-1");
  });

  it("ignores an older poll response after a newer status was applied", async () => {
    let resolveOlder!: (result: ReturnType<typeof ok>) => void;
    vi.mocked(getImport)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOlder = resolve; }))
      .mockResolvedValueOnce(ok(importedScene("PACKAGING", "QUEUED")))
      .mockResolvedValue(ok(importedScene("PACKAGING", "QUEUED")));

    render(<ImportScenePage importId="import-1" />);
    await waitFor(() => expect(getImport).toHaveBeenCalledTimes(1));
    const pollAgain = pollingHarness.task;
    expect(pollAgain).not.toBeNull();

    await act(async () => {
      await pollAgain!(new AbortController().signal);
    });
    expect(await screen.findByText("Đang chờ worker nhận scene…")).toBeInTheDocument();

    await act(async () => {
      resolveOlder(ok(importedScene("FAILED", "FAILED", {
        error: "stale failure",
        failure_code: "invalid_source",
        retryable: false,
      })));
    });
    expect(screen.getByText("Đang chờ worker nhận scene…")).toBeInTheDocument();
    expect(screen.queryByText("stale failure")).toBeNull();
  });

  it("shows an actionable retry error without losing the failed state", async () => {
    vi.mocked(getImport).mockResolvedValue(ok(importedScene("FAILED", "FAILED", {
      error: "temporary failure",
      failure_code: "runtime_failure",
      retryable: true,
    })));
    vi.mocked(retryImport).mockRejectedValue(new Error("Worker chưa sẵn sàng"));

    render(<ImportScenePage importId="import-1" />);
    expect(await screen.findByText("temporary failure")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại scene import" }));

    expect(await screen.findByText("Worker chưa sẵn sàng")).toBeInTheDocument();
    expect(screen.getByText("temporary failure")).toBeInTheDocument();
  });

  it("labels an imported SOG as the original source when opening the viewer", async () => {
    const ready = importedScene("READY", "SUCCEEDED");
    ready.input_kind = "gaussian_sog";
    ready.delivery_ref = { artifact_uri: "artifact://sog", artifact_checksum: "sha256:test" };
    vi.mocked(getImport).mockResolvedValue(ok(ready));

    render(<ImportScenePage importId="import-1" />);

    expect(await screen.findByTestId("scene-workspace")).toBeInTheDocument();
    expect(screen.getByText("Scene import · SOG tải lên · giữ nguyên bytes")).toBeInTheDocument();
  });

  it("passes default camera and allows saving current camera pose", async () => {
    const ready = importedScene("READY", "SUCCEEDED");
    ready.default_camera = { position: [1, 2, 3], target: [0, 0, 0], fov: 60 };
    vi.mocked(getImport).mockResolvedValue(ok(ready));
    vi.mocked(updateImportCamera).mockResolvedValue({
      ...ready,
      default_camera: { position: [1.2, 3.4, 5.6], target: [0, 0, 0], fov: 60 },
    });

    render(<ImportScenePage importId="import-1" />);

    expect(await screen.findByTestId("initial-camera")).toHaveTextContent('{"position":[1,2,3],"target":[0,0,0],"fov":60}');
    fireEvent.click(screen.getByRole("button", { name: "Lưu góc nhìn" }));

    await waitFor(() => {
      expect(updateImportCamera).toHaveBeenCalledWith("import-1", {
        position: [1.2, 3.4, 5.6],
        target: [0, 0, 0],
        fov: 60,
      });
    });
  });

  it("allows unbookmarking to clear default camera and return to initial camera", async () => {
    const ready = importedScene("READY", "SUCCEEDED");
    ready.initial_camera = { position: [10, 20, 30], target: [0, 0, 0], fov: 60 };
    ready.default_camera = { position: [1, 2, 3], target: [0, 0, 0], fov: 60 };
    vi.mocked(getImport).mockResolvedValue(ok(ready));
    vi.mocked(clearImportCamera).mockResolvedValue({
      ...ready,
      default_camera: null,
    });

    render(<ImportScenePage importId="import-1" />);

    expect(await screen.findByTestId("initial-camera")).toHaveTextContent('{"position":[1,2,3],"target":[0,0,0],"fov":60}');
    fireEvent.click(screen.getByRole("button", { name: "Gỡ bookmark" }));

    await waitFor(() => {
      expect(clearImportCamera).toHaveBeenCalledWith("import-1");
      expect(screen.getByTestId("bookmark")).toHaveTextContent("null");
    });
    expect(screen.getByTestId("initial-camera")).toHaveTextContent('{"position":[1,2,3],"target":[0,0,0],"fov":60}');
    expect(screen.getByTestId("fallback-camera")).toHaveTextContent('{"position":[10,20,30],"target":[0,0,0],"fov":60}');
  });
  it("saving the first bookmark does not replace an absent bootstrap camera", async () => {
    const ready = importedScene("READY", "SUCCEEDED");
    vi.mocked(getImport).mockResolvedValue(ok(ready));
    vi.mocked(updateImportCamera).mockResolvedValue({ ...ready, default_camera: { position: [1.2, 3.4, 5.6], target: [0, 0, 0], fov: 60 } });
    render(<ImportScenePage importId="import-1" />);
    await screen.findByTestId("scene-workspace");
    expect(screen.queryByTestId("initial-camera")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Lưu góc nhìn" }));
    await waitFor(() => expect(screen.getByTestId("save-status")).toHaveTextContent("saved"));
    expect(screen.queryByTestId("initial-camera")).toBeNull();
    expect(screen.getByTestId("fallback-camera")).toHaveTextContent('"fov":85');
  });

  it("keeps the bookmark and shows an error if unbookmarking fails", async () => {
    const ready = importedScene("READY", "SUCCEEDED");
    ready.default_camera = { position: [1, 2, 3], target: [0, 0, 0], fov: 85 };
    vi.mocked(getImport).mockResolvedValue(ok(ready));
    vi.mocked(clearImportCamera).mockRejectedValue(new Error("offline"));
    render(<ImportScenePage importId="import-1" />);
    await screen.findByTestId("scene-workspace");
    fireEvent.click(screen.getByRole("button", { name: "Gỡ bookmark" }));
    await waitFor(() => expect(screen.getByTestId("save-status")).toHaveTextContent("error"));
    expect(screen.getByTestId("bookmark")).toHaveTextContent('"position":[1,2,3]');
  });

});
