"use client";

import { Aperture, Box, Compass, Cpu, Images, Layers, ScanSearch, ShieldCheck } from "lucide-react";
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
              <img src={fileUrl(frame.name)} alt="" className="size-full object-cover" loading="lazy" decoding="async" />
              {stage === "ST-CAMERA-POSE" && index < revealed && (
                <span className="absolute top-1.5 left-1.5 rounded border border-line-dark bg-viewport-deep/85 px-1.5 py-0.5 font-mono text-[10px] text-on-dark">
                  cam {index + 1}
                </span>
              )}
            </li>
          ))}
        </ul>
      );
      break;
    case "ST-METRIC-CANONICALIZE":
      icon = <Compass aria-hidden />;
      body = (
        <div className="flex flex-col gap-3 rounded-xl bg-paper-sunken p-5 text-sm">
          <div className="flex items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-ember-soft text-ember-strong">
              <Compass className="size-5" />
            </div>
            <div>
              <p className="font-semibold text-ink">Căn chuẩn tỉ lệ hệ mét & mặt sàn</p>
              <p className="text-xs text-ink-muted">Quy đổi toạ độ SFM sang đơn vị thực (mét) và đặt mặt phẳng sàn tại z = 0m</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 pt-2 text-xs">
            <div className="rounded-lg border border-line bg-paper p-3">
              <span className="text-ink-muted">Điểm neo kích thước:</span>
              <p className="mt-1 font-mono font-medium text-ink">Anchor A–B: 1.20 m</p>
            </div>
            <div className="rounded-lg border border-line bg-paper p-3">
              <span className="text-ink-muted">Độ lệch kiểm chuẩn:</span>
              <p className="mt-1 font-mono font-medium text-sage">Δ &lt; 0.8% (đạt)</p>
            </div>
          </div>
        </div>
      );
      break;
    case "ST-RGB-GEOMETRY":
      icon = <Layers aria-hidden />;
      body = (
        <div className="flex flex-col gap-3 rounded-xl bg-paper-sunken p-5 text-sm">
          <div className="flex items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-ember-soft text-ember-strong">
              <Layers className="size-5" />
            </div>
            <div>
              <p className="font-semibold text-ink">Lưới hình học & Voxel Occupancy</p>
              <p className="text-xs text-ink-muted">Trích xuất lưới va chạm và vùng di chuyển an toàn cho robot</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 pt-2 text-xs">
            <div className="rounded-lg border border-line bg-paper p-3">
              <span className="text-ink-muted">Độ phân giải Voxel:</span>
              <p className="mt-1 font-mono font-medium text-ink">0.05 m (5 cm)</p>
            </div>
            <div className="rounded-lg border border-line bg-paper p-3">
              <span className="text-ink-muted">Mặt phẳng sàn:</span>
              <p className="mt-1 font-mono font-medium text-ink">Ground Collider ready</p>
            </div>
          </div>
        </div>
      );
      break;
    case "ST-OBJECT-EXTRACT":
      icon = <Box aria-hidden />;
      body = (
        <div className="flex flex-col gap-3 rounded-xl bg-paper-sunken p-5 text-sm">
          <div className="flex items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-ember-soft text-ember-strong">
              <Box className="size-5" />
            </div>
            <div>
              <p className="font-semibold text-ink">Tách cụm vật thể & gán nhãn</p>
              <p className="text-xs text-ink-muted">Phân cụm 3DGS, sinh hộp bao bounding box và tách từng vật thể độc lập</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 pt-2 text-xs">
            <div className="rounded-lg border border-line bg-paper p-3">
              <span className="text-ink-muted">Thuật toán phân tách:</span>
              <p className="mt-1 font-mono font-medium text-ink">SAM2 + 3DGS cluster</p>
            </div>
            <div className="rounded-lg border border-line bg-paper p-3">
              <span className="text-ink-muted">Vật thể phát hiện:</span>
              <p className="mt-1 font-mono font-medium text-sage">Kệ hàng, pallet, thùng</p>
            </div>
          </div>
        </div>
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
        : stage === "ST-VISUAL-RECON"
          ? "Brush huấn luyện Gaussian Splatting tái dựng chi tiết quang cảnh 3D."
          : stage === "ST-METRIC-CANONICALIZE"
            ? "Xác nhận tỉ lệ thực tế theo mét và xoay hệ trục toạ độ sàn về phẳng."
            : stage === "ST-RGB-GEOMETRY"
              ? "Tạo lưới va chạm (collision mesh) và vùng không gian di chuyển cho robot."
              : stage === "ST-OBJECT-EXTRACT"
                ? "Tách các đối tượng độc lập trong kho để mô phỏng tương tác vật lý."
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
