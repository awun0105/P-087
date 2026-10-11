import { Suspense } from "react";

import { UnifiedInputFlow } from "@/features/studio/UnifiedInputFlow";

export default function Page() {
  // Query (`?step=`, `?upload=`, `?sample=`) đọc ở client nên cần Suspense boundary khi build tĩnh.
  return (
    <Suspense>
      <UnifiedInputFlow />
    </Suspense>
  );
}
