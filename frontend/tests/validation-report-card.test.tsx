/**
 * Thẻ báo cáo validation (S10): dữ liệu đi đúng đường thật — ValidationReport dạng contract (fixture của repo) →
 * parser ở biên API (`getReviewState`) → UI. Fixture là báo cáo tổng hợp, không phải kết quả Isaac.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ValidationReportCard } from "@/features/studio/ValidationReportCard";
import { getReviewState, type ReviewStateView } from "@/lib/api/studio";

type Report = { candidate_checksum: string; report_checksum: string; environment_versions: Record<string, string> } & Record<string, unknown>;

function fixture(name: string): Report {
  return JSON.parse(readFileSync(resolve(__dirname, "../../fixtures/validation_report", name), "utf8")) as Report;
}

const PASSED = fixture("validation_report.json");
const FAILED = fixture("failed_validation_report.json");

/** Trạng thái duyệt như backend trả (`ReviewState`), rồi đi qua parser thật của client. */
async function parsed(report: Report | null, extra: Record<string, unknown> = {}): Promise<ReviewStateView> {
  const body = {
    job_id: "job-a",
    record: {
      scene_revision: "rev-004",
      status: report ? "READY_FOR_REVIEW" : "CANDIDATE_READY",
      candidate_checksum: report?.candidate_checksum ?? PASSED.candidate_checksum,
      validation_report_checksum: report?.report_checksum ?? null,
    },
    validation: report,
    isaac_runtime_proof: report ? false : null,
    warning_ids: [],
    approval: null,
    release: null,
    release_archive: null,
    blockers: [],
    ...extra,
  };
  vi.mocked(global.fetch).mockResolvedValueOnce({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) } as Response);
  return getReviewState("job-a");
}

describe("ValidationReportCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("báo cáo không có bằng chứng Isaac: hiện cảnh báo kèm môi trường, check, Start–Goal và bằng chứng", async () => {
    render(<ValidationReportCard state={await parsed(PASSED)} />);
    const card = screen.getByRole("region", { name: "Báo cáo validation" });
    expect(within(card).getByText("Chưa có bằng chứng chạy Isaac Sim thật.")).toBeInTheDocument();
    expect(within(card).getByText("isaac_sim=UNVERIFIED, gpu=UNVERIFIED")).toBeInTheDocument();
    expect(within(card).getByText("ISAAC_LOAD")).toBeInTheDocument();
    expect(within(card).getByText("Synthetic fixture result; Isaac was not executed.")).toBeInTheDocument();
    expect(within(card).getByText("fixture-pair-001")).toBeInTheDocument();
    expect(within(card).getByText("Thông · CLEAR")).toBeInTheDocument();
    // Kết luận chung và check đều PASS nhưng luôn đi cùng cảnh báo ở trên.
    expect(within(card).getAllByText("Đạt · PASS").length).toBeGreaterThanOrEqual(2);
    expect(within(card).getAllByText("Bằng chứng (1)").length).toBeGreaterThanOrEqual(1);
    expect(within(card).getAllByText("artifact://jobs/job-fixture-001/simulation/validation_evidence.json").length).toBeGreaterThanOrEqual(1);
  });

  it("Nguồn kết quả cho đối chiếu revision, checksum gói và checksum báo cáo; nút chép báo kết quả", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<ValidationReportCard state={await parsed(PASSED)} />);
    expect(screen.getByText("rev-004")).toBeInTheDocument();
    expect(screen.getByText(PASSED.candidate_checksum)).toBeInTheDocument();
    expect(screen.getByText(PASSED.report_checksum)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chép checksum báo cáo" }));
    expect(await screen.findByText("Đã chép")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(PASSED.report_checksum);
  });

  it("không chép được thì báo lỗi thay vì im lặng", async () => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    render(<ValidationReportCard state={await parsed(PASSED)} />);
    fireEvent.click(screen.getByRole("button", { name: "Chép checksum báo cáo" }));
    expect(await screen.findByText("Không chép được")).toBeInTheDocument();
  });

  it("có bằng chứng Isaac thật thì không hiện cảnh báo; cờ vắng mặt thì vẫn cảnh báo", async () => {
    const { unmount } = render(<ValidationReportCard state={await parsed(PASSED, { isaac_runtime_proof: true })} />);
    expect(screen.queryByText("Chưa có bằng chứng chạy Isaac Sim thật.")).toBeNull();
    unmount();
    render(<ValidationReportCard state={await parsed(PASSED, { isaac_runtime_proof: undefined })} />);
    expect(screen.getByText("Chưa có bằng chứng chạy Isaac Sim thật.")).toBeInTheDocument();
  });

  it("báo cáo không đạt: check lỗi vẫn là blocker, không hiển thị như warning có thể chấp nhận", async () => {
    render(<ValidationReportCard state={await parsed(FAILED)} />);
    expect(screen.getAllByText("Không đạt · FAIL").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("ROBOT_SPAWN")).toBeInTheDocument();
    expect(screen.queryByText("Cần Reviewer chấp nhận")).toBeNull();
    expect(screen.getByText("Lỗi · ERROR")).toBeInTheDocument();
  });

  it("optional path warning is marked for Reviewer acceptance on its path row", async () => {
    const state = await parsed(PASSED, { isaac_runtime_proof: true, warning_ids: ["path:fixture-pair-001"] });
    render(<ValidationReportCard state={state} />);
    const row = screen.getByText("fixture-pair-001").closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Cần Reviewer chấp nhận")).toBeInTheDocument();
  });

  it("CLEAR without source-bound collision coverage is shown as an unverified claim", async () => {
    const state = await parsed(PASSED, {
      isaac_runtime_proof: true,
      warning_ids: ["collision-support:fixture-pair-001"],
    });
    render(<ValidationReportCard state={state} />);

    const row = screen.getByText("fixture-pair-001").closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText(/CLEAR chỉ là kết quả quan sát của candidate/)).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("Cần Reviewer chấp nhận")).toBeInTheDocument();
  });

  it("shows motion-suspected path coverage in clear Vietnamese", async () => {
    const report = {
      ...PASSED,
      collision_quality_ref: {
        artifact_type: "CollisionQualityReport",
        schema_version: "1.0",
        artifact_uri: "artifact://jobs/job-fixture-001/collision/quality.json",
        artifact_checksum: "sha256:" + "b".repeat(64),
        data_class: "derived",
        producer_stage: "ST-COLLIDER",
        job_id: "job-fixture-001",
      },
      collision_path_support: [
        {
          pair_id: "fixture-pair-001",
          state: "motion_suspected",
          observation_ids: [],
          coverage_fraction: 0,
          diagnostic_ref: {
            artifact_type: "CollisionPathCoverageDiagnostic",
            schema_version: "1.0",
            artifact_uri: "artifact://jobs/job-fixture-001/collision/path-pair-1.json",
            artifact_checksum: "sha256:" + "c".repeat(64),
            data_class: "derived",
            producer_stage: "ST-ISAAC-VALIDATE",
            job_id: "job-fixture-001",
          },
        },
      ],
    } as Report;
    const state = await parsed(report, {
      isaac_runtime_proof: true,
      warning_ids: ["collision-support:fixture-pair-001"],
    });
    expect(state.validation?.collision_path_support).toMatchObject([
      { pair_id: "fixture-pair-001", state: "motion_suspected", coverage_fraction: 0 },
    ]);
    render(<ValidationReportCard state={state} />);

    const row = screen.getByText("fixture-pair-001").closest("li");
    expect(row?.textContent).toContain("Coverage collider 0.0% · nghi có chuyển động");
    fireEvent.click(within(row as HTMLElement).getByText("Bằng chứng (2)"));
    expect(within(row as HTMLElement).getByText("artifact://jobs/job-fixture-001/collision/path-pair-1.json")).toBeInTheDocument();
  });

  it("báo cáo của gói khác với gói hiện tại thì cảnh báo không khớp", async () => {
    const state = await parsed(PASSED);
    render(<ValidationReportCard state={{ ...state, record: { ...state.record, candidate_checksum: "sha256:" + "0".repeat(64) } }} />);
    expect(screen.getByText(/thuộc một gói khác/)).toBeInTheDocument();
  });

  it("chưa có báo cáo thì không vẽ gì (màn duyệt giữ trạng thái Chưa khả dụng)", async () => {
    const { container } = render(<ValidationReportCard state={await parsed(null)} />);
    expect(container).toBeEmptyDOMElement();
  });
});
