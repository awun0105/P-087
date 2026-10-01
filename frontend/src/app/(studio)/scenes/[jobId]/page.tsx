import { ScenePage } from "@/features/studio/ScenePage";

export default async function SceneRoute({ params, searchParams }: PageProps<"/scenes/[jobId]">) {
  const { jobId } = await params;
  const query = await searchParams;
  return <ScenePage key={`${jobId}:${query.tab === "progress" ? "progress" : "default"}`} jobId={jobId} initialTab={query.tab === "progress" ? "progress" : undefined} />;
}
