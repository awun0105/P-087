import { AppShell } from "@/components/shell";

/** UI cũ giữ nguyên để phát triển lại sau; `src/proxy.ts` chặn khi chưa bật flag. */
export default function LegacyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="legacy-root min-h-screen bg-slate-950 font-sans">
      <AppShell>{children}</AppShell>
    </div>
  );
}
