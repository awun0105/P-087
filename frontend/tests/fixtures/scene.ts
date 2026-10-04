/**
 * Dữ liệu test cho viewer.
 *
 * Bám sát `fixtures/scene_ir/scene.json` của repo nhưng khai bằng tay, để test
 * không phải đọc file và vẫn kiểm được đúng hình dạng backend trả về.
 *
 * Checksum ở đây **phải** khớp `^sha256:[0-9a-f]{64}$` — backend validate bằng
 * pattern đó nên một fixture dùng `sha256:env0000` sẽ khiến mọi test pass trong khi
 * không response nào thật có hình dạng đó. Fixture sai hướng với type là kiểu lệch
 * mà TypeScript không bắt được.
 */

import type { ArtifactRef, SceneIR, SceneResponse, Transform } from "@/lib/contracts/api";

export const JOB_ID = "job-fixture-001";

/** Checksum hợp lệ theo `src/models/contracts/artifacts.py` Checksum pattern. */
export function sha(seed: string): string {
  let out = "";
  for (let i = 0; i < 8; i += 1) {
    out += Array.from(seed).reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0, 7).toString(16).padStart(8, "0");
  }
  return `sha256:${out.slice(0, 64)}`;
}

/** `Transform` của SceneIR luôn có `quaternion_order`/`angle_unit` — không optional. */
export function transform(
  translation: [number, number, number],
  rotation: [number, number, number, number],
  frame = "world",
): Transform {
  return {
    semantics: "parent_from_local",
    parent_frame: frame,
    local_frame: frame,
    translation_xyz: translation,
    rotation_quaternion_xyzw: rotation,
    quaternion_order: "xyzw",
    angle_unit: "radian",
  };
}

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
    metric_scale: { status: "UNCONFIRMED", meters_per_unit: null },
    environment: {
      // SceneIR v1.35.2 trong contract có `visual_ref`; bản fixture cũ thiếu nó nên
      // frontend không có đường đọc visual của environment.
      visual_ref: null,
      geometry_ref: ref(`artifact://jobs/${JOB_ID}/scene/environment_geometry.ply`, sha("env0000")),
      collider_ref: ref(`artifact://jobs/${JOB_ID}/scene/floor_collider.json`, sha("floor000")),
    },
    objects: [
      {
        id: "object-pallet-001",
        name: "Fixture Pallet",
        state: "CONFIRMED",
        origin: "reconstructed",
        active: true,
        local_frame: "object-pallet-001",
        transform: transform([1, 2, 0], [0, 0, 0, 1], "world"),
        geometry_ref: ref(`artifact://jobs/${JOB_ID}/scene/object_pallet_geometry.ply`, sha("pallet00")),
        // SceneObject v1.35.2 có 5 field này; thiếu chúng thì frontend không diễn đạt
        // được object `user_added`, vì validator yêu cầu asset_ref hoặc
        // primitive_dimensions_xyz_m.
        visual_ref: null,
        asset_ref: null,
        primitive_dimensions_xyz_m: null,
        semantic_class: "pallet",
        tags: ["fixture"],
        collider: {
          collider_id: "collider-pallet-001",
          collider_type: "AABB",
          local_transform: transform([0, 0, 0], [0, 0, 0, 1], "object-pallet-001"),
          dimensions_xyz_m: [1, 1, 1],
          // `provenance` là bắt buộc trong ColliderSpec, không phải optional.
          provenance: { fixture: true },
          geometry_ref: ref(`artifact://jobs/${JOB_ID}/scene/pallet_collider.json`, sha("pcoll000")),
          parameters: {},
        },
        provenance: {},
      },
    ],
    provenance: {},
    scene_ir_checksum: sha("sceneiri"),
  };
}

export function buildFixtureScene(): SceneResponse {
  return {
    job_id: JOB_ID,
    scene_id: "scene-fixture-001",
    scene_revision: "rev-001",
    scene_uri: `artifact://jobs/${JOB_ID}/scene/scene_ir.rev-001.json`,
    scene_checksum: sha("scenefile"),
    supersedes_revision: null,
    scene: sceneIR(),
    visual: {
      available: true,
      format: "real2sim.synthetic.visual.v1",
      producer: "foundation-fixture-generator",
      producer_version: "1.0",
      reference: ref(`artifact://jobs/${JOB_ID}/reconstruction/mock_visual.json`, sha("visual00")),
      source_input_checksum: sha("afe1bbad"),
      brush_compatibility_proof: false,
      unavailable_reason: null,
    },
  };
}
