/** T-067: Gaussian của vật tải tối đa 4 cùng lúc; vật đang chọn trước, vật ẩn sau cùng. */
import { Asset } from "playcanvas";
import { describe, expect, it, vi } from "vitest";

import { SceneOverlay, type OverlayObject } from "@/features/viewer/scene-overlay";
import type { ViewerAppLike } from "@/features/viewer/PlayCanvasScene";

function fakeApp() {
  return {
    root: { findComponents: () => [], addChild: vi.fn() },
    renderNextFrame: false,
    scene: { layers: { insert: vi.fn(), layerList: [] } },
    systems: { light: { addComponent: vi.fn() }, gsplat: { addComponent: vi.fn() } },
    assets: { add: vi.fn(), load: vi.fn(), remove: vi.fn() },
  };
}

const item = (id: string, extra: Partial<OverlayObject> = {}): OverlayObject => ({
  id, url: `/objects/${id}.ply`, position: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1], visible: true, ...extra,
});

const loadedNames = (app: ReturnType<typeof fakeApp>) => app.assets.load.mock.calls.map(([asset]) => (asset as Asset).name);

describe("object splat loading (T-067)", () => {
  it("loads at most four objects at a time and continues as each finishes", () => {
    const app = fakeApp();
    const overlay = new SceneOverlay(app as unknown as ViewerAppLike);
    overlay.setObjects(Array.from({ length: 10 }, (_, index) => item(`o${index}`)));
    expect(app.assets.load).toHaveBeenCalledTimes(4);
    (app.assets.load.mock.calls[0][0] as Asset).fire("load");
    expect(app.assets.load).toHaveBeenCalledTimes(5);
    (app.assets.load.mock.calls[1][0] as Asset).fire("error", "boom");
    expect(app.assets.load).toHaveBeenCalledTimes(6);
  });

  it("loads the selected object next, and hidden objects last", () => {
    const app = fakeApp();
    const overlay = new SceneOverlay(app as unknown as ViewerAppLike);
    overlay.setObjects([...Array.from({ length: 6 }, (_, index) => item(`o${index}`)), item("hidden", { visible: false }), item("o6")]);
    overlay.prioritizeObject("o5");
    (app.assets.load.mock.calls[0][0] as Asset).fire("load");
    expect(loadedNames(app).at(-1)).toBe("r2s-object-o5");
    for (let index = 1; index < 5; index += 1) (app.assets.load.mock.calls[index][0] as Asset).fire("load");
    expect(loadedNames(app).at(-1)).toBe("r2s-object-hidden");
  });

  it("removing a queued object never loads it", () => {
    const app = fakeApp();
    const overlay = new SceneOverlay(app as unknown as ViewerAppLike);
    const items = Array.from({ length: 6 }, (_, index) => item(`o${index}`));
    overlay.setObjects(items);
    overlay.setObjects(items.filter((entry) => entry.id !== "o4"));
    (app.assets.load.mock.calls[0][0] as Asset).fire("load");
    expect(loadedNames(app)).not.toContain("r2s-object-o4");
  });
});
