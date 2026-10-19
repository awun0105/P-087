/** Host collision updates for the pinned MIT supersplat-viewer 1.35.2; no splat reload.
 * Upstream: Copyright (c) 2011-2026 PlayCanvas Ltd.; see viewer-collision-LICENSE.txt.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../node_modules/@playcanvas/supersplat-viewer/", import.meta.url);
const pkg = JSON.parse(readFileSync(new URL("package.json", root), "utf8"));
if (pkg.version !== "1.35.2") throw new Error("Revalidate host collision patch before changing supersplat-viewer version");
function patch(file, replacements, marker = "REAL2SIM_HOST_COLLISION") {
  const path = fileURLToPath(new URL(file, root));
  let source = readFileSync(path, "utf8");
  if (source.includes(marker)) return;
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


patch("dist/viewer.js", [
  ["let hostCollision = false;", `let hostCollision = false;
        // REAL2SIM_OBJECT_COLLISION: query provider keeps authored object colliders in camera Walk.
        let collisionProvider = null;
        this.setCollisionProvider = (provider) => {
            if (this.destroyed) return;
            collisionProvider = provider;
            attachCollision?.(collisionReady);
        };`],
  ["attachCollision = (collision) => {", "attachCollision = (collision) => {\n                const controllerCollision = collisionProvider ? collisionProvider(collision) : collision;"],
  ["this.inputController.collision = collision;", "this.inputController.collision = controllerCollision;"],
  ["this.cameraManager.setCollision(collision);", "this.cameraManager.setCollision(controllerCollision);"],
  ["this.navCursor.collision = collision;", "this.navCursor.collision = controllerCollision;"],
  ["state.hasCollision = !!collision;", "state.hasCollision = !!controllerCollision;"],
  ["state.walkAllowed = !!collision && isWalkAllowed(sceneBound, collision);", "state.walkAllowed = !!controllerCollision && isWalkAllowed(sceneBound, controllerCollision);"],
  ["setCollisionMesh: (positions, indices) => viewer.setCollisionMesh(positions, indices),", "setCollisionMesh: (positions, indices) => viewer.setCollisionMesh(positions, indices),\n        setCollisionProvider: (provider) => viewer.setCollisionProvider(provider),"],
  ["export { createViewer };", "export function createMeshCollision(positions, indices) { return new MeshCollision(positions, indices); }\nexport { createViewer };"],
], "REAL2SIM_OBJECT_COLLISION");
patch("dist/viewer.d.ts", [
  ["type ViewerHandle = {", `/** REAL2SIM_OBJECT_COLLISION: the pinned viewer's display-space query contract. */
export interface CollisionQuery {
    voxelResolution: number;
    queryRay(ox: number, oy: number, oz: number, dx: number, dy: number, dz: number, maxDist: number): { x: number; y: number; z: number } | null;
    querySphere(cx: number, cy: number, cz: number, radius: number, out: { x: number; y: number; z: number }): boolean;
    queryCapsule(cx: number, cy: number, cz: number, halfHeight: number, radius: number, out: { x: number; y: number; z: number }): boolean;
    isFreeAt(x: number, y: number, z: number): boolean;
    querySurfaceNormal(x: number, y: number, z: number, dx: number, dy: number, dz: number): { nx: number; ny: number; nz: number };
}
export declare function createMeshCollision(positions: Float32Array, indices: Uint32Array): CollisionQuery;
type ViewerHandle = {
    setCollisionProvider(provider: ((environment: CollisionQuery | null) => CollisionQuery | null) | null): void;`],
], "REAL2SIM_OBJECT_COLLISION");

patch("dist/viewer.js", [
  ["        // ground probe: cast a ray downward to find the terrain surface", `        // REAL2SIM_WALK_SUPPORT: no stepping into missing collision behind a removed object.
        const previousX = this._position.x, previousY = this._position.y, previousZ = this._position.z;
        // ground probe: cast a ray downward to find the terrain surface`],
  ["        const hasGround = groundY !== null;", "        const hasGround = groundY !== null;\n        if (hasGround) this._hostWalkGround = groundY;"],
  ["        this._checkCollision(this._position, d);", `        this._checkCollision(this._position, d);
        if (this.collision?.preventUnsupportedWalk && this._hostWalkGround !== undefined &&
            !isWalkStepSupported(this.collision, this._position.x, this._hostWalkGround, this._position.z, this.capsuleRadius)) {
            this._position.set(previousX, previousY, previousZ);
            this._velocity.set(0, 0, 0);
        }`],
  ["        this._jumpHeld = false;\n        this._pendingMove[0] = 0;", "        this._jumpHeld = false;\n        this._hostWalkGround = undefined;\n        this._pendingMove[0] = 0;"],
  ["export { createViewer };", `/** Check the capsule footprint against existing surfaces within a 25cm step, never invent a floor. */
export function isWalkStepSupported(collision, x, groundY, z, radius) {
    for (const [dx, dz] of [[0,0],[radius,0],[-radius,0],[0,radius],[0,-radius]]) {
        const hit = collision.queryRay(x+dx, groundY+0.25, z+dz, 0,-1,0,0.5);
        if (!hit) return false;
    }
    return true;
}
export { createViewer };`],
], "REAL2SIM_WALK_SUPPORT");

// Keep the pinned collision algorithm, but let environment preparation yield to input/paint.
patch("dist/viewer.js", [
  ["function buildBVH(tris, start, count) {", "function* buildBVH(tris, start, count) {"],
  ["    for (let i = start; i < start + count; i++) {", "    for (let i = start; i < start + count; i++) {\n        if ((i & 2047) === 0) yield;"],
  ["    while (left <= right) {", "    while (left <= right) {\n        if (((left + count - 1 - right) & 2047) === 0) yield;"],
  ["        left: buildBVH(tris, start, leftCount),", "        left: yield* buildBVH(tris, start, leftCount),"],
  ["        right: buildBVH(tris, start + leftCount, count - leftCount),", "        right: yield* buildBVH(tris, start + leftCount, count - leftCount),"],
  ["    constructor(positions, indices) {", `    constructor(positions, indices, deferred = false) {
        this._buildSteps = this.buildSteps(positions, indices);
        if (!deferred) {
            while (!this._buildSteps.next().done) {}
            this._buildSteps = null;
        }
    }
    *buildSteps(positions, indices) {`],
  ["        for (let i = 0; i < numTris; i++) {", "        for (let i = 0; i < numTris; i++) {\n            if ((i & 2047) === 0) yield;"],
  ["        this._root = buildBVH(tris, 0, numTris);", "        this._root = yield* buildBVH(tris, 0, numTris);"],
  ["        let hostCollision = false;", `        let hostCollision = false;
        // REAL2SIM_COOPERATIVE_COLLISION: one prepared environment per viewer lifetime.
        let preparedEnvironment = null;
        this.setCollisionMeshAsync = async (positions, indices, signal) => {
            signal.throwIfAborted();
            const previous = preparedEnvironment;
            const collision = previous?.positions === positions && previous?.indices === indices
                ? previous.collision : await createMeshCollisionAsync(positions, indices, signal);
            if (this.destroyed || signal.aborted) return;
            preparedEnvironment = { positions, indices, collision };
            hostCollision = true;
            collisionReady = collision;
            attachCollision?.(collisionReady);
        };`],
  ["                    this.meshOverlay = new MeshDebugOverlay(app, collision, camera, !!this.cameraFrame);", "                    // Allocate the large debug mesh only when it is visible."],
  ["                        if (this.meshOverlay) this.meshOverlay.enabled = value;", "                        if (value && !this.meshOverlay) this.meshOverlay = new MeshDebugOverlay(app, collision, camera, !!this.cameraFrame);\n                        if (this.meshOverlay) this.meshOverlay.enabled = value;"],
  ["        setCollisionMesh: (positions, indices) => viewer.setCollisionMesh(positions, indices),", "        setCollisionMesh: (positions, indices) => viewer.setCollisionMesh(positions, indices),\n        setCollisionMeshAsync: (positions, indices, signal) => viewer.setCollisionMeshAsync(positions, indices, signal),"],
  ["export { createViewer };", `export async function createMeshCollisionAsync(positions, indices, signal) {
    signal?.throwIfAborted();
    const collision = new MeshCollision(positions, indices, true);
    const steps = collision._buildSteps;
    let deadline = performance.now() + 8;
    try {
        while (true) {
            signal?.throwIfAborted();
            if (steps.next().done) return collision;
            if (performance.now() >= deadline) {
                await new Promise(resolve => setTimeout(resolve, 0));
                deadline = performance.now() + 8;
            }
        }
    } finally {
        steps.return();
        collision._buildSteps = null;
    }
}
export { createViewer };`],
], "REAL2SIM_COOPERATIVE_COLLISION");
patch("dist/viewer.d.ts", [
  ["type ViewerHandle = {", `/** REAL2SIM_COOPERATIVE_COLLISION: abortable, UI-friendly environment preparation. */
export declare function createMeshCollisionAsync(positions: Float32Array, indices: Uint32Array, signal?: AbortSignal): Promise<CollisionQuery>;
type ViewerHandle = {
    setCollisionMeshAsync(positions: Float32Array, indices: Uint32Array, signal: AbortSignal): Promise<void>;`],
], "REAL2SIM_COOPERATIVE_COLLISION");
patch("dist/viewer.d.ts", [
  ["    voxelResolution: number;", "    /** REAL2SIM_WALK_SUPPORT: block walking into unsupported footprints. */\n    preventUnsupportedWalk?: boolean;\n    voxelResolution: number;"],
  ["export declare function createMeshCollision(", "export declare function isWalkStepSupported(collision: CollisionQuery, x: number, groundY: number, z: number, radius: number): boolean;\nexport declare function createMeshCollision("],
], "REAL2SIM_WALK_SUPPORT");
