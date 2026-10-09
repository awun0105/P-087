"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/features/studio/AuthProvider";
import { errorMessage } from "@/lib/ui-error";
import {
  cancelRegistrationOperation,
  enqueueRegistration,
  getRegistrationOperation,
  getRegistrationOperationInspection,
  isRegistrationOperationActive,
  isRegistrationOperationPollable,
  parseRegistrationRequest,
  prepareRegistration,
  type RegistrationFinding,
  type RegistrationOperationInspection,
  type RegistrationOperation,
  type RegistrationPreflight,
  type RegistrationRequestPayload,
  type JsonObject,
  type JsonValue,
} from "@/lib/api/registration";
import { usePolling } from "@/features/studio/usePolling";

interface SavedRegistration {
  version: 1;
  expected_scene_revision: string;
  request?: RegistrationRequestPayload;
  operation_id?: string;
}

interface RegistrationSession extends SavedRegistration {
  operation: RegistrationOperation | null;
}

const FINDING_LABELS: Record<RegistrationFinding, string> = {
  SOURCE_FORMAT_REQUIRED: "Cần file point cloud PCD hoặc PLY đã nhận dạng.",
  SOURCE_HEADER_REQUIRED: "Không đọc được header point cloud hợp lệ.",
  SOURCE_UNITS_REQUIRED: "Cần khai báo đơn vị tọa độ LiDAR.",
  SOURCE_FRAME_REQUIRED: "Cần khai báo hệ tọa độ của bản đồ LiDAR.",
  SAME_SCENE_CONTEXT_MISSING: "Chưa có khai báo hai nguồn cùng mô tả một scene.",
  DIFFERENT_SCENE: "Khai báo input cho biết bản đồ LiDAR thuộc scene khác.",
  EMPTY_CLOUD: "Point cloud không có điểm hợp lệ.",
  POINT_COUNT_UNAVAILABLE: "Không xác định được số điểm trong point cloud.",
  POINT_BUDGET_EXCEEDED: "Point cloud vượt giới hạn xử lý hiện tại.",
  RAW_SCANS_REQUIRE_TRAJECTORY: "Chuỗi scan thô cần quỹ đạo LiDAR; luồng này chỉ nhận map tĩnh.",
  METRIC_SCALE_UNKNOWN: "Scene RGB chưa có tỉ lệ mét được xác nhận.",
  FLOOR_UNSUPPORTED: "Chưa có bằng chứng mặt sàn phù hợp.",
  FLOOR_UNCERTAIN: "Bằng chứng mặt sàn chưa chắc chắn.",
  TARGET_FLOOR_EVIDENCE_REQUIRED: "Cần bằng chứng mặt sàn của scene RGB.",
  LOW_OVERLAP: "Phần chồng lấp giữa hai bản đồ có thể quá nhỏ.",
  LOW_COVERAGE: "Độ phủ hình học có thể chưa đủ.",
  HIGH_RESIDUAL: "Sai số khớp hình học có thể vượt ngưỡng.",
  AMBIGUOUS_CANDIDATES: "Có thể có nhiều phương án căn chỉnh tương đương.",
  UNOBSERVABLE: "Hình học hiện có không xác định được phép căn chỉnh.",
  SEARCH_BUDGET_EXCEEDED: "Tìm kiếm vượt ngân sách xử lý hiện tại.",
  ICP_NOT_CONVERGED: "Bước tinh chỉnh ICP chưa hội tụ.",
  STALE_TARGET: "Scene đã thay đổi; cần kiểm tra lại revision mới nhất.",
  UNQUALIFIED_PROFILE: "Profile căn chỉnh chưa được qualification trên dữ liệu held-out.",
  METRIC_CONFIRMATION_REQUIRED: "Cần xác nhận tỉ lệ mét trước khi kiểm tra chất lượng.",
};

const OPERATION_LABELS: Record<RegistrationOperation["state"], string> = {
  REQUESTED: "Đã nhận yêu cầu",
  QUEUED: "Đang chờ xử lý",
  RUNNING: "Đang căn chỉnh",
  WAITING_RESOURCES: "Đang chờ tài nguyên",
  PROPOSED: "Có đề xuất cần kiểm tra",
  AMBIGUOUS: "Có nhiều phương án, chưa thể chọn",
  INSUFFICIENT: "Chưa đủ bằng chứng để đề xuất",
  FAILED: "Căn chỉnh thất bại",
  REVIEWED: "Đã kiểm tra",
  CONFIRMED: "Đã xác nhận",
  COMMITTED: "Đã áp dụng",
  CANCELLED: "Đã hủy",
};

function storageKey(jobId: string, userId: string): string {
  return `real2sim:rgb-lidar-registration:v1:${encodeURIComponent(userId)}:${encodeURIComponent(jobId)}`;
}

function readSavedRegistration(key: string, jobId: string, userId: string): SavedRegistration | null {
  try {
    const text = window.sessionStorage.getItem(key);
    if (!text) return null;
    const value: unknown = JSON.parse(text);
    if (
      typeof value !== "object" || value === null || Array.isArray(value)
      || !("version" in value) || value.version !== 1
      || !("expected_scene_revision" in value) || typeof value.expected_scene_revision !== "string"
    ) return null;
    const record = value as Record<string, unknown>;
    const request = record.request === undefined ? undefined : parseRegistrationRequest(record.request);
    const operationId = record.operation_id;
    if (request && (request.target_job_id !== jobId || request.requested_by !== userId)) return null;
    if (operationId !== undefined && typeof operationId !== "string") return null;
    if (!request && !operationId) return null;
    return {
      version: 1,
      expected_scene_revision: value.expected_scene_revision,
      ...(request ? { request } : {}),
      ...(typeof operationId === "string" ? { operation_id: operationId } : {}),
    };
  } catch {
    return null;
  }
}

function persistRegistration(key: string, saved: SavedRegistration): boolean {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(saved));
    return true;
  } catch {
    return false;
  }
}

function clearRegistration(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Browser storage can be disabled; the in-memory flow still works.
  }
}

function jsonObject(value: JsonValue | undefined): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

function vectorText(value: JsonValue | undefined, length: number): string | null {
  if (!Array.isArray(value) || value.length !== length) return null;
  const numbers: number[] = [];
  for (const part of value) {
    if (typeof part !== "number" || !Number.isFinite(part)) return null;
    numbers.push(part);
  }
  return numbers.map((part) => part.toFixed(3)).join(", ");
}

function ratioText(value: JsonValue | undefined): string | null {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : null;
}

function metersText(value: JsonValue | undefined): string | null {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(3)} m` : null;
}

function numberText(value: JsonValue | undefined): string | null {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : null;
}

function integerText(value: JsonValue | undefined): string | null {
  return typeof value === "number" && Number.isInteger(value) ? String(value) : null;
}

interface RegistrationInspectionState {
  key: string;
  loading: boolean;
  data?: RegistrationOperationInspection;
  error?: string;
}

export function RegistrationPanel({
  jobId,
  sceneRevision,
  canMutateJob,
}: {
  jobId: string;
  sceneRevision: string;
  canMutateJob: boolean;
}) {
  const { me } = useAuth();
  const userId = me?.user?.user_id ?? null;
  const key = userId ? storageKey(jobId, userId) : null;
  const [session, setSession] = useState<RegistrationSession | null>(null);
  const [preflight, setPreflight] = useState<RegistrationPreflight | null>(null);
  const [inspectionState, setInspectionState] = useState<RegistrationInspectionState>({ key: "", loading: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null | undefined>(undefined);
  const [storageUnavailable, setStorageUnavailable] = useState(false);
  const [recoverPending, setRecoverPending] = useState(false);
  const recoveryStarted = useRef(new Set<string>());

  const loaded = loadedKey === key;
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      const saved = key && userId ? readSavedRegistration(key, jobId, userId) : null;
      if (!active) return;
      setSession(saved ? { ...saved, operation: null } : null);
      setPreflight(null);
      setRecoverPending(saved?.request !== undefined && saved.operation_id === undefined);
      setStorageUnavailable(false);
      setLoadedKey(key);
    });
    return () => { active = false; };
  }, [jobId, key, userId]);

  const submit = useCallback(async (request: RegistrationRequestPayload) => {
    if (!userId || !key || request.target_job_id !== jobId || request.requested_by !== userId) {
      setError("Yêu cầu căn chỉnh không thuộc user hoặc scene hiện tại.");
      return;
    }
    if (request.expected_scene_revision !== sceneRevision) {
      setError("Scene đã đổi revision. Hãy kiểm tra lại dữ liệu trước khi chạy.");
      return;
    }
    setBusy(true);
    setError(null);
    const pending: SavedRegistration = {
      version: 1,
      expected_scene_revision: request.expected_scene_revision,
      request,
    };
    if (!persistRegistration(key, pending)) setStorageUnavailable(true);
    setSession({ ...pending, operation: null });
    try {
      const operation = await enqueueRegistration(jobId, request);
      const accepted: SavedRegistration = {
        version: 1,
        expected_scene_revision: request.expected_scene_revision,
        operation_id: operation.operation_id,
      };
      if (!persistRegistration(key, accepted)) setStorageUnavailable(true);
      setSession({ ...accepted, operation });
      setPreflight(null);
      setError(null);
      setRecoverPending(false);
    } catch (cause) {
      if (cause instanceof ApiError && cause.isClientError) {
        clearRegistration(key);
        setSession(null);
        setPreflight(null);
      }
      setError(errorMessage(cause, "Chưa xác nhận được yêu cầu căn chỉnh."));
    } finally {
      setBusy(false);
    }
  }, [jobId, key, sceneRevision, userId]);

  useEffect(() => {
    const request = session?.request;
    if (!loaded || !recoverPending || !request || !canMutateJob || !userId || request.expected_scene_revision !== sceneRevision) return;
    if (recoveryStarted.current.has(request.request_id)) return;
    recoveryStarted.current.add(request.request_id);
    setRecoverPending(false);
    void submit(request);
  }, [canMutateJob, loaded, recoverPending, sceneRevision, session?.request, submit, userId]);

  const operationId = session?.operation_id ?? null;
  const operation = session?.operation ?? null;
  const poll = useCallback(async (signal: AbortSignal) => {
    if (!operationId) return;
    const result = await getRegistrationOperation(jobId, operationId, signal);
    if (signal.aborted) return;
    if (!result.ok) {
      setError(errorMessage(result.error, "Không đọc được trạng thái căn chỉnh."));
      return;
    }
    setError(null);
    setSession((current) => current?.operation_id === operationId ? { ...current, operation: result.data } : current);
  }, [jobId, operationId]);
  const operationPollable = operation === null || isRegistrationOperationPollable(operation.state);
  const pendingOperation = Boolean(operationId && operationPollable);
  usePolling(poll, 3000, Boolean(operationId && operationPollable), operationId);

  const inspectionOutputKey = operation
    ? JSON.stringify([operation.proposal_ref, operation.qa_report_ref])
    : "";
  const hasInspectionOutput = Boolean(operation && (operation.proposal_ref || operation.qa_report_ref));
  const inspectionRequestKey = operationId && hasInspectionOutput
    ? `${jobId}:${operationId}:${inspectionOutputKey}`
    : "";
  useEffect(() => {
    if (!operationId || !inspectionRequestKey) return;
    const controller = new AbortController();
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setInspectionState({ key: inspectionRequestKey, loading: true });
      try {
        const result = await getRegistrationOperationInspection(jobId, operationId, controller.signal);
        if (!active || controller.signal.aborted) return;
        if (!result.ok) {
          setInspectionState({
            key: inspectionRequestKey,
            loading: false,
            error: errorMessage(result.error, "Không đọc được proposal và báo cáo QA."),
          });
        } else {
          setInspectionState({ key: inspectionRequestKey, loading: false, data: result.data });
        }
      } catch (cause) {
        if (active && !controller.signal.aborted) {
          setInspectionState({
            key: inspectionRequestKey,
            loading: false,
            error: errorMessage(cause, "Không đọc được proposal và báo cáo QA."),
          });
        }
      }
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [inspectionRequestKey, jobId, operationId]);
  const currentInspectionState = inspectionState.key === inspectionRequestKey ? inspectionState : null;
  const inspection = currentInspectionState?.data ?? null;

  async function prepare() {
    if (!key || !userId || !canMutateJob || busy) return;
    setBusy(true);
    setError(null);
    setSession(null);
    setPreflight(null);
    setRecoverPending(false);
    clearRegistration(key);
    try {
      const prepared = await prepareRegistration(jobId, sceneRevision);
      if (prepared.request.requested_by !== userId) {
        throw new ApiError(502, "Backend trả request registration cho user khác");
      }
      setPreflight(prepared.preflight);
      if (prepared.preflight.state === "READY") {
        setSession({
          version: 1,
          expected_scene_revision: sceneRevision,
          request: prepared.request,
          operation: null,
        });
      }
    } catch (cause) {
      setError(errorMessage(cause, "Không kiểm tra được dữ liệu căn chỉnh."));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!operationId || !canMutateJob || busy || !operation || !isRegistrationOperationActive(operation.state)) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await cancelRegistrationOperation(jobId, operationId);
      setSession((current) => current?.operation_id === operationId ? { ...current, operation: updated } : current);
    } catch (cause) {
      setError(errorMessage(cause, "Không hủy được yêu cầu căn chỉnh."));
    } finally {
      setBusy(false);
    }
  }

  const stale = session !== null && session.expected_scene_revision !== sceneRevision;
  const canStart = canMutateJob && Boolean(userId) && !busy && !operationId && !stale
    && preflight?.state === "READY" && session?.request !== undefined
    && session.request.requested_by === userId
    && session.request.target_job_id === jobId
    && session.request.expected_scene_revision === sceneRevision;

  return (
    <div className="space-y-3 p-4" aria-labelledby="registration-panel-title">
      <div>
        <h3 id="registration-panel-title" className="text-base font-semibold">Căn chỉnh map LiDAR với scene RGB</h3>
        <p className="mt-1 text-sm text-ink-muted">
          Kiểm tra dữ liệu đã nhận và tạo một đề xuất căn chỉnh. Thao tác này chưa thay đổi scene hoặc collision mesh.
        </p>
      </div>
      {!canMutateJob && <Notice>Scene này ở chế độ chỉ xem; bạn không thể chạy hoặc hủy registration.</Notice>}
      {canMutateJob && !userId && <Notice>Đăng nhập để chuẩn bị registration bền vững.</Notice>}
      {stale && <Notice tone="ochre">Yêu cầu gắn với revision {session.expected_scene_revision}; revision hiện tại là {sceneRevision}. Hãy kiểm tra lại trước khi chạy.</Notice>}
      {storageUnavailable && <Notice tone="ochre">Trình duyệt không lưu được yêu cầu trong phiên. Nếu tải lại trang, cần kiểm tra dữ liệu và tạo yêu cầu mới.</Notice>}
      {error && <div role="alert"><Notice tone="rust">{error}</Notice></div>}
      {preflight?.state === "INSUFFICIENT" && (
        <div role="status">
          <Notice tone="ochre">
            <p className="font-medium">Chưa thể chạy registration.</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {preflight.findings.map((finding) => <li key={finding}>{FINDING_LABELS[finding]}</li>)}
            </ul>
          </Notice>
        </div>
      )}
      {preflight?.state === "READY" && !operationId && session?.request && (
        <div role="status"><Notice tone="neutral">Dữ liệu đạt preflight cho profile hiện tại. Kết quả vẫn cần được kiểm tra trước khi áp dụng.</Notice></div>
      )}
      {operation && (
        <div role="status">
          <Notice tone={operation.state === "FAILED" ? "rust" : operation.state === "PROPOSED" ? "ochre" : "neutral"}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={operation.state === "PROPOSED" ? "ochre" : operation.state === "FAILED" ? "rust" : "neutral"}>
                  {OPERATION_LABELS[operation.state]}
                </Badge>
                <span className="text-sm">Lần chạy {operation.attempt}</span>
              </div>
              {canMutateJob && isRegistrationOperationActive(operation.state) && (
                <Button variant="secondary" size="sm" disabled={busy || operation.cancellation_requested} onClick={() => void cancel()}>
                  {operation.cancellation_requested ? "Đang chờ xác nhận hủy" : "Hủy căn chỉnh"}
                </Button>
              )}
            </div>
            {operation.state === "PROPOSED" && (
              <p className="mt-2 text-sm">Đã có proposal{operation.qa_report_ref ? " và báo cáo QA" : ""}. Chưa có transform nào được áp dụng.</p>
            )}
            {operation.state === "AMBIGUOUS" && <p className="mt-2 text-sm">Cần xem các phương án và bằng chứng trước khi chọn.</p>}
            {operation.cancellation_requested && operation.state !== "CANCELLED" && (
              <p className="mt-2 text-sm">Worker sẽ dừng an toàn rồi mới xác nhận hủy.</p>
            )}
            {stale && <p className="mt-2 text-sm">Kết quả này gắn với revision cũ và không thể áp dụng cho revision hiện tại.</p>}
          </Notice>
        </div>
      )}
      {operation && hasInspectionOutput && (
        <section className="space-y-3 border-t border-line pt-3" aria-label="Chi tiết proposal và QA">
          <h4 className="text-sm font-semibold">Chi tiết proposal và QA</h4>
          {currentInspectionState?.loading && <p className="text-sm text-ink-muted" role="status">Đang kiểm tra artifact và checksum…</p>}
          {currentInspectionState?.error && <div role="alert"><Notice tone="rust">{currentInspectionState.error}</Notice></div>}
          {inspection && (
            <div className="space-y-3">
              {inspection.current_scene_revision === null ? (
                <Notice tone="ochre">Không xác minh được revision scene hiện tại; chỉ xem kết quả đã lưu.</Notice>
              ) : inspection.current_scene_revision !== inspection.expected_scene_revision ? (
                <Notice tone="ochre">
                  Proposal thuộc revision {inspection.expected_scene_revision}; scene hiện tại là {inspection.current_scene_revision}.
                </Notice>
              ) : null}
              {inspection.proposal && (
                <div className="space-y-2 rounded-lg border border-line bg-paper-sunken p-3">
                  <p className="text-sm font-medium">Proposal: {String(inspection.proposal.state ?? "unknown")}</p>
                  {Array.isArray(inspection.proposal.candidates) && inspection.proposal.candidates.map((value, index) => {
                    const candidate = jsonObject(value);
                    if (!candidate) return null;
                    const transform = jsonObject(candidate.transform_target_from_source);
                    const candidateId = typeof candidate.candidate_id === "string" ? candidate.candidate_id : `candidate-${index + 1}`;
                    const parent = typeof transform?.parent_frame === "string" ? transform.parent_frame : "world";
                    const local = typeof transform?.local_frame === "string" ? transform.local_frame : "LiDAR map";
                    const rgbScaleFactor = numberText(candidate.rgb_scale_factor);
                    return (
                      <div key={candidateId} className="border-t border-line pt-2 text-sm">
                        <p className="font-medium">{candidateId} · điểm xếp hạng {numberText(candidate.score) ?? "không có"}</p>
                        <p className="text-ink-muted">Transform: T_{parent}_from_{local}</p>
                        {transform && <p className="text-ink-muted">Dịch chuyển xyz (m): {vectorText(transform.translation_xyz, 3) ?? "không có"}</p>}
                        {transform && <p className="text-ink-muted">Quaternion xyzw: {vectorText(transform.rotation_quaternion_xyzw, 4) ?? "không có"}</p>}
                        {rgbScaleFactor !== null && <p className="text-ink-muted">Giả thuyết scale RGB: {rgbScaleFactor}×</p>}
                      </div>
                    );
                  })}
                  {Array.isArray(inspection.proposal.findings) && inspection.proposal.findings.length > 0 && (
                    <ul className="list-disc pl-5 text-sm text-ink-muted">
                      {inspection.proposal.findings.map((finding, index) => <li key={`${String(finding)}-${index}`}>{String(finding)}</li>)}
                    </ul>
                  )}
                </div>
              )}
              {inspection.qa_report && (
                <div className="space-y-2 rounded-lg border border-line bg-paper-sunken p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">QA:</span>
                    <Badge tone={inspection.qa_report.result === "PASS" ? "sage" : inspection.qa_report.result === "FAIL" ? "rust" : "ochre"}>
                      {String(inspection.qa_report.result ?? "unknown")}
                    </Badge>
                  </div>
                  <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
                    {([
                      ["Độ phủ nguồn", ratioText(inspection.qa_report.source_coverage_ratio)],
                      ["Độ phủ RGB", ratioText(inspection.qa_report.target_coverage_ratio)],
                      ["Overlap", ratioText(inspection.qa_report.overlap_ratio)],
                      ["P95 residual hai chiều", metersText(inspection.qa_report.bidirectional_p95_residual_m)],
                      ["Chênh lệch sàn", metersText(inspection.qa_report.floor_difference_m)],
                      ["Observable DOF", integerText(inspection.qa_report.observable_dof)],
                      ["Candidate margin", ratioText(inspection.qa_report.candidate_margin)],
                    ] as const).filter(([, value]) => value !== null).map(([label, value]) => (
                      <div key={label} className="flex justify-between gap-2"><dt className="text-ink-muted">{label}</dt><dd>{value}</dd></div>
                    ))}
                  </dl>
                  {Array.isArray(inspection.qa_report.regions) && inspection.qa_report.regions.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-sm font-medium">Metric theo vùng</p>
                      {inspection.qa_report.regions.map((value, index) => {
                        const region = jsonObject(value);
                        if (!region) return null;
                        const regionId = typeof region.region_id === "string" ? region.region_id : `region-${index + 1}`;
                        return (
                          <p key={`${regionId}-${index}`} className="text-sm text-ink-muted">
                            {regionId}: phủ nguồn {ratioText(region.source_coverage_ratio) ?? "—"}, phủ đích {ratioText(region.target_coverage_ratio) ?? "—"},
                            {" "}{integerText(region.correspondence_count) ?? "—"} correspondence, P95 {metersText(region.p95_residual_m) ?? "—"}
                          </p>
                        );
                      })}
                    </div>
                  )}
                  {Array.isArray(inspection.qa_report.findings) && inspection.qa_report.findings.length > 0 && (
                    <ul className="list-disc pl-5 text-sm text-ink-muted">
                      {inspection.qa_report.findings.map((finding, index) => {
                        const code = typeof finding === "string" ? finding as RegistrationFinding : null;
                        return <li key={`${String(finding)}-${index}`}>{code && FINDING_LABELS[code] ? FINDING_LABELS[code] : String(finding)}</li>;
                      })}
                    </ul>
                  )}
                </div>
              )}
              <p className="text-xs text-ink-muted">Thông tin này chỉ để kiểm tra. Chưa xác nhận hoặc áp dụng transform.</p>
            </div>
          )}
        </section>
      )}
      {canMutateJob && userId && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={busy || pendingOperation} onClick={() => void prepare()}>
            {busy && !operationId ? "Đang kiểm tra…" : operationId ? "Kiểm tra revision mới" : "Kiểm tra dữ liệu"}
          </Button>
          {canStart && <Button disabled={busy} onClick={() => void submit(session.request!)}>
            {busy ? "Đang gửi…" : error ? "Gửi lại cùng yêu cầu" : "Bắt đầu căn chỉnh"}
          </Button>}
        </div>
      )}
      {operationId && operationPollable && <p className="text-xs text-ink-muted" role="status">Trạng thái được đọc từ máy chủ; trang sẽ tự cập nhật khi worker hoặc Reviewer thay đổi kết quả.</p>}
    </div>
  );
}
