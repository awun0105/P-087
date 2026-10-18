/**
 * ObjectReviewView (ADR 0006, PRODUCT-07): xác nhận/loại ứng viên gửi đúng revision, UI hiển
 * thị revision backend trả về. Canvas 3D được thay bằng stub (jsdom không có WebGL).
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectReviewView, type SaveState } from "@/features/studio/ObjectReviewView";
import { SimulationPackagePanel } from "@/features/studio/SimulationPackagePanel";
import { ObjectifyContext, type ObjectifyHandle } from "@/features/studio/scene/objectifyContext";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";

vi.mock("@/features/studio/StageViewer", () => ({
  CollisionMeshCanvas: () => <div data-testid="mesh" />,
}));
vi.mock("@/features/studio/MetricSceneView", () => ({
  MetricSceneView: ({
    boxes,
    objects = [],
    shells = [],
    physicsObjects = [],
    gizmo,
    onTool,
    onDelete,
    onTransform,
    lockedReason,
    regionEdit,
  }: {
    boxes: {
      id: string;
      color: string;
      center: [number, number, number];
      rotation_xyzw: [number, number, number, number];
      dimensions: [number, number, number];
    }[];
    objects?: { id: string; url: string | null; visible: boolean }[];
    shells?: { id: string; url: string; style: string }[];
    physicsObjects?: {
      id: string;
      position: [number, number, number];
      rotation_xyzw: [number, number, number, number];
      colliderLocalTransform: { translation_xyz: [number, number, number] } | null;
    }[];
    gizmo?: { id: string; mode: string } | null;
    onTool?: (tool: "translate" | "rotate" | "none") => void;
    onDelete?: () => void;
    onTransform?: (id: string, position: [number, number, number], rotation: [number, number, number, number]) => void;
    regionEdit?: Parameters<typeof import("@/features/studio/MetricSceneView").MetricSceneView>[0]["regionEdit"];
    lockedReason?: string | null;
  }) => (
    <div data-testid="metric-scene" data-objects={JSON.stringify(objects)} data-boxes={JSON.stringify(boxes)} data-physics-objects={JSON.stringify(physicsObjects)} data-shells={JSON.stringify(shells)}>
      {regionEdit && <button onClick={() => regionEdit.onChange(regionEdit.boxes.map((box) => ({ ...box, half: [box.half[0] / 2, box.half[1], box.half[2]] })))} type="button">Kéo mặt hộp</button>}
      {boxes.map((box) => `${box.id}:${box.color}`).join(",")}
      <span data-testid="splats">{objects.map((item) => `${item.id}:${item.url ? "ply" : "none"}:${item.visible}`).join(",")}</span>
      <span data-testid="gizmo">{gizmo ? `${gizmo.id}:${gizmo.mode}` : "none"}</span>
      <span data-testid="locked">{lockedReason ?? "none"}</span>
      {onTool && <button type="button" onClick={() => onTool("translate")}>Dịch</button>}
      {onDelete && <button type="button" onClick={onDelete}>Xoá</button>}
      {onTransform && gizmo && <button type="button" onClick={() => onTransform(gizmo.id, [7, 8, 9], [0, 0, Math.SQRT1_2, Math.SQRT1_2])}>Áp pose kiểm tra</button>}
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
    // Box ban đầu của Chỉnh vùng (T-023): mặc định trả box đã tính; test có thể xếp hàng phản hồi riêng.
    if (url.includes("/region/fit")) {
      const queued = routes["/region/fit"];
      return queued?.length ? queued.shift()! : reply(regionFit);
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

  it("lets an already confirmed Draft object remain in the fixed background", async () => {
    const initial = { ...scene("rev-061", "CONFIRMED", "CONFIRMED"), provenance: { object_geometry: "awaiting_review" } };
    const fixed = { ...scene("rev-062", "CANDIDATE", "IGNORED"), provenance: { object_geometry: "awaiting_review" } };
    routeFetch({
      "/objects/candidate-001/ignore": [reply({ scene: fixed })],
      "/scene": [reply({ scene: initial })],
    });
    render(<ObjectReviewView jobId="job-a" sceneStateControls={<p>Trạng thái đã lưu</p>} />);
    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Vật thể" }), { button: 0, ctrlKey: false });
    const checkbox = await screen.findByRole("checkbox", { name: "Đánh dấu Vật thể 1 để làm nền" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(calls("/objects/candidate-001/ignore")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Tạo mesh cho 1 vật đã chọn" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cho 1 vật đã chọn làm nền" }));
    await waitFor(() => expect(calls("/objects/candidate-001/ignore")).toHaveLength(1));
    expect(JSON.parse(calls("/objects/candidate-001/ignore")[0][1]!.body as string).expected_scene_revision).toBe("rev-061");
    expect(await screen.findByRole("button", { name: "Tạo mesh cho 0 vật đã chọn" })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: "Đánh dấu Vật thể 1 để làm nền" })).not.toBeChecked();
    const panel = screen.getByRole("complementary", { name: "Danh sách vật thể" });
    expect(within(panel).getByRole("region", { name: "Tạo mesh vật thể" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Duyệt vật thể" })).not.toBeInTheDocument();
  });

  it("keeps marking local and excludes only marked objects using returned revisions", async () => {
    const initial = { ...scene("rev-001", "CONFIRMED", "CONFIRMED"), provenance: { object_geometry: "awaiting_review" } };
    const first = initial.objects[0];
    initial.objects.push({ ...first, id: "candidate-002", name: "Vật thể 2" }, { ...first, id: "candidate-003", name: "Vật thể 3" });
    const fixed = (object: typeof first) => ({ ...object, state: "CANDIDATE", active: false, provenance: { ...object.provenance, review: "IGNORED" } });
    const afterFirst = { ...initial, scene_revision: "rev-002", objects: [fixed(first), ...initial.objects.slice(1)] };
    const afterBoth = { ...afterFirst, scene_revision: "rev-003", objects: [fixed(first), fixed(initial.objects[1]), initial.objects[2]] };
    routeFetch({
      "/objects/candidate-001/ignore": [reply({ scene: afterFirst })],
      "/objects/candidate-002/ignore": [reply({ scene: afterBoth })],
      "/scene": [reply({ scene: initial })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Đánh dấu Vật thể 1 để làm nền" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Đánh dấu Vật thể 2 để làm nền" }));
    expect(calls("/ignore")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Tạo mesh cho 3 vật đã chọn" })).toBeEnabled();
    expect(screen.queryByText("Mesh riêng")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cho 2 vật đã chọn làm nền" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạo mesh cho 1 vật đã chọn" })).toBeEnabled());
    const revisions = ["candidate-001", "candidate-002"].map(id => JSON.parse(calls(`/objects/${id}/ignore`)[0][1]!.body as string).expected_scene_revision);
    expect(revisions).toEqual(["rev-001", "rev-002"]);
    expect(calls("/objects/candidate-003/ignore")).toHaveLength(0);
    expect(calls("/scene/geometry/build")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Cho 0 vật đã chọn làm nền" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Tách riêng các vật/ })).not.toBeInTheDocument();
  });

  it("retains unfinished background selections after a partial failure and retries from the saved revision", async () => {
    const initial = { ...scene("rev-001", "CONFIRMED", "CONFIRMED"), provenance: { object_geometry: "awaiting_review" } };
    initial.objects.push({ ...initial.objects[0], id: "candidate-002", name: "Vật thể 2" });
    const fixed = (object: typeof initial.objects[0]) => ({ ...object, state: "CANDIDATE", active: false, provenance: { ...object.provenance, review: "IGNORED" } });
    const afterFirst = { ...initial, scene_revision: "rev-002", objects: [fixed(initial.objects[0]), initial.objects[1]] };
    const afterBoth = { ...initial, scene_revision: "rev-003", objects: initial.objects.map(fixed) };
    routeFetch({
      "/objects/candidate-001/ignore": [reply({ scene: afterFirst })],
      "/objects/candidate-002/ignore": [reply({ detail: "Lưu vật thất bại" }, 500), reply({ scene: afterBoth })],
      "/scene": [reply({ scene: initial })],
    });
    const onSaveState = vi.fn();
    render(<ObjectReviewView jobId="job-a" onSaveState={onSaveState} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Đánh dấu Vật thể 1 để làm nền" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Đánh dấu Vật thể 2 để làm nền" }));
    fireEvent.click(screen.getByRole("button", { name: "Cho 2 vật đã chọn làm nền" }));
    await waitFor(() => expect(onSaveState).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" })));
    expect(screen.getByRole("checkbox", { name: "Đánh dấu Vật thể 1 để làm nền" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Đánh dấu Vật thể 2 để làm nền" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Tạo mesh cho 1 vật đã chọn" })).toBeEnabled();
    onSaveState.mock.calls.at(-1)![0].retry();
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạo mesh cho 0 vật đã chọn" })).toBeEnabled());
    expect(calls("/objects/candidate-001/ignore")).toHaveLength(1);
    expect(calls("/objects/candidate-002/ignore").map(([, init]) => JSON.parse(init!.body as string).expected_scene_revision)).toEqual(["rev-002", "rev-002"]);
  });

  it("can keep remaining undecided objects as background without starting a mesh job", async () => {
    const initial = { ...scene("rev-001", "CANDIDATE"), provenance: { object_geometry: "awaiting_review" } };
    const fixed = { ...scene("rev-002", "CANDIDATE", "IGNORED"), provenance: { object_geometry: "awaiting_review" } };
    routeFetch({ "/objects/candidate-001/ignore": [reply({ scene: fixed })], "/scene": [reply({ scene: initial })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Giữ vật chưa chọn làm nền" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạo mesh cho 0 vật đã chọn" })).toBeEnabled());
    expect(screen.getByRole("checkbox", { name: "Đánh dấu Vật thể 1 để làm nền" })).not.toBeChecked();
    expect(calls("/scene/geometry/build")).toHaveLength(0);
  });

  it("orders scene-state before objects and preserves the viewer and selection across panel tabs", async () => {
    routeFetch({ "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })] });
    render(<ObjectReviewView jobId="job-a" sceneStateControls={<p>Thao tác trạng thái</p>} />);
    const viewer = await screen.findByTestId("metric-scene");
    expect(screen.getByRole("heading", {name: "Quản lý scene"})).toBeInTheDocument();
    const stateTab = screen.getByRole("tab", { name: "Trạng thái scene" });
    const objectsTab = screen.getByRole("tab", { name: "Vật thể" });
    expect(within(stateTab.closest('[role="tablist"]') as HTMLElement).getAllByRole("tab").map(tab => tab.textContent)).toEqual(["Trạng thái scene", "Vật thể", "Sàn & tường"]);
    expect(stateTab).toHaveAttribute("aria-selected", "true");
    fireEvent.mouseDown(objectsTab, { button: 0, ctrlKey: false });
    const object = await screen.findByRole("button", { name: "Chọn Vật thể 1" });
    fireEvent.click(object);
    expect(object).toHaveAttribute("aria-pressed", "true");
    fireEvent.mouseDown(screen.getByRole("tab", {name: "Sàn & tường"}), { button: 0, ctrlKey: false });
    expect(screen.getByRole("tab", {name: "Sàn & tường"})).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("metric-scene")).toBe(viewer);
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
    fireEvent.click(screen.getByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));

    expect(screen.getAllByText("Đã gộp vào candidate-002").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Khôi phục Vật thể 1" })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Thu gọn panel quản lý scene" }));
    expect(screen.queryByText("1 vật thể · 1 chờ xác nhận")).toBeNull();
    const openLeft = screen.getByRole("button", { name: "Mở panel quản lý scene" });
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
    routeFetch({ "/scene": [reply({ scene: base, representations: base.objects.map((item) => ({ object_id: item.id, visual_policy: "source", source_visual_required: true, source_transform: item.transform, readiness_blockers: [] })) })] });
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
    const response = { scene: base, representations: [{ object_id: "candidate-001", visual_policy: "source", source_visual_required: true, source_transform: base.objects[0].transform, readiness_blockers: [] }] };
    routeFetch({ "/scene": [reply(response), reply(response)] });
    const view = render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByText("Vật thể 1"));
    fireEvent.click(screen.getByRole("button", { name: "Ẩn trên màn hình" }));
    expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:false");
    view.rerender(<ObjectReviewView jobId="job-b" />);
    await waitFor(() => expect(screen.getByTestId("splats")).toHaveTextContent("candidate-001:ply:true"));
  });

  it("Pending preview binds Gaussian and static Studio collision to the editable object at B without confirming it", async () => {
    const base = scene("rev-001", "CANDIDATE");
    base.objects[0] = { ...base.objects[0], visual_ref: { ...ref, artifact_type: "ObjectGaussians" } } as (typeof base.objects)[0];
    const pose = { ...base.objects[0].transform, translation_xyz: [8, 9, 10] };
    routeFetch({ "/scene": [reply({ scene: base, representations: [{ object_id: "candidate-001", visual_policy: "source", source_visual_required: true, source_transform: pose, readiness_blockers: [] }] })] });
    render(<ObjectReviewView jobId="job-a" />);
    const view = await screen.findByTestId("metric-scene");
    const objects = JSON.parse(view.dataset.objects!);
    expect(objects.filter((item: { url: string | null }) => item.url)).toHaveLength(1);
    expect(objects).toHaveLength(1);
    expect(objects[0]).toMatchObject({ id: "candidate-001", position: base.objects[0].transform.translation_xyz, visible: true });
    expect(JSON.parse(view.dataset.physicsObjects!)).toMatchObject([{id: "candidate-001", dynamic: false}]);
    fireEvent.click(screen.getByText("Vật thể 1"));
    fireEvent.click(screen.getByRole("button", { name: "Ẩn trên màn hình" }));
    expect(JSON.parse(view.dataset.objects!)[0].visible).toBe(false);
  });

  it("missing SOURCE metadata cannot silently place a moved Candidate at current pose", async () => {
    const base = scene("rev-001", "CANDIDATE");
    base.objects[0] = { ...base.objects[0], visual_ref: { ...ref, artifact_type: "ObjectGaussians" } } as (typeof base.objects)[0];
    routeFetch({ "/scene": [reply({ scene: base })] });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText(/SOURCE_POLICY_MISSING/)).toBeInTheDocument();
    const objects = JSON.parse(screen.getByTestId("metric-scene").dataset.objects!);
    expect(objects.every((item: { url: string | null }) => item.url === null)).toBe(true);
  });

  it("archive separates Ignore, Delete, Merge, viewport Hide and simulation disable", async () => {
    const base = scene("rev-001", "CANDIDATE");
    base.objects = [
      scene("rev-001", "CANDIDATE", "IGNORED").objects[0],
      scene("rev-001", "CANDIDATE", "DELETED").objects[0],
      scene("rev-001", "CANDIDATE", "MERGED", "candidate-005").objects[0],
      { ...scene("rev-001", "CONFIRMED", "CONFIRMED").objects[0], active: false },
      base.objects[0],
    ].map((object, index) => ({ ...object, id: `candidate-00${index + 1}`, name: `Vật thể ${index + 1}` }));
    routeFetch({ "/scene": [reply({ scene: base })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 5" }));
    const requests = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Ẩn trên màn hình" }));
    expect(screen.getByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 5" })).toHaveAttribute("aria-pressed", "true");
    for (const name of ["Đã loại · 1", "Đã xoá · 1", "Đã gộp · 1", "Ẩn trên màn hình · 1", "Tắt trong mô phỏng · 1"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    for (let index = 1; index <= 5; index += 1) expect(screen.getByRole("button", { name: `Khôi phục Vật thể ${index}` })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 5" }));
    expect(screen.getByRole("button", { name: "Chưa loại · 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Chọn Vật thể 5" })).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls).toHaveLength(requests);
  });

  it.each(["IGNORED", "DELETED"])("restore %s returns Candidate without implicitly confirming it", async (review) => {
    routeFetch({
      "/objects/candidate-001/restore": [reply({ scene: scene("rev-002", "CANDIDATE") })],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE", review) })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    expect(await screen.findByRole("button", { name: "Xác nhận Vật thể 1" })).toBeInTheDocument();
    const request = calls("/objects/candidate-001/restore")[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toEqual({ expected_scene_revision: "rev-001" });
    expect(JSON.parse(screen.getByTestId("metric-scene").dataset.physicsObjects!)).toMatchObject([{id: "candidate-001", dynamic: false}]);
  });

  it("restore simulation-disabled object sends active=true while viewport restore stays local", async () => {
    const base = scene("rev-001", "CONFIRMED", "CONFIRMED");
    base.objects[0].active = false;
    routeFetch({
      "/objects/candidate-001/hide": [reply({ scene: scene("rev-002", "CONFIRMED", "CONFIRMED") })],
      "/scene": [reply({ scene: base })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    expect(await screen.findByRole("button", { name: "Chưa loại · 1" })).toHaveAttribute("aria-pressed", "true");
    expect(JSON.parse((calls("/objects/candidate-001/hide")[0][1] as RequestInit).body as string)).toEqual({ expected_scene_revision: "rev-001", active: true });
  });

  it("merged restore explains group restoration and requires explicit confirmation", async () => {
    routeFetch({
      "/objects/candidate-001/restore": [reply({ scene: scene("rev-002", "CANDIDATE") })],
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE", "MERGED", "candidate-002") })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Khôi phục nhóm trước khi gộp?");
    expect(calls("/objects/candidate-001/restore")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Hủy" }));
    expect(calls("/objects/candidate-001/restore")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục cả nhóm" }));
    expect(await screen.findByRole("button", { name: "Xác nhận Vật thể 1" })).toBeInTheDocument();
    expect(calls("/objects/candidate-001/restore")).toHaveLength(1);
  });

  it("legacy INVALID_OBJECT_ACTIVATION offers a Candidate repair instead of automatic confirmation", async () => {
    const base = scene("rev-001", "CANDIDATE");
    base.objects[0].active = true;
    const policy = { object_id: "candidate-001", visual_policy: "source", source_visual_required: false, source_transform: null, readiness_blockers: ["INVALID_OBJECT_ACTIVATION"] };
    routeFetch({
      "/objects/candidate-001/restore": [reply({ scene: scene("rev-002", "CANDIDATE"), representations: [{ ...policy, readiness_blockers: [] }] })],
      "/scene": [reply({ scene: base, representations: [policy] })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    const repair = await screen.findByRole("button", { name: "Khôi phục trạng thái candidate-001" });
    expect(calls("/objects/candidate-001/restore")).toHaveLength(0);
    fireEvent.click(repair);
    await waitFor(() => expect(screen.queryByText(/INVALID_OBJECT_ACTIVATION/)).toBeNull());
    expect(screen.getByRole("button", { name: "Xác nhận Vật thể 1" })).toBeInTheDocument();
    expect(calls("/objects/candidate-001/confirm")).toHaveLength(0);
  });

  it("Candidate inspector exposes Merge and explains that it joins parts of one object", async () => {
    routeFetch({ "/scene": [reply({ scene: membershipScene() })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Gộp với ứng viên khác" }));
    expect(screen.getByRole("button", { name: /Gộp ứng viên \/ Sửa nhóm Gaussian/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/một vật bị tách nhầm thành nhiều ứng viên/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Chọn để gộp Vật thể 1" })).toBeChecked();
  });

  it("Candidate Move/Rotate, Hide/Show, Delete/Restore keep Gaussian, collider and gizmo bound to one object", async () => {
    const initial = scene("rev-001", "CANDIDATE");
    const gaussian = { ...ref, artifact_type: "ObjectGaussians", artifact_uri: "artifact://jobs/job-a/scene/object.ply" };
    initial.objects[0] = { ...initial.objects[0], visual_ref: gaussian } as (typeof initial.objects)[0];
    const rotation = [0, 0, Math.SQRT1_2, Math.SQRT1_2];
    const moved = { ...initial, scene_revision: "rev-002", objects: [{ ...initial.objects[0], transform: { ...initial.objects[0].transform, translation_xyz: [7, 8, 9], rotation_quaternion_xyzw: rotation } }] };
    const deleted = { ...moved, scene_revision: "rev-003", objects: [{ ...moved.objects[0], provenance: { review: "DELETED" } }] };
    const restored = { ...moved, scene_revision: "rev-004" };
    const policy = { object_id: "candidate-001", visual_policy: "source", source_visual_required: true, source_transform: initial.objects[0].transform, readiness_blockers: [] };
    routeFetch({
      "/scene/edits": [reply({ scene: moved, representations: [policy] })],
      "/objects/candidate-001/delete": [reply({ scene: deleted, representations: [{ ...policy, visual_policy: "omit", source_visual_required: false }] })],
      "/objects/candidate-001/restore": [reply({ scene: restored, representations: [policy] })],
      "/scene": [reply({ scene: initial, representations: [policy] })],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ObjectReviewView jobId="job-a" />);
    const canvas = await screen.findByTestId("metric-scene");
    const objects = () => JSON.parse(canvas.dataset.objects!);
    const boxes = () => JSON.parse(canvas.dataset.boxes!);
    expect(objects()).toHaveLength(1);
    expect(objects()[0]).toMatchObject({ id: "candidate-001", visible: true });
    expect(objects()[0].url).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Dịch" }));
    expect(screen.getByTestId("gizmo")).toHaveTextContent("candidate-001:translate");
    fireEvent.click(screen.getByRole("button", { name: "Áp pose kiểm tra" }));
    await waitFor(() => expect(objects()[0].position).toEqual([7, 8, 9]));
    expect(objects()[0].rotation_xyzw).toEqual(rotation);
    expect(boxes()[0]).toMatchObject({ id: "candidate-001", center: [7, 8, 9], rotation_xyzw: rotation });
    expect(objects().some((item: { id: string }) => item.id.startsWith("source:"))).toBe(false);
    expect(JSON.parse(canvas.dataset.physicsObjects!)).toMatchObject([{id: "candidate-001", position: [7,8,9], dynamic: false}]);
    const transformRequest = JSON.parse((calls("/scene/edits")[0][1] as RequestInit).body as string);
    expect(transformRequest).toMatchObject({ expected_scene_revision: "rev-001", edits: [{ object_id: "candidate-001", translation_xyz: [7, 8, 9], rotation_quaternion_xyzw: rotation }] });
    const requests = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Ẩn trên màn hình" }));
    expect(objects()[0].visible).toBe(false);
    expect(boxes()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    expect(objects()[0]).toMatchObject({ id: "candidate-001", position: [7, 8, 9], rotation_xyzw: rotation, visible: true });
    expect(vi.mocked(fetch).mock.calls).toHaveLength(requests);
    fireEvent.click(screen.getByRole("button", { name: "Xoá" }));
    await waitFor(() => expect(objects()[0].visible).toBe(false));
    expect(boxes()).toHaveLength(0);
    expect(objects()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    await waitFor(() => expect(objects()[0].visible).toBe(true));
    expect(objects()[0]).toMatchObject({ id: "candidate-001", position: [7, 8, 9], rotation_xyzw: rotation });
    expect(boxes()[0]).toMatchObject({ id: "candidate-001", center: [7, 8, 9], rotation_xyzw: rotation });
    expect(calls("/objects/candidate-001/delete")).toHaveLength(1);
    expect(calls("/objects/candidate-001/restore")).toHaveLength(1);
  });

  it("Ignore retains only the source observation at A; Restore rebinds the editable visual at B", async () => {
    const base = scene("rev-001", "CANDIDATE");
    const gaussian = { ...ref, artifact_type: "ObjectGaussians" };
    base.objects[0] = { ...base.objects[0], visual_ref: gaussian } as (typeof base.objects)[0];
    const policy = { object_id: "candidate-001", visual_policy: "source", source_visual_required: true, source_transform: { ...base.objects[0].transform, translation_xyz: [8, 9, 10] }, readiness_blockers: [] };
    const ignored = { ...base, scene_revision: "rev-002", objects: [{ ...base.objects[0], provenance: { review: "IGNORED" } }] };
    routeFetch({
      "/objects/candidate-001/ignore": [reply({ scene: ignored, representations: [policy] })],
      "/objects/candidate-001/restore": [reply({ scene: { ...base, scene_revision: "rev-003" }, representations: [policy] })],
      "/scene": [reply({ scene: base, representations: [policy] })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    const canvas = await screen.findByTestId("metric-scene");
    const objects = () => JSON.parse(canvas.dataset.objects!);
    fireEvent.click(screen.getByRole("button", { name: "Loại Vật thể 1" }));
    await waitFor(() => expect(objects()[0].position).toEqual([8, 9, 10]));
    expect(objects()).toHaveLength(1);
    expect(objects()[0]).toMatchObject({ id: "candidate-001", visible: true });
    expect(JSON.parse(canvas.dataset.boxes!)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Đã loại/xoá/gộp/ẩn · 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục Vật thể 1" }));
    await waitFor(() => expect(objects()[0].position).toEqual(base.objects[0].transform.translation_xyz));
    expect(JSON.parse(canvas.dataset.boxes!)).toHaveLength(1);
  });

  it("scene Draft: hiện banner Tạo mesh, khoá Dịch/Xoay bằng lý do, và gizmo không mở", async () => {
    const policy = { object_id: "candidate-001", visual_policy: "source", source_visual_required: false, source_transform: null, readiness_blockers: [] };
    const base = scene("rev-001", "CONFIRMED");
    routeFetch({ "/scene": [reply({ scene: { ...base, provenance: { ...base.provenance, object_geometry: "awaiting_review" } }, representations: [policy] })] });
    render(<ObjectReviewView jobId="job-a" />);

    const banner = await screen.findByRole("region", { name: "Tạo mesh vật thể" });
    expect(banner).toHaveTextContent("Tạo mesh cho 1 vật đã chọn");
    expect(screen.queryByText(/Đang duyệt tách vật/)).not.toBeInTheDocument();
    expect(screen.getByTestId("locked")).toHaveTextContent("Cần tạo mesh trước");
    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Dịch" }));
    expect(screen.getByTestId("gizmo")).toHaveTextContent("none");
  });

  it("khoá Tạo gói mô phỏng khi scene chưa có mesh: nút vô hiệu, tooltip nêu lý do, không gửi POST", async () => {
    routeFetch({});
    render(<SimulationPackagePanel jobId="job-a" sceneRevision="rev-001" lockedReason="Cần tạo mesh trước" onSceneChanged={() => {}} />);

    const create = await screen.findByRole("button", { name: "Tạo gói mô phỏng" });
    expect(create).toBeDisabled();
    expect(create).toHaveAttribute("title", "Cần tạo mesh trước");
    expect(calls("/simulation-package").some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("vật đã dựng hiện nguồn collider là vỏ Gaussian, kèm lý do máy chủ ghi", async () => {
    const policy = { object_id: "candidate-001", visual_policy: "source", source_visual_required: false, source_transform: null, readiness_blockers: [] };
    const base = scene("rev-001", "CONFIRMED", undefined, undefined, [0.1, 0, 0]);
    const built = {
      ...base,
      objects: base.objects.map((item) => ({
        ...item,
        provenance: { ...item.provenance, surface_selection: { chosen: "gaussian_shell", reason: "ObjectGS không đạt QA" } },
      })),
    };
    routeFetch({ "/scene": [reply({ scene: built, representations: [policy] })] });
    render(<ObjectReviewView jobId="job-a" />);

    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    expect(screen.getByText("Collider: Vỏ Gaussian")).toBeInTheDocument();
    expect(screen.getByText("ObjectGS không đạt QA")).toBeInTheDocument();
  });

  it("scene Draft: khoá Thêm vật cản hộp và Thêm từ thư viện; scene sẵn sàng vẫn bấm được", async () => {
    const policy = { object_id: "candidate-001", visual_policy: "source", source_visual_required: false, source_transform: null, readiness_blockers: [] };
    const base = scene("rev-001", "CONFIRMED");
    routeFetch({ "/scene": [reply({ scene: { ...base, provenance: { ...base.provenance, object_geometry: "awaiting_review" } }, representations: [policy] })] });
    const { unmount } = render(<ObjectReviewView jobId="job-a" />);

    const catalogButton = await screen.findByRole("button", { name: "Thêm từ thư viện" });
    const obstacleButton = screen.getByRole("button", { name: "Thêm vật cản hộp" });
    expect(catalogButton).toBeDisabled();
    expect(catalogButton).toHaveAttribute("title", "Cần tạo mesh trước");
    expect(obstacleButton).toBeDisabled();
    expect(obstacleButton).toHaveAttribute("title", "Cần tạo mesh trước");
    unmount();

    routeFetch({ "/scene": [reply({ scene: base, representations: [policy] })] });
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByRole("button", { name: "Thêm từ thư viện" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Thêm vật cản hộp" })).toBeEnabled();
  });
});

/** Scene theo vật có membership, collision theo vật và khoá object_geometry: nút Chỉnh vùng hiện khi chọn vật. */
function regionScene(revision = "rev-001") {
  const result = membershipScene(revision);
  return {
    ...result,
    environment: { ...result.environment, object_aware_collision_ref: ref },
    provenance: { ...result.provenance, object_geometry: "ready" },
  };
}

/** Scene Draft thật: `object_geometry` đang chờ duyệt, có membership, không có collision theo vật. */
function draftRegionScene(revision = "rev-001") {
  const result = membershipScene(revision);
  return { ...result, provenance: { ...result.provenance, object_geometry: "awaiting_review" } };
}

const regionPreview = {
  scene_revision: "rev-001",
  membership_checksum: `sha256:${"b".repeat(64)}`,
  object_id: "candidate-001",
  added_count: 3,
  removed_count: 0,
  object_gaussian_count: 120,
  protected_floor_count: 0,
  overlaps: {},
  claimed: {},
  added_sample_m: [],
  removed_sample_m: [],
  shell_glb_base64: null,
  shell_error: null,
};

/** Box ban đầu máy chủ trả về: lệch tâm so với gốc để chứng minh panel dùng đúng box này (T-023). */
const regionFit = {
  scene_revision: "rev-001",
  membership_checksum: `sha256:${"b".repeat(64)}`,
  object_id: "candidate-001",
  center_m: [0.12, -0.05, 0.3],
  half_extents_m: [0.3, 0.2, 0.15],
  yaw_rad: 0,
  rows: 120,
};

describe("ObjectReviewView chỉnh vùng (T-016)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("chọn vật có tay nắm; kéo hộp mở xem trước, huỷ không ghi scene", async () => {
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: regionScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    const handle = await screen.findByRole("button", { name: "Kéo mặt hộp" });
    expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument();
    expect(vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes("/region/preview"))).toHaveLength(0);
    fireEvent.click(handle);
    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    expect(await within(inspector).findByRole("region", { name: "Chỉnh vùng" })).toBeInTheDocument();
    expect(within(inspector).getByRole("tab", { name: "Chỉnh vùng" })).toHaveAttribute("aria-selected", "true");
    fireEvent.mouseDown(within(inspector).getByRole("tab", { name: "Thông tin" }), { button: 0, ctrlKey: false });
    expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument();
    fireEvent.mouseDown(within(inspector).getByRole("tab", { name: "Chỉnh vùng" }), { button: 0, ctrlKey: false });
    expect(within(inspector).getByRole("region", { name: "Chỉnh vùng" })).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(global.fetch).mock.calls.some(([url]) => String(url).includes("/region/preview"))).toBe(true));
    const preview = vi.mocked(global.fetch).mock.calls.find(([url]) => String(url).includes("/region/preview"));
    expect(JSON.parse(String(preview![1]?.body)).boxes[0].half_extents_m[0]).toBe(regionFit.half_extents_m[0] / 2);
    fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
    expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument();
    expect(vi.mocked(global.fetch).mock.calls.some(([url]) => String(url).includes("/region/apply"))).toBe(false);
  });

  it("scene có object_geometry: Chỉnh vùng mở panel của vật đang chọn; Brush/Lasso vẫn là trình sửa chi tiết", async () => {
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: regionScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));

    expect(await screen.findByRole("region", { name: "Chỉnh vùng" })).toHaveTextContent("Chỉnh vùng · Vật thể 1");
    expect(screen.getByRole("list", { name: "Box vùng" })).toHaveTextContent("Cộng #1");

    expect(screen.getByRole("button", { name: "Chỉnh chi tiết (Brush/Lasso)" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh chi tiết (Brush/Lasso)" }));
    expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Chỉnh vùng Gaussian nguồn" })).toBeInTheDocument();
  });

  it("Draft (object_geometry đang duyệt, không có collision theo vật): Chỉnh vùng vẫn mở panel; Brush/Lasso bị khoá kèm lý do", async () => {
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: draftRegionScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));

    const brush = screen.getByRole("button", { name: "Chỉnh chi tiết (Brush/Lasso)" });
    expect(brush).toBeDisabled();
    expect(brush).toHaveAttribute("title", "Dùng Chỉnh vùng khi đang duyệt; Brush/Lasso dùng được sau khi Tạo mesh");

    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));
    expect(await screen.findByRole("region", { name: "Chỉnh vùng" })).toHaveTextContent("Chỉnh vùng · Vật thể 1");
  });

  it("scene cũ chưa có object_geometry giữ nút Chỉnh vùng Gaussian cũ", async () => {
    const legacy = membershipScene();
    routeFetch({
      "/scene": [reply({ scene: { ...legacy, environment: { ...legacy.environment, object_aware_collision_ref: ref } } })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));

    expect(screen.getByRole("button", { name: "Chỉnh vùng Gaussian · Box / Brush / Lasso" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Chỉnh vùng" })).not.toBeInTheDocument();
  });

  it("Apply trên Draft (201) gửi revision và membership, đóng panel rồi tải lại scene", async () => {
    const before = { ...draftRegionScene(), objects: draftRegionScene().objects.map((object) => ({ ...object, visual_ref: { ...ref, artifact_type: "ObjectGaussians" } })) };
    const after = { ...draftRegionScene("rev-002"), objects: draftRegionScene("rev-002").objects.map((object) => ({
      ...object,
      visual_ref: { ...ref, artifact_type: "ObjectGaussians" },
      geometry_ref: { ...ref, artifact_uri: "artifact://jobs/job-a/scene/objects/shells/updated.glb", artifact_checksum: `sha256:${"f".repeat(64)}` },
    })) };
    const routes = {
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/region/apply": [reply({ job_id: "job-a", previous_scene_revision: "rev-001", scene_revision: "rev-002", scene: {} }, 201)],
      "/scene": [reply({ scene: before }), reply({ scene: after })],
    };
    routeFetch(routes);
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument());
    await waitFor(() => expect(routes["/scene"]).toHaveLength(0));
    await waitFor(() => expect(JSON.parse(screen.getByTestId("metric-scene").getAttribute("data-boxes")!)[0].boundsUrl).toBe(jobArtifactContentUrl("job-a", after.objects[0].geometry_ref)));
    const apply = vi.mocked(global.fetch).mock.calls.find(([url]) => String(url).includes("/region/apply"));
    expect(JSON.parse((apply![1] as RequestInit).body as string)).toMatchObject({
      expected_scene_revision: "rev-001",
      membership_checksum: `sha256:${"b".repeat(64)}`,
      claim_from: [],
    });
  });

  it("Apply trên Ready (202) đóng panel và yêu cầu đọc lại tiến độ qua trạng thái tách vật chung", async () => {
    const refresh = vi.fn();
    const handle = { state: null, error: null, sending: false, pending: false, send: vi.fn(), cancel: vi.fn(), refresh };
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/region/apply": [reply({ status: "queued", mode: "region", scene_revision: "rev-001", operation_id: "op-1" }, 202)],
      "/scene": [reply({ scene: regionScene() })],
    });
    render(
      <ObjectifyContext.Provider value={handle as unknown as ObjectifyHandle}>
        <ObjectReviewView jobId="job-a" />
      </ObjectifyContext.Provider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument());
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("chọn vật khác thì panel chỉnh vùng của vật cũ đóng", async () => {
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: regionScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));
    expect(await screen.findByRole("region", { name: "Chỉnh vùng" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Chọn Vật thể 2" }));
    expect(screen.queryByRole("region", { name: "Chỉnh vùng" })).not.toBeInTheDocument();
  });
});

/** Vật thứ hai đã xác nhận có Gaussian riêng: Draft không được vẽ Gaussian của nó (tránh chồng với môi trường). */
function shellScene(objectGeometry: "awaiting_review" | "ready") {
  const result = membershipScene();
  return {
    ...result,
    provenance: { ...result.provenance, object_geometry: objectGeometry },
    objects: result.objects.map((object) => ({
      ...object,
      visual_ref: { ...ref, artifact_type: "ObjectGaussians" },
      ...((object as unknown as { id: string }).id === "candidate-002" ? { state: "CONFIRMED", active: true } : {}),
    })),
  };
}

describe("ObjectReviewView vỏ và Gaussian theo Draft/Ready (T-017)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("Draft: không nạp Gaussian của vật nào; mọi vật có vỏ, vật đang chọn là selected", async () => {
    routeFetch({ "/scene": [reply({ scene: shellScene("awaiting_review") })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));

    const stage = screen.getByTestId("metric-scene");
    const objects = JSON.parse(stage.getAttribute("data-objects") ?? "[]") as { url: string | null }[];
    expect(objects.every((item) => item.url === null)).toBe(true);
    const shells = JSON.parse(stage.getAttribute("data-shells") ?? "[]") as { id: string; url: string; style: string }[];
    expect(shells.map((shell) => [shell.id, shell.style])).toEqual([
      ["candidate-001", "selected"],
      ["candidate-002", "idle"],
    ]);
    expect(shells[0].url).toBe(jobArtifactContentUrl("job-a", ref));
  });

  it("Ready: vật đã xác nhận nạp Gaussian như trước và không có vỏ vẽ riêng", async () => {
    routeFetch({ "/scene": [reply({ scene: shellScene("ready") })] });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));

    const stage = screen.getByTestId("metric-scene");
    const objects = JSON.parse(stage.getAttribute("data-objects") ?? "[]") as { id: string; url: string | null }[];
    const visual = { ...ref, artifact_type: "ObjectGaussians" } as never;
    expect(objects.find((item) => item.id === "candidate-002")?.url).toBe(jobArtifactContentUrl("job-a", visual));
    expect(stage.getAttribute("data-shells")).toBe("[]");
  });

  it("mở panel gọi fit đúng một lần và panel hiện box của máy chủ, không dựng từ kích thước", async () => {
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: regionScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));
    expect(await screen.findByRole("region", { name: "Chỉnh vùng" })).toBeInTheDocument();

    const fits = vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes("/region/fit"));
    expect(fits).toHaveLength(1);
    expect(String(fits[0][0])).toContain("expected_scene_revision=rev-001");
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();
    const previews = vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes("/region/preview"));
    expect(JSON.parse(previews[0][1]!.body as string).boxes[0]).toMatchObject({
      center_m: [0.12, -0.05, 0.3],
      half_extents_m: [0.3, 0.2, 0.15],
    });
  });

  it("fit lỗi: không có box và không có Apply; Thử lại gọi lại máy chủ rồi mới mở panel", async () => {
    routeFetch({
      "/region/fit": [reply({ detail: "vật còn 10 Gaussian (tối thiểu 50) nên không lấy được vùng hiện tại" }, 422), reply(regionFit)],
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: regionScene() })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh vùng" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("tối thiểu 50");
    expect(screen.queryByRole("list", { name: "Box vùng" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByRole("region", { name: "Chỉnh vùng" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cộng #1" })).toBeInTheDocument();
    const fits = vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes("/region/fit"));
    expect(fits).toHaveLength(2);
  });

  it("Chỉnh vùng không cần kích thước primitive: vật không có kích thước vẫn mở được", async () => {
    const scene = regionScene();
    routeFetch({
      "/region/preview": Array.from({ length: 4 }, () => reply(regionPreview)),
      "/scene": [reply({ scene: { ...scene, objects: scene.objects.map((item) => ({ ...item, primitive_dimensions_xyz_m: null })) } })],
    });
    render(<ObjectReviewView jobId="job-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Chọn Vật thể 1" }));
    const open = screen.getByRole("button", { name: "Chỉnh vùng" });
    expect(open).toBeEnabled();
    fireEvent.click(open);
    expect(await screen.findByRole("region", { name: "Chỉnh vùng" })).toBeInTheDocument();
  });
});

describe("ObjectReviewView Benchmark theo quyền sửa job (T-033)", () => {
  const emptyTruth = {
    schema_version: "1.0",
    include_in_benchmark: false,
    data_source: "self_capture",
    robot: null,
    distances: [],
    gaps: [],
    key_obstacle_ids: [],
    layouts: {},
    manual_baseline_minutes: null,
    l4: null,
    notes: "",
  };

  beforeEach(() => {
    vi.mocked(global.fetch).mockReset();
  });

  it("canMutateJob=false: panel Benchmark chỉ đọc, không có nút Lưu hoạt động", async () => {
    routeFetch({
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })],
      "/benchmark-truth": [reply({ version: 0, truth: emptyTruth, updated_at: null })],
    });
    render(<ObjectReviewView jobId="job-a" canMutateJob={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Benchmark" }));
    expect((await screen.findByLabelText("Bề rộng (m)")) as HTMLInputElement).toBeDisabled();
    expect((screen.getByRole("button", { name: "Lưu" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/chỉ có quyền xem/)).toBeInTheDocument();
  });

  it("canMutateJob=true: panel Benchmark sửa được và Lưu khi có thay đổi", async () => {
    routeFetch({
      "/scene": [reply({ scene: scene("rev-001", "CANDIDATE") })],
      "/benchmark-truth": [reply({ version: 0, truth: emptyTruth, updated_at: null })],
    });
    render(<ObjectReviewView jobId="job-a" canMutateJob />);
    fireEvent.click(await screen.findByRole("button", { name: "Benchmark" }));
    const width = (await screen.findByLabelText("Bề rộng (m)")) as HTMLInputElement;
    expect(width).toBeEnabled();
    fireEvent.change(width, { target: { value: "0.8" } });
    expect((screen.getByRole("button", { name: "Lưu" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
