"use client";

import { useEffect, useState } from "react";

import { Badge, Card, Notice } from "@/components/studio/primitives";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import { parseLidarCalibrationQAReport, type LidarCalibrationQAReport } from "@/lib/contracts/lidarCalibrationQA";
import type { ProductArtifactRef } from "@/lib/contracts/api";

export function LidarCalibrationQAStage({ jobId, artifacts }: { jobId: string; artifacts: ProductArtifactRef[] }) {
  const reportRef = artifacts.find((ref) => ref.artifact_type === "LidarCalibrationQAReport");
  const [report, setReport] = useState<LidarCalibrationQAReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!reportRef) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(jobArtifactContentUrl(jobId, reportRef), { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const value: unknown = await response.json();
        if (!controller.signal.aborted) setReport(parseLidarCalibrationQAReport(value, jobId));
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Không đọc được báo cáo QA.");
      }
    })();
    return () => controller.abort();
  }, [jobId, reportRef?.artifact_checksum, reportRef?.artifact_uri]);

  if (!reportRef) {
    return <Notice tone="ochre" className="m-4">Job cũ chưa có artifact QA calibration. Tạo job mới để chạy QA trên dữ liệu đầu vào hiện tại.</Notice>;
  }
  if (error) return <Notice tone="rust" className="m-4">Không thể xác minh báo cáo QA calibration: {error}</Notice>;
  if (!report) return <p role="status" className="p-6 text-sm text-ink-muted">Đang tải báo cáo QA calibration…</p>;

  const status = report.result === "FAIL" ? "Có lỗi cấu trúc" : "Chẩn đoán, chưa đủ điều kiện nghiệm thu";
  const statusTone = report.result === "FAIL" ? "rust" : "ochre";
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <Notice tone="ochre">
        <div className="flex flex-wrap items-center gap-2"><Badge tone={statusTone}>{status}</Badge><Badge tone="neutral">Collision eligibility: không</Badge></div>
        <p className="mt-2">Overlay và điểm số chỉ có giá trị chẩn đoán. Ngưỡng sản xuất và kiểm chứng trên chuỗi thực địa held-out vẫn đang chờ; kết quả này không được dùng làm collision source.</p>
        <p className="mt-1">Muốn thay calibration hoặc timing, hãy tạo job mới để giữ nguyên report và artifact bất biến của job này.</p>
      </Notice>

      <Card className="p-5">
        <h2 className="text-lg font-bold">Tóm tắt phép chiếu</h2>
        <dl className="mt-3 grid gap-x-6 divide-y divide-line sm:grid-cols-2 sm:divide-y-0">
          <Metric label="Frame lấy mẫu" value={`${report.sampled_frame_count}`} />
          <Metric label="Frame ghép được với pose LiDAR" value={`${report.matched_frame_count}`} />
          <Metric label="Frame có overlap đủ theo profile" value={`${report.observable_frame_count}`} />
          <Metric label="Điểm LiDAR được chiếu" value={`${report.projected_point_count.toLocaleString("vi-VN")}`} />
          <Metric label="Điểm nằm gần cạnh ảnh" value={`${report.overlap_point_count.toLocaleString("vi-VN")}`} />
          <Metric label="Tỉ lệ overlap" value={report.overlap_fraction === null ? "Chưa đo được" : `${(report.overlap_fraction * 100).toFixed(1)}%`} />
          <Metric label="Sai lệch timestamp lớn nhất" value={report.maximum_timestamp_residual_sec === null ? "Chưa đo được" : `${(report.maximum_timestamp_residual_sec * 1000).toFixed(1)} ms`} />
          <Metric label="Khả năng quan sát" value={report.observability} />
        </dl>
      </Card>

      <Card className="p-5">
        <h2 className="text-lg font-bold">Phát hiện và hướng xử lý</h2>
        {report.findings.length === 0
          ? <p className="mt-3 text-sm text-ink-muted">Không có phát hiện bổ sung.</p>
          : <ul className="mt-3 divide-y divide-line">{report.findings.map((finding, index) => (
            <li key={`${finding.code}:${index}`} className="py-3">
              <p className="font-mono text-xs text-ink-muted">{finding.code}</p>
              <p className="mt-1 text-sm">{finding.detail}</p>
              <p className="mt-1 text-sm text-ember-strong">Cách xử lý: {finding.remediation}</p>
            </li>
          ))}</ul>}
      </Card>

      <Card className="p-5">
        <h2 className="text-lg font-bold">Overlay LiDAR trên frame RGB ({report.overlay_refs.length})</h2>
        {report.overlay_refs.length === 0
          ? <p className="mt-3 text-sm text-ink-muted">Chưa có overlay inspectable. Xem các finding để biết dữ liệu hoặc khai báo nào còn thiếu.</p>
          : <ul className="mt-4 grid gap-4 lg:grid-cols-2">{report.overlay_refs.map((ref) => (
            <li key={`${ref.artifact_uri}:${ref.artifact_checksum}`} className="overflow-hidden rounded-xl border border-line bg-paper-raised p-2">
              <img src={jobArtifactContentUrl(jobId, ref)} alt="Frame RGB với các điểm chiếu LiDAR màu cyan" className="h-auto max-h-[70vh] w-full object-contain" />
              <p className="mt-2 break-all font-mono text-[10px] text-ink-subtle">{ref.artifact_uri.split("/").pop()}</p>
            </li>
          ))}</ul>}
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="grid gap-1 py-2 sm:grid-cols-[14rem_1fr]"><dt className="text-sm text-ink-muted">{label}</dt><dd className="break-all text-sm">{value}</dd></div>;
}
