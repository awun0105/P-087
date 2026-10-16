import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportSetupStep } from "@/features/studio/ImportSetupStep";
import { NewSceneFlow } from "@/features/studio/NewSceneFlow";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { createImport, listSamples, listUploads, uploadVideo, removeSample } from "@/lib/api/studio";
import type { Me } from "@/lib/api/auth";
import type { UploadRecord, SampleSummary } from "@/lib/contracts/studio";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
const authState = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me, refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation, useSearchParams: () => new URLSearchParams() }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => authState }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  listUploads: vi.fn(), listSamples: vi.fn(), createImport: vi.fn(), uploadVideo: vi.fn(), removeSample: vi.fn(),
}));

const video: UploadRecord = { upload_id: "video-1", original_name: "warehouse.mp4", media_type: "video/mp4", size_bytes: 100, checksum: "sha256:test", artifact_uri: "artifact://test/video", received_at: "2026-10-01T00:00:00Z", project_ids: [], input_kind: "rgb_video" };
const gaussian: UploadRecord = { ...video, upload_id: "ply-1", original_name: "warehouse.ply", media_type: "application/x-ply", input_kind: "gaussian_ply" };
const sog: UploadRecord = { ...video, upload_id: "sog-1", original_name: "external.sog", media_type: "application/x-sog", input_kind: "gaussian_sog" };

beforeEach(() => {
  vi.clearAllMocks();
  authState.me = { auth_required: false, user: null };
  authState.refresh.mockResolvedValue(undefined);
  sessionStorage.clear();
  history.replaceState({}, "", "/new/import-scene");
  vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [video, gaussian] } });
  vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [] } });
});

describe("hai cửa vào dữ liệu đã dựng sẵn", () => {
  it("mỗi trang chỉ có form của nhánh đó và quay về khung tải input chung", async () => {
    const demo = render(<NewSceneFlow source="sample" />);
    expect(await screen.findByText("Chưa có video mẫu")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Kéo file 3DGS/)).toBeNull();
    expect(screen.getByRole("link", { name: /Về trang tạo scene/ })).toHaveAttribute("href", "/new/import-video");
    expect(createImport).not.toHaveBeenCalled();
    demo.unmount();

    render(<NewSceneFlow source="gaussian" />);
    expect(screen.getByLabelText(/Kéo file 3DGS/)).toHaveAttribute(
      "accept",
      ".ply,.sog,.zip,application/zip,application/x-sog",
    );
    expect(screen.getByText(/PLY\/SOG hoặc ZIP gồm PLY \+ COLMAP/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Về trang tạo scene/ })).toHaveAttribute("href", "/new/import-video");
  });

  it("video tải ở nhánh 3DGS được nối sang khung tải input chung thay vì bắt tải lại", async () => {
    vi.mocked(uploadVideo).mockReturnValue({ promise: Promise.resolve(video), abort: vi.fn() } as never);
    render(<NewSceneFlow source="gaussian" />);
    const input = screen.getByLabelText(/Kéo file 3DGS/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "kho.zip", { type: "application/zip" })] } });
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/new/import-video?upload=video-1"));
  });

  it("import chỉ chọn 3DGS; lỗi giữ tên và gọi đúng API", async () => {
    vi.mocked(createImport).mockRejectedValue(new Error("Không chuyển đổi được"));
    render(<ImportSetupStep preselect="video-1" onBack={vi.fn()} />);
    const name = await screen.findByLabelText("Tên scene import");
    expect(screen.getAllByRole("radio")).toHaveLength(1);
    expect(screen.getByRole("radio")).toHaveAttribute("value", "ply-1");
    expect(screen.getByRole("radio")).toBeChecked();
    fireEvent.change(name, { target: { value: "Kho import" } });
    fireEvent.click(screen.getByRole("button", { name: "Mở scene import" }));
    expect(await screen.findByText("Không chuyển đổi được")).toBeInTheDocument();
    expect(name).toHaveValue("Kho import");
    const firstCall = vi.mocked(createImport).mock.calls[0];
    expect(firstCall?.slice(0, 2)).toEqual(["ply-1", "Kho import"]);
    expect(firstCall?.[2]).toEqual(expect.any(String));
    fireEvent.click(screen.getByRole("button", { name: "Mở scene import" }));
    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(2));
    expect(vi.mocked(createImport).mock.calls[1]?.[2]).toBe(firstCall?.[2]);
    expect(navigation.push).not.toHaveBeenCalled();
  });

  it("cho phép chọn SOG đã upload ở luồng mở scene", async () => {
    vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [sog] } });
    render(<ImportSetupStep preselect="sog-1" onBack={vi.fn()} />);
    expect(await screen.findByRole("radio", { name: /external\.sog/ })).toBeInTheDocument();
    expect(screen.getByRole("radio")).toBeChecked();
    expect(screen.getByRole("radio")).toHaveAttribute("value", "sog-1");
    expect(screen.getByRole("button", { name: "Mở scene import" })).toBeEnabled();
  });
});

describe("trình hướng dẫn mẫu", () => {
  it("có 3 bước, không còn bước mở scene riêng", async () => {
    vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [] } });
    render(<NewSceneFlow source="sample" />);
    expect(screen.getByText("Chọn mẫu")).toBeInTheDocument();
    expect(screen.getByText("Xem thông tin")).toBeInTheDocument();
    expect(screen.getByText("Xem tiến trình")).toBeInTheDocument();
    expect(screen.queryByText("Mở scene mẫu")).toBeNull();
  });
});

describe("upload 3DGS", () => {
  it("chặn đuôi không thuộc nhánh 3DGS và không gọi upload", () => {
    render(<UploadDropzone onUploaded={vi.fn()} />);
    const input = screen.getByLabelText(/Kéo file 3DGS/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "kho.mp4", { type: "video/mp4" })] } });
    expect(screen.getByText(/Mở 3DGS chỉ nhận/)).toBeInTheDocument();
    expect(uploadVideo).not.toHaveBeenCalled();
  });

  it("báo lỗi upload và giữ khung chọn file", async () => {
    vi.mocked(uploadVideo).mockReturnValue({ promise: Promise.reject(new Error("Mạng lỗi")), abort: vi.fn() } as never);
    render(<UploadDropzone onUploaded={vi.fn()} />);
    const input = screen.getByLabelText(/Kéo file 3DGS/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "scene.ply", { type: "application/x-ply" })] } });
    expect(await screen.findByText("Mạng lỗi")).toBeInTheDocument();
    expect(screen.getByLabelText(/Kéo file 3DGS/)).toBeInTheDocument();
  });

  it("gọi onUploaded với record máy chủ trả về", async () => {
    const onUploaded = vi.fn();
    vi.mocked(uploadVideo).mockReturnValue({ promise: Promise.resolve(gaussian), abort: vi.fn() } as never);
    render(<UploadDropzone onUploaded={onUploaded} />);
    const input = screen.getByLabelText(/Kéo file 3DGS/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "scene.ply", { type: "application/x-ply" })] } });
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(gaussian));
  });
});


describe("bỏ dự án khỏi thư viện demo", () => {
  const sample: SampleSummary = { sample_id: "demo-1", title: "Kho A", description: "", origin: "pipeline_job", source: { dataset: "Studio", sequence: "Kho", note: "" }, cover: null, video: null, frame_count: null, total_seconds: null, has_processing: false, machine: {} };

  it("Reviewer bỏ mẫu sau xác nhận; lỗi giữ thẻ và cho thử lại", async () => {
    authState.me = { auth_required: true, user: { user_id: "reviewer", display_name: "Reviewer", role: "reviewer", email: "reviewer@example.test", active: true, daily_job_quota: 10 } };
    vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [sample] } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.mocked(removeSample).mockRejectedValueOnce(new Error("Máy chủ chưa ghi được")).mockResolvedValueOnce(undefined);
    render(<NewSceneFlow source="sample" />);
    const remove = await screen.findByRole("button", { name: "Bỏ Kho A khỏi demo" });
    fireEvent.click(remove);
    expect(removeSample).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(remove);
    expect(await screen.findByRole("alert")).toHaveTextContent("Máy chủ chưa ghi được");
    expect(screen.getByRole("button", { name: "Bỏ Kho A khỏi demo" })).toBeEnabled();
    fireEvent.click(remove);
    expect(await screen.findByText("Chưa có video mẫu")).toBeInTheDocument();
    expect(removeSample).toHaveBeenLastCalledWith("demo-1");
    confirm.mockRestore();
  });

  it("người xem không có thao tác bỏ mẫu", async () => {
    vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [sample] } });
    render(<NewSceneFlow source="sample" />);
    await screen.findByText("Kho A");
    expect(screen.queryByRole("button", { name: "Bỏ Kho A khỏi demo" })).not.toBeInTheDocument();
  });
});
