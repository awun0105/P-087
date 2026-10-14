/** Host collision updates for the pinned MIT supersplat-viewer 1.35.2; no splat reload. */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../node_modules/@playcanvas/supersplat-viewer/", import.meta.url);
const pkg = JSON.parse(readFileSync(new URL("package.json", root), "utf8"));
if (pkg.version !== "1.35.2") throw new Error("Revalidate host collision patch before changing supersplat-viewer version");
function patch(file, replacements) {
  const path = fileURLToPath(new URL(file, root));
  let source = readFileSync(path, "utf8");
  if (source.includes("REAL2SIM_HOST_COLLISION")) return;
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) throw new Error(`Viewer patch anchor changed: ${file}: ${before}`);
    source = source.replace(before, after);
  }
  writeFileSync(path, source);
}
patch("dist/viewer.js", [
  ["let attachCollision;", `let attachCollision;
        // REAL2SIM_HOST_COLLISION: replace collision independently of gsplat streaming.
        let hostCollision = false;
        let overlayChanged = null;
        this.setCollisionMesh = (positions, indices) => {
            if (this.destroyed) return;
            hostCollision = true;
            collisionReady = positions && indices ? new MeshCollision(positions, indices) : null;
            attachCollision?.(collisionReady);
        };`],
  ["if (this.destroyed || !collision)", "if (this.destroyed || hostCollision || !collision)"],
  ["attachCollision = (collision) => {", `attachCollision = (collision) => {
                if (overlayChanged) events.off('collisionOverlayEnabled:changed', overlayChanged);
                this.meshOverlay?.destroy();
                this.meshOverlay = null;
                this.voxelOverlay?.destroy();
                this.voxelOverlay = null;
                state.hasCollisionOverlay = false;`],
  ["state.hasCollision = true;", "state.hasCollision = !!collision;"],
  ["state.walkAllowed = isWalkAllowed(sceneBound, collision);", `state.walkAllowed = !!collision && isWalkAllowed(sceneBound, collision);
                if (!state.walkAllowed && state.cameraMode === 'walk') state.cameraMode = 'fly';`],
  ["events.on('collisionOverlayEnabled:changed', setOverlayEnabled);", "overlayChanged = setOverlayEnabled;\n                    events.on('collisionOverlayEnabled:changed', overlayChanged);"],
  ["events.on('collisionOverlayEnabled:changed', (value) => {\n                        this.meshOverlay.enabled = value;\n                        app.renderNextFrame = true;\n                    });", `overlayChanged = (value) => {
                        if (this.meshOverlay) this.meshOverlay.enabled = value;
                        app.renderNextFrame = true;
                    };
                    events.on('collisionOverlayEnabled:changed', overlayChanged);
                    overlayChanged(state.collisionOverlayEnabled);`],
  ["if (collisionReady)\n                attachCollision(collisionReady);", "if (collisionReady || hostCollision)\n                attachCollision(collisionReady);"],
  ["resetCamera: () => viewer.resetCamera(),", "resetCamera: () => viewer.resetCamera(),\n        setCollisionMesh: (positions, indices) => viewer.setCollisionMesh(positions, indices),"],
]);
patch("dist/viewer.d.ts", [
  ["type ViewerHandle = {", `type ViewerHandle = {
    /** REAL2SIM_HOST_COLLISION: display-world mesh; null blocks Walk while replacing collision. */
    setCollisionMesh(positions: Float32Array | null, indices: Uint32Array | null): void;`],
]);
