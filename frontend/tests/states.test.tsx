/**
 * Test cho các trạng thái dùng chung.
 *
 * Mục đích: khoá lại rằng lỗi/rỗng/rỗng-dữ-liệu đều render ra chữ, chứ không
 * phải màn hình trắng. Đây là bài test rẻ nhất chống lại kiểu hỏng khó thấy nhất.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Checksum, EmptyState, ErrorState, JobStatusBadge, LoadingState, PrivacyBadge } from "@/components/states";
import { JOB_STATUSES, PRIVACY_RESULTS } from "@/lib/contracts/api";

describe("ErrorState", () => {
  it("hiện tiêu đề và detail nguyên văn", () => {
    render(<ErrorState title="Không tải được job" detail="404: không tìm thấy job: x" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Không tải được job");
    expect(alert).toHaveTextContent("404: không tìm thấy job: x");
  });
});

describe("EmptyState và LoadingState", () => {
  it("hiện thông điệp rỗng", () => {
    render(<EmptyState message="Chưa có project nào." />);
    expect(screen.getByTestId("empty-state")).toHaveTextContent("Chưa có project nào.");
  });

  it("hiện nhãn đang tải", () => {
    render(<LoadingState label="Đang tải scene…" />);
    expect(screen.getByTestId("loading-state")).toHaveTextContent("Đang tải scene…");
  });
});

describe("JobStatusBadge", () => {
  it("render được mọi trạng thái trong contract", () => {
    for (const status of JOB_STATUSES) {
      const { unmount } = render(<JobStatusBadge status={status} />);
      expect(screen.getByTestId("job-status")).toHaveTextContent(status);
      unmount();
    }
  });
});

describe("PrivacyBadge", () => {
  it("nói rõ gate cho phép hay chặn dispatch", () => {
    const { unmount } = render(<PrivacyBadge result="VERIFIED_ANONYMIZED" dispatchAllowed />);
    expect(screen.getByTestId("privacy-badge")).toHaveTextContent("cho phép dispatch");
    unmount();

    render(<PrivacyBadge result="PRELIMINARY_SCREENED" dispatchAllowed={false} />);
    expect(screen.getByTestId("privacy-badge")).toHaveTextContent("chặn dispatch");
  });

  it("render được mọi kết quả privacy trong contract", () => {
    for (const result of PRIVACY_RESULTS) {
      const { unmount } = render(<PrivacyBadge result={result} dispatchAllowed={false} />);
      expect(screen.getByTestId("privacy-badge")).toHaveTextContent(result);
      unmount();
    }
  });
});

describe("Checksum", () => {
  it("rút gọn checksum dài nhưng giữ nguyên trong title", () => {
    const full = `sha256:${"a".repeat(64)}`;
    render(<Checksum value={full} label="input" />);
    const node = screen.getByTitle(full);
    expect(node.textContent).toContain("input:");
    expect(node.textContent).not.toContain(full);
  });

  it("hiện dấu gạch khi không có checksum", () => {
    render(<Checksum value={null} />);
    expect(screen.getByText("—")).toBeDefined();
  });
});
