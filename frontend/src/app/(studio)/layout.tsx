import { TooltipProvider } from "@/components/shadcn/tooltip";
import { AppShell } from "@/features/shell/AppShell";
import { AuthProvider } from "@/features/studio/AuthProvider";

/** Khung Studio: shell sidebar + header theo dashboard donor, theme tối palette (PRODUCT.md D-01, D-04). */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="studio-root min-h-screen bg-paper text-ink antialiased">
        <TooltipProvider>
          <AppShell>{children}</AppShell>
        </TooltipProvider>
      </div>
    </AuthProvider>
  );
}
