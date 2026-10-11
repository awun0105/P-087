"use client";

import { notifySuccess } from "@/components/studio/feedback";

import { errorMessage } from "@/lib/ui-error";

import { CheckCircle2, Download, Loader2, PackageOpen, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/studio/primitives";
import {
  createSimulationPackage,
  getSimulationPackage,
  simulationPackageDownloadUrl,
  type SimulationPackageView,
} from "@/lib/api/studio";
import { cn } from "@/lib/cn";

/** Tên dễ hiểu cho từng luật preflight (SIM-04); luật lạ hiện nguyên mã. */
const RULE_LABEL: Record<string, string> = {
  METRIC_SCALE_MISSING: "Tỉ lệ mét đã xác nhận",
  COLLIDER_MISSING: "Mọi vật và môi trường có collider",
  TRANSFORM_INVALID: "Vị trí/hướng hợp lệ",
  OBJECT_OUT_OF_BOUNDS: "Vật nằm trong kho, trên sàn",
  OBJECT_CONFIRMATION_INCOMPLETE: "Không còn ứng viên đang bật chưa xác nhận",
  COLLISION_SOURCE_COVERAGE: "Coverage ownership collider nguồn",
  REQUIRED_ARTIFACT_MISSING: "Đủ file hình học/collider",
};

/**
 * Gói mô phỏng cho Isaac: backend khoét vật khỏi mesh môi trường, gắn collider (khối lồi hoặc hộp), chạy
 * preflight; PASS thì đóng gói USD để tải. Gói khoá theo revision scene — sửa vật sau đó thì
 * phải tạo lại. Physics chưa chạy ở đây (Isaac cần máy RTX).
 */
export function SimulationPackagePanel({
  jobId,
  sceneRevision,
  canCreate = true,
  onSceneChanged,
}: {
  jobId: string;
  sceneRevision: string;
  canCreate?: boolean;
  onSceneChanged: () => void;
}) {
  const [result, setResult] = useState<{ revision: string; value: SimulationPackageView | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getSimulationPackage(jobId, controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        setError(null);
        setResult({ revision: sceneRevision, value });
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(cause, "Không đọc được gói"));
      },
    );
    return () => controller.abort();
  }, [jobId, sceneRevision]);

  async function create() {
    if (!canCreate) return;
    setBusy(true);
    setError(null);
    try {
      const value = await createSimulationPackage(jobId);
      // Preflight FAIL không publish revision: báo cáo thuộc source hiện tại,
      // dù physics enrichment tạm có một scene_revision khác (backend contract).
      setResult({ revision: value.package_ref ? value.scene_revision : value.source_scene_revision, value });
      // PASS tạo revision scene có physics; màn cha tải lại scene để đồng bộ.
      if (value.package_ref) { notifySuccess("Đã tạo gói mô phỏng của revision mới."); onSceneChanged(); }
    } catch (cause: unknown) {
      setError(errorMessage(cause, "Tạo gói thất bại"));
    } finally {
      setBusy(false);
    }
  }

  const value = result?.revision === sceneRevision ? result.value : null;
  const pkg = value && (value.package_ref ? value.scene_revision : value.source_scene_revision) === sceneRevision ? value : null;
  return (
    <section className="space-y-3 p-5" aria-label="Gói mô phỏng">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          <PackageOpen className="size-4" aria-hidden /> Gói mô phỏng Isaac
        </p>
        {canCreate && (
          <Button size="sm" variant={pkg?.package_ref ? "secondary" : "primary"} disabled={busy} onClick={create}>
            {busy && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
            {pkg?.package_ref
              ? "Kiểm tra lại"
              : pkg?.export_capability?.status === "blocked"
                ? "Thử lại xuất USD"
                : "Tạo gói mô phỏng"}
          </Button>
        )}
      </div>
      {!canCreate && <p className="text-xs text-ink-muted">Chỉ chủ sở hữu Guest, Editor hoặc Reviewer mới được tạo gói cho job này.</p>}
      {error && <p role="alert" className="text-sm text-rust">{error}</p>}
      {!pkg && !error && (
        <p className="text-sm text-ink-muted">
          Chỉ vật đã xác nhận thành vật riêng trong gói (hình + collider + khối lượng + nhãn); ứng viên chưa xác nhận nằm
          trong hình của nền. Hệ thống khoét chỗ vật khỏi collision mesh môi trường, rồi kiểm
          trước khi đóng gói USD.
        </p>
      )}
      {pkg && (
        <div className="space-y-2 text-xs">
          <ul className="space-y-1">
            {pkg.preflight.rules.map((rule) => (
              <li key={rule.rule_id} className="flex items-start gap-1.5">
                {rule.result === "PASS" ? (
                  <CheckCircle2 className="mt-px size-3.5 shrink-0 text-sage" aria-label="Đạt" />
                ) : (
                  <XCircle className="mt-px size-3.5 shrink-0 text-rust" aria-label="Không đạt" />
                )}
                <span className={cn(rule.result === "PASS" ? "text-ink-muted" : "text-ink")}>
                  {RULE_LABEL[rule.rule_id] ?? rule.rule_id}
                  {rule.result !== "PASS" && rule.affected_object_ids.length > 0 && (
                    <span className="text-ink-subtle"> · {rule.affected_object_ids.join(", ")}</span>
                  )}
                  {rule.result !== "PASS" && rule.remediation && (
                    <span className="block text-ink-subtle">{rule.remediation}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-ink-muted">
            {pkg.confirmed_objects} vật · môi trường {pkg.environment_triangles.toLocaleString("vi-VN")} tam giác (khoét{" "}
            {pkg.carved_triangles.toLocaleString("vi-VN")}) · scene {pkg.scene_revision}
          </p>
          {pkg.retained_shared_triangles > 0 && (
            <p role="status" className="rounded-md border border-line p-3 text-ink-muted" aria-label="Tam giác nền được giữ lại">
              Giữ lại {pkg.retained_shared_triangles.toLocaleString("vi-VN")} tam giác nền nằm trong vùng chồng giữa vật
              bị khoét và ứng viên chưa xử lý ({pkg.retained_shared_object_ids.join(", ")}) vì chưa biết chúng thuộc vật nào.
              Xác nhận hoặc xoá các ứng viên đó rồi tạo lại gói nếu muốn khoét hết.
            </p>
          )}
          {pkg.export_capability && (
            <div className="space-y-1 rounded-md border border-line p-3" aria-label="Khả năng xuất USD">
              <p className={pkg.export_capability.status === "blocked" ? "font-medium text-rust" : "text-ink-muted"}>
                Khả năng xuất USD: {pkg.export_capability.status === "blocked" ? "Bị chặn" : "Sẵn sàng"} ·{" "}
                {pkg.export_capability.effective_mode} · builder {pkg.export_capability.builder_version}
                {pkg.export_capability.runtime_version && ` · OpenUSD ${pkg.export_capability.runtime_version}`}
              </p>
              {pkg.export_capability.blockers.length > 0 && (
                <ul className="space-y-1" role="alert">
                  {pkg.export_capability.blockers.map((blocker, index) => (
                    <li key={`${blocker.code}-${index}`}>
                      <span className="font-medium">{blocker.code}</span>: {blocker.message}
                      {blocker.affected_object_ids.length > 0 && (
                        <span className="block text-ink-subtle">Vật liên quan: {blocker.affected_object_ids.join(", ")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {pkg.export_capability.notices.length > 0 && (
                <ul className="space-y-1 text-ink-muted" aria-label="Lưu ý khi xuất USD">
                  {pkg.export_capability.notices.map((notice, index) => (
                    <li key={`${notice.code}-${index}`}>
                      {notice.message}
                      {notice.affected_object_ids.length > 0 && (
                        <span className="block text-ink-subtle">Vật liên quan: {notice.affected_object_ids.join(", ")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {pkg.export_capability.status === "blocked" && (
                <p className="text-ink-muted">
                  Candidate chưa được tạo. Khắc phục điều kiện trên rồi thử lại; lần thử lại đánh giá cùng các yêu cầu của scene hiện tại.
                </p>
              )}
            </div>
          )}
          {pkg.package_ref && pkg.export_capability?.status !== "blocked" ? (
            <a
              href={simulationPackageDownloadUrl(jobId)}
              className={cn(buttonVariants({ size: "sm", variant: "secondary" }), "w-full")}
            >
              <Download aria-hidden /> Tải gói USD cho Isaac (.zip)
            </a>
          ) : pkg.export_capability?.status === "blocked" ? null : pkg.preflight.blocking_result !== "PASS" ? (
            <p className="text-rust">Chưa đạt Preflight; sửa theo các mục đỏ rồi tạo lại.</p>
          ) : (
            <p className="text-rust">Chưa có gói tải xuống; kiểm tra lại capability rồi thử tạo gói.</p>
          )}
        </div>
      )}
    </section>
  );
}
