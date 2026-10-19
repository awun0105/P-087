import { Suspense } from "react";

import { UnifiedInputFlow } from "@/features/studio/UnifiedInputFlow";

export default function NewScenePage() {
  // `/new` là khung upload chung; link mẫu và import cũ được chuyển ở client.
  return (
    <Suspense>
      <UnifiedInputFlow />
    </Suspense>
  );
}
