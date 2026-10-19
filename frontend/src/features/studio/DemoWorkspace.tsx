"use client";

import { useSearchParams } from "next/navigation";
import type { MouseEvent } from "react";

import { TooltipProvider } from "@/components/shadcn/tooltip";
import { FeedbackHost } from "@/components/studio/feedback";
import { PageTitleProvider } from "@/features/shell/Breadcrumbs";
import { NavigationGuardProvider } from "@/features/shell/NavigationGuard";
import { AuthProvider } from "@/features/studio/AuthProvider";
import { ScenePage } from "@/features/studio/ScenePage";
import { StageInspectionPage } from "@/features/studio/inspection/StageInspectionPage";

/** Separate document lifetime keeps pending work and browser/GPU state inside one demo session. */
export function DemoWorkspace({ sessionId, jobId }: { sessionId: string; jobId: string }) {
  const params = useSearchParams();
  const stage = params.get("stage");
  const navigateOutside = (event: MouseEvent) => {
    const anchor = (event.target as Element).closest("a");
    if (!anchor || anchor.hasAttribute("download") || !anchor.href) return;
    const url = new URL(anchor.href);
    if (url.origin !== window.location.origin || url.pathname.startsWith("/api/") || url.pathname === `/demo-workspace/${sessionId}`) return;
    event.preventDefault();
    event.stopPropagation();
    window.top!.location.href = url.href;
  };
  return <AuthProvider><PageTitleProvider><TooltipProvider><NavigationGuardProvider>
    <div className="studio-root h-dvh overflow-hidden bg-paper text-ink [&_main]:h-full" onClickCapture={navigateOutside}>
      {stage ? <StageInspectionPage jobId={jobId} stageId={stage} /> : <ScenePage jobId={jobId} />}
      <FeedbackHost />
    </div>
  </NavigationGuardProvider></TooltipProvider></PageTitleProvider></AuthProvider>;
}
