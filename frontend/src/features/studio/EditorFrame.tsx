"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** Path của SuperSplat editor đã build (`npm run build:editor` → public/editor). */
const EDITOR_PATH = "/editor/";

/**
 * Nhúng SuperSplat editor (vendor, MIT) cùng origin và nạp đúng file 3DGS của
 * scene qua `?load=`. Editor sở hữu công cụ chọn/xóa/di chuyển/đo/export; logo
 * của editor gửi `supersplat:navigate-home` để Studio quyết định điều hướng.
 */
export function EditorFrame({
  contentUrl,
  filename,
  homeHref,
  title,
}: {
  contentUrl: string;
  filename: string;
  homeHref: string;
  title: string;
}) {
  const router = useRouter();
  const [loaded, setLoaded] = useState(false);
  const src = `${EDITOR_PATH}?${new URLSearchParams({ load: contentUrl, filename }).toString()}`;

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (typeof event.data === "object" && event.data?.type === "supersplat:navigate-home") {
        router.push(homeHref);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [router, homeHref]);

  return (
    <div className="relative size-full bg-viewport">
      {!loaded && (
        <div className="absolute inset-0 z-10 grid place-items-center text-paper/80" role="status">
          <div className="flex flex-col items-center gap-3 text-sm">
            <Loader2 className="size-6 animate-spin text-ember motion-reduce:animate-none" aria-hidden />
            Đang mở editor 3D…
          </div>
        </div>
      )}
      <iframe
        key={src}
        src={src}
        title={title}
        onLoad={() => setLoaded(true)}
        className="size-full border-0"
        allow="fullscreen; clipboard-write; xr-spatial-tracking"
      />
    </div>
  );
}
