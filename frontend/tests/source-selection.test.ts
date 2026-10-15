import { describe, expect, it } from "vitest";
import { selectedSourceRows } from "../vendor/supersplat/src/source-selection";

describe("source Gaussian identity", () => {
  const checksum = "sha256:" + "a".repeat(64);
  const layer = () => ({
    resource: { numRows: 5, sourceFileRows: new Uint32Array([4, 0, 3, 1, 2]), membershipSourceChecksum: checksum },
    // Instance order differs from upload order after editing. Duplicate references
    // still describe one original Gaussian, not two ownership assignments.
    instances: { count: 4, sourceRow: new Uint32Array([2, 0, 2, 4]), flags: new Uint8Array([1, 0, 1, 1]) },
  });
  it("maps instances through Morton order into exact original PLY rows", () => {
    expect(selectedSourceRows([layer()], checksum, 5)).toEqual([2, 3]);
  });
  it("accepts identity upload order and ignores unselected locked rows", () => {
    const value = layer();
    const resource = { ...value.resource, sourceFileRows: null };
    expect(selectedSourceRows([{ ...value, resource }], checksum, 5)).toEqual([2, 4]);
  });
  it("rejects foreign layers, wrong checksum/count and invalid row mapping", () => {
    for (const layers of [[], [layer(), layer()]]) expect(() => selectedSourceRows(layers, checksum, 5)).toThrow();
    expect(() => selectedSourceRows([layer()], "sha256:" + "b".repeat(64), 5)).toThrow(/checksum/);
    expect(() => selectedSourceRows([layer()], checksum, 4)).toThrow(/count/);
    const broken = layer(); broken.instances.sourceRow[0] = 99;
    expect(() => selectedSourceRows([broken], checksum, 5)).toThrow(/mapping/);
  });
});
