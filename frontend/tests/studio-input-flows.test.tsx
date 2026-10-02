/** Proof của form/API bằng mock; không thay acceptance video/GPU hoặc renderer. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportSetupStep } from "@/features/studio/ImportSetupStep";
import { NewSceneFlow } from "@/features/studio/NewSceneFlow";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { VideoSetupStep } from "@/features/studio/VideoSetupStep";
import { createImport, createSceneFromUpload, listSamples, listUploads, uploadVideo } from "@/lib/api/studio";
import type { UploadRecord } from "@/lib/contracts/studio";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation, useSearchParams: () => new URLSearchParams() }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => ({ me: { auth_required: false, user: null } }) }));
vi.mock("@/features/studio/useProcessingForm", () => ({ useProcessingForm: () => ({ options: null, values: null, evaluation: null, error: null, activePreset: null }) }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  listUploads: vi.fn(), listSamples: vi.fn(), createImport: vi.fn(), createSceneFromUpload: vi.fn(), uploadVideo: vi.fn(),
}));

const video: UploadRecord = { upload_id: "video-1", original_name: "warehouse.mp4", media_type: "video/mp4", size_bytes: 100, checksum: "sha256:test", artifact_uri: "artifact://test/video", received_at: "2026-10-01T00:00:00Z", project_ids: [], input_kind: "rgb_video" };
const gaussian: UploadRecord = { ...video, upload_id: "ply-1", original_name: "warehouse.ply", media_type: "application/x-ply", input_kind: "gaussian_ply" };

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  history.replaceState({}, "", "/new");
  vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [video, gaussian] } });
  vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [] } });
});

describe("ba cửa vào", () => {
  it("remount giữ form; chuyển video bỏ xác nhận của đầu vào cũ", async () => {
    const second = { ...video, upload_id: "video-2", original_name: "room.mp4" };
    vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [video, second] } });
    const view = render(<VideoSetupStep preselect="video-1" onBack={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Tên scene"), { target: { value: "Tên nháp" } });
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    await waitFor(() => expect(sessionStorage.getItem("studio:draft:video:v1:local")).toContain("Tên nháp"));
    view.unmount();
    render(<VideoSetupStep preselect={null} onBack={vi.fn()} />);
    expect(await screen.findByLabelText("Tên scene")).toHaveValue("Tên nháp");
    screen.getAllByRole("checkbox").forEach((checkbox) => expect(checkbox).toBeChecked());
    fireEvent.click(within(screen.getByRole("group", { name: "Video đã tải lên" })).getAllByRole("radio")[1]);
    screen.getAllByRole("checkbox").forEach((checkbox) => expect(checkbox).not.toBeChecked());
    expect(screen.getByLabelText("Tên scene")).toHaveValue("room");
  });
  it("trang chọn dẫn tới ba trang riêng; mỗi trang chỉ có form của nhánh đó", async () => {
    const chooser = render(<NewSceneFlow />);
    expect(screen.getByRole("link", { name: /Dựng từ video/ })).toHaveAttribute("href", "/new/import-video");
    expect(screen.getByRole("link", { name: /Mở 3DGS/ })).toHaveAttribute("href", "/new/import-scene");
    expect(screen.getByRole("link", { name: /Thử mẫu/ })).toHaveAttribute("href", "/new/try-demo");
    expect(screen.queryByLabelText(/Kéo video/)).toBeNull();
    chooser.unmount();

    const demo = render(<NewSceneFlow source="sample" />);
    expect(await screen.findByText("Chưa có video mẫu")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Kéo video/)).toBeNull();
    expect(screen.getByRole("link", { name: /Đổi cách bắt đầu/ })).toHaveAttribute("href", "/new");
    expect(createSceneFromUpload).not.toHaveBeenCalled();
    expect(createImport).not.toHaveBeenCalled();
    demo.unmount();

    const scene = render(<NewSceneFlow source="gaussian" />);
    expect(screen.getByLabelText(/Kéo file 3DGS/)).toHaveAttribute("accept", ".ply,.zip,application/zip");
    expect(screen.queryByLabelText(/Kéo video/)).toBeNull();
    scene.unmount();

    render(<NewSceneFlow source="video" />);
    expect(screen.getByLabelText(/Kéo video/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Kéo file 3DGS/)).toBeNull();
  });

  it("link cũ /new?source=… và /new?sample=… được chuyển sang trang mới, giữ tham số còn lại", async () => {
    history.replaceState({}, "", "/new?source=video&step=setup&upload=video-1");
    const first = render(<NewSceneFlow />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/new/import-video?step=setup&upload=video-1"));
    first.unmount();
    history.replaceState({}, "", "/new?sample=aisle");
    render(<NewSceneFlow />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/new/try-demo?sample=aisle"));
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
    expect(createImport).toHaveBeenCalledWith("ply-1", "Kho import");
    expect(createSceneFromUpload).not.toHaveBeenCalled();
    expect(navigation.push).not.toHaveBeenCalled();
  });

  it("video loại PLY khỏi lựa chọn; chỉ submit sau đủ khai báo và giữ dữ liệu khi lỗi", async () => {
    vi.mocked(createSceneFromUpload).mockRejectedValue(new Error("Đã hết hạn mức"));
    render(<VideoSetupStep preselect="ply-1" onBack={vi.fn()} />);
    const name = await screen.findByLabelText("Tên scene");
    expect(within(screen.getByRole("group", { name: "Video đã tải lên" })).getAllByRole("radio")).toHaveLength(1);
    const start = screen.getByRole("button", { name: "Bắt đầu xử lý" });
    expect(start).toBeDisabled();
    fireEvent.change(name, { target: { value: "Kho video" } });
    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm thử nghiệm" } });
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    expect(start).toBeEnabled();
    fireEvent.click(start);
    expect(await screen.findByText("Đã hết hạn mức")).toBeInTheDocument();
    expect(name).toHaveValue("Kho video");
    expect(createSceneFromUpload).toHaveBeenCalledWith("video-1", "Kho video", expect.objectContaining({ rights_to_use_confirmed: true, anonymization_confirmed: true, retention_acknowledged: true, declared_owner: "Nhóm thử nghiệm" }), undefined, undefined);
    expect(createImport).not.toHaveBeenCalled();
  });
});

describe("gói LiDAR ở trang dựng từ video", () => {
  const scans: UploadRecord = {
    ...video, upload_id: "lidar-1", original_name: "aisle.zip", media_type: "application/zip", input_kind: "lidar_scan_sequence",
    detection: { kind: "lidar_scan_sequence", gaussian: null, ply_member: null, colmap_dir: null, colmap_format: null,
      lidar: { geometry_format: "pcd", cloud_member: null, point_count: null, scan_count: 100, pose_count: 500, trajectory_member: "traj_gt.txt", calibration_member: "calibrations.txt", calibration_format: "torwic_txt", frame_times_member: "frame_times.txt", pairing: "index_in_name" } },
  };

  it("giải thích ba luồng; không chọn gói thì chạy luồng A và không gửi LiDAR", async () => {
    vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [video, scans] } });
    vi.mocked(createSceneFromUpload).mockResolvedValue({ job: { job_id: "job-1" } } as never);
    render(<VideoSetupStep preselect="video-1" onBack={vi.fn()} />);
    await screen.findByLabelText("Tên scene");
    const flows = within(screen.getByRole("list", { name: "Ba luồng xử lý" }));
    expect(flows.getAllByRole("listitem")).toHaveLength(3);
    expect(flows.getByText(/Luồng A · sẽ chạy/)).toBeInTheDocument();
    expect(screen.getByText(/không tự ước lượng quỹ đạo/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm" } });
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu xử lý" }));
    await waitFor(() => expect(createSceneFromUpload).toHaveBeenCalled());
    expect(vi.mocked(createSceneFromUpload).mock.calls[0][4]).toBeUndefined();
  });

  it("chọn gói scan thô: hiện nhận diện và luồng C, bắt khai đủ rồi mới gửi kèm LiDAR", async () => {
    vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [video, scans] } });
    vi.mocked(createSceneFromUpload).mockResolvedValue({ job: { job_id: "job-1" } } as never);
    render(<VideoSetupStep preselect="video-1" onBack={vi.fn()} />);
    await screen.findByLabelText("Tên scene");
    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm" } });
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    fireEvent.click(screen.getByRole("radio", { name: /aisle\.zip/ }));
    expect(screen.getByText(/100 scan · 500 pose/, { selector: "p" })).toHaveTextContent("luồng C");
    expect(within(screen.getByRole("list", { name: "Ba luồng xử lý" })).getByText(/Luồng C · sẽ chạy/)).toBeInTheDocument();
    const start = screen.getByRole("button", { name: "Bắt đầu xử lý" });
    expect(start).toBeDisabled();
    expect(screen.getByText("Chưa khai nguồn gốc quỹ đạo LiDAR")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /Quỹ đạo chuẩn/ }));
    expect(screen.getByText("Chưa xác nhận video và LiDAR cùng một lượt quay")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /cùng một lượt quay/ }));
    expect(start).toBeEnabled();
    fireEvent.click(start);
    await waitFor(() => expect(createSceneFromUpload).toHaveBeenCalled());
    expect(vi.mocked(createSceneFromUpload).mock.calls[0][4]).toEqual({ upload_id: "lidar-1", trajectory_origin: "ground_truth", same_scene_confirmed: true });
  });
});

describe("upload lifecycle", () => {
  it("chặn đuôi sai nhánh trước khi gửi; unmount abort và bỏ response muộn", async () => {
    let resolve!: (value: UploadRecord) => void;
    const abort = vi.fn();
    vi.mocked(uploadVideo).mockReturnValue({ abort, promise: new Promise((done) => { resolve = done; }) });
    const uploaded = vi.fn();
    const view = render(<UploadDropzone kind="video" onUploaded={uploaded} />);
    const input = screen.getByLabelText(/Kéo video/);
    fireEvent.change(input, { target: { files: [new File(["ply"], "wrong.ply")] } });
    expect(uploadVideo).not.toHaveBeenCalled();
    expect(screen.getByText(/Dựng từ video chỉ nhận/)).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [new File(["video"], "valid.mp4")] } });
    expect(uploadVideo).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(abort).toHaveBeenCalledTimes(1);
    resolve(video);
    await waitFor(() => expect(uploaded).not.toHaveBeenCalled());
  });
});
