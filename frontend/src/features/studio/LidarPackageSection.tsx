"use client";

import { Radar } from "lucide-react";
import { useId, useState } from "react";

import { Badge, Card, Notice } from "@/components/studio/primitives";
import { describeDetection, inputKind, isLidar } from "@/features/studio/inputKinds";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { cn } from "@/lib/cn";
import type { LidarAttachment, UploadRecord } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";

/** Lựa chọn LiDAR của form tạo scene: gói đã chọn và hai lời khai contract bắt buộc cho đầu vào RGB + LiDAR. */
export interface LidarChoice {
  uploadId: string | null;
  trajectoryOrigin: "estimated" | "ground_truth" | null;
  sameScene: boolean;
}

export const NO_LIDAR: LidarChoice = { uploadId: null, trajectoryOrigin: null, sameScene: false };

/** Lý do chưa gửi được (null = hợp lệ); không chọn gói thì luôn hợp lệ vì LiDAR là tuỳ chọn. */
export function lidarBlocker(choice: LidarChoice): string | null {
  if (!choice.uploadId) return null;
  if (!choice.trajectoryOrigin) return "Chưa khai nguồn gốc quỹ đạo LiDAR";
  if (!choice.sameScene) return "Chưa xác nhận video và LiDAR cùng một lượt quay";
  return null;
}

export function lidarAttachment(choice: LidarChoice): LidarAttachment | undefined {
  if (!choice.uploadId || !choice.trajectoryOrigin || !choice.sameScene) return undefined;
  return { upload_id: choice.uploadId, trajectory_origin: choice.trajectoryOrigin, same_scene_confirmed: true };
}

const FLOWS: { id: string; title: string; needs: string; result: string }[] = [
  { id: "A", title: "Chỉ video", needs: "Không cần gì thêm.", result: "Tỉ lệ mét là ước lượng tự động hoặc số đo tay của bạn; mesh va chạm dựng từ 3DGS." },
  { id: "B", title: "Video + LiDAR đã đăng ký", needs: "Gói .zip: một đám mây .ply/.pcd đã ghép + quỹ đạo + calibration + thời điểm frame.", result: "Tỉ lệ mét và mặt sàn lấy từ LiDAR; bạn không phải chọn điểm." },
  { id: "C", title: "Video + scan LiDAR thô", needs: "Gói .zip: các scan .pcd chưa ghép + quỹ đạo + calibration + thời điểm frame.", result: "Hệ thống ghép scan theo quỹ đạo thành đám mây đã đăng ký, rồi xử lý như luồng B." },
];

/**
 * Ô LiDAR tuỳ chọn của trang Dựng từ video (ADR 0009, STUDIO_UX_SPEC `/new/import-video`): giải thích ba luồng và dữ
 * liệu từng luồng cần, cho tải hoặc chọn gói LiDAR, hiện kết quả máy chủ nhận diện, và lấy hai lời khai bắt buộc.
 * Loại gói do máy chủ nhận diện theo nội dung; trang chỉ hiển thị, không tự đoán từ tên file.
 */
export function LidarPackageSection({ uploads, choice, onChange, onUploaded }: {
  uploads: UploadRecord[];
  choice: LidarChoice;
  onChange: (choice: LidarChoice) => void;
  onUploaded: (record: UploadRecord) => void;
}) {
  const ids = { origin: useId() };
  const [notice, setNotice] = useState<string | null>(null);
  const packages = uploads.filter(isLidar);
  const selected = packages.find((item) => item.upload_id === choice.uploadId) ?? null;
  const flow = !selected ? "A" : inputKind(selected) === "lidar_scan_sequence" ? "C" : "B";

  return (
    <Card className="p-5 sm:p-6">
      <h2 className="flex flex-wrap items-center gap-2 text-base font-bold">
        <Radar className="size-4" aria-hidden /> Dữ liệu LiDAR
        <Badge tone="neutral">Không bắt buộc</Badge>
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        Có LiDAR của đúng lượt quay này thì scene lấy tỉ lệ mét từ LiDAR thay cho ước lượng. Hệ thống chọn luồng xử lý theo dữ liệu bạn nộp:
      </p>
      <ul className="mt-4 grid gap-3 md:grid-cols-3" aria-label="Ba luồng xử lý">
        {FLOWS.map((item) => (
          <li key={item.id} aria-current={flow === item.id ? "true" : undefined} className={cn("rounded-xl border p-3 text-sm", flow === item.id ? "border-ember bg-ember-soft/50" : "border-line")}>
            <p className="label-tech text-ink-muted">Luồng {item.id}{flow === item.id ? " · sẽ chạy" : ""}</p>
            <p className="mt-1 font-semibold text-ink">{item.title}</p>
            <p className="mt-1 text-ink-muted">{item.needs}</p>
            <p className="mt-1 text-ink-subtle">{item.result}</p>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-subtle">
        Yêu cầu của gói: quỹ đạo dạng TUM (mỗi dòng <code>thời_điểm x y z qx qy qz qw</code>) là vị trí cảm biến LiDAR, đơn vị mét, trục Z hướng lên;
        dòng thứ <em>i</em> ứng với frame thứ <em>i</em> của video; calibration là phép biến đổi camera ↔ LiDAR của đúng camera quay video.
        Chỉ nộp scan thô mà không có quỹ đạo thì không dùng được: hệ thống không tự ước lượng quỹ đạo.
      </p>

      <fieldset className="mt-5 space-y-2">
        <legend className="text-sm font-medium">Gói LiDAR cho scene này</legend>
        <label className={cn("flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm", !choice.uploadId ? "border-ember bg-ember-soft/50" : "border-line hover:border-line-strong")}>
          <input type="radio" name="lidar" checked={!choice.uploadId} onChange={() => onChange(NO_LIDAR)} className="size-4 accent-ember-strong" />
          Không dùng LiDAR (luồng A)
        </label>
        {packages.map((item) => (
          <label key={item.upload_id} className={cn("flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm", choice.uploadId === item.upload_id ? "border-ember bg-ember-soft/50" : "border-line hover:border-line-strong")}>
            <input type="radio" name="lidar" value={item.upload_id} checked={choice.uploadId === item.upload_id} onChange={() => onChange({ uploadId: item.upload_id, trajectoryOrigin: null, sameScene: false })} className="size-4 accent-ember-strong" />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{item.original_name}</span>
              <span className="block text-ink-muted">
                {describeDetection(item)} · {formatBytes(item.size_bytes)}
                {item.uploaded_by && ` · tải lên bởi ${item.uploaded_by.display_name}`}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      <details className="mt-4 text-sm">
        <summary className="cursor-pointer font-medium text-ember-strong">Tải gói LiDAR mới</summary>
        <div className="mt-3">
          <UploadDropzone
            kind="lidar"
            onUploaded={(record) => {
              if (!isLidar(record)) {
                setNotice(`Máy chủ nhận diện file là ${describeDetection(record)}, không phải gói LiDAR; file không được dùng ở đây.`);
                return;
              }
              setNotice(null);
              onUploaded(record);
              onChange({ uploadId: record.upload_id, trajectoryOrigin: null, sameScene: false });
            }}
          />
          {notice && <Notice tone="ochre" className="mt-3">{notice}</Notice>}
        </div>
      </details>

      {selected && (
        <div className="mt-5 space-y-3 rounded-xl border border-line p-4 text-sm" data-testid="lidar-declarations">
          <p className="font-medium text-ink">Máy chủ nhận diện: {describeDetection(selected)} → luồng {flow}.</p>
          <fieldset>
            <legend id={ids.origin} className="font-medium">Quỹ đạo trong gói đến từ đâu?</legend>
            <div className="mt-2 space-y-2">
              <label className="flex cursor-pointer items-start gap-3">
                <input type="radio" name="trajectory-origin" checked={choice.trajectoryOrigin === "estimated"} onChange={() => onChange({ ...choice, trajectoryOrigin: "estimated" })} className="mt-0.5 size-4 accent-ember-strong" />
                <span>Tự tính bằng SLAM/odometry của bạn</span>
              </label>
              <label className="flex cursor-pointer items-start gap-3">
                <input type="radio" name="trajectory-origin" checked={choice.trajectoryOrigin === "ground_truth"} onChange={() => onChange({ ...choice, trajectoryOrigin: "ground_truth" })} className="mt-0.5 size-4 accent-ember-strong" />
                <span>Quỹ đạo chuẩn (ground truth) của một dataset — kết quả sẽ được ghi là có dùng ground truth</span>
              </label>
            </div>
          </fieldset>
          <label className="flex cursor-pointer items-start gap-3">
            <input type="checkbox" checked={choice.sameScene} onChange={(event) => onChange({ ...choice, sameScene: event.target.checked })} className="mt-0.5 size-4 accent-ember-strong" />
            <span>Video và gói LiDAR thuộc <strong>cùng một lượt quay</strong>, cùng một không gian; quỹ đạo có đúng một dòng cho mỗi frame của video.</span>
          </label>
        </div>
      )}
    </Card>
  );
}
