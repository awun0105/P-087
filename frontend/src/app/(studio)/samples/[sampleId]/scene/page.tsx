import { SampleScene } from "@/features/studio/SampleScene";

export default async function SampleSceneRoute({ params }: PageProps<"/samples/[sampleId]/scene">) {
  const { sampleId } = await params;
  return <SampleScene sampleId={decodeURIComponent(sampleId)} />;
}
