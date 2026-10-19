import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StudioTab } from "@/features/studio/scene/StudioTab";
import type { MetricDraft } from "@/features/studio/MetricConfirmView";
import type { Preview } from "@/features/studio/scene/state";

vi.mock("@/features/studio/scene/PreviewScene", () => ({
  PreviewScene: ({ title }: { title: string }) => <div role="img" aria-label={title} />,
}));
vi.mock("@/features/studio/EditorFrame", () => ({ EditorFrame: () => <p>Gaussian editor</p> }));
vi.mock("@/features/studio/MetricConfirmView", () => ({ MetricConfirmView: () => <p>Metric editor</p> }));
vi.mock("@/features/studio/ObjectReviewView", () => ({ ObjectReviewView: () => <p>Object editor</p> }));

const preview: Preview = { url: "/preview.sog", filename: "preview.sog" };
const metricDraft: MetricDraft = { points: [], typed: { anchor: "", check: "" } };
const props = {
  jobId: "job-1",
  title: "Kho A",
  preview,
  mode: "metric" as const,
  geometry: "succeeded" as const,
  sceneReady: true,
  revision: "rev-001",
  onSaveState: vi.fn(),
  onMetricClose: vi.fn(),
  onMetricConfirmed: vi.fn(),
  metricDraft,
};

describe("StudioTab ownership capabilities", () => {
  it("keeps a foreign scene viewable but never mounts mutation editors", () => {
    render(<StudioTab {...props} canMutate={false} />);

    expect(screen.getByText("Bạn đang xem scene của người khác. Scene này ở chế độ chỉ xem.")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Viewer 3DGS: Kho A" })).toBeInTheDocument();
    expect(screen.queryByText("Metric editor")).toBeNull();
    expect(screen.queryByText("Object editor")).toBeNull();
    expect(screen.queryByText("Gaussian editor")).toBeNull();
  });

  it("keeps owner editing available when the daily run quota is a separate concern", () => {
    render(<StudioTab {...props} canMutate />);
    expect(screen.getByText("Metric editor")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Viewer 3DGS: Kho A" })).toBeNull();
  });
});
