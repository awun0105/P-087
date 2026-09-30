/**
 * ObjectReviewView (ADR 0006, PRODUCT-07): xác nhận/loại ứng viên gửi đúng revision, UI hiển
 * thị revision backend trả về. Canvas 3D được thay bằng stub (jsdom không có WebGL).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectReviewView } from "@/features/studio/ObjectReviewView";

vi.mock("@/features/studio/StageViewer", () => ({
  CollisionMeshCanvas: () => <div data-testid="mesh" />,
}));
vi.mock("@/features/studio/MetricSceneView", () => ({
  MetricSceneView: ({ boxes }: { boxes: { id: string; color: string }[] }) => (
    <div data-testid="metric-scene">{boxes.map((box) => `${box.id}:${box.color}`).join(",")}</div>
  ),
}));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getStageViews: vi.fn(async () => []),
}));

const ref = {
  artifact_type: "SceneObjectGeometry",
  schema_version: "1.0",
  artifact_uri: "artifact://jobs/job-a/scene/candidates/x.glb",
  artifact_checksum: "sha256:" + "a".repeat(64),
  data_class: "derived",
  producer_stage: "ST-OBJECT-ASSOC",
  job_id: "job-a",
};

function scene(revision: string, state: "CANDIDATE" | "CONFIRMED", review?: string) {
  return {
    scene_revision: revision,
    environment: {
      geometry_ref: { ...ref, artifact_uri: "artifact://jobs/job-a/rec05/collision.glb" },
      visual_ref: { ...ref, artifact_uri: "artifact://jobs/job-a/rec06/scene.sog" },
    },
    provenance: { object_extraction: "sampro3d_sam2_v1" },
    objects: [
      {
        id: "candidate-001",
        name: "Vật thể 1",
        state,
        active: state === "CONFIRMED",
        origin: "reconstructed",
        transform: { translation_xyz: [1, 2, 0.3], rotation_quaternion_xyzw: [0, 0, 0, 1] },
        primitive_dimensions_xyz_m: [1, 0.8, 0.6],
        geometry_ref: ref,
        provenance: review ? { review } : {},
      },
    ],
  };
}

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

/** Mock fetch theo URL: mỗi route một hàng đợi phản hồi, gói mô phỏng mặc định chưa có. */
function routeFetch(routes: Record<string, Response[]>) {
  vi.mocked(global.fetch).mockImplementation(async (input) => {
    const url = String(input);
    const key = Object.keys(routes).find((pattern) => url.includes(pattern));
    if (key && routes[key].length) return routes[key].shift()!;
    if (url.includes("/simulation-package")) return reply(null);
    throw new Error(`fetch không mong đợi: ${url}`);
  });
}

function calls(pattern: string) {
  return vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes(pattern));
}

describe("ObjectReviewView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("xác nhận ứng viên với revision hiện tại và hiển thị revision mới", async () => {
    routeFetch({
      "/objects/candidate-001/confirm": [
        reply({ scene_revision: "rev-002", scene: scene("rev-002", "CONFIRMED", "CONFIRMED") }),
      ],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText("1 vật thể · 1 chờ xác nhận")).toBeInTheDocument();
    // Hộp ứng viên màu vàng phủ trên 3DGS hệ mét.
    expect(screen.getByTestId("metric-scene")).toHaveTextContent("candidate-001:#facc15");
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận/ }));
    await waitFor(() => expect(screen.getByText("Đã xác nhận")).toBeInTheDocument());
    const [[url, init]] = calls("/confirm");
    expect(String(url)).toContain("/api/v1/jobs/job-a/scene/objects/candidate-001/confirm");
    expect(JSON.parse((init as RequestInit).body as string).expected_scene_revision).toBe("rev-001");
  });

  it("ẩn ứng viên đã loại trừ khi bật hiển thị", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-003", "CANDIDATE", "IGNORED") })] });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText("1 vật thể · 0 chờ xác nhận")).toBeInTheDocument();
    expect(screen.queryByText("Vật thể 1")).toBeNull();
    fireEvent.click(screen.getByLabelText("Hiện cả ứng viên đã loại"));
    expect(screen.getByText("Đã loại")).toBeInTheDocument();
  });

  it("báo rõ khi bước tách vật thể chưa có scene", async () => {
    routeFetch({ "/scene": [reply({ detail: "Job chưa publish SceneIR" }, 404)] });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText(/Chưa có vật thể/)).toBeInTheDocument();
  });

  it("tạo gói mô phỏng: preflight chưa đạt thì hiện mục lỗi, không có nút tải", async () => {
    const failed = {
      scene_revision: "rev-002",
      source_scene_revision: "rev-001",
      created_at: "2026-09-30T00:00:00Z",
      confirmed_objects: 1,
      environment_triangles: 1000,
      carved_triangles: 20,
      preflight: {
        blocking_result: "FAIL",
        rules: [
          { rule_id: "METRIC_SCALE_MISSING", result: "PASS", affected_object_ids: [], remediation: null },
          {
            rule_id: "OBJECT_OUT_OF_BOUNDS",
            result: "FAIL",
            affected_object_ids: ["user-001"],
            remediation: "Điều chỉnh vật thể về trong ranh giới kho",
          },
        ],
      },
      package_ref: null,
    };
    routeFetch({ "/scene": [reply({ scene: scene("rev-001", "CONFIRMED", "CONFIRMED") })] });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("1 vật thể · 0 chờ xác nhận");
    vi.mocked(global.fetch).mockImplementationOnce(async () => reply(failed));
    fireEvent.click(screen.getByRole("button", { name: "Tạo gói mô phỏng" }));
    expect(await screen.findByText("Vật nằm trong kho, trên sàn")).toBeInTheDocument();
    expect(screen.getByText(/user-001/)).toBeInTheDocument();
    expect(screen.queryByText(/Tải gói/)).toBeNull();
    expect(screen.getByText(/Chưa đạt kiểm tra/)).toBeInTheDocument();
  });
});
