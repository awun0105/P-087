import { Suspense } from "react";
import { notFound } from "next/navigation";
import { DemoWorkspace } from "@/features/studio/DemoWorkspace";

export default async function DemoWorkspacePage({ params, searchParams }: PageProps<"/demo-workspace/[sessionId]">) {
  const { sessionId } = await params;
  const query = await searchParams;
  if (!/^[a-f0-9]{32}$/.test(sessionId) || typeof query.job !== "string") notFound();
  return <Suspense fallback={<p role="status">Đang mở workspace mẫu…</p>}>
    <DemoWorkspace sessionId={sessionId} jobId={query.job} />
  </Suspense>;
}
