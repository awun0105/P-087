"use client";

import { Aperture, Cpu, Images, ScanSearch, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import type { StageId } from "@/lib/contracts/api";
import type { DemoManifest, DemoStage, DemoStageAsset } from "@/lib/contracts/studio";

/**
 * Khung chung của khung xem trước trong phát lại mẫu.
 *
 * - Một **thẻ** là hàm nhận `ShowcaseContext` và trả về phần nội dung hiển thị. Thẻ chỉ được vẽ từ file và số đo có
 *   thật trong bundle; không có thì không vẽ gì (khung hiện "chưa ghi kết quả"), tuyệt đối không điền số giả.
 * - `STAGE_PRESENTERS`: thẻ dựng sẵn theo bước, dùng file chung của bundle (video gốc, frame, 3DGS).
 * - `ASSET_RENDERERS`: thẻ theo loại asset mà bundle khai báo cho từng bước (`stage.assets`).
 *
 * Thêm cảnh demo mới: ghi asset vào bundle (xem docs/DEMO_SCENES.md). Thêm kiểu thẻ mới: thêm kind ở backend
 * (`DemoStageAsset`) và `contracts/studio.ts`, rồi đăng ký một renderer ở đây.
 */
export interface ShowcaseContext {
  demo: DemoManifest;
  stage: StageId;
  /** Tiến độ phát lại của bước, 0..1. */
  fraction: number;
  fileUrl: (name: string) => string;
}

export type ShowcaseRenderer = (context: ShowcaseContext) => ReactNode;

export interface StagePresenter {
  icon: ReactNode;
  handlesAssets?: boolean;
  render: ShowcaseRenderer;
  caption?: (context: ShowcaseContext) => string | undefined;
}

function FrameImage({ src }: { src?: string }) {
  if (!src) return <div className="aspect-video rounded-xl bg-viewport" />;
  // eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API
  return <img src={src} alt="" className="aspect-video w-full rounded-xl object-cover" />;
}

function coverOf(demo: DemoManifest) {
  return demo.frames[Math.floor(demo.frames.length / 2)];
}

function StageResults(context: ShowcaseContext) {
  const record = context.demo.stages.find((stage) => stage.stage_id === context.stage);
  const assets = record?.assets ?? [];
  if (!assets.length) return null;
  return <div className="space-y-4">{assets.map((asset, index) => (
    <div key={index}>
      {asset.title && <p className="mb-2 text-sm font-medium">{asset.title}</p>}
      {ASSET_RENDERERS[asset.kind](asset, context)}
    </div>
  ))}</div>;
}

export const STAGE_PRESENTERS: Partial<Record<StageId, StagePresenter>> = {
  "ST-METRIC-CANONICALIZE": { icon: <Aperture aria-hidden />, render: StageResults, handlesAssets: true },
  "ST-RGB-GEOMETRY": { icon: <Images aria-hidden />, render: StageResults, handlesAssets: true },
  "ST-OBJECT-EXTRACT": { icon: <ScanSearch aria-hidden />, render: StageResults, handlesAssets: true },
  "ST-INPUT-VALIDATE": {
    icon: <ScanSearch aria-hidden />,
    render: ({ demo, fileUrl }) =>
      demo.video ? (
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
        <FrameImage src={coverOf(demo) ? fileUrl(coverOf(demo)!.name) : undefined} />
      ),
  },
  "ST-PRIVACY-GATE": {
    icon: <ShieldCheck aria-hidden />,
    render: ({ demo }) => (
      <div className="grid aspect-video place-items-center rounded-xl bg-paper-sunken p-6 text-center">
        <div className="max-w-sm">
          <ShieldCheck className="mx-auto size-10 text-sage" aria-hidden />
          <p className="mt-3 text-sm font-medium text-ink">Nguồn dữ liệu: {demo.source.dataset}</p>
          <p className="mt-1 text-sm text-ink-muted">{demo.source.sequence}</p>
        </div>
      </div>
    ),
  },
  "ST-FRAME-EXTRACT": {
    icon: <Images aria-hidden />,
    render: (context) => <FrameGrid context={context} withCameras={false} />,
    caption: ({ demo }) =>
      demo.frame_count ? `${demo.frame_count} khung hình được giữ lại để dựng 3D (hiển thị ${demo.frames.length} ảnh đại diện).` : undefined,
  },
  "ST-CAMERA-POSE": {
    icon: <Aperture aria-hidden />,
    render: (context) => <FrameGrid context={context} withCameras />,
    caption: () => "COLMAP khớp điểm đặc trưng giữa các ảnh để tìm vị trí camera của từng khung hình.",
  },
  "ST-VISUAL-RECON": {
    icon: <Cpu aria-hidden />,
    render: ({ demo, fileUrl, fraction }) => {
      const cover = coverOf(demo);
      return (
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
    },
    caption: () => "Brush huấn luyện Gaussian Splatting tái dựng chi tiết quang cảnh 3D.",
  },
};

function FrameGrid({ context, withCameras }: { context: ShowcaseContext; withCameras: boolean }) {
  const { demo, fraction, fileUrl } = context;
  const revealed = Math.max(1, Math.ceil(demo.frames.length * Math.min(1, fraction)));
  return (
    <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4" aria-label="Khung hình đã tách">
      {demo.frames.map((frame, index) => (
        <li
          key={frame.name}
          className={cn(
            "relative aspect-video overflow-hidden rounded-lg bg-paper-sunken transition-opacity duration-300",
            !withCameras && index >= revealed && "opacity-0",
          )}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API */}
          <img src={fileUrl(frame.name)} alt="" className="size-full object-cover" loading="lazy" decoding="async" />
          {withCameras && index < revealed && (
            <span className="absolute top-1.5 left-1.5 rounded border border-line-dark bg-viewport-deep/85 px-1.5 py-0.5 font-mono text-[10px] text-on-dark">
              ảnh {index + 1}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export type AssetRenderer = (asset: DemoStageAsset, context: ShowcaseContext) => ReactNode;

export const ASSET_RENDERERS: Record<DemoStageAsset["kind"], AssetRenderer> = {
  image: (asset, { fileUrl }) =>
    asset.file ? (
      <figure>
        {/* eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API */}
        <img src={fileUrl(asset.file.name)} alt={asset.title ?? ""} className="w-full rounded-xl bg-viewport object-contain" loading="lazy" />
        {asset.caption && <figcaption className="mt-1.5 text-xs text-ink-muted">{asset.caption}</figcaption>}
      </figure>
    ) : null,
  video: (asset, { fileUrl }) =>
    asset.file ? (
      <figure>
        <video
          src={fileUrl(asset.file.name)}
          className="aspect-video w-full rounded-xl bg-viewport object-cover"
          muted
          loop
          autoPlay
          playsInline
          aria-label={asset.title || "Video kết quả của bước"}
        />
        {asset.caption && <figcaption className="mt-1.5 text-xs text-ink-muted">{asset.caption}</figcaption>}
      </figure>
    ) : null,
  facts: (asset) =>
    asset.facts && asset.facts.length > 0 ? (
      <dl className="grid grid-cols-2 gap-2 text-xs">
        {asset.facts.map((fact, index) => (
          <div key={`${fact.label}-${index}`} className="rounded-lg border border-line bg-paper p-3">
            <dt className="text-ink-muted">{fact.label}</dt>
            <dd className="mt-1 font-mono font-medium text-ink">{fact.value}</dd>
          </div>
        ))}
      </dl>
    ) : null,
};

/** Bước đã có bằng chứng thật trong bundle (đã chạy xong); bước pending/failed không được vẽ như thành công. */
export function hasEvidence(record: DemoStage | undefined): boolean {
  return record !== undefined && (record.state ?? "succeeded") === "succeeded";
}

