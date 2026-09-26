"use client";

/**
 * Panel read-only cho các mục wireframe ngoài scope (AMR setup, audit checklist).
 * Pattern tương tự `brush-proof-absent` / `no-runtime-proof`.
 */

import { Banner } from "@/components/ui/banner";
import { Panel, PanelHeader } from "@/components/ui/panel";

interface MockReadonlyPanelProps {
  title: string;
  reason: string;
}

export function MockReadonlyPanel({ title, reason }: MockReadonlyPanelProps) {
  return (
    <Panel>
      <div className="p-3">
        <PanelHeader title={title} />
        <Banner tone="mock" title="Chưa có backend">
          {reason}
        </Banner>
      </div>
    </Panel>
  );
}
