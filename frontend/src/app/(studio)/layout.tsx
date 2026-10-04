import { TooltipProvider } from "@/components/shadcn/tooltip";
import { AppShell } from "@/features/shell/AppShell";
import { AuthProvider } from "@/features/studio/AuthProvider";
import { FeedbackHost } from "@/components/studio/feedback";
import { NavigationGuardProvider } from "@/features/shell/NavigationGuard";

/** Khung Studio: shell sidebar + header theo dashboard donor, theme tối palette (STUDIO_UX_SPEC.md D-01, D-04). */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="studio-root min-h-screen bg-paper text-ink antialiased">
        <TooltipProvider>
          <NavigationGuardProvider><AppShell>{children}</AppShell><FeedbackHost /></NavigationGuardProvider>
        </TooltipProvider>
      </div>
    </AuthProvider>
  );
}
