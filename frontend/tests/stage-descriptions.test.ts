import { describe, expect, it } from "vitest";
import { STUDIO_STAGES, GEOMETRY_REVIEW_STAGE, LIDAR_STAGE, LIDAR_ODOMETRY_STAGE, LIDAR_CALIBRATION_QA_STAGE } from "@/features/studio/stages";

describe("Mô tả các bước", () => {
  for (const stage of [...STUDIO_STAGES, GEOMETRY_REVIEW_STAGE, LIDAR_STAGE, LIDAR_ODOMETRY_STAGE, LIDAR_CALIBRATION_QA_STAGE]) {
    it(stage.id, () => {
      expect(stage.description.trim()).not.toBe("");
      expect(stage.description).not.toMatch(/CoACD|REC-|voxel/);
      const sentences = stage.description.split(/[.!?]+/u).filter((sentence) => sentence.trim());
      expect(sentences.length).toBeGreaterThanOrEqual(1);
      expect(sentences.length).toBeLessThanOrEqual(2);
    });
  }
});
