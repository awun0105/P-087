import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProcessingSettings } from "@/features/studio/ProcessingSettings";
import { useProcessingForm } from "@/features/studio/useProcessingForm";
import { evaluateProcessing, getProcessingOptions, suggestProcessingPreset } from "@/lib/api/studio";
import type { ParameterSpec, ProcessingOptions } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getProcessingOptions: vi.fn(), evaluateProcessing: vi.fn(), suggestProcessingPreset: vi.fn() }));
const numeric = (key: string, group: ParameterSpec["group"], label: string): ParameterSpec => ({
  key, group, label, description: "Thông số fixture", kind: "number", min: 0, max: 100, step: 0.1, unit: null, choices: null,
});
const choice = (key: string, group: ParameterSpec["group"], label: string, values: string[]): ParameterSpec => ({
  ...numeric(key, group, label), kind: "choice", choices: values.map((value) => ({ value, label: value })),
});
const parameters = [
  numeric("sampling.max_frames", "sampling", "Số ảnh"), choice("colmap.matching_mode", "colmap", "Cách ghép ảnh", ["sequential", "sequential_vocab_tree", "exhaustive"]),
  numeric("brush.max_splats", "brush", "Số Gaussian"), choice("geometry.collision_mesh", "geometry", "Kiểu lưới", ["smooth", "faces"]),
  numeric("geometry.external_fill_size_m", "geometry", "Lấp vùng bên ngoài"), numeric("scene.max_objects", "scene", "Số vật thể"),
  choice("simulation.ground_plane", "simulation", "Sàn vật lý", ["enabled", "disabled"]),
];
const values = { "sampling.max_frames": 30, "colmap.matching_mode": "sequential", "brush.max_splats": 50, "geometry.collision_mesh": "smooth", "geometry.external_fill_size_m": 1.6, "scene.max_objects": 60, "simulation.ground_plane": "enabled" };
const evaluation: ProcessingOptions["default_evaluation"] = { resources: [], parameters: [], blocking: false, note: "fixture" };
const options: ProcessingOptions = { profile_id: "fixture", parameters, presets: { minimum_quality: values, maximum: values, machine_maximum: values }, capability: null, default_evaluation: evaluation, resource_note: "fixture" };

function Form() {
  const form = useProcessingForm(true);
  return form.values && <ProcessingSettings parameters={parameters} values={form.values} editable evaluation={form.evaluation} onChange={form.setValue} onScenario={form.applyScenario} scenarioPreset={form.scenarioPreset} scenarioPreferences={form.scenarioPreferences} scenarioNotes={form.scenarioNotes} suggesting={form.suggesting} activePreset={form.activePreset} />;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getProcessingOptions).mockResolvedValue({ ok: true, data: options });
  vi.mocked(evaluateProcessing).mockResolvedValue({ ok: true, data: evaluation });
  vi.mocked(suggestProcessingPreset).mockImplementation(async (preferences) => ({ ok: true, data: {
    preset_name: "video_outdoor_forward", evaluation, params: { ...values,
      "geometry.external_fill_size_m": preferences.environment === "outdoor" ? 0 : 1.6,
      "colmap.matching_mode": preferences.input_type === "video_loop_360" ? "sequential_vocab_tree" : "sequential",
      "simulation.ground_plane": preferences.environment === "outdoor" ? "disabled" : "enabled",
    },
    notes: preferences.target_capacity === "high_quality"
      ? ["Máy xử lý giới hạn VRAM GPU: giảm số gaussian tối đa xuống 1.800.000 Gaussian", "Video 1280×720: độ phân giải huấn luyện 1.280 px"]
      : [],
  } }));
});

describe("scenario wizard", () => {
  it("applies environment and capture choices through the API and shows all advanced groups", async () => {
    render(<Form />);
    await screen.findByRole("radio", { name: "Ngoài trời" });
    fireEvent.click(screen.getByRole("radio", { name: "Ngoài trời" }));
    await screen.findByText("Video ngoài trời · Chuẩn");
    expect(screen.getByLabelText("Lấp vùng bên ngoài", { selector: "input[type=number]" })).toHaveValue(0);
    fireEvent.click(screen.getByRole("radio", { name: "Video quay vòng 360°" }));
    await waitFor(() => expect(screen.getByLabelText("Cách ghép ảnh")).toHaveValue("sequential_vocab_tree"));
    expect(suggestProcessingPreset).toHaveBeenLastCalledWith(expect.objectContaining({ environment: "outdoor", input_type: "video_loop_360" }), expect.any(AbortSignal));
    fireEvent.click(screen.getByText(/Thông số chi tiết/));
    fireEvent.change(screen.getByLabelText("Kiểu lưới"), { target: { value: "faces" } });
    expect(screen.getByLabelText("Kiểu lưới")).toHaveValue("faces");
    expect(screen.queryByText("Video ngoài trời · Chuẩn")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Video quay vòng 360°" }));
    await waitFor(() => expect(screen.getByLabelText("Kiểu lưới")).toHaveValue("smooth"));
    expect(screen.getByText("Video ngoài trời · Chuẩn")).toBeInTheDocument();
    for (const title of ["Lấy mẫu khung hình", "Ước lượng camera · COLMAP", "Dựng 3D Gaussian Splatting · Brush", "Lưới va chạm Voxel", "Tách vật thể · CoACD", "Mô phỏng · OpenUSD"]) expect(screen.getByText(title)).toBeInTheDocument();
  });

  it("offers two capacity levels, labels them and lists the recommender notes", async () => {
    render(<Form />);
    const level = await screen.findByRole("group", { name: "Mức xử lý" });
    const labels = within(level).getAllByRole("radio").map((radio) => radio.parentElement?.textContent);
    expect(labels).toEqual(["Chuẩn (khuyên dùng)", "Chất lượng cao hơn (lâu hơn, nặng hơn)"]);
    expect(screen.queryByText("Tối đa cho máy này")).not.toBeInTheDocument();
    fireEvent.click(within(level).getByRole("radio", { name: "Chất lượng cao hơn (lâu hơn, nặng hơn)" }));
    await screen.findByText("Video ngoài trời · Chất lượng cao hơn");
    expect(suggestProcessingPreset).toHaveBeenLastCalledWith(expect.objectContaining({ target_capacity: "high_quality", input_type: "video_continuous" }), expect.any(AbortSignal));
    const notes = screen.getByRole("list", { name: "Ghi chú của gợi ý" });
    const items = within(notes).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["Máy xử lý giới hạn VRAM GPU: giảm số gaussian tối đa xuống 1.800.000 Gaussian", "Video 1280×720: độ phân giải huấn luyện 1.280 px"]);
    expect(items[0]).toHaveClass("text-ochre");
    expect(items[1]).not.toHaveClass("text-ochre");
    fireEvent.click(within(level).getByRole("radio", { name: "Chuẩn (khuyên dùng)" }));
    await screen.findByText("Video ngoài trời · Chuẩn");
    expect(screen.queryByRole("list", { name: "Ghi chú của gợi ý" })).not.toBeInTheDocument();
  });

  it("preserves full read-only values and disables every parameter control", () => {
    render(<ProcessingSettings parameters={parameters} values={values} editable={false} />);
    expect(screen.queryByRole("region", { name: "Chọn nhanh kịch bản" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Kiểu lưới")).toHaveValue("smooth");
    for (const control of document.querySelectorAll("input, select")) expect(control).toBeDisabled();
    expect(screen.getByText("Mô phỏng · OpenUSD")).toBeInTheDocument();
  });

  it("does not invent a default for controls absent from an older sample", () => {
    const recorded = Object.fromEntries(Object.entries(values).filter(([key]) => key !== "geometry.collision_mesh"));
    render(<ProcessingSettings parameters={parameters} values={recorded} editable={false} />);
    expect(screen.getByText("Không được ghi lại trong video mẫu.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Kiểu lưới")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Cách ghép ảnh")).toHaveValue("sequential");
  });
});

const reviewParameters = [...parameters, choice("scene.geometry_review", "scene", "Duyệt tách vật trước khi tạo mesh", ["required", "auto"])];
const reviewValues = { ...values, "scene.geometry_review": "required" };
const REQUIRED_LABEL = "Dừng để duyệt và chỉnh vùng vật (khuyên dùng)";
const AUTO_LABEL = /Tạo mesh ngay, không duyệt/;

describe("lựa chọn duyệt tách vật", () => {
  it("đặt ngoài thông số nâng cao và mặc định theo giá trị niêm phong", () => {
    render(<ProcessingSettings parameters={reviewParameters} values={reviewValues} editable onChange={vi.fn()} />);
    const group = screen.getByRole("group", { name: "Sau khi tách vật" });
    expect(document.querySelector("details")).not.toContainElement(group);
    expect(screen.getByRole("radio", { name: REQUIRED_LABEL })).toBeChecked();
    expect(screen.getByRole("radio", { name: AUTO_LABEL })).not.toBeChecked();
  });

  it("chọn Tạo mesh ngay gửi scene.geometry_review = auto", () => {
    const onChange = vi.fn();
    render(<ProcessingSettings parameters={reviewParameters} values={reviewValues} editable onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: AUTO_LABEL }));
    expect(onChange).toHaveBeenCalledWith("scene.geometry_review", "auto");
  });

  it("không lặp trong thông số nâng cao, và số đếm chỉ tính các ô còn trong danh sách", () => {
    render(<ProcessingSettings parameters={reviewParameters} values={reviewValues} editable onChange={vi.fn()} />);
    const details = document.querySelector("details") as HTMLElement;
    expect(within(details).queryByLabelText("Duyệt tách vật trước khi tạo mesh")).not.toBeInTheDocument();
    expect(screen.getByText("Thông số chi tiết (7 tham số)")).toBeInTheDocument();
  });

  it("khi chỉ đọc hiện đúng giá trị đã niêm phong và khoá cả hai lựa chọn", () => {
    render(<ProcessingSettings parameters={reviewParameters} values={{ ...reviewValues, "scene.geometry_review": "auto" }} editable={false} />);
    expect(screen.getByRole("radio", { name: AUTO_LABEL })).toBeChecked();
    expect(screen.getByRole("radio", { name: AUTO_LABEL })).toBeDisabled();
    expect(screen.getByRole("radio", { name: REQUIRED_LABEL })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: REQUIRED_LABEL })).toBeDisabled();
  });

  it("không bịa lựa chọn khi giá trị đã ghi không có khóa duyệt tách vật", () => {
    const recorded = Object.fromEntries(Object.entries(reviewValues).filter(([key]) => key !== "scene.geometry_review"));
    render(<ProcessingSettings parameters={reviewParameters} values={recorded} editable={false} />);
    expect(screen.getByText("Scene này tạo trước khi có lựa chọn này nên không dừng để duyệt.")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: AUTO_LABEL })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: REQUIRED_LABEL })).not.toBeInTheDocument();
  });

  it("không hiện khối khi preset không có khóa duyệt tách vật (preset cũ)", () => {
    render(<ProcessingSettings parameters={parameters} values={values} editable onChange={vi.fn()} />);
    expect(screen.queryByRole("group", { name: "Sau khi tách vật" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: AUTO_LABEL })).not.toBeInTheDocument();
  });
});
