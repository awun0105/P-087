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
    expect(geometryPhaseLabel("collider")).toBe("Tạo collider (CoACD)");
    expect(geometryPhaseLabel("environment")).toBe("Dựng nền và collision môi trường");
    expect(geometryPhaseLabel("publish")).toBe("Lưu revision");
    expect(geometryPhaseLabel("new_phase")).toBe("new_phase");
    expect(geometryPhaseLabel(null)).toBeNull();
  });
});

describe("banner Duyệt tách vật", () => {
  it("scene Draft: đếm vật còn giữ và cảnh báo vật có lỗi vỏ", async () => {
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
    const region = await screen.findByRole("region", { name: "Duyệt tách vật" });
    expect(within(region).getByText("Đang duyệt tách vật · 2 vật · chưa có collider")).toBeInTheDocument();
    expect(within(region).getByText("Vỏ của Kệ chưa dựng được — sửa vùng trước khi Tạo mesh")).toBeInTheDocument();
    expect(within(region).getByRole("button", { name: "Tạo mesh" })).toBeEnabled();
  });

  it("bấm Tạo mesh gửi đúng revision đang hiển thị, rồi khoá nút khi yêu cầu đang chạy", async () => {
    vi.mocked(buildObjectGeometry).mockResolvedValue(objectify({ status: "queued", mode: "geometry", operation_id: "op-1" }));
    render(<GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }])} onRevision={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Tạo mesh" }));

    await waitFor(() => expect(buildObjectGeometry).toHaveBeenCalledWith("job-1", "rev-001"));
    expect(await screen.findByRole("button", { name: "Tạo mesh" })).toBeDisabled();
  });

  it("khi scene đang có việc objectify chạy thì nút Tạo mesh bị khoá ngay", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "running", mode: "geometry", phase: "shell", operation_id: "op-1" }));
    render(<GeometryReviewBanner jobId="job-1" scene={draft([{ id: "pallet", name: "Pallet" }])} onRevision={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Tạo mesh" })).toBeDisabled());
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
