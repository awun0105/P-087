"use client";

import { useEffect, useMemo, useState } from "react";

import { recordingCameraPose, type CameraMarkerLike, type DisplayCameraPose, type DisplayRotation } from "@/features/viewer/source-frame";
import { getStageViews } from "@/lib/api/studio";

interface Loaded {
  jobId: string;
  cameras: readonly CameraMarkerLike[] | undefined;
  displayRotation?: DisplayRotation;
}

export interface JobCameras {
  displayRotation?: DisplayRotation;
  /** Quỹ đạo camera COLMAP của job (hệ SfM, cùng hệ với bản xem 3DGS); undefined nếu job chưa có hoặc đọc lỗi. */
  cameras: readonly CameraMarkerLike[] | undefined;
  /** Camera đặt tại frame quay đầu tiên, bên trong scene; undefined khi không có quỹ đạo. */
  initialCamera: DisplayCameraPose | undefined;
  /** Đã có kết quả (có hoặc không có camera). Viewer chỉ nên dựng sau đó: đổi camera sẽ dựng lại viewer. */
  settled: boolean;
}

/**
 * Quỹ đạo camera của job để viewer bản xem 3DGS mở đầu bên trong scene thay vì camera mặc định của thư viện
 * (đặt ngoài, nhìn cả khối Gaussian như một đám mây). `jobId` undefined = caller tự cấp camera, không tải gì.
 * Lỗi tải không chặn viewer: thiếu camera thì viewer dùng camera mặc định như trước.
 */
export function useJobCameras(jobId: string | undefined): JobCameras {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (jobId === undefined) return;
    const controller = new AbortController();
    getStageViews(jobId, controller.signal).then(
      (views) => {
        if (controller.signal.aborted) return;
        // 3DGS Brush ở hệ SfM: dùng camera của lớp 3DGS không có đơn vị mét nếu có, không thì của bước ước lượng camera.
        const sfm = views.find((view) => view.kind === "gaussian" && view.unit === "arbitrary" && view.cameras.length > 0)
          ?? views.find((view) => view.kind === "cameras" && view.cameras.length > 0);
        setLoaded({ jobId, cameras: sfm?.cameras, displayRotation: sfm?.display_rotation_xyzw ?? undefined });
      },
      () => {
        if (!controller.signal.aborted) setLoaded({ jobId, cameras: undefined });
      },
    );
    return () => controller.abort();
  }, [jobId]);

  const settled = jobId === undefined || loaded?.jobId === jobId;
  const cameras = jobId !== undefined && loaded?.jobId === jobId ? loaded.cameras : undefined;
  const initialCamera = useMemo(() => (cameras ? recordingCameraPose("colmap", cameras) : undefined), [cameras]);
  const displayRotation = jobId !== undefined && loaded?.jobId === jobId ? loaded.displayRotation : undefined;
  return { cameras, initialCamera, settled, displayRotation };
}
