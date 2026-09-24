import type { Metadata } from "next";

import { AppShell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Real2Sim Studio — EX-PRODUCT",
  description: "Web Studio cho pipeline Real2Sim: project, job, scene viewer, validation, review.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" className="h-full antialiased">
      <body className="min-h-full bg-slate-950 font-sans">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
