import { ImportScenePage } from "@/features/studio/ImportScenePage";

export default async function ImportRoute({ params }: PageProps<"/imports/[importId]">) {
  const { importId } = await params;
  return <ImportScenePage importId={importId} />;
}
