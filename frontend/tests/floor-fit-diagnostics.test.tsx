import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewTab } from "@/features/studio/scene/ReviewTab";
import { floorFitDiagnostic } from "@/features/studio/scene/floorFitDiagnostic";
import { getJobScene } from "@/lib/api/studio";
import { buildFixtureScene } from "./fixtures/scene";

vi.mock("@/features/studio/ReviewPanel", () => ({ ReviewPanel: () => null }));
vi.mock("@/features/studio/SimulationPackagePanel", () => ({ SimulationPackagePanel: () => null }));
vi.mock("@/features/studio/evaluation/EvaluationCard", () => ({ EvaluationCard: () => null }));
vi.mock("@/features/studio/ValidationReportCard", () => ({ ValidationReportCard: () => null }));
vi.mock("@/lib/api/studio", async (loadOriginal) => ({
  ...(await loadOriginal<typeof import("@/lib/api/studio")>()),
  getJobScene: vi.fn(),
}));

const getJobSceneMock = vi.mocked(getJobScene);

describe("floor fit diagnostics", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps legacy and supported scenes quiet", () => {
    expect(floorFitDiagnostic({})).toBeNull();
    expect(floorFitDiagnostic({ floor_fit: { status: "supported" } })).toBeNull();
    expect(floorFitDiagnostic(null)).toBeNull();
  });

  it("explains confirmed-prior fallback with its band and evidence reference", () => {
    const result = floorFitDiagnostic({
      floor_fit: {
        status: "confirmed_prior_fallback",
        fallback_reason: "insufficient_coverage",
        floor_band_m: 0.09,
        artifact_ref: { artifact_uri: "artifact://jobs/job-1/scene/floor-fit/report.json" },
      },
    });

    expect(result?.tone).toBe("ochre");
    expect(result?.message).toContain("vùng quan sát mặt sàn còn hẹp");
    expect(result?.message).toContain("0.090 m");
    expect(result?.evidenceArtifactUri).toContain("floor-fit/report.json");
  });

  it("shows the persisted fallback diagnostic in Review without breaking old scene responses", async () => {
    const sceneResponse = buildFixtureScene();
    sceneResponse.scene.provenance = {
      floor_fit: {
        artifact_ref: { artifact_uri: "artifact://jobs/job-fixture-001/scene/floor-fit/report.json" },
        status: "confirmed_prior_fallback",
        fallback_reason: "insufficient_points",
        floor_band_m: 0.09,
      },
    };
    getJobSceneMock.mockResolvedValue({ ok: true, data: sceneResponse });

    render(<ReviewTab jobId="job-fixture-001" canMutateJob={false} onSaveState={vi.fn()} />);

    const notice = await screen.findByRole("note");
    expect(notice).toHaveTextContent("Mặt sàn đang dùng mốc REC-06 đã xác nhận");
    expect(notice).toHaveTextContent("0.090 m");
    expect(screen.getByText("artifact://jobs/job-fixture-001/scene/floor-fit/report.json")).toBeInTheDocument();
    await waitFor(() => expect(getJobSceneMock).toHaveBeenCalledWith("job-fixture-001", expect.any(AbortSignal)));
  });
});
