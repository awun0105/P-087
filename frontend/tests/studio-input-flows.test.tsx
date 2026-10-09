/** Proof của form/API bằng mock; không thay acceptance video/GPU hoặc renderer. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportSetupStep } from "@/features/studio/ImportSetupStep";
import { NewSceneFlow } from "@/features/studio/NewSceneFlow";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { VideoSetupStep } from "@/features/studio/VideoSetupStep";
import { createImport, createSceneFromUpload, listSamples, listUploads, uploadPreparedVideo, uploadVideo } from "@/lib/api/studio";
import type { Me } from "@/lib/api/auth";
import type { UploadRecord } from "@/lib/contracts/studio";
import { prepareVideoForUpload } from "@/lib/media/video-normalization";
import type { VideoPreparedArtifact } from "@/lib/media/video-normalization";
import { VideoPreparationError } from "@/lib/media/video-normalization-core";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
const authState = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me, refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation, useSearchParams: () => new URLSearchParams() }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => authState }));
const processingState = vi.hoisted(() => ({ evaluation: null as unknown }));
vi.mock("@/features/studio/useProcessingForm", () => ({ useProcessingForm: () => ({ options: null, values: null, evaluation: processingState.evaluation, error: null, activePreset: null }) }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  listUploads: vi.fn(), listSamples: vi.fn(), createImport: vi.fn(), createSceneFromUpload: vi.fn(), uploadVideo: vi.fn(), uploadPreparedVideo: vi.fn(),
}));
vi.mock("@/lib/media/video-normalization", async (original) => ({
  ...(await original<typeof import("@/lib/media/video-normalization")>()),
  prepareVideoForUpload: vi.fn(),
}));

const video: UploadRecord = { upload_id: "video-1", original_name: "warehouse.mp4", media_type: "video/mp4", size_bytes: 100, checksum: "sha256:test", artifact_uri: "artifact://test/video", received_at: "2026-10-01T00:00:00Z", project_ids: [], input_kind: "rgb_video" };
const gaussian: UploadRecord = { ...video, upload_id: "ply-1", original_name: "warehouse.ply", media_type: "application/x-ply", input_kind: "gaussian_ply" };
const sog: UploadRecord = { ...video, upload_id: "sog-1", original_name: "external.sog", media_type: "application/x-sog", input_kind: "gaussian_sog" };
function guestMe(remaining: number): Me {
  return {
    auth_required: true,
    user: { user_id: "guest-1", email: "guest@example.test", display_name: "Guest Test", role: "guest", active: true, daily_job_quota: 10 },
    quota: {
      policy_id: "guest_calendar_day_v1",
      limit: 3,
      used: 3 - remaining,
      remaining,
      window_start_utc: "2026-10-07T17:00:00Z",
      resets_at_utc: "2026-10-08T17:00:00Z",
      timezone: "Asia/Ho_Chi_Minh",
    },
  };
}
function preparedArtifact(bytes = "prepared-video-bytes"): VideoPreparedArtifact {
  const file = new File([bytes], "prepared.mp4", { type: "video/mp4" });
  const frameMapFile = new File(['{"source_frame_id":0}\n'], "frames.jsonl", { type: "application/x-ndjson" });
  return {
    file,
    frameMapFile,
    manifest: {
      prepared_file: { checksum: "sha256:prepared", size_bytes: file.size },
      frame_map: { size_bytes: frameMapFile.size },
      source_video: { display_width: 1080, display_height: 1920, frame_rate: { numerator: 60, denominator: 1 } },
      prepared_video: { display_width: 720, display_height: 1280, frame_rate: { numerator: 30, denominator: 1 } },
      audio_disposition: "preserved",
    },
    dispose: vi.fn().mockResolvedValue(undefined),
  } as unknown as VideoPreparedArtifact;
}

beforeEach(() => {
    processingState.evaluation = null;
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:prepared-video") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  authState.me = { auth_required: false, user: null };
  authState.refresh.mockResolvedValue(undefined);
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
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tạo scene mới");
    // Mẫu và file 3DGS có sẵn không phải dựng mới: tách khỏi lối dựng từ video và nói rõ điều đó.
    expect(screen.getByText("Dùng kết quả đã dựng sẵn")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Thử mẫu/ })).toHaveTextContent("không tạo scene mới");
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
    expect(screen.getByLabelText(/Kéo file 3DGS/)).toHaveAttribute(
      "accept",
      ".ply,.sog,.zip,application/zip,application/x-sog",
    );
    expect(screen.getByText(/PLY\/SOG hoặc ZIP gồm PLY \+ COLMAP/)).toBeInTheDocument();
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
    const firstCall = vi.mocked(createImport).mock.calls[0];
    expect(firstCall?.slice(0, 2)).toEqual(["ply-1", "Kho import"]);
    expect(firstCall?.[2]).toEqual(expect.any(String));
    fireEvent.click(screen.getByRole("button", { name: "Mở scene import" }));
    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(2));
    expect(vi.mocked(createImport).mock.calls[1]?.[2]).toBe(firstCall?.[2]);
    expect(createSceneFromUpload).not.toHaveBeenCalled();
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
  it("quota Guest hiển thị reset, chặn job mới khi hết lượt và refresh sau lần được chấp nhận", async () => {
    authState.me = guestMe(0);
    const capped = render(<VideoSetupStep preselect="video-1" onBack={vi.fn()} />);
    await screen.findByLabelText("Tên scene");
    expect(screen.getByText("Guest còn 0/3 lượt hôm nay.")).toBeInTheDocument();
    expect(screen.getByText(/Đã dùng 3\/3; đặt lại lúc/)).toHaveTextContent("09/10/2026");
    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm thử nghiệm" } });
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    expect(screen.getByRole("button", { name: "Bắt đầu xử lý" })).toBeDisabled();
    expect(createSceneFromUpload).not.toHaveBeenCalled();
    capped.unmount();

    sessionStorage.clear();
    authState.me = guestMe(1);
    vi.mocked(createSceneFromUpload).mockResolvedValue({ job: { job_id: "job-1" } } as never);
    render(<VideoSetupStep preselect="video-1" onBack={vi.fn()} />);
    await screen.findByLabelText("Tên scene");
    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm thử nghiệm" } });
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu xử lý" }));
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/scenes/job-1"));
    expect(authState.refresh).toHaveBeenCalledOnce();
  });
});

describe("trình hướng dẫn mẫu", () => {
  it("có 3 bước như luồng video, không còn bước mở scene riêng", async () => {
    vi.mocked(listSamples).mockResolvedValue({ ok: true, data: { samples: [] } });
    render(<NewSceneFlow source="sample" />);
    expect(screen.getByText("Chọn mẫu")).toBeInTheDocument();
    expect(screen.getByText("Xem thông tin")).toBeInTheDocument();
    expect(screen.getByText("Xem tiến trình")).toBeInTheDocument();
    expect(screen.queryByText("Mở scene mẫu")).toBeNull();
  });
});

describe("cảnh báo tài nguyên ở trang dựng từ video", () => {
  const vram = (status: "ok" | "danger") => ({ resource: "vram", required_gb: 9, available_gb: 4, status, message: "" });
  async function open(evaluation: unknown) {
    processingState.evaluation = evaluation;
    vi.mocked(listUploads).mockResolvedValue({ ok: true, data: { uploads: [video] } });
    render(<VideoSetupStep preselect="video-1" onBack={vi.fn()} />);
    await screen.findByLabelText("Tên scene");
  }

  it("vượt năng lực máy: báo lỗi, ghi lý do cạnh nút, khoá nút và không còn đường tắt sang Colab", async () => {
    await open({ resources: [vram("danger")], parameters: [], blocking: true, note: "" });
    expect(screen.getByRole("alert")).toHaveTextContent("Thông số vượt cấu hình máy xử lý nên chưa bắt đầu được");
    expect(screen.getByRole("alert")).toHaveTextContent("Cần khoảng 9.0 GB VRAM");
    expect(screen.getByText(/Thông số vượt cấu hình máy xử lý \(giảm các ô tô đỏ/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bắt đầu xử lý" })).toBeDisabled();
    expect(screen.queryByText(/Colab/)).toBeNull();
  });

  it("GPU chỉ đang bận: nhắc job sẽ chờ, không chặn và không đòi giảm thông số", async () => {
    await open({ resources: [vram("danger")], parameters: [], blocking: false, note: "" });
    expect(screen.getByText(/GPU đang bận nên job có thể phải chờ/)).toBeInTheDocument();
    expect(screen.queryByText(/chưa bắt đầu được/)).toBeNull();
    expect(screen.queryByText(/Thông số vượt cấu hình máy xử lý \(giảm/)).toBeNull();
  });

  it("bị chặn vì RAM/đĩa chứ không phải VRAM: không bịa số VRAM", async () => {
    await open({ resources: [vram("ok"), { resource: "ram", required_gb: 40, available_gb: 16, status: "danger", message: "" }], parameters: [], blocking: true, note: "" });
    expect(screen.getByRole("alert")).toHaveTextContent("chưa bắt đầu được");
    expect(screen.getByRole("alert")).not.toHaveTextContent("VRAM, GPU");
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
  it("chặn đuôi sai nhánh; chỉ chuẩn bị và xem trước, rồi mới upload theo lựa chọn rõ ràng", async () => {
    const artifact = preparedArtifact();
    vi.mocked(prepareVideoForUpload).mockResolvedValue(artifact);
    let resolve!: (value: UploadRecord) => void;
    const abort = vi.fn();
    vi.mocked(uploadPreparedVideo).mockReturnValue({ abort, promise: new Promise((done) => { resolve = done; }) });
    const uploaded = vi.fn();
    const view = render(<UploadDropzone kind="video" onUploaded={uploaded} />);
    const input = screen.getByLabelText(/Kéo video/);
    fireEvent.change(input, { target: { files: [new File(["ply"], "wrong.ply")] } });
    expect(uploadVideo).not.toHaveBeenCalled();
    expect(screen.getByText(/Dựng từ video chỉ nhận/)).toBeInTheDocument();
    const source = new File(["source-video"], "valid.mp4", { type: "video/mp4" });
    fireEvent.change(input, { target: { files: [source] } });
    expect(uploadVideo).not.toHaveBeenCalled();
    expect(screen.getByRole("radio", { name: /720p/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Chuẩn bị để xem trước" }));
    const preview = await screen.findByLabelText("Xem trước video đã chuẩn bị");
    expect(preview).toHaveAttribute("src", "blob:prepared-video");
    expect(preview).toHaveClass("bg-media-preview-surface");
    expect(prepareVideoForUpload).toHaveBeenCalledWith(expect.objectContaining({ source, preset: "720p" }));
    expect(uploadPreparedVideo).not.toHaveBeenCalled();
    expect(screen.getByText(/Bản đã chuẩn bị lớn hơn video gốc/)).toBeInTheDocument();
    expect(screen.getByText(/Nguồn: 1080 × 1920 \(dọc\)/)).toBeInTheDocument();
    expect(screen.getByText(/720 × 1280 \(dọc\).*tối đa 30 FPS/)).toBeInTheDocument();
    expect(screen.getByText("Âm thanh: đã giữ nguyên âm thanh.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tải bản đã xem trước lên" }));
    expect(uploadPreparedVideo).toHaveBeenCalledWith(artifact, expect.objectContaining({ accountId: "local", existingRecord: null }));
    view.unmount();
    expect(abort).toHaveBeenCalledTimes(1);
    resolve(video);
    await waitFor(() => expect(uploaded).not.toHaveBeenCalled());
    expect(artifact.dispose).toHaveBeenCalledOnce();
  });

  it("chỉ gửi video gốc nếu người dùng chọn rõ khi bản đã chuẩn bị lớn hơn", async () => {
    vi.mocked(prepareVideoForUpload).mockResolvedValue(preparedArtifact());
    const abort = vi.fn();
    vi.mocked(uploadVideo).mockReturnValue({ abort, promise: Promise.resolve(video) });
    render(<UploadDropzone kind="video" onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Kéo video/), { target: { files: [new File(["source"], "source.mp4", { type: "video/mp4" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Chuẩn bị để xem trước" }));
    await screen.findByLabelText("Xem trước video đã chuẩn bị");
    expect(uploadVideo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Tải video gốc không nén" }));
    await waitFor(() => expect(uploadVideo).toHaveBeenCalledOnce());
    expect(uploadPreparedVideo).not.toHaveBeenCalled();
  });

  it("không hỏi về âm thanh: bản đã chuẩn bị luôn bỏ âm thanh và nói rõ điều đó", async () => {
    const artifact = preparedArtifact();
    artifact.manifest.audio_disposition = "omitted_with_user_consent";
    vi.mocked(prepareVideoForUpload).mockResolvedValueOnce(artifact);
    render(<UploadDropzone kind="video" onUploaded={vi.fn()} />);
    const source = new File(["source"], "source.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByLabelText(/Kéo video/), { target: { files: [source] } });
    fireEvent.click(screen.getByRole("button", { name: "Chuẩn bị để xem trước" }));

    await screen.findByLabelText("Xem trước video đã chuẩn bị");
    expect(screen.queryByLabelText(/đồng ý bỏ toàn bộ âm thanh/)).toBeNull();
    expect(screen.getByText("Âm thanh: đã bỏ (bước dựng 3D không dùng âm thanh).")).toBeInTheDocument();
    expect(uploadVideo).not.toHaveBeenCalled();
  });

  it("hiện pha xử lý và hủy chuẩn bị mà không gửi video lên", async () => {
    let rejectPreparation!: (cause: unknown) => void;
    let preparationSignal: AbortSignal | undefined;
    vi.mocked(prepareVideoForUpload).mockImplementation((request) => {
      preparationSignal = request.signal;
      return new Promise<VideoPreparedArtifact>((_resolve, reject) => { rejectPreparation = reject; });
    });
    render(<UploadDropzone kind="video" onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Kéo video/), { target: { files: [new File(["source"], "source.mp4", { type: "video/mp4" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Chuẩn bị để xem trước" }));

    expect(await screen.findByText("Đang đọc và kiểm tra video gốc")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Hủy chuẩn bị" }));
    expect(preparationSignal?.aborted).toBe(true);
    rejectPreparation(new VideoPreparationError("cancelled", "Video preparation cancelled."));
    expect(await screen.findByText("Đã hủy chuẩn bị; video gốc chưa được tải lên.")).toBeInTheDocument();
    expect(uploadVideo).not.toHaveBeenCalled();
    expect(uploadPreparedVideo).not.toHaveBeenCalled();
  });
});
