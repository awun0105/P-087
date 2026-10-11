"use client";

import { CircleSlash, Layers } from "lucide-react";
import type { ReactNode } from "react";

import { ASSET_RENDERERS, STAGE_PRESENTERS, hasEvidence, type ShowcaseContext } from "@/features/studio/showcase/registry";
import { stageMeta } from "@/features/studio/stages";
import type { StageId } from "@/lib/contracts/api";
import type { DemoManifest } from "@/lib/contracts/studio";
import { formatDuration } from "@/lib/format";

/**
 * Khung xem trước kết quả của bước đang phát lại, vẽ từ chính file và số đo trong demo bundle.
 *
 * Khung chỉ ghép các thẻ trong `showcase/registry.tsx`: thẻ dựng sẵn của bước (video gốc, frame, 3DGS) cùng các thẻ
 * `assets` mà bundle khai báo cho bước đó. Bước chưa có bằng chứng hoặc chưa có thẻ nào thì nói thẳng như vậy, không
 * vẽ số liệu thay thế.
 */
export function DemoShowcase({
  demo,
  stage,
  fraction,
  fileUrl,
}: {
  demo: DemoManifest;
  stage: StageId;
  fraction: number;
  /** URL phục vụ file của đúng video mẫu (allow-list + checksum ở backend). */
  fileUrl: (name: string) => string;
}) {
  const meta = stageMeta(stage);
  const record = demo.stages.find((item) => item.stage_id === stage);
  const context: ShowcaseContext = { demo, stage, fraction, fileUrl };
  const presenter = STAGE_PRESENTERS[stage];
  const evidence = hasEvidence(record);

  const cards: ReactNode[] = [];
  if (evidence && presenter) cards.push(<div key="stage">{presenter.render(context)}</div>);
  if (evidence) {
    (record?.assets ?? []).forEach((asset, index) => {
      const node = ASSET_RENDERERS[asset.kind]?.(asset, context);
      if (node) {
        cards.push(
          <div key={`asset-${index}`} className="space-y-1.5">
            {asset.title && <p className="text-sm font-medium text-ink">{asset.title}</p>}
            {node}
          </div>,
        );
      }
    });
  }

  let note: string | undefined;
  if (!evidence) {
    note = record?.summary || "Mẫu này chưa ghi kết quả của bước này.";
  } else if (cards.length === 0) {
    note = `Bước này đã chạy xong${record?.duration_seconds ? ` trong ${formatDuration(record.duration_seconds)}` : ""}; mẫu chưa kèm hình hay số đo để hiển thị.`;
  }
  const caption = evidence ? (presenter?.caption?.(context) ?? meta?.description) : meta?.description;

  return (
    <figure className="rounded-2xl border border-line bg-paper-raised p-4 sm:p-5">
      <figcaption className="mb-3 flex items-center gap-2 text-sm font-medium text-ink [&_svg]:size-4 [&_svg]:text-ember-strong">
        {presenter?.icon ?? <Layers aria-hidden />}
        {meta?.title}
      </figcaption>
      {cards.length > 0 && <div className="space-y-4">{cards}</div>}
      {note && (
        <p role="status" className="flex items-start gap-2 rounded-xl bg-paper-sunken p-4 text-sm text-ink-muted">
          <CircleSlash className="mt-0.5 size-4 shrink-0" aria-hidden />
          {note}
        </p>
      )}
      <p className="mt-3 text-sm leading-relaxed text-ink-muted">{caption}</p>
    </figure>
  );
}
