"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { SceneResponse } from "@/lib/contracts/api";
import { LocalSplatViewer } from "@/features/viewer/LocalSplatViewer";
import { ViewerPanel } from "@/features/viewer/ViewerPanel";

/** Cùng màn hình của app; chỉ một renderer hoạt động tại một thời điểm. */
export function ViewerWorkspace({ scene }: { scene: SceneResponse | null }) {
  const [localPreview, setLocalPreview] = useState(false);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-3">
      <Button variant={localPreview ? "secondary" : "primary"} onClick={() => setLocalPreview((current) => !current)}>
        {localPreview ? "Quay lại kết quả job" : "Mở file 3DGS có sẵn"}
      </Button>
      {localPreview && <p className="text-xs text-amber-300">Preview file riêng · không thay đổi artifact của job</p>}
    </div>
    {localPreview ? <LocalSplatViewer /> : scene ? <ViewerPanel scene={scene} /> :
      <p className="text-sm text-slate-400">Job chưa có scene để hiển thị. Bạn vẫn có thể mở file 3DGS có sẵn bằng nút phía trên.</p>}
  </div>;
}
