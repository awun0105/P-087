/** Khung xem trước của phát lại mẫu: chỉ vẽ bằng chứng có thật trong bundle, ghép thẻ theo registry. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoShowcase } from "@/features/studio/DemoShowcase";
import { parseDemoManifest, type DemoManifest, type DemoStage } from "@/lib/contracts/studio";

const file = (name: string) => ({ name, media_type: "image/png", size_bytes: 10, checksum: "sha256:" + "0".repeat(64) });
const fileUrl = (name: string) => `/files/${name}`;

function manifest(stages: DemoStage[]): DemoManifest {
  return {
    schema_version: "1.0", demo_id: "d", title: "Mẫu", description: "", origin: "pipeline_job",
    source: { dataset: "TorWIC", sequence: "Aisle", note: "" }, produced_at: "2026-10-10T00:00:00Z", provenance: {},
    stages, video: null, frames: [file("frame-1.png"), file("frame-2.png")], frame_count: 40,
    splat: { ...file("scene.sog"), media_type: "application/octet-stream" },
  };
}
const stage = (stage_id: DemoStage["stage_id"], extra: Partial<DemoStage> = {}): DemoStage => ({ stage_id, duration_seconds: 12, summary: "", ...extra });

describe("khung xem trước phát lại", () => {
  it("bước chưa có bằng chứng nói thẳng và không vẽ số liệu", () => {
    const demo = manifest([stage("ST-METRIC-CANONICALIZE", { state: "pending", duration_seconds: null, summary: "Mẫu này chưa ghi kết quả của bước này." })]);
    render(<DemoShowcase demo={demo} stage="ST-METRIC-CANONICALIZE" fraction={1} fileUrl={fileUrl} />);
    expect(screen.getByRole("status")).toHaveTextContent("chưa ghi kết quả");
    for (const invented of [/1\.20 m/, /Voxel/, /SAM2/, /Kệ hàng/, /Δ/]) expect(screen.queryByText(invented)).toBeNull();
  });

  it("bước đã chạy nhưng bundle không kèm thẻ nào thì báo chưa có hình/số đo", () => {
    const demo = manifest([stage("ST-RGB-GEOMETRY")]);
    render(<DemoShowcase demo={demo} stage="ST-RGB-GEOMETRY" fraction={1} fileUrl={fileUrl} />);
    expect(screen.getByRole("status")).toHaveTextContent("mẫu chưa kèm hình hay số đo");
  });

  it("ghép thẻ asset của bundle: số đo và ảnh lấy từ dữ liệu khai báo", () => {
    const demo = manifest([
      stage("ST-METRIC-CANONICALIZE", {
        assets: [
          { kind: "facts", title: "Số đo đã xác nhận", facts: [{ label: "Khoảng cách A–B", value: "1.35 m" }] },
          { kind: "image", title: "Điểm đo", file: file("metric-1.png"), caption: "A, B và mặt sàn" },
        ],
      }),
    ]);
    render(<DemoShowcase demo={demo} stage="ST-METRIC-CANONICALIZE" fraction={1} fileUrl={fileUrl} />);
    expect(screen.getByText("Khoảng cách A–B")).toBeInTheDocument();
    expect(screen.getByText("1.35 m")).toBeInTheDocument();
    expect(screen.getByAltText("Điểm đo")).toHaveAttribute("src", "/files/metric-1.png");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("thẻ dựng sẵn của bước tách frame dùng frame của bundle", () => {
    const demo = manifest([stage("ST-FRAME-EXTRACT")]);
    render(<DemoShowcase demo={demo} stage="ST-FRAME-EXTRACT" fraction={1} fileUrl={fileUrl} />);
    expect(screen.getByLabelText("Khung hình đã tách").querySelectorAll("img")).toHaveLength(2);
    expect(screen.getByText(/40 khung hình được giữ lại/)).toBeInTheDocument();
  });
});

describe("parseDemoManifest với asset", () => {
  const base = () => JSON.parse(JSON.stringify(manifest([stage("ST-METRIC-CANONICALIZE")])));

  it("chấp nhận asset hợp lệ và bundle cũ không có asset", () => {
    const value = base();
    expect(parseDemoManifest(value).stages).toHaveLength(1);
    value.stages[0].assets = [{ kind: "facts", facts: [{ label: "a", value: "b" }] }, { kind: "image", file: file("ok.png") }];
    expect(parseDemoManifest(value).stages[0].assets).toHaveLength(2);
  });

  it("từ chối kind lạ, facts rỗng và tên file không an toàn", () => {
    for (const bad of [
      { kind: "facts", facts: [] },
      { kind: "image", file: file("../x.png") },
      { kind: "facts", facts: [{ label: "a", value: "b" }], file: file("x.png") },
    ]) {
      const value = base();
      value.stages[0].assets = [bad];
      expect(() => parseDemoManifest(value)).toThrow();
    }
  });

  it("backend mới hơn có loại thẻ lạ: bỏ riêng thẻ đó, không làm hỏng cả mẫu", () => {
    const value = base();
    value.stages[0].assets = [{ kind: "hologram", file: file("x.png") }, { kind: "facts", facts: [{ label: "a", value: "b" }] }];
    const parsed = parseDemoManifest(value);
    expect(parsed.stages[0].assets).toEqual([{ kind: "facts", facts: [{ label: "a", value: "b" }] }]);
  });
});
