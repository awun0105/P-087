/**
 * Một bảng câu chữ cho "việc tiếp theo" (T-062): chuông, banner, thông báo trong Studio, nhãn đầu trang và danh sách scene
 * cùng đọc từ đây, theo `next_action` mà backend tính bằng một hàm duy nhất.
 */
import type { SceneStatusView } from "@/features/studio/sceneStatus";
import type { StudioMode, Tab } from "@/features/studio/scene/state";
import type { GpuCapacity } from "@/lib/api/gpu";
import type { ObjectifyMode } from "@/lib/api/studio";
import type { NextAction, NextActionKind, PipelineWait } from "@/lib/contracts/pipeline";
import type { JobProgress } from "@/lib/contracts/studio";

type WaitingFor = NonNullable<JobProgress["waiting_for"]>;
import { geometryPhaseLabel } from "@/lib/scene/geometry-state";

export interface NextActionView {
  title: string;
  description: string;
  /** Nút đưa người dùng tới đúng chỗ làm việc; null khi không cần thao tác. */
  target: { tab: Tab; mode?: StudioMode; label: string } | null;
  status: SceneStatusView;
}

export interface NextActionContext {
  wait: PipelineWait | null;
  waitingFor: WaitingFor | null;
  objectifyMode: ObjectifyMode | null;
  phase: string | null;
  /** Tên ngắn của bước đang chạy (vd. "Camera"), dùng cho nhãn "Đang chạy · …". */
  currentStepShort: string | null;
  isReviewer: boolean;
  gpu: GpuCapacity | null;
  now: number;
}

const OPERATION_LABEL: Record<ObjectifyMode, string> = {
  geometry: "Đang tạo mesh",
  region: "Đang dựng lại vùng",
  membership: "Đang dựng lại vùng",
  objectify: "Đang tách lại vật thể",
  boxes: "Đang dựng hộp ứng viên",
};

export function operationLabel(mode: ObjectifyMode): string {
  return OPERATION_LABEL[mode];
}

const ACTION = (label: string, tone: SceneStatusView["tone"] = "ochre"): SceneStatusView => ({ label, tone, active: false, group: "action" });
const RUNNING = (label: string, tone: SceneStatusView["tone"] = "ember"): SceneStatusView => ({ label, tone, active: true, group: "running" });

type Row = (action: NextAction, ctx: NextActionContext) => Omit<NextActionView, "status"> & { status?: SceneStatusView };

function minutesLeft(gpu: GpuCapacity, now: number): number | null {
  if (!gpu.since) return null;
  const elapsed = Math.max(0, (now - Date.parse(gpu.since)) / 1000);
  return Math.max(1, Math.ceil((gpu.expected_startup_seconds - elapsed) / 60));
}

function systemWait(action: NextAction, ctx: NextActionContext): NextActionView {
  if (ctx.wait?.kind === "scene_operation" || (ctx.objectifyMode && action.step_id === "ST-SCENE-DECOMPOSE")) {
    const label = ctx.objectifyMode ? operationLabel(ctx.objectifyMode) : "Đang tạo mesh";
    return { title: label, description: geometryPhaseLabel(ctx.phase) ?? "Đang xếp hàng.", target: { tab: "progress", label: "Xem tiến trình" }, status: RUNNING(label) };
  }
  if (action.step_id === "ST-OBJECT-EXTRACT" && ctx.objectifyMode) {
    const label = operationLabel(ctx.objectifyMode);
    return { title: label, description: geometryPhaseLabel(ctx.phase) ?? "Đang xếp hàng.", target: { tab: "progress", label: "Xem tiến trình" }, status: RUNNING(label) };
  }
  const waitingMachine = ctx.waitingFor === "resources" || ctx.waitingFor === "runtime" || ctx.wait?.kind === "queue";
  if (waitingMachine && ctx.gpu && (ctx.gpu.state === "off" || ctx.gpu.state === "starting")) {
    const left = minutesLeft(ctx.gpu, ctx.now);
    return {
      title: "Đang khởi động máy GPU",
      description: left !== null ? `Máy GPU đang được bật, còn khoảng ${left} phút. Job tự chạy khi máy sẵn sàng.` : "Máy GPU đang được bật. Job tự chạy khi máy sẵn sàng.",
      target: { tab: "progress", label: "Xem tiến trình" },
      status: RUNNING("Đang khởi động máy GPU", "ochre"),
    };
  }
  if (ctx.waitingFor === "resources") {
    return { title: "Đang chờ tài nguyên", description: "Giữ nguyên cấu hình đã chọn. Máy xử lý tự chạy tiếp khi đủ tài nguyên; có thể rời trang hoặc huỷ job.", target: null, status: RUNNING("Đang chờ tài nguyên", "ochre") };
  }
  if (ctx.waitingFor === "runtime") {
    return { title: "Đang chờ GPU", description: "Chưa có máy xử lý đúng phiên bản công cụ của job. Job tự chạy khi máy đó lên.", target: null, status: RUNNING("Đang chờ GPU", "ochre") };
  }
  if (ctx.wait?.kind === "queue" || action.step_id === null && !ctx.currentStepShort) {
    return { title: "Đang chờ worker", description: "Job đã vào hàng đợi. Theo dõi các giai đoạn ở tab Tiến trình.", target: null, status: RUNNING("Đang chờ worker", "ochre") };
  }
  // Máy chỉ đang chạy bình thường: không có gì cần người dùng chú ý (chuông trống), nhãn đầu trang vẫn nói đang chạy.
  const label = ctx.currentStepShort ? `Đang chạy · ${ctx.currentStepShort}` : "Đang xử lý";
  return { title: "", description: "", target: null, status: RUNNING(label) };
}

const ROWS: Record<Exclude<NextActionKind, "wait_system">, Row> = {
  review_anonymization: () => ({
    title: "Cần bạn xem bản đã che",
    description: "Khuôn mặt và biển số phát hiện được đã bị che. Xem lại rồi xác nhận để pipeline dựng 3D, hoặc huỷ job.",
    target: { tab: "progress", label: "Xem bản đã che" },
    status: ACTION("Cần xem bản đã che"),
  }),
  confirm_metric: () => ({
    title: "Cần bạn xác nhận tỉ lệ mét",
    description: "Chọn điểm và nhập kích thước thật để pipeline tiếp tục.",
    target: { tab: "studio", mode: "metric", label: "Xác nhận tỉ lệ mét" },
    status: ACTION("Cần xác nhận tỉ lệ"),
  }),
  retry_job: () => ({
    title: "Xử lý chưa hoàn tất",
    description: "Xem nguyên nhân ở giai đoạn lỗi. Sau khi xử lý được nguyên nhân, có thể chạy lại.",
    target: { tab: "progress", label: "Xem bước lỗi" },
    status: { label: "Lỗi · có thể thử lại", tone: "rust", active: false, group: "failed" },
  }),
  job_failed: () => ({
    title: "Xử lý chưa hoàn tất",
    description: "Lỗi của lần chạy này cần được khắc phục trước; chưa thể chạy lại.",
    target: { tab: "progress", label: "Xem bước lỗi" },
    status: { label: "Lỗi", tone: "rust", active: false, group: "failed" },
  }),
  job_cancelled: () => ({
    title: "Đã huỷ xử lý",
    description: "Kết quả đã có vẫn được giữ; mở giai đoạn hoàn tất để xem.",
    target: null,
    status: { label: "Đã huỷ", tone: "neutral", active: false, group: "idle" },
  }),
  retry_geometry: () => ({
    title: "Tạo mesh chưa xong",
    description: "Chỉnh vùng nếu cần rồi thử lại Tạo mesh.",
    target: { tab: "studio", mode: "scene", label: "Mở để sửa vùng" },
    status: { label: "Tạo mesh lỗi", tone: "rust", active: false, group: "action" },
  }),
  review_objects: (action) => ({
    title: "Duyệt vật rồi Tạo mesh",
    description: action.pending_count
      ? `${action.pending_count} vật chờ xác nhận. Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio.`
      : "Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio.",
    target: { tab: "studio", mode: "scene", label: "Mở để duyệt" },
    status: ACTION("Chờ duyệt vật"),
  }),
  choose_object_method: () => ({
    title: "Tách theo vật chưa thành công",
    description: "Chạy lại tách theo vật hoặc dùng hộp ứng viên ngay tại bước “Tách vật thể”.",
    target: { tab: "progress", label: "Xem bước tách vật thể" },
    status: ACTION("Cần chọn cách tách vật thể"),
  }),
  confirm_objects: (action) => ({
    title: "Cần xác nhận vật thể",
    description: `${action.pending_count ?? 0} ứng viên chưa được xác nhận.`,
    target: { tab: "studio", mode: "scene", label: "Xác nhận vật thể" },
    status: ACTION("Cần xác nhận vật thể"),
  }),
  scene_ready: () => ({
    title: "Scene đã dựng xong",
    description: "Xác nhận vật, tạo gói mô phỏng và gửi duyệt ở các tab Studio và Kiểm tra & duyệt.",
    target: null,
    status: { label: "Đã dựng scene", tone: "sage", active: false, group: "done" },
  }),
  released: () => ({
    title: "Đã có bản phát hành",
    description: "Tải đúng gói đã được kiểm tra và duyệt.",
    target: { tab: "results", label: "Xem kết quả" },
    status: { label: "Đã phát hành", tone: "sage", active: false, group: "done" },
  }),
  await_review: (_action, ctx) => ({
    title: "Đạt kiểm tra — chờ duyệt",
    description: ctx.isReviewer ? "Kiểm tra bằng chứng trước khi quyết định." : "Reviewer sẽ quyết định trên đúng gói của revision này.",
    target: { tab: "review", label: "Xem kiểm tra & duyệt" },
    status: ACTION("Chờ duyệt", "ochre"),
  }),
  review_package: () => ({
    title: "Đã có gói mô phỏng",
    description: "Gói candidate có thể tải; bản phát hành cần kiểm định và Reviewer duyệt.",
    target: { tab: "review", label: "Xem kiểm tra & duyệt" },
    status: { label: "Đã có gói", tone: "sage", active: false, group: "done" },
  }),
  fix_preflight: () => ({
    title: "Cần sửa theo preflight",
    description: "Tạo gói và đọc preflight ở Kiểm tra & duyệt.",
    target: { tab: "review", label: "Mở tạo gói mô phỏng" },
    status: ACTION("Cần sửa preflight"),
  }),
  create_package: () => ({
    title: "Sẵn sàng tạo gói",
    description: "Tạo gói và đọc preflight ở Kiểm tra & duyệt.",
    target: { tab: "review", label: "Mở tạo gói mô phỏng" },
    status: { label: "Đã dựng scene", tone: "sage", active: false, group: "done" },
  }),
};

export function nextActionView(action: NextAction, ctx: NextActionContext): NextActionView {
  if (action.kind === "wait_system") return systemWait(action, ctx);
  const row = ROWS[action.kind](action, ctx);
  return { ...row, status: row.status ?? ACTION(row.title) };
}
