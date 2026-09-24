/**
 * Test cho ánh xạ SceneIR → layer (PRODUCT-06).
 *
 * Đây là phần dễ sai nhất của viewer: sai transform nghĩa là mọi thứ vẫn hiện ra
 * nhưng hiện sai chỗ. Test chạy trên SceneIR tổng hợp để không phụ thuộc fixture.
 */

import { describe, expect, it } from "vitest";

import type { SceneIR, SceneObject } from "@/lib/contracts/api";
import {
  buildSceneLayers,
  composeColliderTransform,
  composeTranslation,
  layerKey,
  MISSING_DIMENSIONS,
  multiplyQuaternions,
  rotateVector,
  VIEW_MODES,
  visibleLayers,
} from "@/features/viewer/layers";

function ref(uri: string, checksum: string) {
  return {
    artifact_type: "Geometry",
    schema_version: "1.0",
    artifact_uri: uri,
    artifact_checksum: checksum,
    data_class: "derived" as const,
    producer_stage: "ST-SCENE-DECOMPOSE",
    job_id: "job-1",
  };
}

function identityTransform(localFrame: string, translation: [number, number, number] = [0, 0, 0]) {
  return {
    semantics: "parent_from_local" as const,
    parent_frame: "world",
    local_frame: localFrame,
    translation_xyz: translation,
    rotation_quaternion_xyzw: [0, 0, 0, 1] as [number, number, number, number],
  };
}

function object(overrides: Partial<SceneObject> = {}): SceneObject {
  return {
    id: "object-a",
    name: "Object A",
    state: "CONFIRMED",
    origin: "reconstructed",
    active: true,
    local_frame: "object-a",
    transform: identityTransform("object-a", [1, 2, 0]),
    geometry_ref: ref("artifact://jobs/job-1/scene/a.ply", "sha256:aaa"),
    collider: null,
    provenance: {},
    ...overrides,
  };
}

/** Collider AABB parent đúng vào `ownerFrame`, mặc định 1×1×1 và không có ref. */
function colliderOf(ownerFrame: string) {
  return {
    collider_id: "collider-a",
    collider_type: "AABB" as const,
    local_transform: { ...identityTransform("collider-a"), parent_frame: ownerFrame },
    dimensions_xyz_m: [1, 1, 1] as [number, number, number],
    geometry_ref: null,
    parameters: {},
  };
}

function scene(objects: SceneObject[]): SceneIR {
  return {
    artifact_type: "SceneIR",
    schema_version: "1.0",
    scene_id: "scene-1",
    scene_revision: "rev-001",
    coordinate_system: { unit: "meter", up_axis: "Z", handedness: "right", world_frame: "world" },
    metric_scale: { status: "CONFIRMED", meters_per_unit: 1 },
    environment: {
      geometry_ref: ref("artifact://jobs/job-1/scene/env.ply", "sha256:env"),
      collider_ref: ref("artifact://jobs/job-1/scene/floor.json", "sha256:floor"),
    },
    objects,
    provenance: {},
    scene_ir_checksum: "sha256:scene",
  };
}

describe("buildSceneLayers", () => {
  it("gắn checksum của artifact vào từng layer", () => {
    const layers = buildSceneLayers(scene([object()]), "sha256:scenebytes");
    const objectMesh = layers.geometry.find((layer) => layer.object_id === "object-a" && layer.kind === "geometry");
    expect(objectMesh?.checksum).toBe("sha256:aaa");
    expect(layers.scene_checksum).toBe("sha256:scenebytes");
  });

  it("giữ revision canonical trên kết quả", () => {
    expect(buildSceneLayers(scene([]), "sha256:x").scene_revision).toBe("rev-001");
  });

  it("tạo layer collider cho environment ngay cả khi scene rỗng object", () => {
    const layers = buildSceneLayers(scene([]), "sha256:x");
    const environmentCollider = layers.colliders.find((layer) => layer.collider_id === "environment");
    expect(environmentCollider?.checksum).toBe("sha256:floor");
  });

  it("dùng kích thước chỗ giữ chỗ khi collider thiếu dimensions", () => {
    const layers = buildSceneLayers(scene([]), "sha256:x");
    const environmentCollider = layers.colliders.find((layer) => layer.collider_id === "environment");
    expect(environmentCollider?.dimensions_xyz_m).toEqual(MISSING_DIMENSIONS);
  });

  it("giữ canonical active của object tắt", () => {
    const layers = buildSceneLayers(scene([object({ active: false })]), "sha256:x");
    const mesh = layers.geometry.find((layer) => layer.object_id === "object-a");
    expect(mesh?.canonical_active).toBe(false);
  });
});

describe("composeColliderTransform", () => {
  it("cộng translation khi object không xoay", () => {
    const parent = identityTransform("object-a", [1, 2, 0]);
    const local = identityTransform("collider-a", [0.5, 0, 0]);
    local.parent_frame = "object-a";
    expect(composeTranslation(parent, local)).toEqual([1.5, 2, 0]);
  });

  it("xoay offset của collider theo object trước khi cộng", () => {
    // Xoay 90° quanh Z: trục X local thành trục Y world.
    const parent = identityTransform("object-a", [1, 0, 0]);
    parent.rotation_quaternion_xyzw = [0, 0, Math.SQRT1_2, Math.SQRT1_2];
    const local = identityTransform("collider-a", [1, 0, 0]);
    local.parent_frame = "object-a";
    const composed = composeTranslation(parent, local);
    expect(composed[0]).toBeCloseTo(1, 6);
    expect(composed[1]).toBeCloseTo(1, 6);
  });

  it("giữ frame của chính collider, không lấy frame của object", () => {
    // `ColliderSpec` không có `local_frame`: frame của collider nằm trong
    // `local_transform`. Lấy nhầm sẽ ra `undefined` — vẫn render, nhưng gán sai
    // frame cho collider trong world.
    const owner = object({ collider: colliderOf("object-a") });
    const composed = composeColliderTransform(owner, owner.collider!);
    expect(composed.local_frame).toBe("collider-a");
    expect(composed.parent_frame).toBe("world");
  });

  it("từ chối collider parent sai frame", () => {
    // parent_frame = "world" nhưng object.local_frame = "object-a"
    const owner = object({ collider: colliderOf("world") });
    expect(() => composeColliderTransform(owner, owner.collider!)).toThrow(/contract/);
  });
});

describe("visibleLayers", () => {
  it("GEOMETRY chỉ trả mesh, không trả point cloud", () => {
    const layers = buildSceneLayers(scene([object()]), "sha256:x");
    const kinds = new Set(visibleLayers(layers, "GEOMETRY").map((layer) => layer.kind));
    expect(kinds).toEqual(new Set(["geometry"]));
  });

  it("POINT_CLOUD chỉ trả point cloud", () => {
    const layers = buildSceneLayers(scene([object()]), "sha256:x");
    const kinds = new Set(visibleLayers(layers, "POINT_CLOUD").map((layer) => layer.kind));
    expect(kinds).toEqual(new Set(["point_cloud"]));
  });

  it("COLLIDER chỉ trả collider", () => {
    const layers = buildSceneLayers(scene([object()]), "sha256:x");
    const kinds = new Set(visibleLayers(layers, "COLLIDER").map((layer) => layer.kind));
    expect(kinds).toEqual(new Set(["collider"]));
  });

  it("VISUAL không lấy gì từ SceneIR vì visual do VisualArtifact cấp", () => {
    const layers = buildSceneLayers(scene([object()]), "sha256:x");
    expect(visibleLayers(layers, "VISUAL")).toEqual([]);
  });

  it("loại object canonical active=false khỏi mọi view", () => {
    const layers = buildSceneLayers(scene([object({ active: false })]), "sha256:x");
    for (const mode of VIEW_MODES) {
      expect(visibleLayers(layers, mode).some((layer) => layer.object_id === "object-a")).toBe(false);
    }
  });
});

describe("layerKey", () => {
  it("khác nhau giữa mesh và point cloud của cùng object", () => {
    const layers = buildSceneLayers(scene([object()]), "sha256:x");
    const [mesh] = layers.geometry.filter((layer) => layer.kind === "geometry" && layer.object_id === "object-a");
    const [cloud] = layers.geometry.filter((layer) => layer.kind === "point_cloud" && layer.object_id === "object-a");
    expect(layerKey(mesh!)).not.toBe(layerKey(cloud!));
  });

  it("không đụng nhau giữa mọi layer của một scene", () => {
    // Canvas chọn layer bằng chính khoá này, nên khoá trùng nghĩa là bấm vào một
    // layer lại chọn nhầm layer khác.
    const layers = buildSceneLayers(scene([object({ collider: colliderOf("object-a") })]), "sha256:x");
    const keys = [...layers.geometry, ...layers.colliders].map(layerKey);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("ổn định giữa hai lần dựng cùng scene", () => {
    const first = buildSceneLayers(scene([object()]), "sha256:x");
    const second = buildSceneLayers(scene([object()]), "sha256:x");
    expect(first.colliders.map(layerKey)).toEqual(second.colliders.map(layerKey));
  });
});

describe("quaternion helpers", () => {
  it("nhân với identity trả lại chính nó", () => {
    const q: [number, number, number, number] = [0.1, 0.2, 0.3, Math.sqrt(1 - 0.14)];
    const result = multiplyQuaternions(q, [0, 0, 0, 1]);
    for (let index = 0; index < 4; index += 1) {
      expect(result[index]).toBeCloseTo(q[index]!, 10);
    }
  });

  it("xoay 90° quanh Z đưa trục X thành trục Y", () => {
    const rotated = rotateVector([0, 0, Math.SQRT1_2, Math.SQRT1_2], [1, 0, 0]);
    expect(rotated[0]).toBeCloseTo(0, 6);
    expect(rotated[1]).toBeCloseTo(1, 6);
  });

  it("xoay 180° quanh Z đảo dấu X và Y", () => {
    const rotated = rotateVector([0, 0, 1, 0], [1, 2, 3]);
    expect(rotated[0]).toBeCloseTo(-1, 6);
    expect(rotated[1]).toBeCloseTo(-2, 6);
    expect(rotated[2]).toBeCloseTo(3, 6);
  });
});
