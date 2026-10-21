/**
 * Trạng thái hình học theo vật (T-013): khoá Draft, nhãn phase, và banner "Tạo mesh".
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GeometryReviewBanner } from "@/features/studio/GeometryReviewBanner";
import { buildObjectGeometry, getObjectifyState, type ObjectifyState } from "@/lib/api/studio";
import type { SceneIR } from "@/lib/contracts/api";
import { GEOMETRY_NOT_READY_REASON, geometryPhaseLabel, objectGeometryState } from "@/lib/scene/geometry-state";

vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getObjectifyState: vi.fn(),
  requestObjectify: vi.fn(),
  cancelObjectify: vi.fn(),
  buildObjectGeometry: vi.fn(),
}));

const scene = (provenance: Record<string, unknown>) => ({ provenance }) as Pick<SceneIR, "provenance">;

function objectify(overrides: Partial<ObjectifyState> = {}): ObjectifyState {
  return {
    status: "idle", mode: null, scene_revision: "rev-001", awaiting_choice: false, object_centric: false, available: true,
    note: null, base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false,
    ...overrides,
  };
}

/** Scene Draft tối thiểu: chỉ các trường banner đọc. */
function draft(objects: { id: string; name: string; review?: string; shellError?: string }[], geometry: string | null = "awaiting_review") {
  return {
    scene_revision: "rev-001",
    provenance: geometry === null ? {} : { object_geometry: geometry },
    // Mỗi vật có một nhãn nguồn; lựa chọn duyệt quyết định vật nào được dựng mesh.
    environment: {
      membership: { label_to_object_id: Object.fromEntries(objects.map((item, index) => [String(index), item.id])) },
    },
    objects: objects.map((item) => ({
      id: item.id,
      name: item.name,
      state: "CONFIRMED",
      active: true,
      collider: null,
      provenance: {
        ...(item.review ? { review: item.review } : {}),
        ...(item.shellError ? { shell_error: item.shellError } : {}),
      },
    })),
  } as unknown as SceneIR;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getObjectifyState).mockResolvedValue(objectify());
});

describe("trạng thái hình học của scene", () => {
  it("thiếu khoá là scene cũ đã sẵn sàng", () => {
    expect(objectGeometryState(scene({}))).toBe("ready");
    expect(objectGeometryState(scene({ object_geometry: "ready" }))).toBe("ready");
  });

  it("awaiting_review là Draft; giá trị lạ bị khoá, không coi là sẵn sàng", () => {
    expect(objectGeometryState(scene({ object_geometry: "awaiting_review" }))).toBe("awaiting_review");
    expect(objectGeometryState(scene({ object_geometry: "building" }))).toBe("awaiting_review");
  });

  it("lý do khoá là câu cố định dùng cho tooltip", () => {
    expect(GEOMETRY_NOT_READY_REASON).toBe("Cần tạo mesh trước");
  });

  it("phase tạo mesh hiện bằng tiếng Việt, phase lạ giữ nguyên mã", () => {
    expect(geometryPhaseLabel("shell")).toBe("Dựng vỏ vật");
    expect(geometryPhaseLabel("collider")).toBe("Tạo collider");
    expect(geometryPhaseLabel("environment")).toBe("Dựng nền và collision môi trường");
    expect(geometryPhaseLabel("publish")).toBe("Lưu kết quả");
    expect(geometryPhaseLabel("new_phase")).toBe("new_phase");
    expect(geometryPhaseLabel(null)).toBeNull();
  });
});

describe("nút Tạo mesh", () => {
  it("scene Draft: giữ nút tạo mesh và bỏ khung thông tin tách vật", async () => {
    render(
      <GeometryReviewBanner
        jobId="job-1"
        scene={draft([
          { id: "pallet", name: "Pallet" },
          { id: "rack", name: "Kệ", shellError: "vỏ rỗng" },
          { id: "old", name: "Đã xoá", review: "DELETED" },
        ])}
        onRevision={vi.fn()}
      />,
    );
    const region = await screen.findByRole("region", { name: "Tạo mesh vật thể" });
    expect(screen.queryByText(/Đang duyệt tách vật/)).not.toBeInTheDocument();
    expect(screen.queryByText(/đã chọn để chỉnh sửa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Vỏ của Kệ/)).not.toBeInTheDocument();
    expect(within(region).getByRole("button", { name: "Tạo mesh cho 2 vật đã chọn" })).toBeEnabled();
  });

  it("vật giữ làm nền không còn bị lỗi vỏ chặn tạo mesh", async () => {
    render(
      <GeometryReviewBanner
        jobId="job-1"
        scene={draft([
          { id: "pallet", name: "Pallet" },
          { id: "chair", name: "Ghế", review: "IGNORED", shellError: "vỏ rỗng" },
        ])}
        onRevision={vi.fn()}
      />,
    );
    const region = await screen.findByRole("region", { name: "Tạo mesh vật thể" });
    expect(within(region).getByRole("button", { name: "Tạo mesh cho 1 vật đã chọn" })).toBeEnabled();
    expect(
      within(region).queryByText(/Vỏ của Ghế/),
    ).not.toBeInTheDocument();
  });

  it("khoá tạo mesh trong lúc đang lưu lựa chọn vật thể", async () => {
    render(<GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }])} busy onRevision={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Tạo mesh cho 1 vật đã chọn" })).toBeDisabled();
    expect(buildObjectGeometry).not.toHaveBeenCalled();
  });

  it("bấm Tạo mesh gửi đúng revision đang hiển thị, rồi khoá nút khi yêu cầu đang chạy", async () => {
    vi.mocked(buildObjectGeometry).mockResolvedValue(objectify({ status: "queued", mode: "geometry", operation_id: "op-1" }));
    render(<GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }])} onRevision={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /Tạo mesh cho/ }));

    await waitFor(() => expect(buildObjectGeometry).toHaveBeenCalledWith("job-1", "rev-001"));
    expect(await screen.findByRole("button", { name: /Tạo mesh cho/ })).toBeDisabled();
  });

  it("khi scene đang có việc objectify chạy thì nút Tạo mesh bị khoá ngay", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "running", mode: "geometry", phase: "shell", operation_id: "op-1" }));
    render(<GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }])} onRevision={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("button", { name: /Tạo mesh cho/ })).toBeDisabled());
    expect(buildObjectGeometry).not.toHaveBeenCalled();
  });

  it("scene sẵn sàng hoặc scene cũ không có khoá: không hiện banner", () => {
    const { container } = render(
      <GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }], "ready")} onRevision={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    const legacy = render(<GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }], null)} onRevision={vi.fn()} />);
    expect(legacy.container).toBeEmptyDOMElement();
  });
});

it("requires a choice for every candidate before starting geometry", async () => {
  const pending = draft([{ id: "window", name: "Cửa sổ" }]);
  pending.objects[0].state = "CANDIDATE";
  pending.objects[0].active = false;
  render(<GeometryReviewBanner jobId="job-1" scene={pending} onRevision={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Tạo mesh cho 0 vật đã chọn" })).toBeDisabled();
  expect(screen.getByText("Duyệt các vật còn lại trước khi tạo mesh.")).toBeInTheDocument();
  expect(buildObjectGeometry).not.toHaveBeenCalled();
});
