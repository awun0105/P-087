import { AppShell } from "@/components/shell";

/** UI cũ giữ nguyên để phát triển lại sau; `redirects()` trong next.config.ts chuyển về Studio khi chưa bật `LEGACY_UI=1`. */
export default function LegacyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="legacy-root min-h-screen bg-slate-950 font-sans">
      <AppShell>{children}</AppShell>
    </div>
  );
}
