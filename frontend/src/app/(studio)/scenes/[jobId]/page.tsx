import { ScenePage } from "@/features/studio/ScenePage";

export default async function SceneRoute({ params }: PageProps<"/scenes/[jobId]">) {
  const { jobId } = await params;
  return <ScenePage key={jobId} jobId={jobId} />;
}
