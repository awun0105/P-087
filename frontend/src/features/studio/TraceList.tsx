"use client";

import { Fragment } from "react";

import { CopyButton } from "@/components/studio/feedback";

export interface TraceRow {
  label: string;
  value: string | null;
}

/**
 * "Nguồn kết quả": các định danh và checksum để đối chiếu gói, báo cáo, quyết định duyệt và
 * bản phát hành thuộc cùng một revision. Giá trị hiện đầy đủ (không cắt) vì người dùng cần so từng ký tự hoặc chép đi.
 */
export function TraceList({ rows }: { rows: TraceRow[] }) {
  return (
    <dl className="grid gap-x-4 gap-y-1.5 text-xs sm:grid-cols-[max-content_minmax(0,1fr)]">
      {rows.map((row) => (
        <Fragment key={row.label}>
          <dt className="text-ink-muted">{row.label}</dt>
          <dd className="flex min-w-0 items-start gap-1">
            {row.value ? (
              <>
                <code className="min-w-0 font-mono break-all text-ink">{row.value}</code>
                <CopyButton value={row.value} label={row.label.toLowerCase()} />
              </>
            ) : (
              <span className="text-ink-subtle">—</span>
            )}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}
