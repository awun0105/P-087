import { PageHeader } from "@/components/shell";
import { LocalSplatViewer } from "@/features/viewer/LocalSplatViewer";

/** Preview độc lập với backend và SceneIR để kiểm tra file 3DGS có sẵn. */
export default function LocalViewerPage() {
  return <>
    <PageHeader title="Mở 3DGS" subtitle="File có sẵn · preview trong trình duyệt" />
    <LocalSplatViewer />
  </>;
}
