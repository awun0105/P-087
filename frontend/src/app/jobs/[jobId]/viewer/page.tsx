import { JobTabs, PageHeader } from "@/components/shell";
import { ErrorState } from "@/components/states";
import { ViewerWorkspace } from "@/features/viewer/ViewerWorkspace";
import { getScene } from "@/lib/api/endpoints";

/**
 * Màn hình SceneIR viewer.
 *
 * Trang này là server component: nó đọc SceneIR từ backend rồi truyền nguyên
 * `SceneResponse` xuống `ViewerPanel`. Three.js chỉ nằm trong bundle client của
 * `ViewerPanel`, nên canonical scene không phải đi qua state của trình duyệt.
 */
export default async function ViewerPage({ params }: PageProps<"/jobs/[jobId]/viewer">) {
  const { jobId } = await params;
  const scene = await getScene(jobId);

  if (!scene.ok) {
    return (
      <>
        <PageHeader title="Scene viewer" subtitle={jobId} />
        <JobTabs jobId={jobId} active="Scene" />
        <ErrorState title="Không tải được SceneIR" detail={scene.error.detail} />
        <ViewerWorkspace scene={null} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Scene viewer"
        subtitle={`${scene.data.scene_id} · ${scene.data.scene_revision} · ${scene.data.scene.objects.length} object`}
      />
      <JobTabs jobId={jobId} active="Scene" />
      <ViewerWorkspace scene={scene.data} />
    </>
  );
}
