/** REUSE PlayCanvas Picker + ADAPT SuperSplat measurement/history interactions.
 * Xem THIRD_PARTY_NOTICES.md. Không sửa Gaussian, collider hoặc metric authority.
 */
import { CameraComponent, Color, GSplatComponent, Mat4, Picker, Vec3 } from "playcanvas";
import type { ViewerHandle } from "@playcanvas/supersplat-viewer/viewer";
import { EMPTY_INSPECTION, InspectionHistory, type InspectionPoint, type InspectionState } from "./inspection-history";

/** Controller một viewport; history/readback cùng FIFO, teardown chờ readback kết thúc. */
export class SplatInspection {
  private readonly picker: Picker;
  private readonly canvas: HTMLCanvasElement;
  private readonly history: InspectionHistory<readonly InspectionPoint[]>;
  private state: InspectionState = { ...EMPTY_INSPECTION };
  private disposed = false;
  private originalInput = true;
  private readonly inputGates = new Set<"measure" | "form">();
  private readonly colorA = new Color(0.2, 0.8, 1);
  private readonly colorB = new Color(1, 0.7, 0.2);
  private readonly colorFloor = new Color(0.4, 0.9, 0.4);

  /** `maxPoints` 2 = cặp đo A/B; 5 = A, B rồi 3 điểm sàn cho xác nhận tỉ lệ mét (REC-06). */
  constructor(
    private readonly viewer: ViewerHandle,
    private readonly notify: (state: InspectionState) => void,
    private readonly maxPoints = 2,
  ) {
    const canvas = viewer.app.graphicsDevice.canvas;
    if (!(canvas instanceof HTMLCanvasElement)) throw new Error("Inspection cần HTML canvas");
    this.canvas = canvas;
    this.picker = new Picker(viewer.app, 1, 1, true);
    this.history = new InspectionHistory<readonly InspectionPoint[]>([], (points) => {
      this.state = { ...this.state, points };
      viewer.app.renderNextFrame = true;
    });
    canvas.addEventListener("pointerdown", this.onPointerDown, true);
    for (const event of ["pointermove", "pointerup", "click", "dblclick"]) {
      canvas.addEventListener(event, this.blockNavigation, true);
    }
    viewer.app.on("prerender", this.draw);
    this.publish();
  }

  private camera(): CameraComponent {
    const cameras = this.viewer.app.root.findComponents("camera").filter(
      (component): component is CameraComponent => component instanceof CameraComponent && component.enabled && component.entity.enabled,
    );
    if (cameras.length !== 1) throw new Error("Inspection chỉ hỗ trợ một camera hoạt động, không XR");
    return cameras[0];
  }

  private splat(): GSplatComponent {
    const splats = this.viewer.app.root.findComponents("gsplat").filter(
      (component): component is GSplatComponent => component instanceof GSplatComponent && component.enabled && component.entity.enabled,
    );
    if (splats.length !== 1) throw new Error("Chọn điểm cần một Gaussian asset đang hiển thị");
    return splats[0];
  }

  private publish(): void {
    if (!this.disposed) this.notify({ ...this.state, canUndo: this.history.canUndo, canRedo: this.history.canRedo });
  }

  private schedule(operation: () => void | Promise<void>): void {
    void this.history.enqueue(async () => {
      if (this.disposed) return;
      this.state = { ...this.state, busy: true, error: null };
      this.publish();
      try {
        await operation();
      } catch (error: unknown) {
        this.state = { ...this.state, error: error instanceof Error ? error.message : "Inspection không thực hiện được" };
      } finally {
        this.state = { ...this.state, busy: false };
        this.publish();
      }
    });
  }

  setMeasuring(enabled: boolean): void {
    if (this.disposed || !this.viewer.state.loaded || this.state.measuring === enabled) return;
    this.setInputGate("measure", enabled);
    this.state = { ...this.state, measuring: enabled, error: null };
    this.publish();
  }

  setFormFocused(focused: boolean): void { this.setInputGate("form", focused); }

  private setInputGate(gate: "measure" | "form", blocked: boolean): void {
    if (this.disposed) return;
    if (blocked) {
      if (!this.inputGates.size) this.originalInput = this.viewer.state.inputEnabled;
      this.inputGates.add(gate);
    } else {
      if (!this.inputGates.delete(gate)) return;
    }
    this.viewer.state.inputEnabled = this.inputGates.size ? false : this.originalInput;
  }

  frameScene(): void { this.schedule(() => this.viewer.frameScene()); }
  resetCamera(): void { this.schedule(() => this.viewer.resetCamera()); }
  undo(): void { this.schedule(() => this.history.undo()); }
  redo(): void { this.schedule(() => this.history.redo()); }
  clear(): void { this.schedule(() => this.history.commit([])); }

  private blockNavigation = (event: Event): void => {
    if (!this.state.measuring || this.disposed) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  private onPointerDown = (event: PointerEvent): void => {
    if (!this.state.measuring || this.disposed) return;
    this.blockNavigation(event);
    if (event.button !== 0 || !event.isPrimary || !this.viewer.state.loaded) return;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    if (x < 0 || x >= 1 || y < 0 || y >= 1) return;
    this.schedule(async () => {
      const camera = this.camera();
      const splat = this.splat();
      // Viewer xoay nội dung (hiện upstream Z=180°); không gửi viewer-world làm anchor SfM.
      const worldFromSource = splat.entity.getWorldTransform().clone();
      const m = worldFromSource.data;
      const determinant = m[0] * (m[5] * m[10] - m[6] * m[9]) - m[4] * (m[1] * m[10] - m[2] * m[9]) + m[8] * (m[1] * m[6] - m[2] * m[5]);
      if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-12) throw new Error("Gaussian transform không khả nghịch");
      const sourceFromWorld = new Mat4().invert(worldFromSource);
      this.picker.resize(this.canvas.width, this.canvas.height);
      this.picker.prepare(camera, this.viewer.app.scene);
      const point = await this.picker.getWorldPointAsync(x * this.canvas.width, y * this.canvas.height);
      if (this.disposed) return;
      if (!point) throw new Error("Không có điểm ở vị trí này; chọn lại trên bề mặt rõ nét");
      const source = sourceFromWorld.transformPoint(point);
      const value: InspectionPoint = [source.x, source.y, source.z];
      if (!value.every(Number.isFinite)) throw new Error("GPU trả tọa độ không hữu hạn");
      // Đủ điểm thì click mới bắt đầu bộ mới; history vẫn giữ bộ cũ để undo.
      this.history.commit(this.history.current.length >= this.maxPoints ? [value] : [...this.history.current, value]);
    });
  };

  private draw = (): void => {
    if (this.disposed || !this.state.points.length || !this.viewer.state.loaded) return;
    try {
      const camera = this.camera();
      const transform = this.splat().entity.getWorldTransform();
      const points = this.state.points.map((point) => transform.transformPoint(new Vec3(...point)));
      points.forEach((point, index) => {
        const size = Math.max(point.distance(camera.entity.getPosition()) * 0.004, 0.00001);
        const color = index === 0 ? this.colorA : index === 1 ? this.colorB : this.colorFloor;
        for (const offset of [new Vec3(size, 0, 0), new Vec3(0, size, 0), new Vec3(0, 0, size)]) {
          this.viewer.app.drawLine(point.clone().sub(offset), point.clone().add(offset), color, false);
        }
      });
      if (points.length >= 2) this.viewer.app.drawLine(points[0], points[1], this.colorB, false);
      const floor = points.slice(2);
      floor.forEach((point, index) => {
        const next = floor[(index + 1) % floor.length];
        if (floor.length === 3 || index + 1 < floor.length) this.viewer.app.drawLine(point, next, this.colorFloor, false);
      });
    } catch (error: unknown) {
      // Asset có thể đang unload; báo lỗi tool một lần, không làm hỏng viewport.
      if (!this.state.error) {
        this.state = { ...this.state, error: error instanceof Error ? error.message : "Không render được điểm inspection" };
        this.publish();
      }
    }
  };

  async destroy(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    this.canvas.removeEventListener("pointerdown", this.onPointerDown, true);
    for (const event of ["pointermove", "pointerup", "click", "dblclick"]) {
      this.canvas.removeEventListener(event, this.blockNavigation, true);
    }
    this.viewer.app.off("prerender", this.draw);
    if (this.inputGates.size) this.viewer.state.inputEnabled = this.originalInput;
    await this.history.idle();
    this.picker.destroy();
  }
}
