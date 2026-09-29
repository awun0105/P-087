import { AuthProvider } from "@/features/studio/AuthProvider";
import { StudioHeader } from "@/features/studio/StudioHeader";

/** Khung Studio MVP: nền beige, chữ nâu than; viewport 3D tự đặt nền tối ấm. */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="studio-root min-h-screen bg-paper text-ink antialiased">
        <StudioHeader />
        {children}
      </div>
    </AuthProvider>
  );
}
