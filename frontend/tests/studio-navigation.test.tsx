/** Navigation và trạng thái khóa dùng được bằng keyboard; không cần canvas/GPU. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { isActive } from "@/features/shell/AppShell";
import { backHref, Breadcrumbs, crumbsFor, PageTitleProvider, usePageTitle } from "@/features/shell/Breadcrumbs";
import { SceneTabs, type SceneTabItem } from "@/features/studio/scene/SceneTabs";
import { progressSceneStatus } from "@/features/studio/sceneStatus";
import type { JobProgress } from "@/lib/contracts/studio";

describe("ngữ cảnh điều hướng", () => {
  it("active đúng nhóm route, không nhận prefix trùng tên", () => {
    expect(isActive("/overview", "/overview")).toBe(true);
    expect(isActive("/scenes/job-a", "/overview")).toBe(false);
    expect(isActive("/", "/overview")).toBe(false); // `/` là landing, không phải Tổng quan
    expect(isActive("/scenes", "/scenes")).toBe(true);
    expect(isActive("/scenes/job-a", "/scenes")).toBe(true);
    expect(isActive("/imports/import-a", "/scenes")).toBe(true);
    expect(isActive("/new", "/scenes")).toBe(true);
    expect(isActive("/", "/scenes")).toBe(false);
    expect(isActive("/scenes-old", "/scenes")).toBe(false);
    expect(isActive("/overview-old", "/overview")).toBe(false);
    expect(isActive("/trash-old", "/trash")).toBe(false);
    expect(isActive("/trash", "/trash")).toBe(true);
  });

  it("Tổng quan tách khỏi Scenes; breadcrumb chi tiết quay lại thư viện", () => {
    expect(crumbsFor("/overview")).toEqual([{ label: "Tổng quan" }]);
    expect(crumbsFor("/trang-la")).toEqual([{ label: "Tổng quan", href: "/overview" }]);
    expect(crumbsFor("/scenes/job-a", "Kho A")).toEqual([
      { label: "Scenes", href: "/scenes" },
      { label: "Scene dựng từ video", href: "/scenes" },
      { label: "Kho A" },
    ]);
    expect(crumbsFor("/new")[0].href).toBe("/scenes");
    expect(crumbsFor("/imports/import-a")[0].href).toBe("/scenes");
    expect(crumbsFor("/imports/import-a", "Scene Nhập 1")).toEqual([
      { label: "Scenes", href: "/scenes" },
      { label: "Scene import", href: "/scenes" },
      { label: "Scene Nhập 1" },
    ]);
  });

  it("nút Quay lại trỏ về cấp cha; trang cấp cao nhất không có nút", () => {
    expect(backHref("/scenes/job-a")).toBe("/scenes");
    expect(backHref("/new")).toBe("/scenes");
    expect(backHref("/imports/import-a")).toBe("/scenes");
    expect(backHref("/samples/mau-1")).toBe("/scenes");
    expect(backHref("/scenes/job-a/stages/frames")).toBe(crumbsFor("/scenes/job-a/stages/frames")[1].href);
    expect(backHref("/scenes/job-a/stages/frames")).not.toBe("/scenes");
    expect(backHref("/account")).toBe("/overview");
    for (const top of ["/overview", "/scenes", "/trash", "/team"]) expect(backHref(top)).toBeNull();
  });

  it("breadcrumb lấy tên API và bỏ tên khi màn chi tiết rời đi", () => {
    function Detail() { usePageTitle("Kho phía Bắc"); return null; }
    const view = render(<PageTitleProvider><Breadcrumbs pathname="/scenes/job-a" /><Detail /></PageTitleProvider>);
    expect(screen.getByText("Kho phía Bắc")).toBeInTheDocument();
    view.rerender(<PageTitleProvider><Breadcrumbs pathname="/scenes/job-b" /></PageTitleProvider>);
    expect(screen.queryByText("Kho phía Bắc")).toBeNull();
    expect(screen.getByText("Đang tải scene…")).toBeInTheDocument();
  });

  it("preview không biến RUNNING/chờ metric thành hoàn tất", () => {
    const progress: JobProgress = { job_id: "job-a", status: "RUNNING", current_stage: "ST-METRIC-CANONICALIZE", attempt: 1, started_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", completed_at: null, stages: [], preview_ready: true, waiting_for: "metric_confirmation", error: null };
    expect(progressSceneStatus(progress)).toMatchObject({ label: "Cần xác nhận tỉ lệ", group: "action", active: false });
    expect(progressSceneStatus({ ...progress, waiting_for: null })).toMatchObject({ group: "running", active: true });
    expect(progressSceneStatus({ ...progress, status: "SUCCEEDED", waiting_for: null })).toMatchObject({ group: "done" });
  });
});

describe("scene tabs", () => {
  const tabs: SceneTabItem[] = [
    { id: "progress", label: "Tiến trình", icon: null, locked: null },
    { id: "studio", label: "Studio", icon: null, locked: "Chưa có bản xem" },
    { id: "results", label: "Kết quả", icon: null, locked: null },
  ];
  it("tab khóa hiện lý do khi click và không chuyển vùng", () => {
    const change = vi.fn();
    render(<SceneTabs tabs={tabs} current="progress" onChange={change} />);
    fireEvent.click(screen.getByRole("tab", { name: /Studio/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Chưa có bản xem");
    expect(change).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("tab", { name: "Kết quả" }));
    expect(change).toHaveBeenCalledWith("results");
  });
  it("Arrow/Home/End di chuyển focus và đọc lý do tab khóa", () => {
    render(<SceneTabs tabs={tabs} current="progress" onChange={vi.fn()} />);
    const first = screen.getByRole("tab", { name: "Tiến trình" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Studio/ })).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("Chưa có bản xem");
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(screen.getByRole("tab", { name: "Kết quả" })).toHaveFocus();
  });
});
