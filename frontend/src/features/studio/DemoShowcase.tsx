"use client";

import { Aperture, Cpu, Images, ScanSearch, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { stageMeta } from "@/features/studio/stages";
import { cn } from "@/lib/cn";
import type { StageId } from "@/lib/contracts/api";
import type { DemoManifest } from "@/lib/contracts/studio";

/**
 * Minh họa output của stage đang phát lại bằng chính file trong demo bundle
 * (video gốc, frame đã tách). Không vẽ dữ liệu giả thành kết quả thật.
 */
export function DemoShowcase({
  demo,
  stage,
  fraction,
  fileUrl,
}: {
  demo: DemoManifest;
  stage: StageId;
  fraction: number;
  /** URL phục vụ file của đúng video mẫu (allow-list + checksum ở backend). */
  fileUrl: (name: string) => string;
}) {
  const meta = stageMeta(stage);
  const frames = demo.frames;
  const revealed = Math.max(1, Math.ceil(frames.length * Math.min(1, fraction)));
  const cover = frames[Math.floor(frames.length / 2)];

  let body: ReactNode;
  let icon: ReactNode;
  switch (stage) {
    case "ST-INPUT-VALIDATE":
      icon = <ScanSearch aria-hidden />;
      body = demo.video ? (
        <video
          src={fileUrl(demo.video.name)}
          className="aspect-video w-full rounded-xl bg-viewport object-cover"
          muted
          loop
          autoPlay
          playsInline
          aria-label="Video gốc của video mẫu"
        />
      ) : (
        <FrameImage src={cover ? fileUrl(cover.name) : undefined} />
      );
      break;
    case "ST-PRIVACY-GATE":
      icon = <ShieldCheck aria-hidden />;
      body = (
        <div className="grid aspect-video place-items-center rounded-xl bg-paper-sunken p-6 text-center">
          <div className="max-w-sm">
            <ShieldCheck className="mx-auto size-10 text-sage" aria-hidden />
            <p className="mt-3 text-sm font-medium text-ink">Dữ liệu công khai: {demo.source.dataset}</p>
            <p className="mt-1 text-sm text-ink-muted">
              Người tải lên xác nhận video không có khuôn mặt hay biển số chưa làm mờ. Xác nhận được ghi lại cùng scene.
            </p>
          </div>
        </div>
      );
      break;
    case "ST-FRAME-EXTRACT":
    case "ST-CAMERA-POSE":
      icon = stage === "ST-FRAME-EXTRACT" ? <Images aria-hidden /> : <Aperture aria-hidden />;
      body = (
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4" aria-label="Khung hình đã tách">
          {frames.map((frame, index) => (
            <li
              key={frame.name}
              className={cn(
                "relative aspect-video overflow-hidden rounded-lg bg-paper-sunken transition-opacity duration-300",
                stage === "ST-FRAME-EXTRACT" && index >= revealed && "opacity-0",
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API */}
              <img src={fileUrl(frame.name)} alt="" className="size-full object-cover" loading="lazy" />
              {stage === "ST-CAMERA-POSE" && index < revealed && (
                <span className="absolute top-1.5 left-1.5 rounded bg-viewport/70 px-1.5 py-0.5 font-mono text-[10px] text-ink">
                  cam {index + 1}
                </span>
              )}
            </li>
          ))}
        </ul>
      );
      break;
    default:
      icon = <Cpu aria-hidden />;
      body = (
        <div className="relative aspect-video overflow-hidden rounded-xl bg-viewport">
          {cover && (
            // eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API
            <img
              src={fileUrl(cover.name)}
              alt=""
              className="size-full object-cover transition-[filter] duration-500"
              style={{ filter: `blur(${Math.round((1 - fraction) * 14)}px) saturate(${0.6 + fraction * 0.4})` }}
            />
          )}
        </div>
      );
  }

  const caption =
    stage === "ST-FRAME-EXTRACT" && demo.frame_count
      ? `${demo.frame_count} khung hình được giữ lại để dựng 3D (hiển thị ${frames.length} ảnh đại diện).`
      : stage === "ST-CAMERA-POSE"
        ? "COLMAP khớp điểm đặc trưng giữa các ảnh để tìm vị trí camera của từng khung hình."
        : meta?.description;

  return (
    <figure className="rounded-2xl border border-line bg-paper-raised p-4 sm:p-5">
      <figcaption className="mb-3 flex items-center gap-2 text-sm font-medium text-ink [&_svg]:size-4 [&_svg]:text-ember-strong">
        {icon}
        {meta?.title}
      </figcaption>
      {body}
      <p className="mt-3 text-sm leading-relaxed text-ink-muted">{caption}</p>
    </figure>
  );
}

function FrameImage({ src }: { src?: string }) {
  if (!src) return <div className="aspect-video rounded-xl bg-viewport" />;
  // eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API
  return <img src={src} alt="" className="aspect-video w-full rounded-xl object-cover" />;
}
