"use client";


import { errorMessage } from "@/lib/ui-error";

import dynamic from "next/dynamic";
import {
  Boxes,
  Check,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Library,
  Loader2,
  Pencil,
  Plus,
  Tag,
  Undo2,
  X,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, useSyncExternalStore } from "react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/shadcn/alert-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/shadcn/tabs";
import { subscribeTheme, themeColor, themeKey } from "@/lib/theme";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { ObjectifyNotice } from "@/features/studio/ObjectifyNotice";
import { composeColliderTransform } from "@/features/viewer/layers";
import type { GizmoMode, OverlayBox, OverlayObject } from "@/features/viewer/scene-overlay";
import type { PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import { ApiError } from "@/lib/api/client";
import { jobArtifactContentUrl, listJobArtifacts } from "@/lib/api/endpoints";
import {
  addBoxObstacle,
  addCatalogObject,
  applyObjectAction,
  catalogPreviewUrl,
  editCollider,
  getJobScene,
  getSceneCatalog,
  getStageViews,
  mergeObjectCandidates,
  reassignObjectMembership,
  restoreSceneRevision,
  selectLidarCollisionSource,
  setObjectTransform,
  type ObjectAction,
  type SceneCatalog,
} from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { ColliderEditCommand, ObjectRepresentation, ProductArtifactRef, SceneIR, SceneObject } from "@/lib/contracts/api";
import type { StageView } from "@/lib/contracts/studio";

// Chỉ dùng khi scene không có 3DGS: tải three.js theo nhu cầu, không kéo vào mọi lần mở Studio.
const CollisionMeshCanvas = dynamic(() => import("@/features/studio/StageViewer").then((m) => m.CollisionMeshCanvas), { ssr: false });

/** Hình riêng của một vật trong viewer: Gaussian của vật tách từ scene, hoặc GLB của asset thư viện. */
function objectVisual(jobId: string, object: SceneObject, previews: ReadonlySet<string>): Pick<OverlayObject, "url" | "kind"> {
  if (object.visual_ref?.artifact_type === "ObjectGaussians") return { url: jobArtifactContentUrl(jobId, object.visual_ref), kind: "gsplat" };
  const family = object.provenance?.catalog_family;
  if (typeof family === "string" && previews.has(family)) return { url: catalogPreviewUrl(family), kind: "model" };
  return { url: null };
}

type Vec3Tuple = [number, number, number];
type QuaternionTuple = [number, number, number, number];
type ColliderPreviewDraft = {
  objectId: string;
  sceneRevision: string;
  dimensions: Vec3Tuple;
  localTranslation: Vec3Tuple;
  localRotation: QuaternionTuple;
};
type ColliderChanges = Pick<
  ColliderEditCommand,
  "dimensions_xyz_m" | "local_translation_xyz_m" | "local_rotation_quaternion_xyzw"
>;
type ColliderFormValues = { dimensions: [string, string, string]; translation: [string, string, string]; rotation: [string, string, string] };

function colliderWithPreview(object: SceneObject, draft: ColliderPreviewDraft | null) {
  if (!object.collider || draft?.objectId !== object.id) return object.collider;
  return {
    ...object.collider,
    dimensions_xyz_m: draft.dimensions,
    local_transform: {
      ...object.collider.local_transform,
      translation_xyz: draft.localTranslation,
      rotation_quaternion_xyzw: draft.localRotation,
    },
  };
}

function colliderShapeUrl(jobId: string, collider: SceneObject["collider"]): string | null {
  if (!collider?.geometry_ref || !collider.geometry_ref.artifact_uri.endsWith(".glb")) return null;
  if ((collider.collider_type === "AABB" || collider.collider_type === "OBB") && collider.dimensions_xyz_m) return null;
  return jobArtifactContentUrl(jobId, collider.geometry_ref);
}

function objectColliderTransform(object: SceneObject, draft: ColliderPreviewDraft | null = null) {
  const collider = colliderWithPreview(object, draft);
  return collider ? composeColliderTransform(object, collider) : object.transform;
}

function quaternionToEulerDegrees([x, y, z, w]: QuaternionTuple): Vec3Tuple {
  const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
  const sinPitch = Math.max(-1, Math.min(1, 2 * (w * y - z * x)));
  const pitch = Math.asin(sinPitch);
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
  return [roll, pitch, yaw].map((angle) => Number(((angle * 180) / Math.PI).toFixed(3))) as Vec3Tuple;
}

/** Build qZ × qY × qX from the user-facing local X/Y/Z angles in degrees. */
function eulerDegreesToQuaternion([x, y, z]: Vec3Tuple): QuaternionTuple {
  const half = (angle: number) => (angle * Math.PI) / 360;
  const [sx, sy, sz] = [x, y, z].map(half).map(Math.sin);
  const [cx, cy, cz] = [x, y, z].map(half).map(Math.cos);
  return [
    sx * cy * cz - cx * sy * sz,
    cx * sy * cz + sx * cy * sz,
    cx * cy * sz - sx * sy * cz,
    cx * cy * cz + sx * sy * sz,
  ];
}

function colliderFormValues(object: SceneObject): ColliderFormValues | null {
  const collider = object.collider;
  if (!collider?.dimensions_xyz_m) return null;
  return {
    dimensions: collider.dimensions_xyz_m.map(String) as ColliderFormValues["dimensions"],
    translation: collider.local_transform.translation_xyz.map(String) as ColliderFormValues["translation"],
    rotation: quaternionToEulerDegrees(collider.local_transform.rotation_quaternion_xyzw).map(String) as ColliderFormValues["rotation"],
  };
}

function parseColliderForm(object: SceneObject, values: ColliderFormValues): { preview: Omit<ColliderPreviewDraft, "sceneRevision">; changes: ColliderChanges } | null {
  const collider = object.collider;
  if (!collider?.dimensions_xyz_m) return null;
  const parse = (items: string[]): number[] | null => {
    if (items.some((item) => item.trim() === "")) return null;
    const parsed = items.map(Number);
    return parsed.every(Number.isFinite) ? parsed : null;
  };
  const dimensions = parse(values.dimensions);
  const translation = parse(values.translation);
  const rotationDegrees = parse(values.rotation);
  if (!dimensions || !translation || !rotationDegrees || dimensions.some((value) => value <= 0)) return null;

  const nextDimensions = dimensions as Vec3Tuple;
  const nextTranslation = translation as Vec3Tuple;
  const baseDimensions = collider.dimensions_xyz_m;
  const baseTranslation = collider.local_transform.translation_xyz;
  const baseRotation = collider.local_transform.rotation_quaternion_xyzw;
  const baseAngles = quaternionToEulerDegrees(baseRotation);
  const changed = (a: readonly number[], b: readonly number[], tolerance = 1e-9) =>
    a.some((value, index) => Math.abs(value - b[index]) > tolerance);
  const rotationChanged = changed(rotationDegrees, baseAngles, 1e-3);
  const nextRotation = rotationChanged ? eulerDegreesToQuaternion(rotationDegrees as Vec3Tuple) : baseRotation;
  const changes: ColliderChanges = {};
  if (changed(nextDimensions, baseDimensions)) changes.dimensions_xyz_m = nextDimensions;
  if (changed(nextTranslation, baseTranslation)) changes.local_translation_xyz_m = nextTranslation;
  if (rotationChanged) changes.local_rotation_quaternion_xyzw = nextRotation;
  return {
    preview: { objectId: object.id, dimensions: nextDimensions, localTranslation: nextTranslation, localRotation: nextRotation },
    changes,
  };
}

type ROIForm = { minX: string; minY: string; minZ: string; maxX: string; maxY: string; maxZ: string };

const EMPTY_ROI: ROIForm = { minX: "", minY: "", minZ: "", maxX: "", maxY: "", maxZ: "" };
const ROI_FIELDS: { key: keyof ROIForm; label: string }[] = [
  { key: "minX", label: "X nhỏ nhất (m)" },
  { key: "maxX", label: "X lớn nhất (m)" },
  { key: "minY", label: "Y nhỏ nhất (m)" },
  { key: "maxY", label: "Y lớn nhất (m)" },
  { key: "minZ", label: "Z nhỏ nhất (m)" },
  { key: "maxZ", label: "Z lớn nhất (m)" },
];

function correctionUnavailableReason(scene: SceneIR, object: SceneObject): string | null {
  const membership = scene.environment.membership;
  if (!membership) return "Scene này chưa lưu Gaussian membership.";
  if (!Object.values(membership.label_to_object_id).includes(object.id)) return "Vật không có trong membership hiện tại.";
  if (object.state !== "CANDIDATE") return "Chỉ hỗ trợ ứng viên chưa xác nhận.";
  if (object.origin !== "reconstructed" || object.asset_ref) return "Asset hoặc vật thêm tay không được hỗ trợ.";
  const ownership = object.source_collision;
  if (!ownership) return "Thiếu ownership collision nguồn.";
  if (
    ownership.object_id !== object.id ||
    ownership.source_geometry_ref.artifact_checksum !== scene.environment.geometry_ref.artifact_checksum ||
    ownership.source_geometry_ref.artifact_uri !== scene.environment.geometry_ref.artifact_uri ||
    ownership.extraction_revision !== membership.extraction_revision ||
    JSON.stringify(ownership.source_transform) !== JSON.stringify(object.transform)
  ) {
    return "Pose hoặc ownership collision không còn khớp dữ liệu nguồn.";
  }
  const rotation = object.transform.rotation_quaternion_xyzw;
  if (Math.abs(rotation[0]) > 1e-6 || Math.abs(rotation[1]) > 1e-6 || Math.abs(rotation[2]) > 1e-6 || Math.abs(rotation[3] - 1) > 1e-6) {
    return "Hiệu chỉnh hiện chỉ hỗ trợ vật chưa xoay.";
  }
  return null;
}

function parseROI(form: ROIForm): { min_xyz_m: [number, number, number]; max_xyz_m: [number, number, number] } | null {
  const values = [form.minX, form.minY, form.minZ, form.maxX, form.maxY, form.maxZ];
  if (values.some((value) => value.trim() === "")) return null;
  const numbers = values.map(Number);
  if (numbers.some((value) => !Number.isFinite(value) || Math.abs(value) > 1_000_000)) return null;
  const [minX, minY, minZ, maxX, maxY, maxZ] = numbers;
  if (minX >= maxX || minY >= maxY || minZ >= maxZ) return null;
  return { min_xyz_m: [minX, minY, minZ], max_xyz_m: [maxX, maxY, maxZ] };
}

/** Trạng thái lưu SceneObject cho header scene (STUDIO_UX_SPEC.md Q5: mỗi thao tác là một revision). */
export type SaveState =
  | { status: "saved"; revision: string }
  | { status: "saving"; revision: string }
  | { status: "error"; revision: string; message: string; retry: () => void };

type Filter = "all" | "pending" | "confirmed" | "ignored";

type ArchiveCategory = "ignored" | "deleted" | "merged" | "viewport_hidden" | "simulation_disabled";
const ARCHIVE_CATEGORIES: { value: ArchiveCategory; label: string }[] = [
  { value: "ignored", label: "Đã loại" },
  { value: "deleted", label: "Đã xoá" },
  { value: "merged", label: "Đã gộp" },
  { value: "viewport_hidden", label: "Ẩn trên màn hình" },
  { value: "simulation_disabled", label: "Tắt trong mô phỏng" },
];

function archiveCategory(object: SceneObject, hiddenIds: ReadonlySet<string>): ArchiveCategory | null {
  if (object.provenance.review === "IGNORED") return "ignored";
  if (object.provenance.review === "DELETED") return "deleted";
  if (object.provenance.review === "MERGED") return "merged";
  if (object.state === "CONFIRMED" && !object.active) return "simulation_disabled";
  return hiddenIds.has(object.id) ? "viewport_hidden" : null;
}

const FILTERS: { value: Filter; label: string; match: (object: SceneObject, hiddenIds: ReadonlySet<string>) => boolean }[] = [
  { value: "all", label: "Chưa loại", match: (object, hidden) => !archiveCategory(object, hidden) },
  { value: "pending", label: "Chờ xác nhận", match: (object, hidden) => object.state === "CANDIDATE" && !archiveCategory(object, hidden) },
  { value: "confirmed", label: "Đã xác nhận", match: (object, hidden) => object.state === "CONFIRMED" && !archiveCategory(object, hidden) },
  { value: "ignored", label: "Đã loại/xoá/gộp/ẩn", match: (object, hidden) => Boolean(archiveCategory(object, hidden)) },
];

/**
 * Studio vật thể (ADR 0006, PRODUCT-07/07A, STUDIO_UX_SPEC.md P5): danh sách · viewport 3DGS hệ mét ·
 * inspector. Người dùng xác nhận/loại ứng viên, ẩn/đổi tên vật đã xác nhận hoặc thêm vật cản hộp.
 * Mỗi thao tác là một revision SceneIR mới ở backend; màn hình chỉ giữ revision vừa nhận, không tự
 * sửa scene ở client.
 */
export function ObjectReviewView({
  jobId,
  revision,
  onSaveState,
  sceneStateControls,
}: {
  jobId: string;
  /** Revision mới nhất nơi khác biết; khác revision đang giữ thì tải lại (tránh 409 khi thao tác). */
  revision?: string | null;
  onSaveState?: (state: SaveState) => void;
  sceneStateControls?: ReactNode;
}) {
  const [representations, setRepresentations] = useState<ObjectRepresentation[]>([]);
  const [scene, setScene] = useState<SceneIR | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [viewportHidden, setViewportHidden] = useState({ jobId, ids: new Set<string>() });
  const hiddenIds = useMemo(() => viewportHidden.jobId === jobId ? viewportHidden.ids : new Set<string>(), [viewportHidden, jobId]);
  const acceptScene = (next: SceneIR, policies: ObjectRepresentation[] = []) => {
    setRepresentations(policies);
    setScene(next);
    const retained = new Set(next.objects.filter((item) => !["DELETED", "MERGED"].includes(String(item.provenance.review))).map((item) => item.id));
    setViewportHidden((previous) => ({ jobId, ids: new Set(previous.jobId === jobId ? [...previous.ids].filter((id) => retained.has(id)) : []) }));
  };
  const toggleViewportVisibility = (id: string) => {
    const hiding = !hiddenIds.has(id);
    setViewportHidden((previous) => {
      const ids = new Set(previous.jobId === jobId ? previous.ids : []);
      if (ids.has(id)) ids.delete(id);
      else ids.add(id);
      return { jobId, ids };
    });
    if (id === selected) setTool("none");
    setLeftTab("objects");
    setFilter(hiding ? "ignored" : "all");
  };
  const [mergeRestoreTarget, setMergeRestoreTarget] = useState<string | null>(null);
  const [correctionPanelOpen, setCorrectionPanelOpen] = useState(false);
  const [collisionSourcePanelOpen, setCollisionSourcePanelOpen] = useState(false);
  const [collisionCandidates, setCollisionCandidates] = useState<ProductArtifactRef[]>([]);
  const [collisionCandidatesLoadedFor, setCollisionCandidatesLoadedFor] = useState<string | null>(null);
  const [collisionCandidatesLoading, setCollisionCandidatesLoading] = useState(false);
  const [collisionCandidatesError, setCollisionCandidatesError] = useState<string | null>(null);
  const collisionCandidateRequest = useRef<AbortController | null>(null);
  const [mergeCandidateIds, setMergeCandidateIds] = useState<string[]>([]);
  const [mergePrimaryId, setMergePrimaryId] = useState("");
  const [semanticSourceId, setSemanticSourceId] = useState("");
  const [reassignSourceId, setReassignSourceId] = useState<string | null>(null);
  const [reassignTargetId, setReassignTargetId] = useState<string | null>(null);
  const [roi, setRoi] = useState<ROIForm>(EMPTY_ROI);
  const mutationInFlight = useRef(false);
  const [colliderDraft, setColliderDraft] = useState<ColliderPreviewDraft | null>(null);
  const [colliderFormReset, setColliderFormReset] = useState(0);
  const keepErrorAfterReload = useRef(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [cameras, setCameras] = useState<StageView["cameras"]>([]);
  const [focus, setFocus] = useState<{ id: string; nonce: number } | undefined>();
  const [reload, setReload] = useState(0);
  const [tool, setTool] = useState<GizmoMode | "none">("none");
  const [selectMode, setSelectMode] = useState(true);
  const [catalog, setCatalog] = useState<SceneCatalog | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [leftTab, setLeftTab] = useState("state");
  const [rightCollapsed, setRightCollapsed] = useState(false);
  /** Vật đang chờ đặt bằng chuột: kích thước hộp xem trước + lệnh ghi khi bấm sàn. */
  const [placing, setPlacing] = useState<{ label: string; dimensions: [number, number, number]; commit: (point: [number, number, number]) => void } | null>(null);
  const cancelPlacing = useCallback(() => setPlacing(null), []);
  const stale = Boolean(revision && scene && !busy && revision !== scene.scene_revision);

  const selectObject = (id: string | null) => {
    if (id !== selected) setColliderDraft(null);
    setSelected(id);
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reset ephemeral selection state when scene revision changes
    setMergeCandidateIds([]);
    setMergePrimaryId("");
    setSemanticSourceId("");
    setReassignSourceId(null);
    setReassignTargetId(null);
    setRoi(EMPTY_ROI);
    setColliderDraft(null);
  }, [scene?.scene_revision]);

  /** Chọn và cho camera bay tới vật (từ danh sách hoặc nút trong inspector). */
  const flyTo = (id: string) => {
    selectObject(id);
    setFocus((previous) => ({ id, nonce: (previous?.nonce ?? 0) + 1 }));
    setRightCollapsed(false);
  };
  /** Chọn bằng cách bấm hộp trong 3D: đánh dấu và cuộn danh sách tới vật đó. */
  const selectFromScene = (id: string) => {
    selectObject(id);
    setLeftTab("objects");
    setRightCollapsed(false);
    document.getElementById(`object-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  useEffect(() => {
    const controller = new AbortController();
    getJobScene(jobId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        acceptScene(result.data.scene, result.data.representations);
        if (keepErrorAfterReload.current) keepErrorAfterReload.current = false;
        else setError(null);
        setMissing(false);
        onSaveState?.({ status: "saved", revision: result.data.scene.scene_revision });
      } else if (result.error.status === 404) setMissing(true);
      else setError(errorMessage(result.error));
    });
    return () => controller.abort();
  }, [jobId, reload, stale]); // eslint-disable-line react-hooks/exhaustive-deps -- onSaveState chỉ là kênh báo lên header

  useEffect(() => () => collisionCandidateRequest.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    // Camera quay hệ mét để mở scene tại góc camera đầu tiên; thiếu thì dùng camera mặc định.
    // Tách khỏi lần tải scene: camera không đổi khi sửa vật, tải lại sẽ tạo lại viewer 3D.
    getStageViews(jobId, controller.signal).then(
      (views) => setCameras(views.find((view) => view.kind === "gaussian" && view.unit === "meter")?.cameras ?? []),
      () => undefined,
    );
    return () => controller.abort();
  }, [jobId]);

  useEffect(() => {
    const controller = new AbortController();
    // Danh mục nhãn/asset không đổi theo scene: tải một lần; lỗi thì chỉ mất phần gán nhãn/thư viện.
    getSceneCatalog(controller.signal).then(setCatalog, () => undefined);
    return () => controller.abort();
  }, []);

  const previews = useMemo(() => new Set((catalog?.entries ?? []).filter((item) => item.has_preview).map((item) => item.family)), [catalog]);
  // SOURCE giữ extraction pose; OBJECT dùng pose đã chỉnh. Visibility viewport độc lập lifecycle.
  const missingSourcePolicies = (scene?.objects ?? []).filter((object) =>
    object.state === "CANDIDATE" && object.visual_ref?.artifact_type === "ObjectGaussians" &&
    !["DELETED", "MERGED"].includes(String(object.provenance.review)) &&
    !representations.some((item) => item.object_id === object.id));
  const splats = useMemo<OverlayObject[]>(
    () => (scene?.objects ?? []).flatMap((object) => {
      const policy = representations.find((item) => item.object_id === object.id);
      const visible = !hiddenIds.has(object.id);
      const editingRoot: OverlayObject = {
        id: object.id,
        ...objectVisual(jobId, object, previews),
        position: object.transform.translation_xyz,
        rotation_xyzw: object.transform.rotation_quaternion_xyzw,
        visible: visible && (policy ? policy.visual_policy === "object" : isPlaced(object)),
      };
      if (!policy && object.state === "CANDIDATE" && object.visual_ref?.artifact_type === "ObjectGaussians") {
        editingRoot.url = null;
        return [editingRoot];
      }
      if (policy?.visual_policy !== "source" || !policy.source_visual_required) return [editingRoot];
      editingRoot.url = null;
      editingRoot.visible = visible && isPlaced(object);
      if (!policy.source_transform || policy.readiness_blockers.length) return [editingRoot];
      return [editingRoot, {
        id: `source:${object.id}`,
        ...objectVisual(jobId, object, previews),
        position: policy.source_transform.translation_xyz,
        rotation_xyzw: policy.source_transform.rotation_quaternion_xyzw,
        visible,
      }];
    }),
    [scene, representations, jobId, previews, hiddenIds],
  );

  // Vật động (vật lý của SceneIR) đang đặt trong scene: khi Đi bộ, người đi đẩy được chúng (ADR 0010).
  const physicsObjects = useMemo<PhysicsObjectInput[]>(
    () =>
      (scene?.objects ?? [])
        .filter((object) => object.state === "CONFIRMED" && object.physics?.dynamic && object.active && !isIgnored(object))
        .map((object) => {
          const collider = colliderWithPreview(object, colliderDraft?.sceneRevision === scene?.scene_revision ? colliderDraft : null);
          return {
            id: object.id,
            position: object.transform.translation_xyz,
            rotation_xyzw: object.transform.rotation_quaternion_xyzw,
            colliderUrl: colliderShapeUrl(jobId, collider),
            colliderLocalTransform: collider?.local_transform ?? null,
            dimensions: collider?.dimensions_xyz_m ?? object.primitive_dimensions_xyz_m ?? null,
            mass_kg: object.physics!.mass_kg ?? 10,
            friction: object.physics!.dynamic_friction,
            restitution: object.physics!.restitution,
          };
        }),
    [scene, jobId, colliderDraft],
  );

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((item) => [item.value, scene?.objects.filter((object) => item.match(object, hiddenIds)).length ?? 0])) as Record<Filter, number>,
    [scene, hiddenIds],
  );
  const visibleObjects = useMemo(() => {
    const match = FILTERS.find((item) => item.value === filter)!.match;
    const objects = scene?.objects.filter((object) => match(object, hiddenIds)) ?? [];
    if (filter === "ignored") objects.sort((a, b) =>
      ARCHIVE_CATEGORIES.findIndex((item) => item.value === archiveCategory(a, hiddenIds)) -
      ARCHIVE_CATEGORIES.findIndex((item) => item.value === archiveCategory(b, hiddenIds)));
    return objects;
  }, [scene, filter, hiddenIds]);
  const theme = useSyncExternalStore(subscribeTheme, themeKey, () => "light:default");
  const visibleCollisionCandidates = collisionCandidatesLoadedFor === jobId ? collisionCandidates : [];
  const currentColliderDraft = colliderDraft?.sceneRevision === scene?.scene_revision ? colliderDraft : null;
  const boxes = useMemo<OverlayBox[]>(
    () =>
      (scene?.objects ?? [])
        .flatMap((object) => {
          if (!isPlaced(object) || hiddenIds.has(object.id)) return [];
          const collider = colliderWithPreview(object, currentColliderDraft);
          const dimensions = collider?.dimensions_xyz_m ?? object.primitive_dimensions_xyz_m;
          if (!dimensions) return [];
          const transform = objectColliderTransform(object, currentColliderDraft);
          return {
            id: object.id,
            center: transform.translation_xyz,
            rotation_xyzw: transform.rotation_quaternion_xyzw,
            dimensions,
            color: object.id === selected ? selectedColor() : stateColor(object),
            emphasized: object.id === selected,
            // Collider phân rã lồi bám theo hình vật; vật chỉ có hộp (thêm tay, asset thư viện) thì vẽ hộp.
            shapeUrl: colliderShapeUrl(jobId, collider),
          };
        }),
    // `theme` trong deps: đổi chế độ/bảng màu thì khung vật vẽ lại bằng màu mới.
    [scene, selected, jobId, theme, currentColliderDraft, hiddenIds], // eslint-disable-line react-hooks/exhaustive-deps
  );

  async function run(mutate: (revision: string) => Promise<{ scene: SceneIR; representations?: ObjectRepresentation[] }>) {
    if (!scene || mutationInFlight.current) return false;
    mutationInFlight.current = true;
    const revision = scene.scene_revision;
    setBusy(true);
    setColliderDraft(null);
    setColliderFormReset((value) => value + 1);
    setError(null);
    onSaveState?.({ status: "saving", revision });
    try {
      const response = await mutate(revision);
      const next = response.scene;
      acceptScene(next, response.representations);
      onSaveState?.({ status: "saved", revision: next.scene_revision });
      return true;
    } catch (cause: unknown) {
      // 409: scene đã đổi ở lượt khác — phải tải revision mới trước khi ghi (§S06 recovery).
      const conflict = cause instanceof ApiError && cause.status === 409;
      const message = conflict
        ? "Scene đã đổi ở lượt khác. Tải bản mới rồi thao tác lại."
        : errorMessage(cause, "Thao tác thất bại");
      setError(message);
      if (conflict) {
        keepErrorAfterReload.current = true;
        setReload((value) => value + 1);
      }
      onSaveState?.({
        status: "error",
        revision,
        message,
        retry: conflict ? () => setReload((value) => value + 1) : () => void run(mutate),
      });
      return false;
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  }

  async function loadCollisionCandidates() {
    collisionCandidateRequest.current?.abort();
    const controller = new AbortController();
    collisionCandidateRequest.current = controller;
    setCollisionCandidatesLoading(true);
    setCollisionCandidatesError(null);
    try {
      const result = await listJobArtifacts(jobId, controller.signal);
      if (controller.signal.aborted) return;
      setCollisionCandidatesLoadedFor(jobId);
      if (!result.ok) {
        setCollisionCandidatesError(result.error.message);
        setCollisionCandidates([]);
        return;
      }
      setCollisionCandidates(result.data.artifacts.filter((ref) => ref.artifact_type === "LidarCollisionCandidateManifest"));
    } finally {
      if (!controller.signal.aborted) setCollisionCandidatesLoading(false);
    }
  }

  const act = (object: SceneObject, action: ObjectAction, extra?: ActionExtra) =>
    run((revision) => applyObjectAction(jobId, object.id, action, revision, extra));

  async function restoreListedObject(object: SceneObject, confirmedMerge = false) {
    if (object.provenance.review === "MERGED" && !confirmedMerge) {
      setMergeRestoreTarget(object.id);
      return;
    }
    if (isIgnored(object) || (object.state === "CANDIDATE" && object.active) || (object.state === "CONFIRMED" && !object.active)) {
      const success = await run((revision) => applyObjectAction(jobId, object.id,
        isIgnored(object) || object.state === "CANDIDATE" ? "restore" : "hide", revision,
        object.state === "CONFIRMED" && !isIgnored(object) ? { active: true } : undefined));
      if (!success) return;
    }
    setViewportHidden((previous) => ({ ...previous, ids: new Set([...previous.ids].filter((id) => id !== object.id)) }));
    setFilter("all");
    setLeftTab("objects");
  }

  function openMerge(object: SceneObject) {
    setLeftTab("objects");
    setCorrectionPanelOpen(true);
    setMergeCandidateIds([object.id]);
    setMergePrimaryId(object.id);
    setSemanticSourceId("");
  }

  function toggleMergeCandidate(objectId: string) {
    const nextIds = mergeCandidateIds.includes(objectId)
      ? mergeCandidateIds.filter((id) => id !== objectId)
      : [...mergeCandidateIds, objectId];
    setMergeCandidateIds(nextIds);
    if (!nextIds.includes(mergePrimaryId)) setMergePrimaryId(nextIds[0] ?? "");
    setSemanticSourceId("");
  }

  function cancelCorrectionSelection() {
    setMergeCandidateIds([]);
    setMergePrimaryId("");
    setSemanticSourceId("");
    setReassignSourceId(null);
    setReassignTargetId(null);
    setRoi(EMPTY_ROI);
    setError(null);
  }

  if (missing) {
    return <Notice className="m-4">Chưa có vật thể: bước tách vật thể chạy sau khi dựng collision xong.</Notice>;
  }
  if (!scene) {
    return error ? (
      <Notice tone="rust" className="m-4">
        {error}
      </Notice>
    ) : (
      <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tải vật thể…
      </p>
    );
  }
  const current = scene.objects.find((object) => object.id === selected) ?? null;
  const previous = typeof scene.provenance.edited_from === "string" ? scene.provenance.edited_from : null;
  const membership = scene.environment.membership ?? null;
  const candidateCorrections = scene.objects
    .filter((object) => object.state === "CANDIDATE")
    .map((object) => ({ object, reason: correctionUnavailableReason(scene, object) }));
  const eligibleCorrections = candidateCorrections.filter(({ reason }) => reason === null).map(({ object }) => object);
  const selectedMergeCandidates = eligibleCorrections.filter((object) => mergeCandidateIds.includes(object.id));
  const mergePrimary = selectedMergeCandidates.find((object) => object.id === mergePrimaryId) ?? null;
  const mergeSemanticClasses = new Set(selectedMergeCandidates.map((object) => object.semantic_class));
  const hasSemanticConflict = mergeSemanticClasses.size > 1;
  const parsedROI = parseROI(roi);
  const canMerge = Boolean(
    !busy && membership && selectedMergeCandidates.length >= 2 && mergePrimary &&
    (!hasSemanticConflict || selectedMergeCandidates.some((object) => object.id === semanticSourceId)),
  );
  const canReassign = Boolean(
    !busy && membership && parsedROI && reassignSourceId !== reassignTargetId && eligibleCorrections.length > 0,
  );

  const submitReassignment = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canReassign || !membership || !parsedROI) return;
    void run((revision) =>
      reassignObjectMembership(jobId, {
        expected_scene_revision: revision,
        membership_checksum: membership.labels_ref.artifact_checksum,
        region: parsedROI,
        source_object_id: reassignSourceId,
        target_object_id: reassignTargetId,
      }),
    );
  };

  return (
    <div className="relative size-full overflow-hidden bg-viewport">
      <AlertDialog open={mergeRestoreTarget !== null} onOpenChange={(open) => { if (!open) setMergeRestoreTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Khôi phục nhóm trước khi gộp?</AlertDialogTitle>
            <AlertDialogDescription>
              Các phần trong nhóm sẽ trở lại thành những vật riêng trước lần gộp. Những vật khác giữ nguyên. Nếu nhóm đã được chỉnh sửa sau khi gộp, thao tác sẽ bị chặn để bảo vệ chỉnh sửa đó.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction disabled={busy} onClick={() => {
              const object = scene.objects.find((item) => item.id === mergeRestoreTarget);
              if (object) void restoreListedObject(object, true);
            }}>Khôi phục cả nhóm</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {/* Viewport 3D chiếm toàn bộ không gian khung nhìn */}
      <div className="size-full">
        {scene.environment.visual_ref ? (
          <MetricSceneView
            jobId={jobId}
            visual={scene.environment.visual_ref}
            collision={scene.environment.geometry_ref}
            cameras={cameras}
            boxes={boxes}
            objects={splats}
            gizmo={tool !== "none" && current && isPlaced(current) && !hiddenIds.has(current.id) ? { id: current.id, mode: tool } : null}
            onTransform={(id, position, rotation) => run((revision) => setObjectTransform(jobId, revision, id, position, rotation))}
            focus={focus}
            onPickBox={selectFromScene}
            physicsObjects={physicsObjects}
            placement={
              placing
                ? {
                    label: placing.label,
                    dimensions: placing.dimensions,
                    onPlace: (point) => {
                      placing.commit(point);
                      setPlacing(null);
                    },
                    onCancel: cancelPlacing,
                  }
                : null
            }
            selectMode={selectMode}
            onToggleSelectMode={() => setSelectMode((previous) => !previous)}
            selectedObject={
              current
                ? {
                    id: current.id,
                    name: current.name,
                    viewportHidden: hiddenIds.has(current.id),
                    canTransform: isPlaced(current) && !hiddenIds.has(current.id),
                  }
                : null
            }
            tool={tool}
            onTool={setTool}
            onDuplicate={current && !isIgnored(current) ? () => void act(current, "duplicate") : undefined}
            onToggleVisibility={current ? () => toggleViewportVisibility(current.id) : undefined}
            onDelete={
              current
                ? () => {
                    if (window.confirm(`Xoá "${current.name}" khỏi scene?`)) {
                      void act(current, "delete");
                      selectObject(null);
                    }
                  }
                : undefined
            }
            onDeselect={() => {
              selectObject(null);
              setTool("none");
            }}
          />
        ) : (
            <CollisionMeshCanvas url={jobArtifactContentUrl(jobId, scene.environment.geometry_ref)}>
            {scene.objects.filter((object) => isPlaced(object) && !hiddenIds.has(object.id)).map((object) => (
              <ObjectBox
                key={object.id}
                object={object}
                preview={currentColliderDraft}
                selected={object.id === selected}
                onSelect={() => selectObject(object.id)}
              />
            ))}
          </CollisionMeshCanvas>
        )}
      </div>

      {/* Panel trái trong suốt: Khung vật thể trong scene */}
      <aside
        aria-label="Danh sách vật thể"
        className={cn(
          "absolute top-3 left-3 flex flex-col pointer-events-auto transition-all duration-200",
          sceneStateControls && leftTab === "state" ? "z-30" : "z-20",
          leftCollapsed
            ? "w-auto"
            : "w-72 md:w-80 max-w-[calc(100vw-1.5rem)] max-h-[calc(100%-4.5rem)] rounded-lg border border-line-dark bg-viewport-deep/90 shadow-2xl backdrop-blur-md overflow-hidden text-on-dark",
        )}
      >
        {leftCollapsed ? (
          <button
            type="button"
            onClick={() => setLeftCollapsed(false)}
            className="flex items-center gap-2 rounded-lg border border-line-dark bg-viewport-deep/85 px-3 py-2 text-xs font-medium text-on-dark shadow-xl backdrop-blur-md hover:bg-viewport-deep transition-all"
            title="Xổ xuống danh sách vật thể trong scene"
            aria-label="Mở danh sách vật thể"
          >
            <Boxes className="size-4 text-ember-strong" aria-hidden />
            <span>Vật thể trong scene</span>
            <span className="rounded bg-on-dark/15 px-1.5 py-0.5 font-mono text-[11px] text-on-dark/90">
              {scene.objects.length}
            </span>
            <ChevronDown className="size-3.5 text-on-dark/70" aria-hidden />
          </button>
        ) : (
          <>
            <div className="space-y-2 border-b border-line-dark px-3 py-2.5 bg-viewport-deep/50">
              <div className="flex items-center justify-between gap-2">
                <h2 className="label-tech text-on-dark/70">Vật thể trong scene</h2>
                <div className="flex items-center gap-1">
                  {previous && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      title={`Hoàn tác: quay về ${previous} (ghi thành revision mới)`}
                      aria-label="Hoàn tác"
                      onClick={() => run((revision) => restoreSceneRevision(jobId, revision, previous))}
                      className="size-7 p-0 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10"
                    >
                      <Undo2 className="size-3.5" aria-hidden />
                    </Button>
                  )}
                  <button
                    type="button"
                    onClick={() => setLeftCollapsed(true)}
                    className="rounded p-1 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10 transition-colors"
                    title="Thu gọn danh sách vật thể"
                    aria-label="Thu gọn danh sách vật thể"
                  >
                    <ChevronUp className="size-4" aria-hidden />
                  </button>
                </div>
              </div>
            </div>
            <Tabs value={sceneStateControls ? leftTab : "objects"} onValueChange={setLeftTab} className="min-h-0 gap-0">
              {sceneStateControls && <>
                <TabsList aria-label="Nội dung panel scene" className="mx-3 my-2 w-auto shrink-0 border border-line-dark bg-viewport-deep/70">
                  <TabsTrigger value="state" className="text-on-dark/70 data-active:bg-on-dark/15 data-active:text-on-dark">Trạng thái scene</TabsTrigger>
                  <TabsTrigger value="objects" className="text-on-dark/70 data-active:bg-on-dark/15 data-active:text-on-dark">Vật thể</TabsTrigger>
                </TabsList>
                <TabsContent value="state" forceMount hidden={leftTab !== "state"} className="m-0 overflow-y-auto px-3 py-3 data-[state=inactive]:hidden">
                  {sceneStateControls}
                </TabsContent>
              </>}
              <TabsContent value="objects" forceMount hidden={Boolean(sceneStateControls) && leftTab !== "objects"} className="m-0 flex min-h-0 flex-col data-[state=inactive]:hidden">
              <div className="space-y-2 border-b border-line-dark px-3 py-2.5">
              <p className="text-xs font-semibold text-on-dark">
                {scene.objects.length} vật thể · {scene.objects.filter((object) => object.state === "CANDIDATE" && !isIgnored(object)).length} chờ xác nhận
              </p>
              <div className="flex flex-wrap gap-1" role="group" aria-label="Lọc vật thể">
                {FILTERS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    aria-pressed={filter === item.value}
                    onClick={() => setFilter(item.value)}
                    className={cn(
                      "rounded-md border px-2 py-0.5 text-xs transition-colors",
                      filter === item.value
                        ? "border-ember bg-ember-soft text-ember-strong font-medium"
                        : "border-line-dark text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
                    )}
                  >
                    {`${item.label} · ${counts[item.value]}`}
                  </button>
                ))}
              </div>
            </div>
            <div className="border-b border-line-dark px-3 py-2">
              <button
                type="button"
                aria-expanded={collisionSourcePanelOpen}
                aria-controls="lidar-collision-source-panel"
                disabled={busy}
                onClick={() => {
                  const open = !collisionSourcePanelOpen;
                  setCollisionSourcePanelOpen(open);
                  if (open && collisionCandidatesLoadedFor !== jobId) void loadCollisionCandidates();
                }}
                className="flex w-full items-center justify-between rounded px-1 py-1 text-left text-xs font-semibold text-on-dark hover:bg-on-dark/10 disabled:opacity-50"
              >
                <span>Nguồn collision LiDAR</span>
                <span className="font-normal text-on-dark/60">
                  {scene.environment.collision_source_ref ? "đã chọn" : "chưa chọn"}
                </span>
              </button>
              {collisionSourcePanelOpen && (
                <div id="lidar-collision-source-panel" className="mt-2 space-y-2 rounded-md border border-line-dark bg-viewport-deep/60 p-2 text-xs">
                  <p className="text-on-dark/70">
                    Chỉ manifest đã publish trong job mới xuất hiện. Server sẽ kiểm tra lại QA, mesh, ownership và revision trước khi đổi source.
                  </p>
                  {error && <p className="text-rust" role="alert">{error}</p>}
                  {collisionCandidatesLoading && <p role="status" className="text-on-dark/70">Đang tải candidate đã publish…</p>}
                  {collisionCandidatesError && (
                    <div className="space-y-2" role="alert">
                      <p className="text-rust">{collisionCandidatesError}</p>
                      <button
                        type="button"
                        className="text-ember-strong underline"
                        onClick={() => {
                          setCollisionCandidatesLoadedFor(null);
                          void loadCollisionCandidates();
                        }}
                      >
                        Thử tải lại
                      </button>
                    </div>
                  )}
                  {!collisionCandidatesLoading && !collisionCandidatesError && collisionCandidatesLoadedFor === jobId && visibleCollisionCandidates.length === 0 && (
                    <p role="status" className="text-on-dark/60">
                      Job chưa publish candidate LiDAR. Candidate thiếu QA hoặc ownership vẫn sẽ bị backend chặn.
                    </p>
                  )}
                  {visibleCollisionCandidates.map((candidate) => (
                    <div key={`${candidate.artifact_uri}:${candidate.artifact_checksum}`} className="space-y-1 rounded border border-line-dark p-2">
                      <p className="break-all text-[11px] text-on-dark/60">{candidate.artifact_uri}</p>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busy}
                        onClick={() => void run((expectedRevision) => selectLidarCollisionSource(jobId, {
                          expected_scene_revision: expectedRevision,
                          candidate_manifest_ref: candidate,
                        }))}
                      >
                        Chọn làm collision source
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="border-b border-line-dark px-3 py-2">
              <button
                type="button"
                aria-expanded={correctionPanelOpen}
                aria-controls="membership-correction-panel"
                disabled={busy}
                onClick={() => setCorrectionPanelOpen((open) => !open)}
                className="flex w-full items-center justify-between rounded px-1 py-1 text-left text-xs font-semibold text-on-dark hover:bg-on-dark/10 disabled:opacity-50"
              >
                <span>Gộp ứng viên / Sửa nhóm Gaussian</span>
                <span className="font-normal text-on-dark/60">{membership ? `${eligibleCorrections.length} ứng viên khả dụng` : "chưa có membership"}</span>
              </button>
              {correctionPanelOpen && (
                <div id="membership-correction-panel" className="mt-2 max-h-80 space-y-3 overflow-y-auto rounded-md border border-line-dark bg-viewport-deep/60 p-2 text-xs">
                  {!membership ? (
                    <p className="text-on-dark/70" role="status">
                      Scene này chưa lưu Gaussian membership; hãy chạy tách vật để tạo membership trước khi hiệu chỉnh.
                    </p>
                  ) : (
                    <>
                      <p className="text-on-dark/70">
                        Gộp dùng khi một vật bị tách nhầm thành nhiều ứng viên. Chọn từ hai phần trở lên: Gaussian và ownership được hợp nhất, giữ ID của ứng viên chính.
                      </p>
                      <p className="text-on-dark/70">
                        Lệnh gắn với revision {scene.scene_revision}. Vùng nhập theo tọa độ canonical world, đơn vị mét.
                      </p>
                      <fieldset className="space-y-1.5" disabled={busy}>
                        <legend className="font-semibold text-on-dark">Ứng viên để gộp</legend>
                        {candidateCorrections.length === 0 ? (
                          <p className="text-on-dark/60">Không có ứng viên đang chờ hiệu chỉnh.</p>
                        ) : (
                          candidateCorrections.map(({ object, reason }) => (
                            <div key={object.id}>
                              <label className={cn("flex items-center gap-2 rounded px-1 py-1", reason ? "text-on-dark/50" : "text-on-dark")}>
                                <input
                                  type="checkbox"
                                  aria-label={`Chọn để gộp ${object.name}`}
                                  checked={mergeCandidateIds.includes(object.id)}
                                  disabled={Boolean(reason)}
                                  title={reason ?? undefined}
                                  onChange={() => toggleMergeCandidate(object.id)}
                                  className="accent-ember"
                                />
                                <span className="min-w-0 truncate">{object.name}</span>
                                {object.semantic_class && <span className="ml-auto text-on-dark/50">{object.semantic_class}</span>}
                              </label>
                              {reason && <p className="pl-6 text-[11px] text-on-dark/50">{reason}</p>}
                            </div>
                          ))
                        )}
                      </fieldset>
                      <label className="block space-y-1 text-on-dark/80">
                        <span>Ứng viên chính (giữ ID)</span>
                        <select
                          aria-label="Ứng viên chính để gộp"
                          value={mergePrimaryId}
                          onChange={(event) => setMergePrimaryId(event.target.value)}
                          disabled={busy || selectedMergeCandidates.length < 2}
                          className="w-full rounded border border-line-dark bg-viewport-deep px-2 py-1.5 text-on-dark disabled:opacity-50"
                        >
                          <option value="">Chọn ứng viên</option>
                          {selectedMergeCandidates.map((object) => <option key={object.id} value={object.id}>{object.name}</option>)}
                        </select>
                      </label>
                      {hasSemanticConflict && (
                        <label className="block space-y-1 text-on-dark/80">
                          <span>Nhãn ngữ nghĩa cần giữ</span>
                          <select
                            aria-label="Nguồn nhãn ngữ nghĩa"
                            value={semanticSourceId}
                            onChange={(event) => setSemanticSourceId(event.target.value)}
                            disabled={busy}
                            className="w-full rounded border border-line-dark bg-viewport-deep px-2 py-1.5 text-on-dark"
                          >
                            <option value="">Chọn nhãn từ ứng viên</option>
                            {selectedMergeCandidates.map((object) => <option key={object.id} value={object.id}>{object.name} · {object.semantic_class ?? "chưa gán nhãn"}</option>)}
                          </select>
                        </label>
                      )}
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!canMerge}
                          onClick={() => {
                            if (!membership || !mergePrimaryId) return;
                            void run((revision) => mergeObjectCandidates(jobId, {
                              expected_scene_revision: revision,
                              membership_checksum: membership.labels_ref.artifact_checksum,
                              primary_object_id: mergePrimaryId,
                              secondary_object_ids: selectedMergeCandidates.filter((object) => object.id !== mergePrimaryId).map((object) => object.id),
                              ...(hasSemanticConflict ? { semantic_class_source_object_id: semanticSourceId } : {}),
                            }));
                          }}
                        >
                          Gộp ứng viên
                        </Button>
                        <Button size="sm" variant="ghost" disabled={busy} onClick={cancelCorrectionSelection}>
                          Hủy chọn
                        </Button>
                      </div>

                      <form onSubmit={submitReassignment} className="space-y-2 border-t border-line-dark pt-3">
                        <h3 className="font-semibold text-on-dark">Chuyển vùng giữa các chủ sở hữu</h3>
                        <p className="text-[11px] leading-relaxed text-on-dark/60">
                          Nhập hộp giới hạn theo dữ liệu nguồn. Pose đã chỉnh trong viewer không được dùng để chọn Gaussian.
                        </p>
                        <div className="grid grid-cols-2 gap-1.5">
                          <label className="space-y-1 text-on-dark/70">
                            <span>Nguồn</span>
                            <select aria-label="Chủ sở hữu nguồn" value={reassignSourceId ?? ""} onChange={(event) => setReassignSourceId(event.target.value || null)} disabled={busy} className="w-full rounded border border-line-dark bg-viewport-deep px-1.5 py-1 text-on-dark">
                              <option value="">Nền (background)</option>
                              {eligibleCorrections.map((object) => <option key={object.id} value={object.id}>{object.name}</option>)}
                            </select>
                          </label>
                          <label className="space-y-1 text-on-dark/70">
                            <span>Đích</span>
                            <select aria-label="Chủ sở hữu đích" value={reassignTargetId ?? ""} onChange={(event) => setReassignTargetId(event.target.value || null)} disabled={busy} className="w-full rounded border border-line-dark bg-viewport-deep px-1.5 py-1 text-on-dark">
                              <option value="">Nền (background)</option>
                              {eligibleCorrections.map((object) => <option key={object.id} value={object.id}>{object.name}</option>)}
                            </select>
                          </label>
                        </div>
                        <div className="grid grid-cols-2 gap-1.5">
                          {ROI_FIELDS.map((field) => (
                            <label key={field.key} className="space-y-1 text-on-dark/70">
                              <span>{field.label}</span>
                              <input
                                type="number"
                                step="any"
                                aria-label={field.label}
                                value={roi[field.key]}
                                onChange={(event) => setRoi((currentROI) => ({ ...currentROI, [field.key]: event.target.value }))}
                                disabled={busy}
                                className="w-full rounded border border-line-dark bg-viewport-deep px-1.5 py-1 text-on-dark"
                              />
                            </label>
                          ))}
                        </div>
                        {!parsedROI && <p className="text-[11px] text-on-dark/55">Nhập đủ 6 giới hạn; mỗi giới hạn nhỏ phải thấp hơn giới hạn lớn.</p>}
                        {busy && <p className="text-on-dark/70" role="status">Đang dựng và lưu artifact mới…</p>}
                        <Button size="sm" variant="secondary" type="submit" disabled={!canReassign}>
                          Chuyển vùng Gaussian
                        </Button>
                      </form>
                    </>
                  )}
                </div>
              )}
            </div>
            <ul className="min-h-0 flex-1 divide-y divide-line-dark overflow-y-auto">
              {visibleObjects.length === 0 && (
                <li className="px-3 py-6 text-center text-xs text-on-dark/60">
                  Không có vật nào trong nhóm này.
                </li>
              )}
              {visibleObjects.map((object, index) => (
                <Fragment key={object.id}>
                  {filter === "ignored" && (index === 0 || archiveCategory(object, hiddenIds) !== archiveCategory(visibleObjects[index - 1], hiddenIds)) && (
                    <li className="bg-viewport-deep/60 px-3 py-2">
                      <h3 className="text-xs font-semibold text-on-dark">{ARCHIVE_CATEGORIES.find((item) => item.value === archiveCategory(object, hiddenIds))?.label} · {visibleObjects.filter((item) => archiveCategory(item, hiddenIds) === archiveCategory(object, hiddenIds)).length}</h3>
                    </li>
                  )}
                <li
                  key={object.id}
                  id={`object-${object.id}`}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 transition-colors",
                    object.id === selected ? "bg-ember-soft/30" : "hover:bg-on-dark/5",
                  )}
                >
                  <button
                    type="button"
                    aria-label={`Chọn ${object.name}`}
                    aria-pressed={object.id === selected}
                    onClick={() => flyTo(object.id)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded py-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember"
                  >
                    <span className="size-2.5 shrink-0 rounded-sm" style={{ background: stateColor(object) }} aria-hidden />
                    <span className="truncate text-sm text-on-dark">{object.name}</span>
                  </button>
                  {archiveCategory(object, hiddenIds) ? (
                    <span className="flex shrink-0 items-center gap-1">
                      {hiddenIds.has(object.id) ? <Badge>Ẩn màn hình</Badge> : <StateBadge object={object} />}
                      <Button size="sm" variant="secondary" disabled={busy} aria-label={`Khôi phục ${object.name}`} title="Khôi phục" onClick={() => void restoreListedObject(object)} className="size-7 p-0">
                        <Undo2 className="size-3.5" aria-hidden />
                      </Button>
                    </span>
                  ) : object.state === "CANDIDATE" && !isIgnored(object) ? (
                    <span className="flex shrink-0 gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busy}
                        aria-label={`Xác nhận ${object.name}`}
                        title="Xác nhận"
                        onClick={() => act(object, "confirm")}
                        className="size-7 p-0 border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
                      >
                        <Check className="size-3.5" aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        aria-label={`Loại ${object.name}`}
                        title="Loại"
                        onClick={() => act(object, "ignore")}
                        className="size-7 p-0 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10"
                      >
                        <X className="size-3.5" aria-hidden />
                      </Button>
                    </span>
                  ) : (
                    <StateBadge object={object} />
                  )}
                </li>
                </Fragment>
              ))}
            </ul>
              </TabsContent>
            </Tabs>
          </>
        )}
      </aside>

      {/* Panel phải trong suốt: Chi tiết vật thể */}
      <aside
        aria-label="Inspector"
        className={cn(
          "absolute top-3 right-3 z-20 flex flex-col pointer-events-auto transition-all duration-200",
          rightCollapsed
            ? "w-auto"
            : "w-80 md:w-88 max-w-[calc(100vw-1.5rem)] max-h-[calc(100%-4.5rem)] rounded-lg border border-line-dark bg-viewport-deep/90 shadow-2xl backdrop-blur-md overflow-hidden text-on-dark",
        )}
      >
        {rightCollapsed ? (
          <button
            type="button"
            onClick={() => setRightCollapsed(false)}
            className="flex items-center gap-2 rounded-lg border border-line-dark bg-viewport-deep/85 px-3 py-2 text-xs font-medium text-on-dark shadow-xl backdrop-blur-md hover:bg-viewport-deep transition-all"
            title="Xổ xuống chi tiết vật thể"
            aria-label="Mở chi tiết vật thể"
          >
            <span className="size-2 rounded-full bg-ember" aria-hidden />
            <span>Chi tiết vật thể</span>
            {current && (
              <span className="max-w-28 truncate font-medium text-ember-strong">
                · {current.name}
              </span>
            )}
            <ChevronDown className="size-3.5 text-on-dark/70" aria-hidden />
          </button>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-line-dark px-3 py-2.5 bg-viewport-deep/50">
              <div className="flex items-center gap-1.5 min-w-0">
                <h2 className="label-tech text-on-dark/70">Chi tiết vật thể</h2>
                {current && (
                  <span className="truncate text-xs font-semibold text-on-dark">
                    · {current.name}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setRightCollapsed(true)}
                className="rounded p-1 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10 transition-colors"
                title="Thu gọn chi tiết vật thể"
                aria-label="Thu gọn chi tiết vật thể"
              >
                <ChevronUp className="size-4" aria-hidden />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <ObjectifyNotice jobId={jobId} revision={scene.scene_revision} onRevision={() => setReload((value) => value + 1)} />
              {missingSourcePolicies.length > 0 && <Notice tone="rust" className="m-3">SOURCE_POLICY_MISSING: Không có metadata nguồn để đặt Gaussian của {missingSourcePolicies.map((item) => item.id).join(", ")}. Hãy tải lại scene.</Notice>}
              {representations.some((item) => item.readiness_blockers.length) && (
                <Notice tone="rust" className="m-3">
                  Representation chưa đầy đủ: {representations.flatMap((item) => item.readiness_blockers.map((code) => `${item.object_id}: ${code}`)).join(", ")}
                  {scene.objects.filter((object) => object.state === "CANDIDATE" && object.active && !isIgnored(object)).map((object) => (
                    <div key={object.id} className="mt-2 space-y-1">
                      <p>{object.name} đã bị bật mô phỏng từ phiên bản cũ. Khôi phục để đưa về ứng viên chờ xác nhận, giữ nguyên hình học và vị trí.</p>
                      <Button size="sm" variant="secondary" disabled={busy} onClick={() => void restoreListedObject(object)}>Khôi phục trạng thái {object.id}</Button>
                    </div>
                  ))}
                </Notice>
              )}
              {error && (
                <Notice tone="rust" className="m-3">
                  {error}
                </Notice>
              )}
              {current ? (
                <Inspector
                  key={current.id}
                  object={current}
                  viewportHidden={hiddenIds.has(current.id)}
                  onToggleVisibility={() => toggleViewportVisibility(current.id)}
                  onRestore={() => void restoreListedObject(current)}
                  onMerge={() => openMerge(current)}
                  busy={busy}
                  catalog={catalog}
                  sceneRevision={scene.scene_revision}
                  colliderFormReset={colliderFormReset}
                  onColliderDraftChange={(draft) =>
                    setColliderDraft(draft ? { ...draft, sceneRevision: scene.scene_revision } : null)
                  }
                  onColliderSave={(changes) =>
                    void run((expectedRevision) =>
                      editCollider(jobId, {
                        expected_scene_revision: expectedRevision,
                        object_id: current.id,
                        ...changes,
                      }),
                    )
                  }
                  onAct={(action, extra) => act(current, action, extra)}
                  onFlyTo={() => flyTo(current.id)}
                  onClose={() => selectObject(null)}
                />
              ) : (
                <div className="space-y-2 px-4 py-4 text-xs text-on-dark/70">
                  <p className="text-sm font-medium text-on-dark">Chọn một vật</p>
                  <p>Bấm hộp trong 3D hoặc một dòng trong danh sách để xem chi tiết và thao tác.</p>
                  <Legend />
                </div>
              )}
              {catalog && (
                <CatalogForm
                  catalog={catalog}
                  busy={busy}
                  onAdd={(family, position) => run((revision) => addCatalogObject(jobId, revision, family, position))}
                  onStartPlace={(family, dimensions) => {
                    const entry = catalog.entries.find((item) => item.family === family);
                    setPlacing({
                      label: entry?.semantic_class ? `${entry.semantic_class} (${family.replace(/^SM_/, "")})` : family,
                      dimensions,
                      commit: (point) => run((revision) => addCatalogObject(jobId, revision, family, [point[0], point[1], 0])),
                    });
                  }}
                />
              )}
              <AddObstacleForm
                busy={busy}
                onAdd={(name, dimensions, center) => run((revision) => addBoxObstacle(jobId, revision, name, dimensions, center))}
                onStartPlace={(name, dimensions) => {
                  setPlacing({
                    label: name,
                    dimensions,
                    commit: (point) =>
                      run((revision) =>
                        addBoxObstacle(jobId, revision, name, dimensions, [point[0], point[1], dimensions[2] / 2]),
                      ),
                  });
                }}
              />
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function Legend() {
  const items = [
    ["var(--studio-ochre)", "Ứng viên"],
    ["var(--studio-sage)", "Đã xác nhận"],
    ["var(--studio-ink-subtle)", "Đã loại / đang ẩn"],
    ["var(--studio-ember)", "Đang chọn"],
  ] as const;
  return (
    <ul className="grid grid-cols-2 gap-1 pt-1 text-xs text-on-dark/70">
      {items.map(([color, label]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: color }} aria-hidden />
          {label}
        </li>
      ))}
    </ul>
  );
}

/** Chi tiết + thao tác của vật đang chọn. Đổi tên cũng là một revision (Q5). */
function Inspector({
  object,
  viewportHidden,
  onToggleVisibility,
  onRestore,
  onMerge,
  busy,
  catalog,
  sceneRevision,
  colliderFormReset,
  onColliderDraftChange,
  onColliderSave,
  onAct,
  onFlyTo,
  onClose,
}: {
  object: SceneObject;
  viewportHidden: boolean;
  onToggleVisibility: () => void;
  onRestore: () => void;
  onMerge: () => void;
  busy: boolean;
  catalog: SceneCatalog | null;
  sceneRevision: string;
  colliderFormReset: number;
  onColliderDraftChange: (draft: Omit<ColliderPreviewDraft, "sceneRevision"> | null) => void;
  onColliderSave: (changes: ColliderChanges) => void;
  onAct: (action: ObjectAction, extra?: ActionExtra) => void;
  onFlyTo: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(object.name);
  const [label, setLabel] = useState(object.semantic_class ?? "");
  const [mass, setMass] = useState(object.physics?.mass_source === "user" ? String(object.physics.mass_kg ?? "") : "");
  // Người dùng chọn thẳng một asset trong danh mục Isaac; nhãn lưu vào scene là lớp của asset đó.
  const assets = catalog ? catalog.entries.filter((item) => item.semantic_class) : [];
  const savedFamily = object.physics?.provenance?.asset_family;
  const [family, setFamily] = useState(typeof savedFamily === "string" ? savedFamily : "");
  const chosen = assets.find((item) => item.family === family) ?? assets.find((item) => item.semantic_class === label);
  const removed = isIgnored(object);
  const merged = object.provenance.review === "MERGED";
  const mergedInto = typeof object.provenance.merged_into === "string" ? object.provenance.merged_into : null;
  const massValue = mass.trim() === "" ? null : Number(mass);
  const massValid = massValue === null || (Number.isFinite(massValue) && massValue > 0);
  const [x, y, z] = object.transform.translation_xyz;
  const size = object.primitive_dimensions_xyz_m;
  const rename = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed && trimmed !== object.name) onAct("rename", { name: trimmed });
  };
  return (
    <div className="space-y-4 border-b border-line-dark px-4 py-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-on-dark">{object.name}</p>
          <p className="font-mono text-xs text-on-dark/60">{object.id}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-on-dark/60 hover:text-on-dark hover:bg-on-dark/10 transition-colors" aria-label="Bỏ chọn">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StateBadge object={object} />
        {viewportHidden && <Badge>Ẩn trên màn hình</Badge>}
        <Badge tone="neutral">{object.origin === "reconstructed" ? "Tách từ scene" : "Người dùng thêm"}</Badge>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-on-dark/60">Tâm (m)</dt>
        <dd className="font-mono text-on-dark">
          {x.toFixed(2)}, {y.toFixed(2)}, {z.toFixed(2)}
        </dd>
        {size && (
          <>
            <dt className="text-on-dark/60">Kích thước hình học (m)</dt>
            <dd className="font-mono text-on-dark">{size.map((value) => value.toFixed(2)).join(" × ")}</dd>
          </>
        )}
      </dl>
      <ColliderEditor
        key={`${object.id}:${sceneRevision}:${colliderFormReset}`}
        object={object}
        busy={busy}
        onDraftChange={onColliderDraftChange}
        onSave={onColliderSave}
      />
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" onClick={onFlyTo} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Crosshair aria-hidden /> Bay tới
        </Button>
        {!merged && object.provenance.review !== "DELETED" && (
          <Button size="sm" variant="secondary" onClick={onToggleVisibility}>
            {viewportHidden ? "Hiện trên màn hình" : "Ẩn trên màn hình"}
          </Button>
        )}
        {object.state === "CONFIRMED" && !removed && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("hide", { active: !object.active })}>
            {object.active ? "Tắt trong mô phỏng" : "Bật trong mô phỏng"}
          </Button>
        )}
        {object.state === "CANDIDATE" && !isIgnored(object) && (
          <>
            <Button size="sm" disabled={busy} onClick={() => onAct("confirm")}>
              <Check aria-hidden /> Xác nhận
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("ignore")} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
              <X aria-hidden /> Loại
            </Button>
          </>
        )}
        {(removed || viewportHidden || (object.state === "CONFIRMED" && !object.active)) && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={onRestore} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
            <Undo2 aria-hidden /> Khôi phục
          </Button>
        )}
      </div>
      {object.state === "CANDIDATE" && !removed && <Button size="sm" variant="secondary" disabled={busy} onClick={onMerge}>Gộp với ứng viên khác</Button>}
      {merged && (
        <Notice>
          Vật này đã được gộp vào {mergedInto ?? "một vật khác"}. Khôi phục sẽ trả lại cả nhóm trước lần gộp.
        </Notice>
      )}
      {catalog && !removed && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (massValid) onAct("label", { semantic_class: label || null, mass_kg: label ? massValue : null, asset_family: label ? (chosen?.family ?? null) : null });
          }}
        >
          <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
            <span className="flex items-center gap-1">
              <Tag className="size-3.5" aria-hidden /> Nhãn — chọn asset tương ứng trong thư viện Isaac
            </span>
            <select
              className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
              value={chosen?.family ?? ""}
              onChange={(event) => {
                const entry = assets.find((item) => item.family === event.target.value);
                setFamily(entry?.family ?? "");
                setLabel(entry?.semantic_class ?? "");
              }}
            >
              <option value="" className="bg-viewport-deep text-on-dark">Chưa gán</option>
              {catalog.classes.map((name) => (
                <optgroup key={name} label={name} className="bg-viewport-deep text-on-dark">
                  {assets
                    .filter((item) => item.semantic_class === name)
                    .map((item) => (
                      <option key={item.family} value={item.family} className="bg-viewport-deep text-on-dark">
                        {item.family.replace(/^SM_/, "")} · {item.size_xyz_m.map((value) => value.toFixed(2)).join("×")} m
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          {chosen && (
            <p className="text-xs text-on-dark/70">
              Nhãn <span className="font-medium text-on-dark">{chosen.semantic_class}</span> ·{" "}
              {chosen.dynamic
                ? `khối lượng mặc định ${chosen.default_mass_kg === null ? "theo mật độ × thể tích" : `${chosen.default_mass_kg} kg`}`
                : "vật cố định (collider tĩnh)"}
            </p>
          )}
          <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
            Khối lượng (kg) — bỏ trống để dùng mặc định của nhãn
            <input
              className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
              inputMode="decimal"
              value={mass}
              disabled={!label}
              aria-invalid={!massValid}
              onChange={(event) => setMass(event.target.value)}
            />
          </label>
          {object.physics && (
            <p className="text-xs text-on-dark/70">
              {object.physics.dynamic
                ? `Hiện tại: ${object.physics.mass_kg?.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} kg (${MASS_SOURCE[object.physics.mass_source ?? "user"]}) · ma sát ${object.physics.static_friction}`
                : "Vật cố định: chỉ có collider tĩnh, không có khối lượng."}
            </p>
          )}
          <Button size="sm" variant="secondary" type="submit" disabled={busy || !massValid} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
            Lưu nhãn
          </Button>
        </form>
      )}
      {!merged && <form className="flex items-end gap-2" onSubmit={rename}>
        <label className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs text-on-dark/70">
          Tên
          <input
            className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <Button size="sm" variant="secondary" type="submit" disabled={busy || !name.trim() || name.trim() === object.name} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Pencil aria-hidden /> Đổi tên
        </Button>
      </form>}
    </div>
  );
}

function ColliderEditor({
  object,
  busy,
  onDraftChange,
  onSave,
}: {
  object: SceneObject;
  busy: boolean;
  onDraftChange: (draft: Omit<ColliderPreviewDraft, "sceneRevision"> | null) => void;
  onSave: (changes: ColliderChanges) => void;
}) {
  const collider = object.collider;
  const baseValues = colliderFormValues(object) ?? {
    dimensions: ["", "", ""] as [string, string, string],
    translation: ["", "", ""] as [string, string, string],
    rotation: ["", "", ""] as [string, string, string],
  };
  const [values, setValues] = useState<ColliderFormValues>(baseValues);
  const supported = Boolean(
    collider &&
      (collider.collider_type === "AABB" || collider.collider_type === "OBB") &&
      collider.dimensions_xyz_m,
  );
  const removed = isIgnored(object);
  const merged = object.provenance.review === "MERGED";
  const editable = supported && !removed && !merged;
  const parsed = editable ? parseColliderForm(object, values) : null;
  const changed = Boolean(parsed && Object.keys(parsed.changes).length > 0);
  const formChanged = JSON.stringify(values) !== JSON.stringify(baseValues);

  const update = (group: keyof ColliderFormValues, index: number, value: string) => {
    const nextGroup = [...values[group]] as [string, string, string];
    nextGroup[index] = value;
    const next = { ...values, [group]: nextGroup };
    setValues(next);
    const result = parseColliderForm(object, next);
    onDraftChange(result ? result.preview : null);
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!parsed || !changed || busy) return;
    onSave(parsed.changes);
  };

  const discard = () => {
    setValues(baseValues);
    onDraftChange(null);
  };

  const fields = (
    group: keyof ColliderFormValues,
    title: string,
    labels: readonly string[],
    unit: string,
    min?: string,
  ) => (
    <fieldset disabled={!editable || busy} className="space-y-1.5">
      <legend className="text-xs font-medium text-on-dark/80">{title}</legend>
      <div className="grid grid-cols-3 gap-2">
        {labels.map((axis, index) => {
          const label = `${title} ${axis} (${unit})`;
          return (
            <label key={axis} className="flex min-w-0 flex-col gap-0.5 text-[11px] text-on-dark/60">
              {axis}
              <input
                aria-label={label}
                className="h-8 min-w-0 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-xs text-on-dark focus:border-ember focus:outline-none disabled:opacity-50"
                type="number"
                inputMode="decimal"
                step="any"
                min={min}
                value={values[group][index]}
                onChange={(event) => update(group, index, event.target.value)}
              />
            </label>
          );
        })}
      </div>
    </fieldset>
  );

  return (
    <form className="space-y-3 rounded-md border border-line-dark bg-viewport-deep/50 p-3" onSubmit={submit} aria-label="Chỉnh collider">
      <div>
        <p className="text-xs font-semibold text-on-dark">Collider box</p>
        <p className="mt-0.5 text-[11px] text-on-dark/60">Kích thước và pose trong frame local của vật · mét, Z-up.</p>
      </div>
      {!collider && <p className="text-xs text-on-dark/70">Vật này chưa có collider để chỉnh sửa.</p>}
      {collider && !supported && (
        <p className="text-xs text-on-dark/70">
          Hiện chỉ chỉnh được AABB/OBB có kích thước. Collider {collider.collider_type} cần công cụ hình học riêng.
        </p>
      )}
      {supported && removed && <p className="text-xs text-on-dark/70">Khôi phục vật trước khi chỉnh collider.</p>}
      {editable && (
        <>
          {fields("dimensions", "Kích thước collider", ["X", "Y", "Z"], "m", "0")}
          {fields("translation", "Tịnh tiến local", ["X", "Y", "Z"], "m")}
          {fields("rotation", "Góc xoay local", ["X", "Y", "Z"], "°")}
          <p className="text-[11px] text-on-dark/60">Góc được áp theo thứ tự local X → Y → Z.</p>
          {formChanged && !parsed && (
            <p className="text-xs text-rust" role="alert">
              Kích thước phải là số dương; vị trí và góc phải là số hữu hạn.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" type="submit" disabled={busy || !changed}>
              Lưu collider
            </Button>
            {formChanged && (
              <Button
                size="sm"
                variant="secondary"
                type="button"
                disabled={busy}
                onClick={discard}
                className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
              >
                Hủy chỉnh sửa
              </Button>
            )}
          </div>
        </>
      )}
    </form>
  );
}

type ActionExtra = { active?: boolean; name?: string; semantic_class?: string | null; mass_kg?: number | null; asset_family?: string | null };

const MASS_SOURCE: Record<string, string> = {
  catalog_default: "mặc định của nhãn",
  catalog_density: "mật độ giả định × thể tích",
  user: "bạn nhập",
  asset: "theo asset",
};

/** Vật đang có mặt trong scene: ứng viên chờ xác nhận hoặc vật đã xác nhận đang hiện. */
function isPlaced(object: SceneObject): boolean {
  if (isIgnored(object)) return false;
  return object.state === "CANDIDATE" || object.active;
}

/** Thêm vật từ thư viện asset Isaac: chọn họ asset + vị trí trên sàn. */
function CatalogForm({
  catalog,
  busy,
  onAdd,
  onStartPlace,
}: {
  catalog: SceneCatalog;
  busy: boolean;
  onAdd: (family: string, position: [number, number, number]) => void;
  onStartPlace?: (family: string, dimensions: [number, number, number]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [family, setFamily] = useState(catalog.entries[0]?.family ?? "");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  if (!open) {
    return (
      <div className="border-t border-line-dark p-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Library aria-hidden /> Thêm từ thư viện
        </Button>
      </div>
    );
  }
  const entry = catalog.entries.find((item) => item.family === family);
  const valid = Boolean(entry) && Number.isFinite(Number(x)) && Number.isFinite(Number(y));
  return (
    <form
      className="space-y-2 border-t border-line-dark p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        onAdd(family, [Number(x), Number(y), 0]);
        setOpen(false);
      }}
    >
      <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
        Asset Isaac
        <select className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none" value={family} onChange={(event) => setFamily(event.target.value)}>
          {catalog.entries.map((item) => (
            <option key={item.family} value={item.family} className="bg-viewport-deep text-on-dark">
              {item.semantic_class} · {item.family.replace(/^SM_/, "")}
            </option>
          ))}
        </select>
      </label>
      {entry && (
        <p className="text-xs text-on-dark/70">
          {entry.size_xyz_m.map((value) => value.toFixed(2)).join(" × ")} m ·{" "}
          {entry.dynamic ? (entry.default_mass_kg ? `${entry.default_mass_kg} kg (mặc định)` : "khối lượng theo mật độ giả định") : "vật cố định"}. Trên
          web vật hiện bằng hộp; trong Isaac là asset thật.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
          Vị trí X (m)
          <input className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none" inputMode="decimal" value={x} onChange={(event) => setX(event.target.value)} />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
          Vị trí Y (m)
          <input className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none" inputMode="decimal" value={y} onChange={(event) => setY(event.target.value)} />
        </label>
      </div>
      <p className="text-xs text-on-dark/50">{catalog.physics_note}</p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={busy || !valid}>
          Thêm
        </Button>
        {onStartPlace && entry && (
          <Button
            size="sm"
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              onStartPlace(family, entry.size_xyz_m);
              setOpen(false);
            }}
            className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
            title="Di chuột vào scene để đặt vị trí"
          >
            <Crosshair className="size-3.5" aria-hidden /> Đặt bằng chuột
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} className="text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10">
          Huỷ
        </Button>
      </div>
    </form>
  );
}

/**
 * Màu khung vật lấy từ bảng màu đang chọn (cùng vai trò với badge trạng thái): ember = đang chọn, ochre = ứng viên,
 * sage = đã xác nhận, ink-subtle = đã loại/ẩn. Lớp phủ 3D cần mã màu cụ thể nên đọc giá trị biến lúc vẽ; component
 * gọi `useSyncExternalStore(subscribeTheme, themeKey)` để vẽ lại khi đổi theme.
 */
function selectedColor(): string {
  return themeColor("--studio-ember", "#e8743b");
}

function stateColor(object: SceneObject): string {
  if (isIgnored(object) || !object.active && object.state === "CONFIRMED") return themeColor("--studio-ink-subtle", "#8a7e70");
  return object.state === "CONFIRMED" ? themeColor("--studio-sage", "#5e8c61") : themeColor("--studio-ochre", "#b7862a");
}

function isIgnored(object: SceneObject): boolean {
  return object.provenance.review === "IGNORED" || object.provenance.review === "DELETED" || object.provenance.review === "MERGED";
}

function StateBadge({ object }: { object: SceneObject }) {
  if (object.provenance.review === "MERGED") {
    const mergedInto = typeof object.provenance.merged_into === "string" ? object.provenance.merged_into : "vật khác";
    return <Badge>Đã gộp vào {mergedInto}</Badge>;
  }
  if (object.provenance.review === "DELETED") return <Badge>Đã xoá</Badge>;
  if (isIgnored(object)) return <Badge>Đã loại</Badge>;
  if (object.state === "CANDIDATE") return <Badge tone="ochre">Ứng viên</Badge>;
  return object.active ? <Badge tone="sage">Đã xác nhận</Badge> : <Badge>Tắt trong mô phỏng</Badge>;
}

/** Hộp khung dây trong khung Z-up của collision mesh; màu theo trạng thái review. */
function ObjectBox({ object, preview, selected, onSelect }: {
  object: SceneObject;
  preview: ColliderPreviewDraft | null;
  selected: boolean;
  onSelect: () => void;
}) {
  const collider = colliderWithPreview(object, preview);
  const dimensions = collider?.dimensions_xyz_m ?? object.primitive_dimensions_xyz_m;
  if (!dimensions) return null;
  const color = selected ? selectedColor() : stateColor(object);
  const transform = objectColliderTransform(object, preview);
  return (
    <mesh
      position={transform.translation_xyz}
      quaternion={transform.rotation_quaternion_xyzw}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
    >
      <boxGeometry args={dimensions} />
      <meshBasicMaterial color={color} wireframe />
    </mesh>
  );
}

function AddObstacleForm({
  busy,
  onAdd,
  onStartPlace,
}: {
  busy: boolean;
  onAdd: (name: string, dimensions: [number, number, number], center: [number, number, number]) => void;
  onStartPlace?: (name: string, dimensions: [number, number, number]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState({ name: "", x: "0", y: "0", sx: "0.6", sy: "0.4", sz: "0.5" });
  const field = (key: keyof typeof values, label: string) => (
    <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
      {label}
      <input
        className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
        inputMode={key === "name" ? "text" : "decimal"}
        value={values[key]}
        onChange={(event) => setValues({ ...values, [key]: event.target.value })}
      />
    </label>
  );
  if (!open) {
    return (
      <div className="border-t border-line-dark p-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Plus aria-hidden /> Thêm vật cản hộp
        </Button>
      </div>
    );
  }
  const numbers = [values.x, values.y, values.sx, values.sy, values.sz].map(Number);
  const valid = numbers.every(Number.isFinite) && numbers.slice(2).every((value) => value > 0);
  const validDims = [values.sx, values.sy, values.sz].map(Number).every((v) => Number.isFinite(v) && v > 0);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const [x, y, sx, sy, sz] = numbers;
    // Vật cản đặt trên sàn: tâm hộp cao bằng nửa chiều cao.
    onAdd(values.name, [sx, sy, sz], [x, y, sz / 2]);
    setOpen(false);
  }
  return (
    <form className="space-y-2 border-t border-line-dark p-3" onSubmit={submit}>
      {field("name", "Tên")}
      <div className="grid grid-cols-2 gap-2">
        {field("x", "Tâm X (m)")}
        {field("y", "Tâm Y (m)")}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {field("sx", "Dài (m)")}
        {field("sy", "Rộng (m)")}
        {field("sz", "Cao (m)")}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={busy || !valid}>
          Thêm
        </Button>
        {onStartPlace && (
          <Button
            size="sm"
            type="button"
            variant="secondary"
            disabled={busy || !validDims}
            onClick={() => {
              const [, , sx, sy, sz] = numbers;
              onStartPlace(values.name.trim() || "Vật cản hộp", [sx, sy, sz]);
              setOpen(false);
            }}
            className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
            title="Di chuột vào scene để đặt vị trí"
          >
            <Crosshair className="size-3.5" aria-hidden /> Đặt bằng chuột
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} className="text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10">
          Huỷ
        </Button>
      </div>
    </form>
  );
}
