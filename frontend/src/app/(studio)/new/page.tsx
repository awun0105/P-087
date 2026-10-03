import { Suspense } from "react";

import { NewSceneFlow } from "@/features/studio/NewSceneFlow";

export default function NewScenePage() {
  // Trang chọn cách bắt đầu; link cũ `/new?source=…` / `?sample=…` được chuyển sang trang con ở client.
  return (
    <Suspense>
      <NewSceneFlow />
    </Suspense>
  );
}
