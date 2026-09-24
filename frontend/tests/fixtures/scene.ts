/**
 * Dữ liệu test cho viewer.
 *
 * Bám sát `fixtures/scene_ir/scene.json` của repo nhưng khai bằng tay, để test
 * không phải đọc file và vẫn kiểm được đúng hình dạng backend trả về.
 */

import type { ArtifactRef, SceneIR, SceneResponse } from "@/lib/contracts/api";

export const JOB_ID = "job-fixture-001";

export function ref(uri: string, checksum: string): ArtifactRef {
  return {
    artifact_type: "Geometry",
    schema_version: "1.0",
    artifact_uri: uri,
    artifact_checksum: checksum,
    data_class: "derived",
    producer_stage: "ST-SCENE-DECOMPOSE",
    job_id: JOB_ID,
  };
}

export function sceneIR(): SceneIR {
  return {
    artifact_type: "SceneIR",
    schema_version: "1.0",
    scene_id: "scene-fixture-001",
    scene_revision: "rev-001",
    coordinate_system: { unit: "meter", up_axis: "Z", handedness: "right", world_frame: "world" },
    metric_scale: { status: "CONFIRMED", meters_per_unit: 1 },
    environment: {
      geometry_ref: ref(`artifact://jobs/${JOB_ID}/scene/environment_geometry.ply`, "sha256:env0000"),
      collider_ref: ref(`artifact://jobs/${JOB_ID}/scene/floor_collider.json`, "sha256:floor000"),
    },
    objects: [
      {
        id: "object-pallet-001",
        name: "Fixture Pallet",
        state: "CONFIRMED",
        origin: "reconstructed",
        active: true,
        local_frame: "object-pallet-001",
        transform: {
          semantics: "parent_from_local",
          parent_frame: "world",
          local_frame: "object-pallet-001",
          translation_xyz: [1, 2, 0],
          rotation_quaternion_xyzw: [0, 0, 0, 1],
        },
        geometry_ref: ref(`artifact://jobs/${JOB_ID}/scene/object_pallet_geometry.ply`, "sha256:pallet00"),
        collider: {
          collider_id: "collider-pallet-001",
          collider_type: "AABB",
          local_transform: {
            semantics: "parent_from_local",
            parent_frame: "object-pallet-001",
            local_frame: "collider-pallet-001",
            translation_xyz: [0, 0, 0],
            rotation_quaternion_xyzw: [0, 0, 0, 1],
          },
          dimensions_xyz_m: [1, 1, 1],
          geometry_ref: ref(`artifact://jobs/${JOB_ID}/scene/pallet_collider.json`, "sha256:pcoll000"),
          parameters: {},
        },
        provenance: {},
      },
    ],
    provenance: {},
    scene_ir_checksum: "sha256:sceneiri",
  };
}

export function buildFixtureScene(): SceneResponse {
  return {
    job_id: JOB_ID,
    scene_id: "scene-fixture-001",
    scene_revision: "rev-001",
    scene_uri: `artifact://jobs/${JOB_ID}/scene/scene_ir.rev-001.json`,
    scene_checksum: "sha256:scenefile",
    supersedes_revision: null,
    scene: sceneIR(),
    visual: {
      available: true,
      format: "real2sim.synthetic.visual.v1",
      producer: "foundation-fixture-generator",
      producer_version: "1.0",
      reference: ref(`artifact://jobs/${JOB_ID}/reconstruction/mock_visual.json`, "sha256:visual00"),
      source_input_checksum: "sha256:afe1bbad",
      brush_compatibility_proof: false,
      unavailable_reason: null,
    },
  };
}
