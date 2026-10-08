/**
 * ObjectReviewView (ADR 0006, PRODUCT-07): xác nhận/loại ứng viên gửi đúng revision, UI hiển
 * thị revision backend trả về. Canvas 3D được thay bằng stub (jsdom không có WebGL).
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectReviewView, type SaveState } from "@/features/studio/ObjectReviewView";
import { SimulationPackagePanel } from "@/features/studio/SimulationPackagePanel";

vi.mock("@/features/studio/StageViewer", () => ({
  CollisionMeshCanvas: () => <div data-testid="mesh" />,
}));
vi.mock("@/features/studio/MetricSceneView", () => ({
  MetricSceneView: ({
    boxes,
    objects = [],
    physicsObjects = [],
    gizmo,
    onTool,
    onDelete,
  }: {
    boxes: { id: string; color: string; center: [number, number, number]; rotation_xyzw: [number, number, number, number] }[];
    objects?: { id: string; url: string | null; visible: boolean }[];
    physicsObjects?: {
      id: string;
      position: [number, number, number];
      rotation_xyzw: [number, number, number, number];
      colliderLocalTransform: { translation_xyz: [number, number, number] } | null;
    }[];
    gizmo?: { id: string; mode: string } | null;
    onTool?: (tool: "translate" | "rotate" | "none") => void;
    onDelete?: () => void;
  }) => (
    <div data-testid="metric-scene" data-boxes={JSON.stringify(boxes)} data-physics-objects={JSON.stringify(physicsObjects)}>
      {boxes.map((box) => `${box.id}:${box.color}`).join(",")}
      <span data-testid="splats">{objects.map((item) => `${item.id}:${item.url ? "ply" : "none"}:${item.visible}`).join(",")}</span>
      <span data-testid="gizmo">{gizmo ? `${gizmo.id}:${gizmo.mode}` : "none"}</span>
      {onTool && <button type="button" onClick={() => onTool("translate")}>Dịch</button>}
      {onDelete && <button type="button" onClick={onDelete}>Xoá</button>}
    </div>
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

function scene(
  revision: string,
  state: "CANDIDATE" | "CONFIRMED",
  review?: string,
  mergedInto?: string,
  colliderOffset?: [number, number, number],
) {
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
        local_frame: "candidate-001",
        transform: { translation_xyz: [1, 2, 0.3], rotation_quaternion_xyzw: [0, 0, 0, 1] },
        primitive_dimensions_xyz_m: [1, 0.8, 0.6],
        geometry_ref: ref,
        collider: colliderOffset
          ? {
              collider_id: "collider-001",
              collider_type: "CONVEX_DECOMPOSITION",
              dimensions_xyz_m: null,
              local_transform: {
                semantics: "parent_from_local",
                parent_frame: "candidate-001",
                local_frame: "collider-001",
                translation_xyz: colliderOffset,
                rotation_quaternion_xyzw: [0, 0, 0, 1],
                quaternion_order: "xyzw",
                angle_unit: "radian",
              },
              geometry_ref: { ...ref, artifact_uri: "artifact://jobs/job-a/scene/objects/collider.glb" },
              parameters: {},
              provenance: {},
            }
          : null,
        physics: colliderOffset
          ? {
              dynamic: true,
              mass_kg: 10,
              mass_source: "user",
              static_friction: 0.6,
              dynamic_friction: 0.5,
              restitution: 0,
              provenance: {},
            }
          : null,
        provenance: review ? { review, ...(mergedInto ? { merged_into: mergedInto } : {}) } : {},
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
    // Danh mục asset (pipeline v2): người dùng chọn asset, nhãn gửi đi là lớp của asset.
    if (url.includes("/scene/catalog"))
      return reply({
        classes: ["pallet", "box"],
        entries: [
          { family: "SM_PaletteA", semantic_class: "pallet", size_xyz_m: [1.2, 1.0, 0.15], dynamic: true, default_mass_kg: 25 },
          { family: "SM_CardBoxA", semantic_class: "box", size_xyz_m: [0.4, 0.4, 0.3], dynamic: true, default_mass_kg: null },
        ],
        physics_note: "",
      });
    // Trạng thái tách theo vật: mặc định scene đã là scene theo vật (không hiện thông báo), trừ khi test tự cấp.
    if (url.includes("/scene/objectify/cancel")) {
      const cancelled = routes["/scene/objectify/cancel"];
      return cancelled?.length ? cancelled.shift()! : reply(objectify({ status: "cancelled", cancellation_requested: true }));
    }
    if (url.includes("/scene/objectify")) {
      const queued = routes["/scene/objectify"];
      return queued?.length ? queued.shift()! : reply(objectify({ object_centric: true }));
    }
    const key = Object.keys(routes).find((pattern) => url.includes(pattern));
    if (key && routes[key].length) return routes[key].shift()!;
    if (url.includes("/simulation-package")) return reply(null);
    if (url.includes("/review-state")) {
      return reply({ record: { scene_revision: "rev-001", status: "DRAFT", candidate_checksum: null, validation_report_checksum: null }, validation: null, warning_ids: [], approval: null, release: null, release_archive: null, blockers: ["Chưa có gói mô phỏng"] });
    }
    throw new Error(`fetch không mong đợi: ${url}`);
  });
}

function objectify(overrides: Record<string, unknown>) {
  return { status: "idle", mode: null, awaiting_choice: false, object_centric: false, available: true, note: null, base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false, ...overrides };
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
    // Màu khung lấy từ bảng màu (ochre = ứng viên); jsdom không nạp CSS nên nhận giá trị dự phòng của bảng mặc định.
    expect(screen.getByTestId("metric-scene")).toHaveTextContent("candidate-001:#b7862a");
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận Vật thể 1" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Đã loại/xoá/gộp · 1" }));
    expect(screen.getByText("Vật thể 1")).toBeInTheDocument();
    expect(screen.getByText("Đã loại")).toBeInTheDocument();
  });

  it("inspector đổi tên gửi revision hiện tại; báo trạng thái lưu lên header", async () => {
    const renamed = scene("rev-002", "CONFIRMED", "CONFIRMED");
    renamed.objects[0].name = "Pallet A";
    routeFetch({
      "/objects/candidate-001/rename": [reply({ scene_revision: "rev-002", scene: renamed })],
      "/scene": [reply({ scene: scene("rev-001", "CONFIRMED", "CONFIRMED") })],
    });
    const states: string[] = [];
    render(<ObjectReviewView jobId="job-a" onSaveState={(state) => states.push(`${state.status}:${state.revision}`)} />);
    const choose = await screen.findByRole("button", { name: "Chọn Vật thể 1" });
    expect(choose).toHaveAttribute("aria-pressed", "false");
    choose.focus();
    expect(choose).toHaveFocus();
    fireEvent.click(choose);
    expect(choose).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByLabelText("Tên"), { target: { value: "Pallet A" } });
    fireEvent.click(screen.getByRole("button", { name: /Đổi tên/ }));
    await waitFor(() => expect(states).toContain("saved:rev-002"));
    expect(states).toEqual(["saved:rev-001", "saving:rev-001", "saved:rev-002"]);
    const [[, init]] = calls("/rename");
    expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({ expected_scene_revision: "rev-001", name: "Pallet A" });
  });

  it("409 (scene đổi ở lượt khác): báo lỗi lưu, thử lại là tải bản mới", async () => {
    routeFetch({
      "/objects/candidate-001/confirm": [reply({ detail: "scene đã đổi" }, 409)],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") }), reply({ scene: scene("rev-004", "CANDIDATE") })],
    });
    let last: SaveState | null = null;
    render(<ObjectReviewView jobId="job-a" onSaveState={(state) => (last = state)} />);
    fireEvent.click(await screen.findByRole("button", { name: "Xác nhận Vật thể 1" }));
    expect(await screen.findByText(/Scene đã đổi ở lượt khác/)).toBeInTheDocument();
    expect(last).toMatchObject({ status: "error", revision: "rev-001" });
    act(() => (last as unknown as { retry: () => void }).retry());
    await waitFor(() => expect(last).toMatchObject({ status: "saved", revision: "rev-004" }));
  });

  it("scene theo vật: Gaussian riêng của vật tới viewer; vật đã xoá không vẽ; gizmo theo công cụ đang chọn", async () => {
    const v2 = scene("rev-005", "CONFIRMED", "CONFIRMED");
    const gaussians = { ...ref, artifact_type: "ObjectGaussians", artifact_uri: "artifact://jobs/job-a/scene/objects/x.ply" };
    v2.objects[0] = { ...v2.objects[0], visual_ref: gaussians } as (typeof v2.objects)[0];
    const deleted = scene("rev-006", "CONFIRMED", "DELETED");
    deleted.objects[0] = { ...deleted.objects[0], active: false, visual_ref: gaussians } as (typeof deleted.objects)[0];
    routeFetch({
      "/objects/candidate-001/delete": [reply({ scene_revision: "rev-006", scene: deleted })],
      "/scene": [reply({ scene: v2 })],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByTestId("splats")).toHaveTextContent("candidate-001:ply:true");

    fireEvent.click(screen.getByText("Vật thể 1"));
    fireEvent.click(screen.getByRole("button", { name: /Dịch/ }));
    expect(screen.getByTestId("gizmo")).toHaveTextContent("candidate-001:translate");

    fireEvent.click(screen.getByRole("button", { name: /Xoá/ }));
    await waitFor(() => expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:false"));
    expect(screen.getByTestId("gizmo")).toHaveTextContent("none");
  });

  it("gán nhãn gửi nhãn + khối lượng người dùng nhập; hoàn tác quay về revision trước", async () => {
    const base = scene("rev-002", "CONFIRMED", "CONFIRMED");
    (base.provenance as Record<string, unknown>).edited_from = "rev-001";
    const labelledScene = scene("rev-003", "CONFIRMED", "CONFIRMED");
    (labelledScene.provenance as Record<string, unknown>).edited_from = "rev-002";
    routeFetch({
      "/objects/candidate-001/label": [reply({ scene_revision: "rev-003", scene: labelledScene })],
      "/scene/restore": [reply({ scene_revision: "rev-004", scene: scene("rev-004", "CONFIRMED", "CONFIRMED") })],
      "/scene": [reply({ scene: base })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByText("Vật thể 1"));
    fireEvent.change(await screen.findByLabelText(/Nhãn/), { target: { value: "SM_PaletteA" } });
    expect(screen.getByText(/khối lượng mặc định 25 kg/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Khối lượng/), { target: { value: "31.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu nhãn" }));
    // "/label-suggestions" cũng chứa "/label": chỉ lấy đúng lệnh gán nhãn.
    const labelled = () => calls("/label").filter(([url]) => String(url).endsWith("/label"));
    await waitFor(() => expect(labelled()).toHaveLength(1));
    expect(JSON.parse((labelled()[0][1] as RequestInit).body as string)).toMatchObject({
      expected_scene_revision: "rev-002",
      semantic_class: "pallet",
      asset_family: "SM_PaletteA",
      mass_kg: 31.5,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    await waitFor(() => expect(calls("/scene/restore")).toHaveLength(1));
    expect(JSON.parse((calls("/scene/restore")[0][1] as RequestInit).body as string)).toMatchObject({
      expected_scene_revision: "rev-003",
      target_revision: "rev-002",
    });
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
    // Panel gói nằm ở tab "Kiểm tra & duyệt" (D-07), không còn trong danh sách vật thể.
    routeFetch({});
    render(<SimulationPackagePanel jobId="job-a" sceneRevision="rev-001" onSceneChanged={() => {}} />);
    const create = await screen.findByRole("button", { name: "Tạo gói mô phỏng" });
    vi.mocked(global.fetch).mockImplementationOnce(async () => reply(failed));
    fireEvent.click(create);
    expect(await screen.findByText("Vật nằm trong kho, trên sàn")).toBeInTheDocument();
    expect(screen.getByText(/user-001/)).toBeInTheDocument();
    expect(screen.queryByText(/Tải gói/)).toBeNull();
    expect(screen.getByText(/Chưa đạt Preflight/)).toBeInTheDocument();
  });
  it("báo số tam giác nền được giữ lại vì chung hộp với ứng viên chưa xử lý, không chặn tải gói", async () => {
    const built = {
      scene_revision: "rev-003",
      source_scene_revision: "rev-002",
      created_at: "2026-10-08T00:00:00Z",
      confirmed_objects: 1,
      environment_triangles: 1000,
      carved_triangles: 20,
      retained_shared_triangles: 246,
      retained_shared_object_ids: ["candidate-023", "candidate-009"],
      preflight: { blocking_result: "PASS", rules: [] },
      export_capability: null,
      package_ref: { artifact_uri: "artifact://candidate", artifact_checksum: "sha256:candidate" },
    };
    routeFetch({});
    render(<SimulationPackagePanel jobId="job-a" sceneRevision="rev-003" onSceneChanged={() => {}} />);
    const create = await screen.findByRole("button", { name: "Tạo gói mô phỏng" });
    vi.mocked(global.fetch).mockImplementationOnce(async () => reply(built));
    fireEvent.click(create);

    const notice = await screen.findByRole("status", { name: "Tam giác nền được giữ lại" });
    expect(notice).toHaveTextContent("246");
    expect(notice).toHaveTextContent("candidate-023, candidate-009");
    expect(notice).toHaveTextContent("Xác nhận hoặc xoá các ứng viên đó");
    expect(screen.getByRole("link", { name: /Tải gói USD/ })).toBeInTheDocument();
  });
  it("không hiện thông báo giữ lại khi không có tam giác dùng chung", async () => {
    const built = {
      scene_revision: "rev-003",
      source_scene_revision: "rev-002",
      created_at: "2026-10-08T00:00:00Z",
      confirmed_objects: 1,
      environment_triangles: 1000,
      carved_triangles: 20,
      preflight: { blocking_result: "PASS", rules: [] },
      export_capability: null,
      package_ref: { artifact_uri: "artifact://candidate", artifact_checksum: "sha256:candidate" },
    };
    routeFetch({});
    render(<SimulationPackagePanel jobId="job-a" sceneRevision="rev-003" onSceneChanged={() => {}} />);
    const create = await screen.findByRole("button", { name: "Tạo gói mô phỏng" });
    vi.mocked(global.fetch).mockImplementationOnce(async () => reply(built));
    fireEvent.click(create);

    expect(await screen.findByRole("link", { name: /Tải gói USD/ })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Tam giác nền được giữ lại" })).toBeNull();
  });
  it("hiện lưu ý vật danh mục xuất bằng hộp nhưng không chặn tải gói", async () => {
    const built = {
      scene_revision: "rev-003",
      source_scene_revision: "rev-002",
      created_at: "2026-10-08T00:00:00Z",
      confirmed_objects: 2,
      environment_triangles: 1000,
      carved_triangles: 20,
      preflight: { blocking_result: "PASS", rules: [] },
      export_capability: {
        scene_revision: "rev-003",
        scene_ir_checksum: "sha256:scene",
        status: "supported",
        requested_mode: "auto",
        effective_mode: "hybrid",
        builder_version: "usd-export-capabilities-v2",
        runtime_qualification: "qualified",
        runtime_version: "0.25.5",
        requirements: {
          collider_types: ["aabb"],
          static_physics: false,
          dynamic_physics: true,
          local_collider_offsets: false,
          hybrid_visuals: false,
          external_assets: false,
        },
        blockers: [],
        notices: [
          {
            code: "CATALOG_ASSET_EXPORTED_AS_BOX",
            message: "Vật từ danh mục Isaac được xuất bằng collider hộp.",
            affected_object_ids: ["asset-001", "asset-002"],
          },
        ],
      },
      package_ref: { artifact_uri: "artifact://candidate", artifact_checksum: "sha256:candidate" },
    };
    routeFetch({});
    render(<SimulationPackagePanel jobId="job-a" sceneRevision="rev-003" onSceneChanged={() => {}} />);
    const create = await screen.findByRole("button", { name: "Tạo gói mô phỏng" });
    vi.mocked(global.fetch).mockImplementationOnce(async () => reply(built));
    fireEvent.click(create);

    const notices = await screen.findByRole("list", { name: "Lưu ý khi xuất USD" });
    expect(notices).toHaveTextContent("Vật từ danh mục Isaac được xuất bằng collider hộp.");
    expect(notices).toHaveTextContent("Vật liên quan: asset-001, asset-002");
    expect(screen.getByText(/Khả năng xuất USD: Sẵn sàng/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("link", { name: /Tải gói USD/ })).toBeInTheDocument();
  });
  it("hiện riêng blocker USD dù Preflight đạt và cho thử lại đúng scene", async () => {
    const blocked = {
      scene_revision: "rev-001",
      source_scene_revision: "rev-001",
      scene_ir_checksum: "sha256:scene",
      created_at: "2026-10-08T00:00:00Z",
      confirmed_objects: 1,
      environment_triangles: 1000,
      carved_triangles: 20,
      preflight: { blocking_result: "PASS", rules: [] },
      export_capability: {
        schema_version: "1.0",
        scene_revision: "rev-001",
        scene_ir_checksum: "sha256:scene",
        status: "blocked",
        requested_mode: "auto",
        effective_mode: "hybrid",
        builder_version: "usd-export-capabilities-v2",
        runtime_qualification: "failed",
        runtime_version: null,
        requirements: {
          collider_types: ["convex_decomposition"],
          static_physics: false,
          dynamic_physics: true,
          local_collider_offsets: false,
          hybrid_visuals: true,
          external_assets: false,
        },
        blockers: [
          {
            code: "USD_RUNTIME_UNQUALIFIED",
            message: "The configured USD Python runtime did not pass the required API capability probe.",
            affected_object_ids: ["object-1"],
          },
        ],
      },
      candidate: null,
      package_ref: null,
    };
    routeFetch({});
    render(<SimulationPackagePanel jobId="job-a" sceneRevision="rev-001" onSceneChanged={() => {}} />);

    const retry = await screen.findByRole("button", { name: "Tạo gói mô phỏng" });
    vi.mocked(global.fetch).mockImplementationOnce(async () => reply(blocked));
    fireEvent.click(retry);

    expect(await screen.findByText("USD_RUNTIME_UNQUALIFIED")).toBeInTheDocument();
    expect(screen.getByText(/configured USD Python runtime/)).toBeInTheDocument();
    expect(screen.getByText(/Khả năng xuất USD: Bị chặn · hybrid/)).toBeInTheDocument();
    expect(screen.queryByText(/Chưa đạt Preflight/)).toBeNull();
    expect(await screen.findByRole("button", { name: "Thử lại xuất USD" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Tải gói USD/ })).toBeNull();
    expect(screen.getByText(/Candidate chưa được tạo/)).toBeInTheDocument();

    const posts = calls("/simulation-package").filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts).toHaveLength(1);
    expect((posts[0][1] as RequestInit).body).toBeUndefined();
  });
  it("giữ object đã gộp trong nhóm audit và không cho sửa tombstone", async () => {
    routeFetch({
      "/scene": [reply({ scene: scene("rev-003", "CANDIDATE", "MERGED", "candidate-002") })],
    });
    render(<ObjectReviewView jobId="job-a" />);

    expect(await screen.findByText("1 vật thể · 0 chờ xác nhận")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Đã loại/xoá/gộp · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));

    expect(screen.getAllByText("Đã gộp vào candidate-002").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Khôi phục Vật thể 1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Đổi tên" })).toBeNull();
  });

  it("dùng collider local transform cho preview và physics pose", async () => {
    routeFetch({
      "/scene": [reply({ scene: scene("rev-004", "CONFIRMED", "CONFIRMED", undefined, [2, -1, 0.5]) })],
    });
    render(<ObjectReviewView jobId="job-a" />);

    const metricScene = await screen.findByTestId("metric-scene");
    const boxes = JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]") as { center: number[] }[];
    const physicsObjects = JSON.parse(metricScene.getAttribute("data-physics-objects") ?? "[]") as {
      position: number[];
      colliderLocalTransform: { translation_xyz: number[] } | null;
    }[];
    expect(boxes[0]?.center).toEqual([3, 1, 0.8]);
    expect(physicsObjects[0]?.position).toEqual([1, 2, 0.3]);
    expect(physicsObjects[0]?.colliderLocalTransform?.translation_xyz).toEqual([2, -1, 0.5]);
  });

  it("tách theo vật lỗi sau 3 lần: cho chọn chạy lại hoặc dùng hộp; chọn hộp gửi mode boxes", async () => {
    routeFetch({
      "/scene/objectify": [
        reply(objectify({ awaiting_choice: true, note: "tách theo vật lỗi sau 3 lần: hết VRAM" })),
        reply(objectify({ status: "queued", mode: "boxes", awaiting_choice: true, base_revision: "rev-002" })),
      ],
      "/scene": [reply({ scene: scene("rev-002", "CONFIRMED", "CONFIRMED") })],
    });
    render(<ObjectReviewView jobId="job-a" />);

    expect(await screen.findByText(/không thành công sau 3 lần thử/)).toBeTruthy();
    expect(screen.getByText(/hết VRAM/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Chạy lại tách theo vật/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Dùng hộp ứng viên/ }));

    const posts = () => calls("/scene/objectify").filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(JSON.parse((posts()[0][1] as RequestInit).body as string)).toEqual({ expected_scene_revision: "rev-002", mode: "boxes" });
    expect(await screen.findByText(/Đang dựng hộp ứng viên/)).toBeTruthy();
  });

  it("hủy objectify đang chạy và giữ trạng thái dừng cho đến worker acknowledgement", async () => {
    routeFetch({
      "/scene/objectify": [reply(objectify({ status: "running", mode: "objectify" }))],
      "/scene/objectify/cancel": [
        reply(objectify({ status: "running", mode: "objectify", cancellation_requested: true })),
      ],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })],
    });
    render(<ObjectReviewView jobId="job-a" />);

    expect(await screen.findByText(/Đang chạy lại tách theo vật/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Hủy yêu cầu" }));

    expect(await screen.findByText(/Đang dừng tiến trình và giải phóng tài nguyên/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy yêu cầu" })).toBeNull();
    const cancellations = calls("/scene/objectify/cancel").filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "POST",
    );
    expect(cancellations).toHaveLength(1);
  });

  it("scene theo vật: không hiện thông báo tách vật", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-002", "CONFIRMED", "CONFIRMED") })] });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("Vật thể 1");
    await waitFor(() => expect(calls("/scene/objectify")).toHaveLength(1));
    expect(screen.queryByText(/hộp ứng viên/)).toBeNull();
  });

  it("hỗ trợ thu gọn và xổ xuống 2 panel bên trong viewport", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })] });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText("1 vật thể · 1 chờ xác nhận")).toBeInTheDocument();

    // Thu gọn panel trái
    fireEvent.click(screen.getByRole("button", { name: "Thu gọn danh sách vật thể" }));
    expect(screen.queryByText("1 vật thể · 1 chờ xác nhận")).toBeNull();
    const openLeft = screen.getByRole("button", { name: "Mở danh sách vật thể" });
    expect(openLeft).toBeInTheDocument();

    // Xổ xuống panel trái
    fireEvent.click(openLeft);
    expect(screen.getByText("1 vật thể · 1 chờ xác nhận")).toBeInTheDocument();

    // Thu gọn panel phải
    fireEvent.click(screen.getByRole("button", { name: "Thu gọn chi tiết vật thể" }));
    const openRight = screen.getByRole("button", { name: "Mở chi tiết vật thể" });
    expect(openRight).toBeInTheDocument();

    // Xổ xuống panel phải
    fireEvent.click(openRight);
    expect(screen.getByText("Chọn một vật")).toBeInTheDocument();
  });
});
