import { describe, expect, it } from "vitest";
import { InspectionHistory, pointDistance, proposedMetricScale } from "../src/features/viewer/inspection-history";

describe("inspection history (not backend revisions)", () => {
  it("serializes async work with undo in initiation order", async () => {
    const applied: number[] = [];
    const history = new InspectionHistory(0, (value) => applied.push(value));
    const first = history.enqueue(async () => { await Promise.resolve(); history.commit(1); });
    const second = history.enqueue(() => history.undo());
    await Promise.all([first, second]);
    expect(applied).toEqual([1, 0]);
    expect(history.canRedo).toBe(true);
  });

  it("does not poison queue or advance history after failure", async () => {
    const history = new InspectionHistory(0, (value) => { if (value === 1) throw new Error("failed"); });
    await expect(history.enqueue(() => history.commit(1))).rejects.toThrow("failed");
    expect(history.current).toBe(0);
    expect(history.canUndo).toBe(false);
    await history.enqueue(() => history.commit(2));
    expect(history.current).toBe(2);
  });

  it("drops redo branch only after a successful new operation", () => {
    const history = new InspectionHistory(0, () => undefined);
    history.commit(1); history.commit(2); history.undo(); history.commit(3);
    expect(history.canRedo).toBe(false);
    history.undo(); expect(history.current).toBe(1);
  });
});

describe("measurement is a proposal, not metric confirmation", () => {
  it("computes native-source distance and a scale proposal", () => {
    expect(pointDistance([[0, 0, 0], [3, 4, 0]])).toBe(5);
    expect(proposedMetricScale(5, 2)).toBe(0.4);
  });

  it("rejects missing/degenerate and nonfinite points or distances", () => {
    expect(pointDistance([[0, 0, 0]])).toBeNull();
    expect(pointDistance([[NaN, 0, 0], [1, 1, 1]])).toBeNull();
    for (const value of [0, -1, Infinity, NaN]) expect(proposedMetricScale(2, value)).toBeNull();
    expect(proposedMetricScale(0, 2)).toBeNull();
    expect(proposedMetricScale(null, 2)).toBeNull();
  });
});
