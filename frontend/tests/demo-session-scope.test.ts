import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { window.history.replaceState(null, "", "/"); vi.resetModules(); });

describe("demo document API scope", () => {
  it("keeps late work in the original private API after navigation", async () => {
    const token = "a".repeat(32);
    window.history.replaceState(null, "", `/demo-workspace/${token}?job=job-a`);
    vi.resetModules();
    const { demoApiPath, demoSceneHref } = await import("@/lib/api/demo-session");
    const prefix = `/api/v1/demo-sessions/${token}`;
    expect(demoApiPath("/api/v1/jobs/job-a/scene/edits")).toBe(`${prefix}/api/v1/jobs/job-a/scene/edits`);
    expect(demoApiPath("/api/v1/auth/me")).toBe(`${prefix}/api/v1/auth/me`);
    expect(demoApiPath("/api/v1/auth/users")).toBe(`${prefix}/api/v1/auth/users`);
    expect(demoApiPath("/api/v1/samples/sample")).toBe(`${prefix}/api/v1/samples/sample`);
    expect(demoSceneHref("ST-CAMERA-POSE")).toContain(`/demo-workspace/${token}?`);
    window.history.replaceState(null, "", "/scenes/job-a");
    expect(demoApiPath("/api/v1/jobs/job-a/scene/edits")).toBe(`${prefix}/api/v1/jobs/job-a/scene/edits`);
    expect(demoApiPath(`${prefix}/api/v1/jobs/job-a/scene`)).toBe(`${prefix}/api/v1/jobs/job-a/scene`);
  });

  it("leaves real-job requests and the parent sample document unscoped", async () => {
    window.history.replaceState(null, "", "/samples/sample/scene");
    vi.resetModules();
    const { demoApiPath, demoSceneHref } = await import("@/lib/api/demo-session");
    expect(demoApiPath("/api/v1/jobs/job-a/scene")).toBe("/api/v1/jobs/job-a/scene");
    expect(demoSceneHref(null)).toBeNull();
  });
});
