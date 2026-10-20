import type { StageAction } from "@/features/studio/PipelineTimeline";
import type { StageId } from "@/lib/contracts/api";
import type { PipelineView } from "@/lib/contracts/pipeline";

/** Hành động người dùng làm được; handler vắng (không có quyền) thì không có nút. */
export interface StepActionHandlers {
  confirmMetric?: () => void;
  openStudio?: () => void;
  showAnonymization?: () => void;
  retryJob?: () => void;
  retryGeometry?: () => void;
  cancelOperation?: () => void;
  rerunObjectify?: () => void;
  useBoxes?: () => void;
}

export interface StepActionOptions {
  retryDisabled?: boolean;
  retryHint?: string;
}

/**
 * Mọi nút ở dòng tiến trình (T-061), tính từ `next_action` của backend: một quy tắc duy nhất, gắn vào đúng bước.
 * "Dùng hộp ứng viên" chỉ hiện khi tách vật cần người chọn cách xử lý.
 */
export function stepActions(view: PipelineView, handlers: StepActionHandlers, busy: boolean, options: StepActionOptions = {}): StageAction[] {
  const actions: StageAction[] = [];
  const add = (stageId: StageId, label: string, onClick: (() => void) | undefined, extra: Partial<StageAction> = {}) => {
    if (onClick) actions.push({ stageId, label, onClick, disabled: busy, ...extra });
  };
  const action = view.next_action;
  switch (action.kind) {
    case "confirm_metric":
      add("ST-METRIC-CANONICALIZE", "Xác nhận tỉ lệ mét", handlers.confirmMetric);
      break;
    case "review_anonymization":
      add("ST-ANONYMIZATION-REVIEW", "Xem bản đã che", handlers.showAnonymization);
      break;
    case "retry_job": {
      const stage = view.progress.error?.stage_id;
      if (stage) add(stage, "Thử lại", handlers.retryJob, { disabled: busy || options.retryDisabled, hint: options.retryHint });
      break;
    }
    case "review_objects":
      add("ST-OBJECT-CONFIRM", "Mở để duyệt", handlers.openStudio);
      break;
    case "confirm_objects":
      add("ST-OBJECT-CONFIRM", "Xác nhận vật", handlers.openStudio);
      break;
    case "retry_geometry":
      add("ST-SCENE-DECOMPOSE", "Mở để sửa vùng", handlers.openStudio);
      add("ST-SCENE-DECOMPOSE", "Thử lại Tạo mesh", handlers.retryGeometry);
      break;
    case "choose_object_method":
      if (view.objectify?.available && view.objectify.retryable !== false) {
        add("ST-OBJECT-EXTRACT", "Chạy lại tách theo vật", handlers.rerunObjectify);
      }
      add("ST-OBJECT-EXTRACT", "Dùng hộp ứng viên", handlers.useBoxes);
      break;
    default:
      break;
  }
  // Việc nền của hàng đợi tách vật (Tạo mesh, sửa vùng, tách lại) đang xếp hàng hoặc chạy: cho hủy.
  const cancellable = view.steps.find(
    (item) => (item.step_id === "ST-SCENE-DECOMPOSE" || item.step_id === "ST-OBJECT-EXTRACT") && (item.state === "running" || item.state === "queued"),
  );
  const target = cancellable?.step_id ?? (view.wait?.kind === "scene_operation" ? "ST-SCENE-DECOMPOSE" : null);
  if (target && !view.objectify?.cancellation_requested) add(target, "Hủy yêu cầu", handlers.cancelOperation);
  return actions;
}
