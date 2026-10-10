"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, ArrowUp, Check, FileCheck2, FileUp, Loader2, Play, Trash2, X } from "lucide-react";

import { PageHeader } from "@/components/studio/feedback";
import { Badge, Button, Card, EmptyState, Notice, ProgressBar, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { ASSEMBLY_ACCEPT, rejectAssemblyFileName } from "@/features/studio/inputKinds";
import { describeDiagnostic, describeFact, routeName } from "@/features/studio/inputMessages";
import { canEdit } from "@/lib/api/auth";
import {
  createInputAssembly,
  getStagedInputUpload,
  importGaussianFromAssembly,
  resolveInputAssembly,
  reviseInputAssembly,
  runInputAssembly,
  stageExistingInputUpload,
  uploadAssemblyFile,
  type AssemblyFileUploadHandle,
} from "@/lib/api/inputAssemblies";
import { uploadPreparedVideo } from "@/lib/api/studio";
import type { DataOrigin, SourceRightsAttestation } from "@/lib/contracts/studio";
import type {
  CandidateState,
  AssemblyUploadResponse,
  CloudObservationState,
  DistanceUnit,
  EvidenceValue,
  InputAssemblyDeclarations,
  InputAssemblySnapshot,
  InputAssemblyWriteRequest,
  InputBinding,
  InputResolutionCandidate,
  InputResolutionReport,
  InputWorkflowIntent,
  TrajectoryConvention,
} from "@/lib/contracts/inputAssembly";
import type { VideoResolutionPreset } from "@/lib/contracts/videoPreparation";
import { VideoPreparationError, type VideoPreparationPhase } from "@/lib/media/video-normalization-core";
import { prepareVideoForUpload, type VideoPreparedArtifact, type VideoPreparationProgress } from "@/lib/media/video-normalization";
import { errorMessage } from "@/lib/ui-error";
import { formatBytes } from "@/lib/format";
import { ProcessingSettings } from "@/features/studio/ProcessingSettings";
import { useProcessingForm } from "@/features/studio/useProcessingForm";

const VIDEO_FORMATS = new Set(["video_mp4", "video_mov"]);
const CLOUD_FORMATS = new Set(["point_cloud_ply", "point_cloud_pcd"]);
const GAUSSIAN_FORMATS = new Set(["gaussian_ply", "gaussian_ply_colmap", "gaussian_sog"]);
const VIDEO_PRESETS: { value: VideoResolutionPreset; detail: string }[] = [
  { value: "1080p", detail: "tối đa 1920 × 1080 ngang / 1080 × 1920 dọc" },
  { value: "720p", detail: "mặc định · tối đa 1280 × 720 ngang / 720 × 1280 dọc" },
  { value: "480p", detail: "tối đa 854 × 480 ngang / 480 × 854 dọc" },
];
const INPUT_DRAFT_PREFIX = "r2s:input-assembly:v1";
/** Chờ người dùng gõ xong ô khai báo trước khi tự phân tích, để không tạo một revision cho mỗi phím. */
const AUTO_ANALYZE_DELAY_MS = 700;

type UploadStatus = "selected" | "preparing" | "uploading" | "ready" | "failed" | "cancelled";

interface InputEntry {
  id: string;
  file: File | null;
  originalName: string;
  isVideo: boolean;
  preset: VideoResolutionPreset;
  included: boolean;
  status: UploadStatus;
  progress: number | null;
  preparation: VideoPreparationProgress | null;
  error: string | null;
  /** Lối đi tiếp mà người dùng phải tự chọn khi không chuẩn bị được video; không bao giờ tự áp dụng. */
  recovery: "upload_original" | null;
  useOriginal: boolean;
  legacyUploadId: string | null;
  staged: AssemblyUploadResponse | null;
}

/** Lý do không chuẩn bị được video, bằng tiếng Việt, kèm lối đi tiếp phù hợp. */
function preparationFailure(error: VideoPreparationError): { message: string; recovery: InputEntry["recovery"] } {
  const reasons: Partial<Record<VideoPreparationError["code"], string>> = {
    unsupported_codec: "Trình duyệt này không giải mã được codec của video (thường gặp với HEVC/H.265 quay bằng điện thoại).",
    unsupported_media: "Trình duyệt này không đọc được định dạng của video.",
    hdr_unsupported: "Video HDR chưa được hỗ trợ ở bước chuẩn bị trên trình duyệt.",
    storage_unavailable: "Trình duyệt không cấp vùng lưu tạm để chuẩn bị video.",
    storage_insufficient: "Trình duyệt không đủ dung lượng lưu tạm để chuẩn bị video.",
    duration_limit: "Video dài hơn giới hạn 2 giờ của bước chuẩn bị trên trình duyệt.",
    pixel_limit: "Độ phân giải của video vượt giới hạn của bước chuẩn bị trên trình duyệt.",
    frame_map_limit: "Video có quá nhiều frame cho bước chuẩn bị trên trình duyệt.",
    verification_failed: "Bản đã chuẩn bị không qua bước tự kiểm trên trình duyệt này.",
    media_processing_failed: "Trình duyệt gặp lỗi khi nén video.",
  };
  return {
    message: `${reasons[error.code] ?? "Không thể chuẩn bị video trên trình duyệt này."} Video gốc chưa được tải lên; bạn có thể chọn tải video gốc không nén.`,
    recovery: "upload_original",
  };
}

interface StoredInputDraft {
  schema_version: 1;
  account_id: string;
  uploads: { upload_id: string; original_name: string; included: boolean; preset: VideoResolutionPreset }[];
  scan_order: string[];
  rgb_frame_times_file_id?: string;
  lidar_scan_times_file_id?: string;
  intent: InputWorkflowIntent | null;
  cloud_state: DeclarationChoice<CloudObservationState>;
  same_scene: "" | "yes" | "no";
  coordinate_unit: DeclarationChoice<DistanceUnit>;
  lidar_frame_id: string;
  trajectory_convention: DeclarationChoice<TrajectoryConvention>;
  clock_relation: DeclarationChoice<"same_clock" | "known_offset" | "unknown">;
  clock_offset: string;
  timestamp_unit?: DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">;
  rgb_timestamp_unit?: DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">;
  lidar_timestamp_unit?: DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">;
  scene_name: string;
  data_origin: DataOrigin | "";
  data_owner: string;
  data_purpose: string;
}

type DeclarationChoice<T extends string> = T | "";

function newEntry(file: File, isVideo: boolean): InputEntry {
  return {
    id: globalThis.crypto.randomUUID(),
    file,
    originalName: file.name,
    isVideo,
    preset: "720p",
    included: true,
    status: "selected",
    progress: null,
    preparation: null,
    error: null,
    recovery: null,
    useOriginal: false,
    legacyUploadId: null,
    staged: null,
  };
}

function inputDraftKey(accountId: string): string {
  return `${INPUT_DRAFT_PREFIX}:${encodeURIComponent(accountId)}`;
}

function parseInputDraft(raw: string, accountId: string): StoredInputDraft | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return null;
    const draft = value as Partial<StoredInputDraft>;
    if (draft.schema_version !== 1 || draft.account_id !== accountId || !Array.isArray(draft.uploads) || !Array.isArray(draft.scan_order)) return null;
    const uploads = draft.uploads.filter((item): item is StoredInputDraft["uploads"][number] =>
      Boolean(item && typeof item.upload_id === "string" && item.upload_id && typeof item.original_name === "string" &&
        typeof item.included === "boolean" && ["1080p", "720p", "480p"].includes(item.preset))
    );
    const legacyTimestampUnit = choiceValue(draft.timestamp_unit, ["seconds", "milliseconds", "microseconds", "nanoseconds"]);
    return {
      schema_version: 1,
      account_id: accountId,
      uploads,
      scan_order: draft.scan_order.filter((item): item is string => typeof item === "string"),
      rgb_frame_times_file_id: typeof draft.rgb_frame_times_file_id === "string" ? draft.rgb_frame_times_file_id : "",
      lidar_scan_times_file_id: typeof draft.lidar_scan_times_file_id === "string" ? draft.lidar_scan_times_file_id : "",
      intent: draft.intent === "video_reconstruction" || draft.intent === "gaussian_view_import" ? draft.intent : null,
      cloud_state: choiceValue(draft.cloud_state, ["registered_map", "single_static_cloud", "raw_scan_sequence"]),
      same_scene: choiceValue(draft.same_scene, ["yes", "no"]),
      coordinate_unit: choiceValue(draft.coordinate_unit, ["m", "cm", "mm"]),
      lidar_frame_id: typeof draft.lidar_frame_id === "string" ? draft.lidar_frame_id.slice(0, 128) : "",
      trajectory_convention: choiceValue(draft.trajectory_convention, ["world_from_sensor", "world_from_camera", "unknown"]),
      clock_relation: choiceValue(draft.clock_relation, ["same_clock", "known_offset", "unknown"]),
      clock_offset: typeof draft.clock_offset === "string" ? draft.clock_offset.slice(0, 64) : "",
      timestamp_unit: legacyTimestampUnit,
      rgb_timestamp_unit: choiceValue(draft.rgb_timestamp_unit, ["seconds", "milliseconds", "microseconds", "nanoseconds"]) || legacyTimestampUnit,
      lidar_timestamp_unit: choiceValue(draft.lidar_timestamp_unit, ["seconds", "milliseconds", "microseconds", "nanoseconds"]) || legacyTimestampUnit,
      scene_name: typeof draft.scene_name === "string" ? draft.scene_name.slice(0, 200) : "",
      data_origin: choiceValue(draft.data_origin, ["public_or_synthetic", "self_collected_no_pii", "anonymized"]),
      data_owner: typeof draft.data_owner === "string" ? draft.data_owner.slice(0, 200) : "",
      data_purpose: typeof draft.data_purpose === "string" ? draft.data_purpose.slice(0, 500) : "",
    };
  } catch {
    return null;
  }
}

function choiceValue<const T extends string>(value: unknown, choices: readonly T[]): T | "" {
  return typeof value === "string" && choices.some((choice) => choice === value) ? value as T : "";
}

async function looksLikeVideo(file: File): Promise<boolean> {
  if (/\.(mp4|mov)$/i.test(file.name) || file.type.startsWith("video/")) return true;
  const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  return bytes.length >= 8 && String.fromCharCode(...bytes.slice(4, 8)) === "ftyp";
}

function evidence<T>(value: T | null): EvidenceValue<T> | null {
  return value === null ? null : {
    value,
    provenance: "declared",
    method: "user_confirmation",
    evidence_checksum: null,
  };
}

function candidateStateLabel(state: CandidateState): string {
  return {
    ready: "Sẵn sàng",
    needs_input: "Cần bổ sung",
    pending_verification: "Đang chờ xác minh",
    unsupported: "Chưa hỗ trợ",
    invalid: "Không hợp lệ",
  }[state];
}

/** Máy chủ không nhận ra vai trò nào trong file: mọi cách xử lý sẽ loại nó, nên đừng báo "đã xác minh". */
const UNUSABLE_FORMATS = new Set(["unknown"]);

/** ZIP được stage theo từng thành viên, nên một upload có thể vừa có phần dùng được vừa không. */
function unusableStaged(staged: AssemblyUploadResponse | null): { unusable: number; total: number } {
  const files = staged?.staged_files ?? [];
  return { unusable: files.filter((item) => UNUSABLE_FORMATS.has(item.observed_format)).length, total: files.length };
}

function formatLabel(format: string): string {
  const labels: Record<string, string> = {
    video_mp4: "Video MP4",
    video_mov: "Video MOV",
    point_cloud_ply: "Point cloud PLY",
    point_cloud_pcd: "Point cloud PCD",
    gaussian_ply: "Gaussian PLY",
    gaussian_ply_colmap: "Gaussian PLY + COLMAP",
    gaussian_sog: "Gaussian SOG",
    calibration_json: "Calibration JSON",
    calibration_torwic_text: "Calibration text",
    calibration_ros_yaml: "Calibration ROS (tf YAML)",
    calibration_kalibr_camchain: "Camera ↔ IMU (Kalibr, chưa dùng được làm calibration LiDAR)",
    tum_trajectory: "Trajectory TUM",
    rgb_frame_times: "RGB frame times (legacy)",
    timestamp_rows: "Timestamp rows (chưa gán vai trò)",
    zip_unknown: "ZIP cần kiểm tra thành phần",
    unknown: "Định dạng chưa nhận diện",
  };
  return labels[format] ?? format;
}

function preparationLabel(phase: VideoPreparationPhase | undefined): string {
  switch (phase) {
    case "hashing": return "Đang đọc và kiểm tra video gốc";
    case "probing": return "Đang kiểm tra video";
    case "encoding": return "Đang chuẩn bị video trước khi upload";
    case "verifying": return "Đang kiểm tra frame map";
    default: return "Đang chuẩn bị video";
  }
}

function mergeBindings(current: InputBinding[], next: InputBinding[]): InputBinding[] {
  const replacing = new Set(next.map((item) => item.role));
  return [...current.filter((item) => !replacing.has(item.role)), ...next];
}

function cloudStateFrom(candidate: InputResolutionCandidate): CloudObservationState | null {
  if (candidate.candidate_kind !== "video_recipe") return null;
  const role = candidate.bindings.find((item) =>
    item.role === "registered_lidar_map" || item.role === "static_lidar_cloud" || item.role === "lidar_scan"
  )?.role;
  if (role === "registered_lidar_map") return "registered_map";
  if (role === "static_lidar_cloud") return "single_static_cloud";
  if (role === "lidar_scan") return "raw_scan_sequence";
  return null;
}

function actorId(userId: string | undefined, authRequired: boolean | undefined): string {
  return userId ?? (authRequired ? "anonymous" : "local");
}

export function UnifiedInputFlow() {
  const { me } = useAuth();
  const accountId = actorId(me?.user?.user_id, me?.auth_required);
  return <UnifiedInputFlowBody key={accountId} accountId={accountId} />;
}

function UnifiedInputFlowBody({ accountId }: { accountId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { me, refresh } = useAuth();
  const ids = { upload: useId(), intent: useId(), name: useId(), owner: useId(), origin: useId(), purpose: useId(), rgbTimes: useId(), lidarTimes: useId() };
  const draftKey = inputDraftKey(accountId);
  const [entries, setEntries] = useState<InputEntry[]>([]);
  const [draftLoaded, setDraftLoaded] = useState(false);
  const [scanOrder, setScanOrder] = useState<string[]>([]);
  const [scanOrderConfirmed, setScanOrderConfirmed] = useState(false);
  const [rgbFrameTimesFileId, setRgbFrameTimesFileId] = useState("");
  const [lidarScanTimesFileId, setLidarScanTimesFileId] = useState("");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<InputAssemblySnapshot | null>(null);
  const [report, setReport] = useState<InputResolutionReport | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [intent, setIntent] = useState<InputWorkflowIntent | null>(null);
  const [bindings, setBindings] = useState<InputBinding[]>([]);
  const [cloudState, setCloudState] = useState<DeclarationChoice<CloudObservationState>>("");
  const [sameScene, setSameScene] = useState<"" | "yes" | "no">("");
  const [coordinateUnit, setCoordinateUnit] = useState<DeclarationChoice<DistanceUnit>>("");
  const [lidarFrameId, setLidarFrameId] = useState("");
  const [trajectoryConvention, setTrajectoryConvention] = useState<DeclarationChoice<TrajectoryConvention>>("");
  const [clockRelation, setClockRelation] = useState<DeclarationChoice<"same_clock" | "known_offset" | "unknown">>("");
  const [clockOffset, setClockOffset] = useState("");
  const [rgbTimestampUnit, setRgbTimestampUnit] = useState<DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">>("");
  const [lidarTimestampUnit, setLidarTimestampUnit] = useState<DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">>("");
  const [sceneName, setSceneName] = useState("");
  const [dataOrigin, setDataOrigin] = useState<DataOrigin | "">("");
  const [dataOwner, setDataOwner] = useState("");
  const [dataPurpose, setDataPurpose] = useState("");
  const [rights, setRights] = useState(false);
  const [anonymized, setAnonymized] = useState(false);
  const [autoAnonymize, setAutoAnonymize] = useState(false);
  const [retention, setRetention] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const handles = useRef(new Map<string, (() => void)>());
  const preparationControllers = useRef(new Map<string, AbortController>());
  const preparedArtifacts = useRef(new Map<string, VideoPreparedArtifact>());
  const mounted = useRef(true);
  const processedLegacyId = useRef<string | null>(null);
  // Phân tích tự chạy sau mỗi thay đổi input (debounce); `analyzeRef` luôn trỏ bản `analyze` của render mới nhất.
  const autoAnalyzeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tăng mỗi khi input đổi: kết quả của lần phân tích bắt đầu trước đó không còn đúng và phải bị bỏ.
  const inputGeneration = useRef(0);
  const analyzeRef = useRef<(auto: boolean) => Promise<void>>(async () => undefined);
  const processing = useProcessingForm(intent === "video_reconstruction");

  const includedEntries = useMemo(() => entries.filter((item) => item.included), [entries]);
  const stagedEntries = useMemo(() => includedEntries.filter((item) => item.staged), [includedEntries]);
  const stagedFiles = useMemo(() => stagedEntries.flatMap((item) => item.staged?.staged_files ?? []), [stagedEntries]);
  const fileNamesById = useMemo(() => new Map(entries.flatMap((entry) =>
    (entry.staged?.staged_files ?? []).map((file) => [
      file.file_id,
      file.archive_member ? `${entry.originalName} · ${file.archive_member}` : entry.originalName,
    ] as const)
  )), [entries]);
  const observedVideos = stagedFiles.filter((item) => VIDEO_FORMATS.has(item.observed_format));
  const observedGaussians = stagedFiles.filter((item) => GAUSSIAN_FORMATS.has(item.observed_format));
  const observedClouds = stagedFiles.filter((item) => CLOUD_FORMATS.has(item.observed_format));
  const timestampFiles = stagedFiles.filter((item) => item.observed_format === "timestamp_rows" || item.observed_format === "rgb_frame_times");
  const hasMixedSceneKinds = observedVideos.length > 0 && observedGaussians.length > 0;
  const activeCandidate = report?.candidates.find((item) => item.candidate_id === selectedCandidateId) ??
    report?.candidates.find((item) => item.candidate_id === report.recommended_candidate_id) ?? null;
  const isGuest = me?.user?.role === "guest";
  const guestQuotaEmpty = isGuest && me?.quota?.remaining === 0;
  const processingBlocked = Boolean(processing.options && (
    !processing.values || processing.loading || processing.evaluating || processing.error || processing.evaluation?.blocking
  ));

  /** Kết quả cũ không còn đúng: xoá và tự phân tích lại sau một nhịp để gộp nhiều thay đổi liên tiếp. */
  function scheduleAutoAnalyze() {
    if (autoAnalyzeTimer.current) clearTimeout(autoAnalyzeTimer.current);
    autoAnalyzeTimer.current = setTimeout(() => void analyzeRef.current(true), AUTO_ANALYZE_DELAY_MS);
  }

  function invalidateResolution() {
    inputGeneration.current += 1;
    setReport(null);
    setSelectedCandidateId(null);
    setError(null);
    scheduleAutoAnalyze();
  }

  function clearDraft() {
    try {
      window.sessionStorage.removeItem(draftKey);
    } catch {
      // Clearing a convenience draft must not turn an accepted job/import into an error.
    }
  }

  function appendScanFiles(staged: AssemblyUploadResponse) {
    const scanIds = staged.staged_files.filter((item) => CLOUD_FORMATS.has(item.observed_format)).map((item) => item.file_id);
    if (scanIds.length) setScanOrder((current) => [...current, ...scanIds.filter((id) => !current.includes(id))]);
  }

  function patchEntry(entryId: string, patch: Partial<InputEntry>) {
    if (!mounted.current) return;
    setEntries((current) => current.map((item) => item.id === entryId ? { ...item, ...patch } : item));
  }

  useEffect(() => {
    mounted.current = true;
    const uploadHandles = handles.current;
    const controllers = preparationControllers.current;
    const artifacts = preparedArtifacts.current;
    return () => {
      mounted.current = false;
      if (autoAnalyzeTimer.current) clearTimeout(autoAnalyzeTimer.current);
      for (const cancel of uploadHandles.values()) cancel();
      for (const controller of controllers.values()) controller.abort();
      for (const prepared of artifacts.values()) void prepared.dispose().catch(() => undefined);
      uploadHandles.clear();
      controllers.clear();
      artifacts.clear();
    };
  }, []);

  useEffect(() => {
    let alive = true;
    async function restoreDraft() {
      let raw: string | null = null;
      try {
        raw = window.sessionStorage.getItem(draftKey);
      } catch {
        // Storage may be disabled; the upload flow can still run for this page visit.
      }
      const draft = raw ? parseInputDraft(raw, accountId) : null;
      if (!draft || draft.uploads.length === 0) {
        if (alive) setDraftLoaded(true);
        return;
      }

      const restored: InputEntry[] = [];
      const missing: string[] = [];
      for (let offset = 0; offset < draft.uploads.length; offset += 4) {
        const batch = draft.uploads.slice(offset, offset + 4);
        const results = await Promise.allSettled(batch.map((item) => getStagedInputUpload(item.upload_id)));
        if (!alive) return;
        results.forEach((result, index) => {
          const saved = batch[index];
          if (result.status === "rejected") {
            missing.push(saved.original_name);
            return;
          }
          restored.push({
            id: `restored:${saved.upload_id}`,
            file: null,
            originalName: saved.original_name || result.value.source_file.original_name,
            isVideo: result.value.staged_files.some((item) => VIDEO_FORMATS.has(item.observed_format)),
            preset: saved.preset,
            included: saved.included,
            status: "ready",
            progress: 1,
            preparation: null,
            error: null,
            recovery: null,
            useOriginal: false,
            legacyUploadId: null,
            staged: result.value,
          });
        });
      }
      if (!alive) return;
      setEntries(restored);
      const cloudIds = restored.flatMap((entry) => entry.staged?.staged_files
        .filter((item) => CLOUD_FORMATS.has(item.observed_format)).map((item) => item.file_id) ?? []);
      const ordered = draft.scan_order.filter((id) => cloudIds.includes(id));
      setScanOrder([...ordered, ...cloudIds.filter((id) => !ordered.includes(id))]);
      const timestampIds = new Set(restored.filter((entry) => entry.included).flatMap((entry) => entry.staged?.staged_files
        .filter((item) => item.observed_format === "timestamp_rows" || item.observed_format === "rgb_frame_times")
        .map((item) => item.file_id) ?? []));
      setRgbFrameTimesFileId(timestampIds.has(draft.rgb_frame_times_file_id ?? "") ? draft.rgb_frame_times_file_id! : "");
      setLidarScanTimesFileId(timestampIds.has(draft.lidar_scan_times_file_id ?? "") ? draft.lidar_scan_times_file_id! : "");
      setIntent(draft.intent);
      setCloudState(draft.cloud_state);
      setSameScene(draft.same_scene);
      setCoordinateUnit(draft.coordinate_unit);
      setLidarFrameId(draft.lidar_frame_id);
      setTrajectoryConvention(draft.trajectory_convention);
      setClockRelation(draft.clock_relation);
      setClockOffset(draft.clock_offset);
      setRgbTimestampUnit(draft.rgb_timestamp_unit ?? "");
      setLidarTimestampUnit(draft.lidar_timestamp_unit ?? "");
      setSceneName(draft.scene_name);
      setDataOrigin(draft.data_origin);
      setDataOwner(draft.data_owner);
      setDataPurpose(draft.data_purpose);
      if (restored.length) setNotice("Đã khôi phục các upload của tài khoản này và xác minh lại với máy chủ.");
      if (missing.length) setError(`Không thể khôi phục một số upload đã hết hạn hoặc không còn quyền truy cập: ${missing.join(", ")}`);
      setDraftLoaded(true);
    }
    void restoreDraft();
    return () => { alive = false; };
  }, [accountId, draftKey]);

  useEffect(() => {
    if (!draftLoaded) return;
    const uploads = entries.flatMap((entry) => entry.staged ? [{
      upload_id: entry.staged.upload_id,
      original_name: entry.originalName,
      included: entry.included,
      preset: entry.preset,
    }] : []);
    try {
      if (uploads.length === 0) {
        window.sessionStorage.removeItem(draftKey);
        return;
      }
      const liveCloudIds = new Set(entries.flatMap((entry) => entry.staged?.staged_files
        .filter((item) => CLOUD_FORMATS.has(item.observed_format)).map((item) => item.file_id) ?? []));
      const liveTimestampIds = new Set(entries.filter((entry) => entry.included).flatMap((entry) => entry.staged?.staged_files
        .filter((item) => item.observed_format === "timestamp_rows" || item.observed_format === "rgb_frame_times")
        .map((item) => item.file_id) ?? []));
      const draft: StoredInputDraft = {
        schema_version: 1,
        account_id: accountId,
        uploads,
        scan_order: scanOrder.filter((id) => liveCloudIds.has(id)),
        rgb_frame_times_file_id: liveTimestampIds.has(rgbFrameTimesFileId) ? rgbFrameTimesFileId : "",
        lidar_scan_times_file_id: liveTimestampIds.has(lidarScanTimesFileId) ? lidarScanTimesFileId : "",
        intent,
        cloud_state: cloudState,
        same_scene: sameScene,
        coordinate_unit: coordinateUnit,
        lidar_frame_id: lidarFrameId,
        trajectory_convention: trajectoryConvention,
        clock_relation: clockRelation,
        clock_offset: clockOffset,
        rgb_timestamp_unit: rgbTimestampUnit,
        lidar_timestamp_unit: lidarTimestampUnit,
        scene_name: sceneName,
        data_origin: dataOrigin,
        data_owner: dataOwner,
        data_purpose: dataPurpose,
      };
      window.sessionStorage.setItem(draftKey, JSON.stringify(draft));
    } catch {
      // Tab-scoped recovery is best-effort when the browser disables session storage.
    }
  }, [accountId, cloudState, clockOffset, clockRelation, coordinateUnit, dataOrigin, dataOwner, dataPurpose, draftKey, draftLoaded, entries, intent, lidarFrameId, lidarScanTimesFileId, rgbFrameTimesFileId, lidarTimestampUnit, rgbTimestampUnit, sameScene, scanOrder, sceneName, trajectoryConvention]);

  useEffect(() => {
    const legacyUploadId = params.get("upload");
    if (!draftLoaded || !legacyUploadId || processedLegacyId.current === legacyUploadId || !canEdit(me)) return;
    processedLegacyId.current = legacyUploadId;
    let alive = true;
    void stageExistingInputUpload(legacyUploadId).then((staged) => {
      if (!alive) return;
      const entry: InputEntry = {
        id: `existing:${legacyUploadId}`,
        file: null,
        originalName: staged.source_file.original_name,
        isVideo: staged.staged_files.some((item) => VIDEO_FORMATS.has(item.observed_format)),
        preset: "720p",
        included: true,
        status: "ready",
        progress: 1,
        preparation: null,
        error: null,
        recovery: null,
        useOriginal: false,
        legacyUploadId,
        staged,
      };
      setEntries((current) => current.some((item) => item.staged?.upload_id === legacyUploadId) ? current : [...current, entry]);
      appendScanFiles(staged);
      setNotice("Đã nối upload cũ vào inventory chung; file đã xác minh không cần tải lại.");
      const videoName = staged.staged_files.find((item) => VIDEO_FORMATS.has(item.observed_format))?.source_file.original_name;
      if (videoName) setSceneName((current) => current || videoName.replace(/\.[^.]+$/, ""));
    }).catch((cause: unknown) => {
      if (alive) setError(errorMessage(cause, "Không thể nối upload cũ vào inventory chung."));
    });
    return () => { alive = false; };
  }, [draftLoaded, params, me]);

  useEffect(() => {
    const legacySource = params.get("source");
    // `/new?sample=<id>` là link cũ của trình hướng dẫn mẫu; không có `source` thì `sample` quyết định đích.
    const target = legacySource ?? (params.get("sample") ? "sample" : null);
    if (target === null) return;
    const query = new URLSearchParams(params.toString());
    query.delete("source");
    const suffix = query.size ? `?${query.toString()}` : "";
    if (target === "sample") router.replace(`/new/try-demo${suffix}`);
    else if (target === "gaussian") router.replace(`/new/import-scene${suffix}`);
    else if (target === "video") router.replace(`/new${suffix}`);
  }, [params, router]);

  async function addFiles(files: FileList | File[]) {
    if (!draftLoaded) return;
    const dropped = Array.from(files);
    if (!dropped.length) return;
    // Lọc sớm theo đuôi để không tải lên thứ pipeline không có chỗ dùng; nội dung vẫn do server probe.
    const unusable = dropped.filter((file) => rejectAssemblyFileName(file.name) !== null);
    const candidates = dropped.filter((file) => rejectAssemblyFileName(file.name) === null);
    // Chỉ ghi đè notice khi thật sự có file bị bỏ qua: notice đang hiện có thể là lời nhắc khác.
    const skipped = unusable.length
      ? `Đã bỏ qua ${unusable.length} file pipeline không đọc được: ${unusable.map((file) => file.name).join(", ")}.`
      : null;
    if (!candidates.length) {
      setError(`${rejectAssemblyFileName(dropped[0].name)} Đã bỏ qua: ${dropped.map((file) => file.name).join(", ")}.`);
      return;
    }
    if (entries.length + candidates.length > 100) {
      setError("Một lần xử lý nhận tối đa 100 file. Hãy chia dữ liệu thành các nhóm nhỏ hơn.");
      if (skipped) setNotice(skipped);
      return;
    }
    setAdding(true);
    setError(null);
    try {
      const newItems = await Promise.all(candidates.map(async (file) => newEntry(file, await looksLikeVideo(file))));
      setEntries((current) => [...current, ...newItems]);
      invalidateResolution();
      setScanOrderConfirmed(false);
    } catch (cause: unknown) {
      setError(errorMessage(cause, "Không đọc được danh sách file đã chọn."));
    } finally {
      // Sau `invalidateResolution` (hàm đó xoá error, không xoá notice) và đúng cho cả nhánh lỗi.
      if (skipped) setNotice(skipped);
      setAdding(false);
    }
  }

  async function uploadOne(entry: InputEntry, choice: { useOriginal?: boolean } = {}): Promise<void> {
    setError(null);
    // Lựa chọn của người dùng đi kèm lời gọi (state chưa kịp cập nhật) và được lưu vào entry cho các lần thử lại.
    const useOriginal = choice.useOriginal ?? entry.useOriginal;
    if (useOriginal !== entry.useOriginal) patchEntry(entry.id, { useOriginal });
    if (entry.legacyUploadId && !entry.staged) {
      patchEntry(entry.id, { status: "uploading", progress: null, error: null });
      try {
        const staged = await stageExistingInputUpload(entry.legacyUploadId);
        appendScanFiles(staged);
        patchEntry(entry.id, { status: "ready", progress: 1, staged, error: null });
        invalidateResolution();
        return;
      } catch (cause: unknown) {
        patchEntry(entry.id, { status: "failed", progress: null, error: errorMessage(cause, "Không thể nối upload hiện có.") });
        return;
      }
    }
    if (!entry.file) return;
    try {
      let prepared = preparedArtifacts.current.get(entry.id);
      if (entry.isVideo && !useOriginal && !prepared) {
        const controller = new AbortController();
        preparationControllers.current.set(entry.id, controller);
        patchEntry(entry.id, { status: "preparing", progress: null, preparation: { phase: "hashing", progress: 0 }, error: null, recovery: null });
        prepared = await prepareVideoForUpload({
          source: entry.file,
          preset: entry.preset,
          signal: controller.signal,
          onProgress: (progress) => patchEntry(entry.id, { preparation: progress }),
        });
        preparationControllers.current.delete(entry.id);
        preparedArtifacts.current.set(entry.id, prepared);
      }
      if (entry.isVideo && !useOriginal && prepared) {
        patchEntry(entry.id, { status: "uploading", progress: 0, error: null });
        const upload = uploadPreparedVideo(prepared, {
          accountId,
          onProgress: (progress) => patchEntry(entry.id, { progress }),
        });
        handles.current.set(entry.id, upload.abort);
        const record = await upload.promise;
        handles.current.delete(entry.id);
        patchEntry(entry.id, { legacyUploadId: record.upload_id, progress: 1 });
        const staged = await stageExistingInputUpload(record.upload_id);
        appendScanFiles(staged);
        patchEntry(entry.id, { status: "ready", staged, progress: 1, error: null });
        preparedArtifacts.current.delete(entry.id);
        await prepared.dispose();
      } else {
        patchEntry(entry.id, { status: "uploading", progress: 0, error: null, recovery: null });
        const upload: AssemblyFileUploadHandle = uploadAssemblyFile(
          entry.file,
          accountId,
          (progress) => patchEntry(entry.id, { progress }),
        );
        handles.current.set(entry.id, upload.abort);
        const staged = await upload.promise;
        handles.current.delete(entry.id);
        appendScanFiles(staged);
        patchEntry(entry.id, { status: "ready", staged, progress: 1, error: null });
      }
      invalidateResolution();
      const videoName = entry.file.name.replace(/\.[^.]+$/, "");
      if (entry.isVideo) setSceneName((current) => current || videoName);
    } catch (cause: unknown) {
      handles.current.delete(entry.id);
      preparationControllers.current.delete(entry.id);
      const cancelled = cause instanceof VideoPreparationError && cause.code === "cancelled" ||
        cause instanceof DOMException && cause.name === "AbortError";
      const failure = !cancelled && cause instanceof VideoPreparationError ? preparationFailure(cause) : null;
      patchEntry(entry.id, {
        status: cancelled ? "cancelled" : "failed",
        progress: null,
        preparation: null,
        error: cancelled ? "Đã hủy thao tác. Có thể chọn Tiếp tục để nối phiên upload." : failure?.message ?? errorMessage(cause, "Upload thất bại."),
        recovery: failure?.recovery ?? null,
      });
    }
  }

  async function uploadPending() {
    if (busy || adding) return;
    const queue = entries.filter((item) => item.included && item.status !== "ready" && (item.file !== null || item.legacyUploadId !== null));
    if (!queue.length) return;
    setBusy(true);
    for (const entry of queue) await uploadOne(entry);
    setBusy(false);
  }

  function cancelEntry(entryId: string) {
    handles.current.get(entryId)?.();
    preparationControllers.current.get(entryId)?.abort();
  }

  function removeEntry(entryId: string) {
    const removed = entries.find((item) => item.id === entryId);
    const removedFileIds = new Set(removed?.staged?.staged_files.map((item) => item.file_id) ?? []);
    const prepared = preparedArtifacts.current.get(entryId);
    preparedArtifacts.current.delete(entryId);
    if (prepared) void prepared.dispose().catch(() => undefined);
    setEntries((current) => current.filter((item) => item.id !== entryId));
    setScanOrder((current) => current.filter((id) => !removedFileIds.has(id)));
    setRgbFrameTimesFileId((current) => removedFileIds.has(current) ? "" : current);
    setLidarScanTimesFileId((current) => removedFileIds.has(current) ? "" : current);
    if (removedFileIds.has(rgbFrameTimesFileId)) setRgbTimestampUnit("");
    if (removedFileIds.has(lidarScanTimesFileId)) setLidarTimestampUnit("");
    setBindings((current) => current.filter((item) =>
      !["rgb_frame_times", "lidar_scan_times"].includes(item.role) ||
      !item.file_ids.some((fileId) => removedFileIds.has(fileId)),
    ));
    setScanOrderConfirmed(false);
    if (removed?.staged && removed.staged.staged_files.some((item) => VIDEO_FORMATS.has(item.observed_format))) {
      setRights(false);
      setAnonymized(false);
      setRetention(false);
    }
    invalidateResolution();
  }

  function setIncluded(entryId: string, included: boolean) {
    const entry = entries.find((item) => item.id === entryId);
    const excludedFileIds = new Set(included ? [] : entry?.staged?.staged_files.map((item) => item.file_id) ?? []);
    setEntries((current) => current.map((item) => item.id === entryId ? { ...item, included } : item));
    setRgbFrameTimesFileId((current) => excludedFileIds.has(current) ? "" : current);
    setLidarScanTimesFileId((current) => excludedFileIds.has(current) ? "" : current);
    if (excludedFileIds.has(rgbFrameTimesFileId)) setRgbTimestampUnit("");
    if (excludedFileIds.has(lidarScanTimesFileId)) setLidarTimestampUnit("");
    if (!included) {
      setBindings((current) => current.filter((item) => ![
        ...(excludedFileIds.has(rgbFrameTimesFileId) ? ["rgb_frame_times"] : []),
        ...(excludedFileIds.has(lidarScanTimesFileId) ? ["lidar_scan_times"] : []),
      ].includes(item.role)));
    }
    setScanOrderConfirmed(false);
    invalidateResolution();
  }

  function buildDeclarations(cloudOverride?: CloudObservationState | null): InputAssemblyDeclarations {
    const offset = clockOffset.trim() === "" ? null : Number(clockOffset);
    return {
      same_scene: evidence(sameScene === "" ? null : sameScene === "yes"),
      cloud_state: evidence(cloudOverride ?? (cloudState || null)),
      coordinate_unit: evidence(coordinateUnit || null),
      lidar_frame_id: evidence(lidarFrameId.trim() || null),
      world_frame_id: null,
      trajectory_convention: evidence(trajectoryConvention || null),
      clock_relation: evidence(clockRelation || null),
      clock_offset_seconds: Number.isFinite(offset) && offset !== null ? evidence(offset) : null,
      timestamp_unit: null,
      rgb_timestamp_unit: evidence(rgbTimestampUnit || null),
      lidar_timestamp_unit: evidence(lidarTimestampUnit || null),
    };
  }

  function writeRequest(
    nextIntent: InputWorkflowIntent | null = intent,
    nextBindings: InputBinding[] = bindings,
    cloudOverride?: CloudObservationState | null,
    includeTimeSelections = true,
  ): InputAssemblyWriteRequest {
    const timeBindings: InputBinding[] = [];
    if (includeTimeSelections && timestampFiles.some((item) => item.file_id === rgbFrameTimesFileId)) {
      timeBindings.push({ binding_id: "binding-rgb-frame-times", role: "rgb_frame_times", file_ids: [rgbFrameTimesFileId] });
    }
    if (includeTimeSelections && timestampFiles.some((item) => item.file_id === lidarScanTimesFileId)) {
      timeBindings.push({ binding_id: "binding-lidar-scan-times", role: "lidar_scan_times", file_ids: [lidarScanTimesFileId] });
    }
    return {
      upload_ids: [...new Set(stagedEntries.map((item) => item.staged!.upload_id))],
      declarations: buildDeclarations(cloudOverride),
      bindings: mergeBindings(nextBindings, timeBindings),
      requested_intent: nextIntent,
    };
  }

  async function analyze(
    nextIntent: InputWorkflowIntent | null = intent,
    nextBindings: InputBinding[] = bindings,
    cloudOverride?: CloudObservationState | null,
    includeTimeSelections = true,
    auto = false,
  ) {
    if (autoAnalyzeTimer.current) {
      clearTimeout(autoAnalyzeTimer.current);
      autoAnalyzeTimer.current = null;
    }
    if (busy || adding) {
      // Thay đổi xảy ra giữa chừng một lần phân tích hay thêm file: chạy lại sau khi xong thay vì mất lịch.
      if (auto) scheduleAutoAnalyze();
      return;
    }
    // Tự phân tích chỉ chạy khi đã đủ điều kiện; chưa đủ thì im lặng chờ, không báo lỗi thay người dùng.
    const notReady = includedEntries.some((item) => item.status !== "ready" || !item.staged);
    if (auto && (notReady || !stagedEntries.length || (hasMixedSceneKinds && !nextIntent))) return;
    if (notReady) {
      setError("Hãy hoàn tất, thử lại hoặc bỏ mọi file đang chờ tải lên.");
      return;
    }
    if (!stagedEntries.length) {
      setError("Chọn ít nhất một file đã upload để phân tích.");
      return;
    }
    if (hasMixedSceneKinds && !nextIntent) {
      setError("Chọn rõ mục đích cho gói có cả video và scene 3DGS.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    setReport(null);
    setSnapshot(null);
    const generation = inputGeneration.current;
    try {
      const request = writeRequest(nextIntent, nextBindings, cloudOverride, includeTimeSelections);
      const next = snapshot
        ? await reviseInputAssembly(snapshot.assembly_id, snapshot.revision, request)
        : await createInputAssembly(request);
      setSnapshot(next);
      const resolved = await resolveInputAssembly(next.assembly_id, next.revision);
      // Người dùng đã đổi input trong lúc chờ: bỏ kết quả này (lịch phân tích mới đã được xếp bởi lần đổi đó).
      if (generation !== inputGeneration.current) return;
      setReport(resolved.report);
      setSelectedCandidateId(resolved.report.recommended_candidate_id);
      setIntent(nextIntent);
      setBindings(request.bindings);
      if (cloudOverride !== undefined) setCloudState(cloudOverride ?? "");
    } catch (cause: unknown) {
      setError(errorMessage(cause, "Không phân tích được tập input."));
    } finally {
      setBusy(false);
    }
  }

  // Gán trong effect (không gán lúc render) để ref luôn là closure đã commit của render gần nhất.
  useEffect(() => {
    analyzeRef.current = (auto: boolean) => analyze(intent, bindings, undefined, true, auto);
  });

  async function chooseCandidate(candidate: InputResolutionCandidate) {
    if (candidate.state === "unsupported" || candidate.state === "invalid" || candidate.state === "pending_verification") return;
    const nextIntent: InputWorkflowIntent = candidate.candidate_kind === "gaussian_view_import"
      ? "gaussian_view_import"
      : "video_reconstruction";
    let nextBindings: InputBinding[] = candidate.candidate_kind === "gaussian_view_import"
      ? [{ binding_id: "binding-gaussian-master", role: "gaussian_scene", file_ids: [candidate.source_file_id] }]
      : candidate.bindings;
    if (candidate.candidate_kind === "video_recipe") {
      const scanBinding = candidate.bindings.find((item) => item.role === "lidar_scan");
      if (scanBinding) {
        const selectedOrder = scanOrder.filter((id) => scanBinding.file_ids.includes(id));
        if (!scanOrderConfirmed || selectedOrder.length !== scanBinding.file_ids.length) {
          setError("Sắp xếp các scan theo thời gian rồi xác nhận thứ tự trước khi dùng chuỗi này.");
          return;
        }
        nextBindings = mergeBindings(nextBindings, [{ ...scanBinding, file_ids: selectedOrder }]);
      }
    }
    const nextCloud = cloudStateFrom(candidate);
    setSelectedCandidateId(candidate.candidate_id);
    await analyze(nextIntent, nextBindings, nextCloud === null ? undefined : nextCloud, false);
  }

  async function submitReadyRoute(event: React.FormEvent) {
    event.preventDefault();
    const candidate = activeCandidate;
    if (!snapshot || !report || report.state !== "ready" || !candidate || candidate.state !== "ready" ||
        candidate.candidate_id !== report.recommended_candidate_id || submitting || !sceneName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      if (candidate.candidate_kind === "gaussian_view_import") {
        const imported = await importGaussianFromAssembly(snapshot.assembly_id, {
          revision: snapshot.revision,
          resolution_checksum: report.report_checksum,
          candidate_id: candidate.candidate_id,
          name: sceneName.trim(),
        });
        clearDraft();
        router.push(`/imports/${encodeURIComponent(imported.imported_scene.import_id)}`);
        return;
      }
      if (!dataOrigin || !dataOwner.trim() || !dataPurpose.trim() || !rights || !anonymized || !retention) {
        setError("Hoàn tất xác nhận nguồn dữ liệu trước khi tạo job.");
        return;
      }
      if (guestQuotaEmpty) {
        setError("Bạn đã dùng hết 3 lượt chạy job Guest hôm nay. Hạn mức sẽ đặt lại lúc 00:00 giờ Việt Nam.");
        return;
      }
      if (processingBlocked) {
        setError("Cấu hình xử lý chưa được xác nhận hoặc vượt tài nguyên worker.");
        return;
      }
      const attestation: SourceRightsAttestation = {
        data_origin: dataOrigin,
        declared_owner: dataOwner.trim(),
        declared_purpose: dataPurpose.trim(),
        rights_to_use_confirmed: rights,
        anonymization_confirmed: anonymized,
        retention_acknowledged: retention,
      };
      const result = await runInputAssembly(snapshot.assembly_id, {
        revision: snapshot.revision,
        resolution_checksum: report.report_checksum,
        candidate_id: candidate.candidate_id,
        name: sceneName.trim(),
        attestation,
        ...(processing.values ? { processing: processing.values } : {}),
        ...(processing.options?.anonymize_available && (autoAnonymize || processing.options.anonymize_enforced) ? { anonymize: true } : {}),
      });
      if (isGuest) void refresh();
      clearDraft();
      router.push(`/scenes/${encodeURIComponent(result.job.job_id)}`);
    } catch (cause: unknown) {
      if (isGuest) await refresh();
      setError(errorMessage(cause, "Không thể tiếp tục luồng input đã chọn."));
    } finally {
      setSubmitting(false);
    }
  }

  function moveScan(fileId: string, direction: -1 | 1) {
    setScanOrder((current) => {
      const order = [...current];
      const index = order.indexOf(fileId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= order.length) return order;
      [order[index], order[target]] = [order[target], order[index]];
      return order;
    });
    setScanOrderConfirmed(false);
    invalidateResolution();
  }

  const scanFileNames = scanOrder.map((fileId) => {
    const file = stagedFiles.find((item) => item.file_id === fileId);
    return { fileId, name: file?.archive_member?.member_path ?? file?.source_file.original_name ?? fileId };
  });
  const loginHref = `${pathname}${typeof window === "undefined" ? "" : window.location.search}`;
  // Mọi lý do khiến nút tạo scene đang tắt, để người dùng không phải đoán ô nào còn thiếu.
  const createBlockers: string[] = [];
  if (activeCandidate && report?.state === "ready") {
    if (!sceneName.trim()) createBlockers.push("Nhập tên scene.");
    if (activeCandidate.candidate_kind === "video_recipe") {
      if (!dataOwner.trim()) createBlockers.push("Nhập người hoặc đơn vị sở hữu dữ liệu.");
      if (!dataOrigin) createBlockers.push("Chọn nguồn dữ liệu.");
      if (!dataPurpose.trim()) createBlockers.push("Nhập mục đích sử dụng.");
      if (!rights) createBlockers.push("Xác nhận bạn có quyền sử dụng dữ liệu.");
      if (!anonymized) createBlockers.push("Xác nhận video không có khuôn mặt/biển số hoặc đã được làm mờ.");
      if (!retention) createBlockers.push("Xác nhận việc lưu dữ liệu và kết quả.");
      if (processingBlocked) createBlockers.push("Cấu hình xử lý chưa được xác nhận hoặc vượt tài nguyên máy.");
      if (guestQuotaEmpty) createBlockers.push("Đã dùng hết lượt chạy Guest hôm nay.");
    }
  }

  if (me === null) {
    return <main className="mx-auto max-w-4xl px-4 pt-10 pb-20 sm:px-6"><PageHeader title="Tạo scene mới" description="Một khung tải lên cho video, LiDAR, metadata và scene 3DGS." /><p className="mt-8 text-sm text-ink-muted" role="status">Đang kiểm tra quyền truy cập…</p></main>;
  }

  if (!canEdit(me)) {
    return (
      <main className="mx-auto max-w-4xl px-4 pt-10 pb-20 sm:px-6">
        <PageHeader title="Tạo scene mới" description="Một khung tải lên cho video, LiDAR, metadata và scene 3DGS." />
        <EmptyState icon={<FileUp aria-hidden />} title="Đăng nhập để tải dữ liệu lên" className="mt-8" action={<a href={`/login?next=${encodeURIComponent(loginHref)}`} className={buttonVariants({})}>Đăng nhập</a>}>
          Video được chuẩn bị ở 720p mặc định trước khi gửi; file khác được phân loại theo nội dung sau upload.
        </EmptyState>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pt-10 pb-20 sm:px-6">
      <PageHeader title="Tạo scene từ video" description="Thả video, LiDAR, calibration, quỹ đạo, thời điểm frame, PLY/SOG hoặc ZIP vào cùng một khung. Hệ thống đọc nội dung rồi tự chọn cách xử lý phù hợp." />
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">Tải lên và phân tích chưa tạo job hay trừ quota.</p>
        <a className="text-sm font-medium text-ember-strong hover:underline" href="/new/try-demo">Xem scene mẫu đã xử lý</a>
      </div>

      <section className="mt-5 space-y-4" aria-label="Tập input">
        {!draftLoaded && <p className="text-sm text-ink-muted" role="status">Đang khôi phục upload của tài khoản…</p>}
        <Card
          className={`p-5 sm:p-6 ${dragging ? "border-ember bg-ember-soft/30" : "border-dashed"}`}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
            onDrop={(event) => { event.preventDefault(); setDragging(false); if (draftLoaded) void addFiles(event.dataTransfer.files); }}
        >
          <input
            id={ids.upload}
            type="file"
            multiple
            accept={ASSEMBLY_ACCEPT}
            className="sr-only"
            disabled={busy || adding || !draftLoaded}
            onChange={(event) => { void addFiles(event.currentTarget.files ?? []); event.currentTarget.value = ""; }}
          />
          <label htmlFor={ids.upload} className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl px-4 py-8 text-center outline-none focus-within:ring-3 focus-within:ring-ember/30">
            <FileUp className="size-8 text-ember-strong" aria-hidden />
            <span className="font-semibold text-ink">Thả tất cả file vào đây hoặc chọn từ máy</span>
            <span className="max-w-2xl text-sm text-ink-muted">Hỗ trợ video MP4/MOV, point cloud PLY/PCD, calibration, trajectory TUM, timestamp RGB/LiDAR, Gaussian PLY/SOG và ZIP. Hệ thống xác định vai trò theo nội dung.</span>
          </label>
          {adding && <p className="text-center text-sm text-ink-muted" role="status">Đang đọc danh sách file…</p>}
        </Card>

          {entries.length > 0 && (
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-bold">Danh sách file</h2>
                <p className="mt-1 text-sm text-ink-muted">Chỉ file đã tải lên và được xác minh mới được dùng. Bỏ chọn một file sẽ loại nó khỏi lần phân tích kế tiếp.</p>
              </div>
              <Button variant="secondary" onClick={() => void uploadPending()} disabled={busy || adding || !entries.some((item) => item.included && item.status !== "ready" && item.file)}>
                {busy ? <><Loader2 className="size-4 animate-spin" aria-hidden /> Đang xử lý</> : <>Tải file đã chọn lên</>}
              </Button>
            </div>
            <ul className="mt-4 divide-y divide-line" aria-label="Các file đã chọn">
              {entries.map((entry) => {
                const formats = [...new Set(entry.staged?.staged_files.map((item) => formatLabel(item.observed_format)) ?? [])];
                const active = entry.status === "preparing" || entry.status === "uploading";
                const { unusable, total } = unusableStaged(entry.staged);
                const allUnusable = total > 0 && unusable === total;
                return (
                  <li key={entry.id} className="py-4 first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-start gap-3">
                      <input
                        type="checkbox"
                        aria-label={`Đưa ${entry.originalName} vào bộ file`}
                        checked={entry.included}
                        disabled={busy || active}
                        onChange={(event) => setIncluded(entry.id, event.target.checked)}
                        className="mt-1 size-4 accent-ember-strong"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="break-all text-sm font-medium text-ink">{entry.originalName}</p>
                        <p className="mt-0.5 text-sm text-ink-muted">
                          {entry.staged ? formats.join(" · ") || "ZIP chưa phân loại" : entry.isVideo ? `Video · ${formatBytes(entry.file?.size ?? 0)}` : `Đang chờ server phân loại · ${formatBytes(entry.file?.size ?? 0)}`}
                          {entry.staged && ` · ${formatBytes(entry.staged.source_file.size_bytes)}`}
                        </p>
                        {unusable > 0 && (
                          <p className="mt-1 text-sm text-ochre-strong">
                            {allUnusable
                              ? "Máy chủ không nhận ra vai trò nào trong file này, nên mọi hướng xử lý đều loại nó. Bỏ chọn hoặc xoá file để phân tích tiếp."
                              : `${unusable}/${total} thành phần trong file này không nhận ra vai trò; mọi hướng xử lý sẽ loại riêng những thành phần đó.`}
                          </p>
                        )}
                        {entry.isVideo && entry.status !== "ready" && (
                          <fieldset className="mt-3">
                            <legend className="text-xs font-semibold text-ink-muted">Độ phân giải tối đa · đầu ra giữ nguyên tỉ lệ và giới hạn 30 FPS</legend>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {VIDEO_PRESETS.map((preset) => (
                                <label key={preset.value} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line px-3 py-2 text-xs">
                                  <input type="radio" name={`${entry.id}-preset`} checked={entry.preset === preset.value} disabled={busy || active} onChange={() => setEntries((current) => current.map((item) => item.id === entry.id ? { ...item, preset: preset.value } : item))} />
                                  <span><strong>{preset.value}</strong><span className="block text-ink-muted">{preset.detail}</span></span>
                                </label>
                              ))}
                            </div>
                          </fieldset>
                        )}
                        {entry.status === "preparing" && (
                          <div className="mt-3" role="status" aria-live="polite">
                            <p className="text-xs text-ink-muted">{preparationLabel(entry.preparation?.phase)} · {Math.round((entry.preparation?.progress ?? 0) * 100)}%</p>
                            <ProgressBar value={entry.preparation?.progress ?? 0} label={`Chuẩn bị ${entry.originalName}`} className="mt-2" />
                          </div>
                        )}
                        {active && entry.status !== "preparing" && (
                          <div className="mt-3" role="status" aria-live="polite">
                            <p className="text-xs text-ink-muted">{entry.progress === null ? "Đang xác minh file…" : entry.progress >= 1 ? "Đang kiểm tra nội dung và tạo inventory…" : `Đang upload ${Math.round(entry.progress * 100)}%`}</p>
                            <ProgressBar value={entry.progress} label={`Tải lên ${entry.originalName}`} className="mt-2" />
                          </div>
                        )}
                        {entry.error && <p className="mt-2 text-sm text-rust" role="alert">{entry.error}</p>}
                        {entry.status === "failed" && entry.recovery && entry.file && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Button size="sm" variant="secondary" onClick={() => void uploadOne(entry, { useOriginal: true })} disabled={busy}>Tải video gốc không nén ({formatBytes(entry.file.size)})</Button>
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {entry.status === "ready"
                          ? allUnusable
                            ? <Badge tone="ochre">Không dùng được</Badge>
                            : <Badge tone="sage"><FileCheck2 aria-hidden /> Đã xác minh</Badge>
                          : null}
                        {(entry.status === "failed" || entry.status === "cancelled") && <Button size="sm" variant="secondary" onClick={() => void uploadOne(entry)} disabled={busy || (!entry.file && !entry.legacyUploadId)}>Tiếp tục</Button>}
                        {active && <Button size="icon" variant="ghost" aria-label={`Hủy ${entry.originalName}`} onClick={() => cancelEntry(entry.id)}><X aria-hidden /></Button>}
                        {!active && <Button size="icon" variant="ghost" aria-label={`Bỏ ${entry.originalName}`} onClick={() => removeEntry(entry.id)} disabled={busy}><Trash2 aria-hidden /></Button>}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      </section>

      {observedVideos.length > 0 && observedGaussians.length > 0 && (
        <Card className="mt-5 p-5 sm:p-6">
          <label htmlFor={ids.intent} className="text-sm font-semibold">Chọn mục đích cho gói có video và 3DGS</label>
          <select id={ids.intent} value={intent ?? ""} onChange={(event) => { setIntent((event.target.value || null) as InputWorkflowIntent | null); invalidateResolution(); }} className="mt-2 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm">
            <option value="">Chọn một mục đích</option>
            <option value="video_reconstruction">Dựng scene từ video</option>
            <option value="gaussian_view_import">Mở scene 3DGS để xem</option>
          </select>
          <p className="mt-2 text-xs text-ink-muted">Hai mục đích là hai luồng riêng. Chọn một luồng sẽ giữ nguyên các file; không tự gửi cả hai lệnh.</p>
        </Card>
      )}

      {timestampFiles.length > 0 && (
        <Card className="mt-5 p-5 sm:p-6">
          <h2 className="text-base font-bold">Gán vai trò cho file timestamp</h2>
          <p className="mt-1 text-sm text-ink-muted">Các dòng số không tự cho biết là thời gian camera hay LiDAR. Chọn đúng file cho từng cảm biến; hệ thống sẽ kiểm tra thứ tự và số dòng.</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label htmlFor={ids.rgbTimes} className="text-sm">File timestamp của frame RGB
              <select id={ids.rgbTimes} value={rgbFrameTimesFileId} onChange={(event) => { const fileId = event.target.value; setRgbFrameTimesFileId(fileId); if (fileId !== rgbFrameTimesFileId) setRgbTimestampUnit(""); if (fileId && fileId === lidarScanTimesFileId) { setLidarScanTimesFileId(""); setLidarTimestampUnit(""); } setBindings((current) => current.filter((item) => item.role !== "rgb_frame_times" && !(fileId && fileId === lidarScanTimesFileId && item.role === "lidar_scan_times"))); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                <option value="">Chưa gán</option>
                {timestampFiles.map((file) => <option key={file.file_id} value={file.file_id} disabled={file.file_id === lidarScanTimesFileId}>{fileNamesById.get(file.file_id) ?? file.file_id}</option>)}
              </select>
            </label>
            {rgbFrameTimesFileId && (
              <label className="text-sm">Đơn vị timestamp RGB
                <select value={rgbTimestampUnit} onChange={(event) => { setRgbTimestampUnit(event.target.value as DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                  <option value="">Chưa xác nhận</option><option value="seconds">Giây (s)</option><option value="milliseconds">Mili giây (ms)</option><option value="microseconds">Micro giây (µs)</option><option value="nanoseconds">Nano giây (ns)</option>
                </select>
              </label>
            )}
            {cloudState === "raw_scan_sequence" && (
              <>
                <label htmlFor={ids.lidarTimes} className="text-sm">File có một timestamp cho mỗi scan LiDAR
                  <select id={ids.lidarTimes} value={lidarScanTimesFileId} onChange={(event) => { const fileId = event.target.value; setLidarScanTimesFileId(fileId); if (fileId !== lidarScanTimesFileId) setLidarTimestampUnit(""); if (fileId && fileId === rgbFrameTimesFileId) { setRgbFrameTimesFileId(""); setRgbTimestampUnit(""); } setBindings((current) => current.filter((item) => item.role !== "lidar_scan_times" && !(fileId && fileId === rgbFrameTimesFileId && item.role === "rgb_frame_times"))); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                    <option value="">Chưa gán</option>
                    {timestampFiles.map((file) => <option key={file.file_id} value={file.file_id} disabled={file.file_id === rgbFrameTimesFileId}>{fileNamesById.get(file.file_id) ?? file.file_id}</option>)}
                  </select>
                </label>
                {lidarScanTimesFileId && (
                  <label className="text-sm">Đơn vị timestamp LiDAR
                    <select value={lidarTimestampUnit} onChange={(event) => { setLidarTimestampUnit(event.target.value as DeclarationChoice<"seconds" | "milliseconds" | "microseconds" | "nanoseconds">); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                      <option value="">Chưa xác nhận</option><option value="seconds">Giây (s)</option><option value="milliseconds">Mili giây (ms)</option><option value="microseconds">Micro giây (µs)</option><option value="nanoseconds">Nano giây (ns)</option>
                    </select>
                  </label>
                )}
              </>
            )}
          </div>
          {rgbFrameTimesFileId && (lidarScanTimesFileId || stagedFiles.some((item) => item.observed_format === "tum_trajectory")) && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-sm">Quan hệ đồng hồ giữa video và LiDAR
                <select value={clockRelation} onChange={(event) => { setClockRelation(event.target.value as DeclarationChoice<"same_clock" | "known_offset" | "unknown">); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                  <option value="">Chưa xác nhận</option><option value="same_clock">Cùng đồng hồ</option><option value="known_offset">Biết độ lệch</option><option value="unknown">Không biết</option>
                </select>
              </label>
              {clockRelation === "known_offset" && <label className="text-sm">Độ lệch đồng hồ (giây)
                <input type="number" step="any" value={clockOffset} onChange={(event) => { setClockOffset(event.target.value); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3" />
              </label>}
            </div>
          )}
        </Card>
      )}

      {observedClouds.length > 0 && (
        <Card className="mt-5 p-5 sm:p-6">
          <h2 className="text-base font-bold">Thông tin LiDAR cần khai báo</h2>
          <p className="mt-1 text-sm text-ink-muted">Các giá trị này do bạn khai báo; hệ thống không suy ra đơn vị, scene hoặc frame từ tên file.</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="text-sm">Trạng thái cloud
              <select value={cloudState} onChange={(event) => { const nextCloudState = event.target.value as DeclarationChoice<CloudObservationState>; setCloudState(nextCloudState); if (nextCloudState !== "raw_scan_sequence") { setLidarScanTimesFileId(""); setLidarTimestampUnit(""); } setBindings((current) => current.filter((item) => !["registered_lidar_map", "static_lidar_cloud", "lidar_scan"].includes(item.role) && (nextCloudState === "raw_scan_sequence" || item.role !== "lidar_scan_times"))); setScanOrderConfirmed(false); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                <option value="">Chọn trạng thái</option><option value="registered_map">Map đã đăng ký</option><option value="single_static_cloud">Một cloud quan sát tĩnh</option><option value="raw_scan_sequence">Chuỗi scan thô theo thời gian</option>
              </select>
            </label>
            <label className="text-sm">Đơn vị tọa độ
              <select value={coordinateUnit} onChange={(event) => { setCoordinateUnit(event.target.value as DeclarationChoice<DistanceUnit>); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                <option value="">Chọn đơn vị</option><option value="m">Mét (m)</option><option value="cm">Centimet (cm)</option><option value="mm">Millimet (mm)</option>
              </select>
            </label>
            <label className="text-sm">Tên frame của LiDAR
              <input value={lidarFrameId} onChange={(event) => { setLidarFrameId(event.target.value); invalidateResolution(); }} maxLength={128} placeholder="Ví dụ: lidar" className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3" />
            </label>
            <label className="text-sm">Video và LiDAR có mô tả cùng một scene không?
              <select value={sameScene} onChange={(event) => { setSameScene(event.target.value as "" | "yes" | "no"); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                <option value="">Chưa xác nhận</option><option value="yes">Có, cùng scene quay</option><option value="no">Không, khác scene</option>
              </select>
            </label>
          </div>
          {stagedFiles.some((item) => item.observed_format === "tum_trajectory") && (
            <label className="mt-4 block text-sm">Quỹ đạo TUM biểu diễn frame nào?
              <select value={trajectoryConvention} onChange={(event) => { setTrajectoryConvention(event.target.value as DeclarationChoice<TrajectoryConvention>); invalidateResolution(); }} className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3">
                <option value="">Chọn quy ước</option><option value="world_from_sensor">world_from_sensor (LiDAR)</option><option value="world_from_camera">world_from_camera (camera)</option><option value="unknown">Chưa biết</option>
              </select>
            </label>
          )}
          {cloudState === "raw_scan_sequence" && scanFileNames.length > 1 && (
            <fieldset className="mt-5 rounded-xl border border-line p-4">
              <legend className="px-1 text-sm font-semibold">Thứ tự scan theo thời gian</legend>
              <p className="text-xs text-ink-muted">Danh sách ban đầu theo thứ tự upload, không phải bằng chứng thời gian. Sắp xếp lại nếu cần rồi xác nhận thứ tự thực tế.</p>
              <ol className="mt-3 space-y-2">
                {scanFileNames.map((item, index) => (
                  <li key={item.fileId} className="flex items-center gap-2 rounded-lg border border-line p-2 text-sm">
                    <span className="w-7 shrink-0 font-mono text-xs text-ink-muted">{index + 1}</span><span className="min-w-0 flex-1 break-all">{item.name}</span>
                    <Button type="button" size="icon" variant="ghost" aria-label={`Đưa ${item.name} lên`} disabled={index === 0} onClick={() => moveScan(item.fileId, -1)}><ArrowUp aria-hidden /></Button>
                    <Button type="button" size="icon" variant="ghost" aria-label={`Đưa ${item.name} xuống`} disabled={index === scanFileNames.length - 1} onClick={() => moveScan(item.fileId, 1)}><ArrowDown aria-hidden /></Button>
                  </li>
                ))}
              </ol>
              <label className="mt-3 flex items-start gap-2 text-sm">
                <input type="checkbox" checked={scanOrderConfirmed} onChange={(event) => { setScanOrderConfirmed(event.target.checked); invalidateResolution(); }} className="mt-1 size-4 accent-ember-strong" />
                Tôi đã kiểm tra và xác nhận danh sách trên là thứ tự scan theo thời gian.
              </label>
            </fieldset>
          )}
        </Card>
      )}

      {entries.length > 0 && (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-2xl text-sm text-ink-muted">Hệ thống tự chọn cách xử lý phù hợp từ các file bạn thêm. Sẵn sàng chỉ nghĩa là dữ liệu chạy được, chưa phải kết quả kiểm tra hình học hay va chạm đã đạt.</p>
          <Button onClick={() => void analyze()} disabled={busy || adding || !stagedEntries.length || includedEntries.some((item) => item.status !== "ready") || (hasMixedSceneKinds && !intent)}>
            {busy ? <><Loader2 className="size-4 animate-spin" aria-hidden /> Đang phân tích</> : "Phân tích lại"}
          </Button>
        </div>
      )}

      {notice && <Notice tone="ochre" className="mt-4">{notice}</Notice>}
      {error && <div role="alert" className="mt-4"><Notice tone="rust">{error}</Notice></div>}

      {report && (
        <section className="mt-6 space-y-4" aria-labelledby="resolution-heading">
          <div>
            <h2 id="resolution-heading" className="text-lg font-bold">Kết quả nhận diện và hướng xử lý</h2>
            <p className="mt-1 text-sm text-ink-muted">Kết quả ứng với bộ file hiện tại (lần {report.assembly_revision}); đổi file hoặc khai báo thì hệ thống tự phân tích lại.</p>
          </div>
          {report.state !== "ready" && <Notice tone={report.state === "invalid" ? "rust" : "ochre"}>{report.state === "needs_input" ? "Cần bổ sung lựa chọn hoặc khai báo trước khi tiếp tục." : report.state === "pending_verification" ? "Một hoặc nhiều file vẫn đang chờ xác minh." : report.state === "unsupported" ? "Chưa có runtime đủ điều kiện cho các hướng này." : "Có dữ liệu mâu thuẫn hoặc không hợp lệ; sửa input rồi phân tích lại."}</Notice>}
          {report.missing_facts.length > 0 && (
            <Card className="p-5">
              <h3 className="text-sm font-semibold">Thông tin còn thiếu</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-muted">
                {report.missing_facts.map((fact) => <li key={`${fact.code}:${fact.related_file_ids.join(",")}`}>{describeFact(fact)}</li>)}
              </ul>
            </Card>
          )}
          {report.candidates.length === 0 ? <EmptyState icon={<FileUp aria-hidden />} title="Chưa có cách xử lý phù hợp">Thêm video RGB hoặc sửa file theo các lý do ở trên.</EmptyState> : (
            <div className="grid gap-3">
              {report.candidates.map((candidate) => {
                const recommended = report.recommended_candidate_id === candidate.candidate_id;
                const candidateFileIds = candidate.candidate_kind === "gaussian_view_import"
                  ? [candidate.source_file_id]
                  : candidate.bindings.flatMap((binding) => binding.file_ids);
                const candidateNames = [...new Set(candidateFileIds)].map((id) => fileNamesById.get(id) ?? id);
                const excludedNames = candidate.excluded_file_ids.map((id) => fileNamesById.get(id) ?? id);
                const requiresScanOrder = candidate.candidate_kind === "video_recipe" && candidate.required_facts.some((fact) => fact.code === "SCAN_SEQUENCE_ORDER_REQUIRED");
                const cannotUse = candidate.state === "unsupported" || candidate.state === "invalid" || candidate.state === "pending_verification" || (requiresScanOrder && !scanOrderConfirmed);
                return (
                  <Card key={candidate.candidate_id} className={`p-5 ${recommended ? "border-ember" : ""}`}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{routeName(candidate)}</h3><Badge tone={candidate.state === "ready" ? "sage" : candidate.state === "unsupported" || candidate.state === "invalid" ? "rust" : "ochre"}>{candidateStateLabel(candidate.state)}</Badge></div>
                        {candidate.runtime.status !== "qualified" && (
                          <p className="mt-1 text-xs text-ink-muted">Máy xử lý chưa sẵn sàng cho cách này.</p>
                        )}
                        {candidateNames.length > 0 && <p className="mt-2 text-xs text-ink-muted">Input: {candidateNames.join(" · ")}</p>}
                        {excludedNames.length > 0 && <p className="mt-1 text-xs text-ink-muted">Bỏ qua (không có chỗ dùng): {excludedNames.join(" · ")}</p>}
                      </div>
                      {candidate.state === "needs_input" && <Button size="sm" variant="secondary" onClick={() => void chooseCandidate(candidate)} disabled={busy || cannotUse}>Dùng cách này</Button>}
                    </div>
                    {candidate.required_facts.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-muted">{candidate.required_facts.map((fact) => <li key={`${fact.code}:${fact.related_file_ids.join(",")}`}>{describeFact(fact)}</li>)}</ul>}
                    {candidate.diagnostics.length > 0 && <ul className="mt-3 space-y-1 text-sm">{candidate.diagnostics.map((item) => <li key={item.code} className={item.severity === "error" ? "text-rust" : "text-ink-muted"}>{describeDiagnostic(item)}</li>)}</ul>}
                    <details className="mt-3 text-xs text-ink-muted">
                      <summary className="cursor-pointer">Chi tiết kỹ thuật</summary>
                      <p className="mt-1">Nhóm xử lý: {candidate.candidate_kind === "video_recipe" ? candidate.recipe_group : candidate.source_format} · Runtime: {candidate.runtime.status}{candidate.runtime.reason_codes.length > 0 ? ` (${candidate.runtime.reason_codes.join(" · ")})` : ""}</p>
                    </details>
                  </Card>
                );
              })}
            </div>
          )}

          {report.state === "ready" && activeCandidate && activeCandidate.state === "ready" && (
            <form onSubmit={submitReadyRoute} className="space-y-4">
              <Card className="space-y-4 p-5 sm:p-6">
                <div className="flex items-center gap-2"><Check className="size-4 text-sage" aria-hidden /><h3 className="font-semibold">Đã sẵn sàng tạo scene</h3></div>
                <p className="text-sm text-ink-muted">{routeName(activeCandidate)}. Đây mới là kiểm tra dữ liệu có chạy được, chưa phải kết quả kiểm tra hình học hay an toàn vật lý.</p>
                <label htmlFor={ids.name} className="block text-sm font-medium">Tên scene</label>
                <input id={ids.name} value={sceneName} onChange={(event) => setSceneName(event.target.value)} maxLength={200} required className="h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm" />
                {activeCandidate.candidate_kind === "video_recipe" && (
                  <>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <label htmlFor={ids.owner} className="text-sm">Người/đơn vị sở hữu dữ liệu<input id={ids.owner} value={dataOwner} onChange={(event) => setDataOwner(event.target.value)} maxLength={200} required className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3" /></label>
                      <label htmlFor={ids.origin} className="text-sm">Nguồn dữ liệu<select id={ids.origin} value={dataOrigin} onChange={(event) => setDataOrigin(event.target.value as DataOrigin | "")} required className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3"><option value="">Chọn nguồn</option><option value="self_collected_no_pii">Tự thu thập, không có dữ liệu cá nhân</option><option value="anonymized">Đã ẩn danh</option><option value="public_or_synthetic">Công khai hoặc tổng hợp</option></select></label>
                      <label htmlFor={ids.purpose} className="text-sm sm:col-span-2">Mục đích sử dụng<input id={ids.purpose} value={dataPurpose} onChange={(event) => setDataPurpose(event.target.value)} maxLength={500} required className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3" /></label>
                    </div>
                    <div className="space-y-3 text-sm">
                      <label className="flex items-start gap-2"><input type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} className="mt-1 size-4 accent-ember-strong" />Tôi có quyền sử dụng dữ liệu cho mục đích đã khai báo.</label>
                      <label className="flex items-start gap-2"><input type="checkbox" checked={anonymized} onChange={(event) => setAnonymized(event.target.checked)} className="mt-1 size-4 accent-ember-strong" />Video không có khuôn mặt/biển số hoặc đã được làm mờ trước khi upload.</label>
                      {processing.options?.anonymize_available && <label className="flex items-start gap-2"><input type="checkbox" checked={autoAnonymize || Boolean(processing.options.anonymize_enforced)} disabled={Boolean(processing.options.anonymize_enforced)} onChange={(event) => setAutoAnonymize(event.target.checked)} className="mt-1 size-4 accent-ember-strong" /><span>Tự động che khuôn mặt và biển số trước khi dựng 3D.<span className="mt-0.5 block text-xs text-ink-muted">Lớp bảo vệ thêm: bộ phát hiện có thể bỏ sót, nên vẫn cần xác nhận ở dòng trên. Vùng bị che sẽ hiện thành mảng đen trong scene.{processing.options.anonymize_enforced ? " Máy xử lý này luôn bật bước che." : ""}</span></span></label>}
                      <label className="flex items-start gap-2"><input type="checkbox" checked={retention} onChange={(event) => setRetention(event.target.checked)} className="mt-1 size-4 accent-ember-strong" />Tôi hiểu dữ liệu và kết quả được lưu để xử lý scene.</label>
                    </div>
                    {processing.options && processing.values && <ProcessingSettings parameters={processing.options.parameters} values={processing.values} editable evaluation={processing.evaluation} capability={processing.options.capability} activePreset={processing.activePreset} onPreset={processing.applyPreset} onChange={processing.setValue} note={processing.options.resource_note} />}
                    {processing.error && <Notice tone={processing.options ? "rust" : "ochre"}>{processing.error} {!processing.options && "Server sẽ dùng cấu hình mặc định."}<Button type="button" size="sm" variant="secondary" onClick={processing.retry}>Thử lại</Button></Notice>}
                    {guestQuotaEmpty && <Notice tone="ochre">Đã dùng hết 3 lượt Guest hôm nay; quota reset lúc 00:00 giờ Việt Nam.</Notice>}
                  </>
                )}
                {activeCandidate.candidate_kind === "gaussian_view_import" && <p className="text-sm text-ink-muted">Import chỉ đưa scene 3DGS vào viewer hiện tại. Chưa có luồng xử lý tiếp scene đã import.</p>}
                {createBlockers.length > 0 && (
                  <div className="rounded-lg border border-line p-3 text-sm text-ink-muted" role="status">
                    <p className="font-medium text-ink">Còn thiếu để tạo scene:</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5">{createBlockers.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                )}
                <Button type="submit" disabled={submitting || createBlockers.length > 0}>
                  {submitting ? <><Loader2 className="size-4 animate-spin" aria-hidden /> Đang gửi</> : activeCandidate.candidate_kind === "gaussian_view_import" ? "Mở scene 3DGS" : <><Play className="size-4" aria-hidden /> Tạo scene</>}
                </Button>
              </Card>
            </form>
          )}
        </section>
      )}
    </main>
  );
}
