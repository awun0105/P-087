"use client";

import { errorMessage } from "@/lib/ui-error";

import { ClipboardCheck, Download, Pencil, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, Button, Card, Notice, buttonVariants } from "@/components/studio/primitives";
import type { Preview } from "@/features/studio/scene/state";
import { TraceList } from "@/features/studio/TraceList";
import { ApiError } from "@/lib/api/client";
import { getJobScene, getReviewState, getSimulationPackage, releaseDownloadUrl, simulationPackageDownloadUrl, type ReviewStateView, type SimulationPackageView } from "@/lib/api/studio";

interface ResultState {
  key: string;
  pkg: SimulationPackageView | null;
  review: ReviewStateView | null;
  errors: string[];
  packageError: boolean;
  reviewError: boolean;
  revision: string | null;
}

export function ResultsTab({ jobId, preview, revision, onOpenGaussian, onOpenReview }: {
  jobId: string;
  preview: Preview;
  revision: string | null;
  onOpenGaussian?: () => void;
  onOpenReview?: () => void;
}) {
  const [result, setResult] = useState<ResultState | null>(null);
  const [reload, setReload] = useState(0);
  const key = `${jobId}:${revision ?? ""}:${reload}`;
  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled([
      getSimulationPackage(jobId, controller.signal),
      getReviewState(jobId, controller.signal),
      revision ? Promise.resolve(revision) : getJobScene(jobId, controller.signal).then((value) => {
        if (!value.ok) throw new ApiError(value.error.status, value.error.detail);
        return value.data.scene.scene_revision;
      }),
    ]).then(([pkgResult, reviewResult, revisionResult]) => {
      if (controller.signal.aborted) return;
      // Chưa có SceneIR là 404 hợp lệ; lỗi mạng/server phải có đường thử lại.
      const errors = [pkgResult, reviewResult, revisionResult].flatMap((item) => item.status === "rejected" && !(item.reason instanceof ApiError && item.reason.status === 404)
        ? [errorMessage(item.reason, "Không đọc được kết quả")] : []);
      const unreadable = (item: PromiseSettledResult<unknown>) => item.status === "rejected" && !(item.reason instanceof ApiError && item.reason.status === 404);
      setResult({ key, pkg: pkgResult.status === "fulfilled" ? pkgResult.value : null, review: reviewResult.status === "fulfilled" ? reviewResult.value : null, revision: revisionResult.status === "fulfilled" ? revisionResult.value : null, errors, packageError: unreadable(pkgResult), reviewError: unreadable(reviewResult) });
    });
    return () => controller.abort();
  }, [jobId, key, revision]);
  const loading = result?.key !== key;
  const pkg = loading ? null : result?.pkg ?? null;
  const review = loading ? null : result?.review ?? null;
  const currentRevision = revision ?? (loading ? null : result?.revision ?? null);
  const packageCurrent = pkg !== null && currentRevision !== null && pkg.scene_revision === currentRevision;
  const reviewCurrent = review !== null && currentRevision !== null && review.record.scene_revision === currentRevision;
  const released = reviewCurrent && review.record.status === "RELEASED" && review.release !== null && review.release_archive !== null;
  return (
    <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Kết quả của scene</h2>
        <p className="mt-1 text-sm text-ink-muted">Chọn đúng loại file cho công việc tiếp theo.</p>
      </div>
      {loading && <p role="status" className="text-sm text-ink-muted">Đang đọc gói và trạng thái phát hành…</p>}
      {!loading && result && result.errors.length > 0 && <Notice tone="rust">
        {result.errors.join(" · ")} <Button size="sm" variant="secondary" className="ml-2" onClick={() => setReload((value) => value + 1)}>Thử lại</Button>
      </Notice>}
      <ResultCard
        icon={<Pencil aria-hidden />}
        title="Bản làm việc 3DGS"
        badge={<Badge tone="neutral">Chưa quy đổi mét · chưa duyệt</Badge>}
        body={onOpenGaussian ? "Bản 3D để xem và chỉnh. Muốn xuất bản đã chỉnh, mở Chỉnh Gaussian › File › Export." : "Bản 3D của scene, tải về để dùng ở công cụ khác."}
        action={<>
          {onOpenGaussian && <Button size="sm" variant="secondary" onClick={onOpenGaussian}>Chỉnh Gaussian</Button>}
          <a href={preview.url} download={preview.filename} className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <Download aria-hidden /> Tải {preview.filename}
          </a>
        </>}
      />
      <ResultCard
        icon={<ClipboardCheck aria-hidden />}
        title="Gói mô phỏng"
        badge={pkg?.package_ref ? <Badge tone={packageCurrent ? "ochre" : "rust"}>{packageCurrent ? (pkg.preflight.blocking_result === "FAIL" ? "chưa đạt kiểm tra" : "đạt kiểm tra") : currentRevision ? "phiên bản cũ" : "chưa đối chiếu phiên bản"}</Badge> : <Badge tone="neutral">{loading ? "Đang kiểm tra" : result?.packageError ? "Chưa đọc được gói" : "Chưa có"}</Badge>}
        body="Gói OpenUSD cho Isaac Sim 5.0 trở lên: hình, va chạm, khối lượng và nhãn của từng vật. Chưa phải bản phát hành."
        detail={pkg ? `Tạo lúc ${new Date(pkg.created_at).toLocaleString("vi-VN")}${packageCurrent ? "" : currentRevision ? " · Scene đã đổi; cần tạo lại gói." : " · Tải lại trang trước khi tải gói."}` : "Tạo gói trong Kiểm tra & duyệt sau khi xác nhận vật thể."}
        action={
          pkg?.package_ref && packageCurrent ? (
            <a href={simulationPackageDownloadUrl(jobId)} className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải gói
            </a>
          ) : onOpenReview ? <Button size="sm" variant="secondary" onClick={onOpenReview}>Mở Kiểm tra & duyệt</Button> : null
        }
      />
      <ResultCard
        icon={<ShieldCheck aria-hidden />}
        title="Bản phát hành"
        badge={released ? <Badge tone="sage">Đã phát hành</Badge> : <Badge tone="neutral">{loading ? "Đang kiểm tra" : result?.reviewError ? "Chưa đọc được trạng thái" : "Chưa phát hành"}</Badge>}
        body={
          released
            ? "Gói đã qua kiểm tra và được duyệt, kèm báo cáo kiểm tra và bản ghi duyệt."
            : review && !reviewCurrent ? currentRevision ? "Scene đã có phiên bản mới; kết quả duyệt cũ không áp dụng." : "Chưa đối chiếu được phiên bản scene. Thử lại."
              : review?.blockers[0] ?? "Có sau khi gói qua kiểm tra Isaac Sim và được duyệt."
        }
        detail={released ? `Phát hành lúc ${new Date(review.release!.release_timestamp).toLocaleString("vi-VN")}${review.approval ? ` · duyệt bởi ${review.reviewer_name ?? review.approval.reviewer_id}` : ""}` : undefined}
        extra={released ? (
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-ember">Nguồn kết quả của bản phát hành</summary>
            <div className="mt-2">
              <TraceList
                rows={[
                  { label: "Revision scene", value: review.record.scene_revision },
                  { label: "Mã gói", value: review.release!.candidate_checksum ?? review.record.candidate_checksum },
                  { label: "Mã báo cáo kiểm tra", value: review.release!.validation_report_checksum ?? review.record.validation_report_checksum },
                  { label: "Mã bản phát hành", value: review.release!.release_manifest_checksum },
                ]}
              />
            </div>
          </details>
        ) : undefined}
        action={
          released ? (
            <a href={releaseDownloadUrl(jobId)} className={buttonVariants({ size: "sm" })}>
              <Download aria-hidden /> Tải bản phát hành
            </a>
          ) : null
        }
      />
    </div>
  );
}

function ResultCard({ icon, title, badge, body, detail, extra, action }: { icon: ReactNode; title: string; badge: ReactNode; body: string; detail?: string; extra?: ReactNode; action: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center">
      <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper-sunken text-ink-muted [&_svg]:size-5">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 font-bold">
          {title} {badge}
        </p>
        <p className="mt-1 text-sm text-ink-muted">{body}</p>
        {detail && <p className="mt-2 text-xs text-ink-subtle">{detail}</p>}
        {extra}
      </div>
      <div className="flex flex-wrap gap-2 sm:max-w-60 sm:justify-end">{action}</div>
    </Card>
  );
}
