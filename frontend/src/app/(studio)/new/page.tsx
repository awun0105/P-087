import { Suspense } from "react";

import { NewSceneFlow } from "@/features/studio/NewSceneFlow";

export default function NewScenePage() {
  // useSearchParams (`?sample=`) cần Suspense boundary khi build tĩnh.
  return (
    <Suspense>
      <NewSceneFlow />
    </Suspense>
  );
}
