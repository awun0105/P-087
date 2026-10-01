"use client";

import { ClipboardCheck, Download, Pencil, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, Card, buttonVariants } from "@/components/studio/primitives";
import type { Preview } from "@/features/studio/scene/state";
import { getReviewState, getSimulationPackage, releaseDownloadUrl, simulationPackageDownloadUrl, type ReviewStateView, type SimulationPackageView } from "@/lib/api/studio";

export function ResultsTab({ jobId, preview }: { jobId: string; preview: Preview }) {
  const [pkg, setPkg] = useState<SimulationPackageView | null>(null);
  const [review, setReview] = useState<ReviewStateView | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    // Scene chưa có SceneIR (chưa tách vật thể) thì hai lời gọi này lỗi — hiển thị "chưa có".
    getSimulationPackage(jobId, controller.signal).then(setPkg, () => setPkg(null));
    getReviewState(jobId, controller.signal).then(setReview, () => setReview(null));
    return () => controller.abort();
  }, [jobId]);
  const released = review?.record.status === "RELEASED";
  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-6 sm:px-6">
      <ResultCard
        icon={<Pencil aria-hidden />}
        title="Bản làm việc 3DGS"
        badge={<Badge tone="neutral">Chưa quy đổi mét · chưa duyệt</Badge>}
        body="Bản xem Brush (SOG) dùng để xem/chỉnh. Muốn xuất PLY/SOG đã chỉnh, mở Studio › Chỉnh Gaussian › File › Export."
        action={
          <a href={preview.url} download={preview.filename} className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <Download aria-hidden /> Tải {preview.filename}
          </a>
        }
      />
      <ResultCard
        icon={<ClipboardCheck aria-hidden />}
        title="Gói mô phỏng (candidate)"
        badge={pkg?.package_ref ? <Badge tone="ochre">{pkg.scene_revision} · đã qua preflight, chưa validation</Badge> : <Badge tone="neutral">Chưa có</Badge>}
        body="OpenUSD của đúng revision hiện tại cho Isaac Sim ≥ 5.0: hình bằng Gaussian (nền đã vá + từng vật đã xác nhận), collider, khối lượng và nhãn. Scene dựng bằng đường cũ chỉ có collider. Không phải bản phát hành."
        action={
          pkg?.package_ref ? (
            <a href={simulationPackageDownloadUrl(jobId)} className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải gói
            </a>
          ) : null
        }
      />
      <ResultCard
        icon={<ShieldCheck aria-hidden />}
        title="Bản phát hành"
        badge={released ? <Badge tone="sage">Đã phát hành</Badge> : <Badge tone="neutral">Chưa phát hành</Badge>}
        body={
          released
            ? "Gói đã validation và được Reviewer duyệt, kèm release manifest, báo cáo validation và bản ghi duyệt."
            : review?.blockers[0] ?? "Chỉ có sau khi gói qua validation Isaac và được Reviewer duyệt."
        }
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

function ResultCard({ icon, title, badge, body, action }: { icon: ReactNode; title: string; badge: ReactNode; body: string; action: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center">
      <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper-sunken text-ink-muted [&_svg]:size-5">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {title} {badge}
        </p>
        <p className="mt-1 text-sm text-ink-muted">{body}</p>
      </div>
      {action}
    </Card>
  );
}
