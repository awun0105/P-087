import { describe, expect, it } from "vitest";

import matrix from "../../fixtures/contracts/input_assembly_binding_matrix.json";
import type { InputAssemblyBindingMatrix, RecipeGroup } from "@/lib/contracts/inputAssembly";

// JSON module imports widen literal fields; the Python contract test validates the same checked-in fixture.
const bindingMatrix = matrix as unknown as InputAssemblyBindingMatrix;

describe("unified input binding contract", () => {
  it("maps the seven owner-listed combinations across the six recipe groups", () => {
    expect(bindingMatrix.schema_version).toBe("1.0");
    expect(bindingMatrix.cases).toHaveLength(7);

    const groups = new Set<RecipeGroup>(bindingMatrix.cases.flatMap((item) => item.conditional_recipe_groups));
    expect(groups).toEqual(new Set<RecipeGroup>(["R1", "R2", "R3", "R4", "R5", "R6"]));
  });

  it("requires a selection when cloud state changes which route is valid", () => {
    const lidarAndCalibration = bindingMatrix.cases.find((item) => item.case_id === "owner-04-lidar-and-calibration");
    const tumWithoutRgbTimes = bindingMatrix.cases.find(
      (item) => item.case_id === "owner-07-calibration-and-tum-without-rgb-frame-times",
    );

    expect(lidarAndCalibration?.requires_user_choice).toBe(true);
    expect(lidarAndCalibration?.unresolved_role_candidates).toContain("registered_lidar_map");
    expect(tumWithoutRgbTimes?.conditional_recipe_groups).not.toContain("R6");
  });
});
