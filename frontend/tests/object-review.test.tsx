/**
 * ObjectReviewView (ADR 0006, PRODUCT-07): xác nhận/loại ứng viên gửi đúng revision, UI hiển
 * thị revision backend trả về. Canvas 3D được thay bằng stub (jsdom không có WebGL).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    boxes: {
      id: string;
      color: string;
      center: [number, number, number];
      rotation_xyzw: [number, number, number, number];
      dimensions: [number, number, number];
    }[];
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

function boxColliderScene(
  revision = "rev-001",
  dimensions: [number, number, number] = [1, 0.8, 0.6],
  offset: [number, number, number] = [0, 0, 0],
  localRotation: [number, number, number, number] = [0, 0, 0, 1],
  objectRotation: [number, number, number, number] = [0, 0, 0, 1],
) {
  const result = scene(revision, "CONFIRMED", "CONFIRMED");
  const object = result.objects[0] as unknown as Record<string, unknown>;
  object.primitive_dimensions_xyz_m = [1.5, 1.2, 0.9];
  (object.transform as Record<string, unknown>).rotation_quaternion_xyzw = objectRotation;
  object.collider = {
    collider_id: "collider-001",
    collider_type: "AABB",
    dimensions_xyz_m: dimensions,
    local_transform: {
      semantics: "parent_from_local",
      parent_frame: "candidate-001",
      local_frame: "collider-001",
      translation_xyz: offset,
      rotation_quaternion_xyzw: localRotation,
      quaternion_order: "xyzw",
      angle_unit: "radian",
    },
    geometry_ref: null,
    parameters: {},
    provenance: {},
  };
  object.physics = {
    dynamic: true,
    mass_kg: 10,
    mass_source: "user",
    static_friction: 0.6,
    dynamic_friction: 0.5,
    restitution: 0,
    provenance: {},
  };
  return result;
}

function membershipScene(revision = "rev-001") {
  const result = scene(revision, "CANDIDATE") as ReturnType<typeof scene> & { environment: Record<string, unknown> };
  const first = result.objects[0] as Record<string, unknown>;
  const sourceGeometry = result.environment.geometry_ref;
  const addOwnership = (object: Record<string, unknown>) => ({
    ...object,
    source_collision: {
      schema_version: "1.0",
      object_id: object.id,
      source_geometry_ref: sourceGeometry,
      extraction_revision: "extract-001",
      source_transform: object.transform,
      region_kind: "source_obb",
      source_obb_dimensions_xyz_m: [1, 0.8, 0.6],
    },
  });
  const firstCandidate = addOwnership({ ...first, semantic_class: "box" });
  const secondCandidate = addOwnership({
    ...first,
    id: "candidate-002",
    name: "Vật thể 2",
    local_frame: "candidate-002",
    semantic_class: "pallet",
    transform: first.transform,
  });
  return {
    ...result,
    environment: {
      ...result.environment,
      membership: {
        artifact_type: "ObjectMembershipArtifact",
        schema_version: "1.0",
        source_visual_ref: ref,
        source_geometry_ref: sourceGeometry,
        extraction_revision: "extract-001",
        coordinate_system: { unit: "meter", up_axis: "Z", handedness: "right", world_frame: "world" },
        gaussian_count: 200,
        labels_ref: { ...ref, artifact_type: "GaussianMembershipLabels", artifact_checksum: `sha256:${"b".repeat(64)}` },
        labels_encoding: "little-endian-int32",
        background_label: -1,
        label_to_object_id: { "0": "candidate-001", "1": "candidate-002" },
      },
    },
    objects: [firstCandidate, secondCandidate],
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

  it("orders scene-state before objects and preserves the viewer and selection across panel tabs", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })] });
    render(<ObjectReviewView jobId="job-a" sceneStateControls={<p>Thao tác trạng thái</p>} />);
    const viewer = await screen.findByTestId("metric-scene");
    const stateTab = screen.getByRole("tab", { name: "Trạng thái scene" });
    const objectsTab = screen.getByRole("tab", { name: "Vật thể" });
    expect(screen.getAllByRole("tab").map(tab => tab.textContent)).toEqual(["Trạng thái scene", "Vật thể"]);
    expect(stateTab).toHaveAttribute("aria-selected", "true");
    fireEvent.mouseDown(objectsTab, { button: 0, ctrlKey: false });
    const object = await screen.findByRole("button", { name: "Chọn Vật thể 1" });
    fireEvent.click(object);
    expect(object).toHaveAttribute("aria-pressed", "true");
    fireEvent.mouseDown(stateTab, { button: 0, ctrlKey: false });
    expect(screen.getByTestId("metric-scene")).toBe(viewer);
    fireEvent.mouseDown(objectsTab, { button: 0, ctrlKey: false });
    expect(screen.getByRole("button", { name: "Chọn Vật thể 1" })).toHaveAttribute("aria-pressed", "true");
    expect(calls("/scene").filter(([url]) => String(url).endsWith("/scene"))).toHaveLength(1);
  });

  it("scene chưa có head (409) hiện lý do của backend; chỉ 404 mới là chưa tách vật thể", async () => {
    routeFetch({ "/scene": [reply({ detail: "Scene này chưa được chuẩn bị để xem. Nhờ quản trị chuẩn bị scene." }, 409)] });
    const view = render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText("Scene này chưa được chuẩn bị để xem. Nhờ quản trị chuẩn bị scene.")).toBeInTheDocument();
    expect(screen.queryByText(/Chưa có vật thể/)).toBeNull();
    view.unmount();

    routeFetch({ "/scene": [reply({ detail: "Job chưa publish SceneIR" }, 404)] });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText(/Chưa có vật thể/)).toBeInTheDocument();
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

  it("chỉ liệt kê candidate đã publish và gửi exact ref cùng revision khi được chọn", async () => {
    const candidateManifest = {
      ...ref,
      artifact_type: "LidarCollisionCandidateManifest",
      artifact_uri: "artifact://jobs/job-a/collider/lidar-candidates/candidate-1/manifest.json",
    };
    const onSaveState = vi.fn();
    routeFetch({
      "/jobs/job-a/artifacts": [reply({ job_id: "job-a", artifacts: [candidateManifest], excluded_artifact_count: 0 })],
      "/scene/collision-source/lidar": [reply({ scene_revision: "rev-002", scene: scene("rev-002", "CONFIRMED", "CONFIRMED") })],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })],
    });
    render(<ObjectReviewView jobId="job-a" onSaveState={onSaveState} />);
    await screen.findByText("1 vật thể · 1 chờ xác nhận");
    fireEvent.click(screen.getByRole("button", { name: /Nguồn collision LiDAR/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Chọn làm collision source" }));

    await waitFor(() => expect(calls("/scene/collision-source/lidar")).toHaveLength(1));
    const [, init] = calls("/scene/collision-source/lidar")[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      expected_scene_revision: "rev-001",
      candidate_manifest_ref: candidateManifest,
    });
    await waitFor(() => expect(onSaveState).toHaveBeenCalledWith({ status: "saved", revision: "rev-002" }));
  });

  it("nêu rõ khi job chưa publish candidate LiDAR", async () => {
    routeFetch({
      "/jobs/job-a/artifacts": [reply({ job_id: "job-a", artifacts: [], excluded_artifact_count: 0 })],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("1 vật thể · 1 chờ xác nhận");
    fireEvent.click(screen.getByRole("button", { name: /Nguồn collision LiDAR/ }));

    expect(await screen.findByText(/Job chưa publish candidate LiDAR/)).toBeInTheDocument();
    expect(calls("/scene/collision-source/lidar")).toHaveLength(0);
  });

  it("gộp nhiều ứng viên bằng membership checksum và semantic source đã chọn", async () => {
    routeFetch({
      "/scene/corrections/merge": [reply({ scene: membershipScene("rev-002") })],
      "/scene": [reply({ scene: membershipScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("2 vật thể · 2 chờ xác nhận");
    fireEvent.click(screen.getByRole("button", { name: /Sửa nhóm Gaussian/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn để gộp Vật thể 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn để gộp Vật thể 2" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Ứng viên chính để gộp" }), { target: { value: "candidate-001" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Nguồn nhãn ngữ nghĩa" }), { target: { value: "candidate-002" } });
    fireEvent.click(screen.getByRole("button", { name: "Gộp ứng viên" }));

    await waitFor(() => expect(calls("/scene/corrections/merge")).toHaveLength(1));
    const [, init] = calls("/scene/corrections/merge")[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      expected_scene_revision: "rev-001",
      membership_checksum: `sha256:${"b".repeat(64)}`,
      primary_object_id: "candidate-001",
      secondary_object_ids: ["candidate-002"],
      semantic_class_source_object_id: "candidate-002",
    });
    expect(await screen.findByText(/Lệnh gắn với revision rev-002/)).toBeInTheDocument();
  });

  it("reassign ROI gửi bounds canonical theo mét và reload scene mới", async () => {
    routeFetch({
      "/scene/corrections/reassign": [reply({ scene: membershipScene("rev-002") })],
      "/scene": [reply({ scene: membershipScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("2 vật thể · 2 chờ xác nhận");
    fireEvent.click(screen.getByRole("button", { name: /Sửa nhóm Gaussian/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "Chủ sở hữu nguồn" }), { target: { value: "candidate-001" } });
    fireEvent.change(screen.getByLabelText("X nhỏ nhất (m)"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("X lớn nhất (m)"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Y nhỏ nhất (m)"), { target: { value: "-1" } });
    fireEvent.change(screen.getByLabelText("Y lớn nhất (m)"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Z nhỏ nhất (m)"), { target: { value: "0.1" } });
    fireEvent.change(screen.getByLabelText("Z lớn nhất (m)"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Chuyển vùng Gaussian" }));

    await waitFor(() => expect(calls("/scene/corrections/reassign")).toHaveLength(1));
    const [, init] = calls("/scene/corrections/reassign")[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      expected_scene_revision: "rev-001",
      membership_checksum: `sha256:${"b".repeat(64)}`,
      region: { min_xyz_m: [0, -1, 0.1], max_xyz_m: [2, 3, 1.5] },
      source_object_id: "candidate-001",
      target_object_id: null,
    });
    expect(await screen.findByText(/Lệnh gắn với revision rev-002/)).toBeInTheDocument();
  });

  it("hủy selection và giữ canonical scene sau conflict 409", async () => {
    routeFetch({
      "/scene/corrections/merge": [reply({ detail: "stale scene" }, 409)],
      "/scene": [reply({ scene: membershipScene() }), reply({ scene: membershipScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("2 vật thể · 2 chờ xác nhận");
    fireEvent.click(screen.getByRole("button", { name: /Sửa nhóm Gaussian/ }));
    const firstCandidate = screen.getByRole("checkbox", { name: "Chọn để gộp Vật thể 1" });
    fireEvent.click(firstCandidate);
    expect(firstCandidate).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Hủy chọn" }));
    expect(firstCandidate).not.toBeChecked();

    fireEvent.click(firstCandidate);
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn để gộp Vật thể 2" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Nguồn nhãn ngữ nghĩa" }), { target: { value: "candidate-001" } });
    fireEvent.click(screen.getByRole("button", { name: "Gộp ứng viên" }));

    expect(await screen.findByText(/Scene đã đổi ở lượt khác/)).toBeInTheDocument();
    expect(screen.getByText(/Lệnh gắn với revision rev-001/)).toBeInTheDocument();
    expect(calls("/scene").filter(([url]) => String(url).endsWith("/scene"))).toHaveLength(2);
  });

  it("nói rõ khi scene cũ chưa có membership và khóa correction commands", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })] });
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByText("1 vật thể · 1 chờ xác nhận");
    fireEvent.click(screen.getByRole("button", { name: /Sửa nhóm Gaussian/ }));
    expect(await screen.findByText(/chưa lưu Gaussian membership/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Gộp ứng viên" })).toBeNull();
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

  it("409 (scene đổi ở lượt khác): tự tải bản mới và giữ thông báo xung đột", async () => {
    routeFetch({
      "/objects/candidate-001/confirm": [reply({ detail: "scene đã đổi" }, 409)],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") }), reply({ scene: scene("rev-004", "CANDIDATE") })],
    });
    let last: SaveState | null = null;
    const states: SaveState[] = [];
    render(<ObjectReviewView jobId="job-a" onSaveState={(state) => { last = state; states.push(state); }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Xác nhận Vật thể 1" }));
    expect(await screen.findByText(/Scene đã đổi ở lượt khác/)).toBeInTheDocument();
    await waitFor(() => expect(last).toMatchObject({ status: "saved", revision: "rev-004" }));
    expect(states.some((state) => state.status === "error" && state.revision === "rev-001")).toBe(true);
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

  it("previews box dimensions and local pose, then saves them against the canonical revision", async () => {
    const worldRotation: [number, number, number, number] = [0, 0, Math.SQRT1_2, Math.SQRT1_2];
    const original = boxColliderScene("rev-001", [1, 0.8, 0.6], [0, 0, 0], [0, 0, 0, 1], worldRotation);
    const saved = boxColliderScene("rev-002", [1.2, 0.8, 0.6], [0.25, 0, 0], [0, 0, Math.SQRT1_2, Math.SQRT1_2], worldRotation);
    routeFetch({
      "/scene/collider": [reply({ scene_revision: "rev-002", scene: saved })],
      "/scene": [reply({ scene: original })],
    });
    render(<ObjectReviewView jobId="job-a" />);

    const metricScene = await screen.findByTestId("metric-scene");
    const readBox = () => JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]") as {
      center: number[];
      dimensions: number[];
      rotation_xyzw: number[];
    }[];
    expect(readBox()[0]).toMatchObject({ center: [1, 2, 0.3], dimensions: [1, 0.8, 0.6] });

    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    expect(screen.getByText("1.50 × 1.20 × 0.90")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Kích thước collider X (m)"), { target: { value: "1.2" } });
    fireEvent.change(screen.getByLabelText("Tịnh tiến local X (m)"), { target: { value: "0.25" } });
    fireEvent.change(screen.getByLabelText("Góc xoay local Z (°)"), { target: { value: "90" } });

    expect(readBox()[0]?.center).toEqual([1, 2.25, 0.3]);
    expect(readBox()[0]?.dimensions).toEqual([1.2, 0.8, 0.6]);
    expect(readBox()[0]?.rotation_xyzw[2]).toBeCloseTo(1);
    const physicsObjects = JSON.parse(metricScene.getAttribute("data-physics-objects") ?? "[]") as {
      dimensions: number[];
      colliderLocalTransform: { translation_xyz: number[] };
    }[];
    expect(physicsObjects[0]?.dimensions).toEqual([1.2, 0.8, 0.6]);
    expect(physicsObjects[0]?.colliderLocalTransform.translation_xyz).toEqual([0.25, 0, 0]);

    const save = screen.getByRole("button", { name: "Lưu collider" });
    fireEvent.click(save);
    fireEvent.click(save);
    await waitFor(() => expect(calls("/scene/collider")).toHaveLength(1));
    const [, init] = calls("/scene/collider")[0];
    const payload = JSON.parse((init as RequestInit).body as string);
    expect(payload).toMatchObject({
      expected_scene_revision: "rev-001",
      object_id: "candidate-001",
      dimensions_xyz_m: [1.2, 0.8, 0.6],
      local_translation_xyz_m: [0.25, 0, 0],
    });
    expect(payload.local_rotation_quaternion_xyzw[2]).toBeCloseTo(Math.SQRT1_2);
    expect(await screen.findByLabelText("Kích thước collider X (m)")).toHaveValue(1.2);
    expect(readBox()[0]?.dimensions).toEqual([1.2, 0.8, 0.6]);
  });

  it("cancel restores the canonical collider preview without sending a request", async () => {
    routeFetch({ "/scene": [reply({ scene: boxColliderScene() })] });
    render(<ObjectReviewView jobId="job-a" />);
    const metricScene = await screen.findByTestId("metric-scene");
    const readBox = () => JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]") as { center: number[]; dimensions: number[] }[];
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.change(screen.getByLabelText("Tịnh tiến local X (m)"), { target: { value: "0.5" } });
    expect(readBox()[0]?.center).toEqual([1.5, 2, 0.3]);
    fireEvent.click(screen.getByRole("button", { name: "Hủy chỉnh sửa" }));
    expect(readBox()[0]?.center).toEqual([1, 2, 0.3]);
    expect(calls("/scene/collider")).toHaveLength(0);
  });

  it("rejects non-positive dimensions in the form and leaves the canonical preview intact", async () => {
    routeFetch({ "/scene": [reply({ scene: boxColliderScene() })] });
    render(<ObjectReviewView jobId="job-a" />);
    const metricScene = await screen.findByTestId("metric-scene");
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.change(screen.getByLabelText("Kích thước collider X (m)"), { target: { value: "0" } });

    expect(await screen.findByRole("alert")).toHaveTextContent("Kích thước phải là số dương");
    expect(JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]")[0].dimensions).toEqual([1, 0.8, 0.6]);
    expect(screen.getByRole("button", { name: "Lưu collider" })).toBeDisabled();
    expect(calls("/scene/collider")).toHaveLength(0);
  });

  it("stale collider save reloads the newer canonical scene and drops the local preview", async () => {
    routeFetch({
      "/scene/collider": [reply({ detail: "stale revision" }, 409)],
      "/scene": [reply({ scene: boxColliderScene() }), reply({ scene: boxColliderScene("rev-003", [2, 0.8, 0.6], [0.1, 0, 0]) })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    const metricScene = await screen.findByTestId("metric-scene");
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.change(screen.getByLabelText("Tịnh tiến local X (m)"), { target: { value: "0.5" } });
    expect(JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]")[0].center).toEqual([1.5, 2, 0.3]);
    fireEvent.click(screen.getByRole("button", { name: "Lưu collider" }));

    expect(await screen.findByText(/Scene đã đổi ở lượt khác/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Kích thước collider X (m)")).toHaveValue(2));
    expect(JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]")[0].center).toEqual([1.1, 2, 0.3]);
    expect(JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]")[0].dimensions).toEqual([2, 0.8, 0.6]);
  });

  it("failed collider save rolls the form and preview back to canonical state", async () => {
    routeFetch({
      "/scene/collider": [reply({ detail: "artifact store unavailable" }, 500)],
      "/scene": [reply({ scene: boxColliderScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    const metricScene = await screen.findByTestId("metric-scene");
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.change(screen.getByLabelText("Kích thước collider X (m)"), { target: { value: "2" } });
    expect(JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]")[0].dimensions).toEqual([2, 0.8, 0.6]);
    fireEvent.click(screen.getByRole("button", { name: "Lưu collider" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Kích thước collider X (m)")).toHaveValue(1));
    expect(JSON.parse(metricScene.getAttribute("data-boxes") ?? "[]")[0].dimensions).toEqual([1, 0.8, 0.6]);
  });

  it("does not expose box edits for a convex-decomposition collider", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-001", "CONFIRMED", "CONFIRMED", undefined, [0, 0, 0]) })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));

    expect(await screen.findByText(/Hiện chỉ chỉnh được AABB\/OBB/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Kích thước collider X (m)")).toBeNull();
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

    expect(await screen.findByText("Tách theo vật không thành công.")).toBeTruthy();
    expect(screen.getByText(/sau 3 lần: hết VRAM/)).toBeTruthy();
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
  it("Ẩn/Hiện Candidate chỉ đổi viewport, giữ revision và không gọi backend", async () => {
    const base = scene("rev-001", "CANDIDATE");
    const gaussians = { ...ref, artifact_type: "ObjectGaussians", artifact_uri: "artifact://jobs/job-a/scene/objects/x.ply" };
    base.objects[0] = { ...base.objects[0], visual_ref: gaussians } as (typeof base.objects)[0];
    base.objects.push({ ...base.objects[0], id: "candidate-002", name: "Vật thể 2" });
    routeFetch({ "/scene": [reply({ scene: base })] });
    const onSave = vi.fn();
    render(<ObjectReviewView jobId="job-a" onSaveState={onSave} />);
    fireEvent.click(await screen.findByText("Vật thể 1"));
    const requests = vi.mocked(fetch).mock.calls.length;
    const saves = onSave.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Ẩn trên màn hình" }));
    expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:false");
    expect(screen.getByTestId("splats")).toHaveTextContent("candidate-002:ply:true");
    expect(JSON.parse(screen.getByTestId("metric-scene").dataset.boxes!)).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Bật trong mô phỏng" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hiện trên màn hình" }));
    expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:true");
    expect(JSON.parse(screen.getByTestId("metric-scene").dataset.boxes!)).toHaveLength(2);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(requests);
    expect(onSave.mock.calls).toHaveLength(saves);
  });

  it("Tắt mô phỏng là lệnh backend riêng, không dùng nút Ẩn viewport", async () => {
    const base = scene("rev-001", "CONFIRMED", "CONFIRMED");
    const disabled = scene("rev-002", "CONFIRMED", "CONFIRMED");
    disabled.objects[0].active = false;
    routeFetch({ "/objects/candidate-001/hide": [reply({ scene: disabled })], "/scene": [reply({ scene: base })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByText("Vật thể 1"));
    fireEvent.click(screen.getByRole("button", { name: "Tắt trong mô phỏng" }));
    expect(await screen.findByRole("button", { name: "Bật trong mô phỏng" })).toBeInTheDocument();
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes("/objects/candidate-001/hide"));
    expect(JSON.parse(call![1]!.body as string)).toMatchObject({ active: false, expected_scene_revision: "rev-001" });
  });

  it("đổi job reset viewport hide dù object ID trùng nhau", async () => {
    const base = scene("rev-001", "CANDIDATE");
    base.objects[0] = { ...base.objects[0], visual_ref: { ...ref, artifact_type: "ObjectGaussians" } } as (typeof base.objects)[0];
    routeFetch({ "/scene": [reply({ scene: base }), reply({ scene: base })] });
    const view = render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByText("Vật thể 1"));
    fireEvent.click(screen.getByRole("button", { name: "Ẩn trên màn hình" }));
    expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:false");
    view.rerender(<ObjectReviewView jobId="job-b" />);
    await waitFor(() => expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:true"));
  });

});
