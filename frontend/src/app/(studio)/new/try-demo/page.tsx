import { Suspense } from "react";

import { NewSceneFlow } from "@/features/studio/NewSceneFlow";

export default function Page() {
  // Query (`?step=`, `?upload=`, `?sample=`) đọc ở client nên cần Suspense boundary khi build tĩnh.
  return (
    <Suspense>
      <NewSceneFlow source="sample" />
    </Suspense>
  );
}
