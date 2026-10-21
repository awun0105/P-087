"use client";

import { useEffect, useState } from "react";
import { Html } from "@react-three/drei";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import * as THREE from "three";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { ViewerLayer } from "@/features/viewer/layers";

/** Không cho GLB tham chiếu URL ngoài inventory kiểm checksum của backend. */
export function requireEmbeddedGlb(bytes: ArrayBuffer): void {
  const view = new DataView(bytes);
  if (bytes.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2 ||
      view.getUint32(8, true) !== bytes.byteLength || view.getUint32(16, true) !== 0x4e4f534a) {
    throw new Error("File GLB không hợp lệ");
  }
  const length = view.getUint32(12, true);
  if (length + 20 > bytes.byteLength) throw new Error("File GLB bị thiếu dữ liệu");
  const json: { buffers?: { uri?: string }[]; images?: { uri?: string }[] } = JSON.parse(new TextDecoder().decode(bytes.slice(20, 20 + length)));
  if ([...(json.buffers ?? []), ...(json.images ?? [])].some((item) => item.uri && !item.uri.startsWith("data:"))) {
    throw new Error("File GLB thiếu dữ liệu đi kèm");
  }
}

function disposeObject(root: THREE.Object3D): void {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry.dispose();
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      Object.values(material).forEach((value: unknown) => { if (value instanceof THREE.Texture) value.dispose(); });
      material.dispose();
    }
  });
}

/** Bytes immutable; đổi checksum/unmount sẽ abort fetch và giải phóng tài nguyên cũ. */
export function GlbArtifact({ jobId, layer }: { jobId: string; layer: ViewerLayer }) {
  const reference = layer.reference;
  const url = reference ? jobArtifactContentUrl(jobId, reference) : null;
  const [state, setState] = useState<{ url: string; root?: THREE.Group; error?: string } | null>(null);
  const wireframe = layer.kind === "collider";
  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    let root: THREE.Group | undefined;
    void fetch(url, { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error(`Artifact HTTP ${response.status}`);
      const bytes = await response.arrayBuffer();
      requireEmbeddedGlb(bytes);
      return new GLTFLoader().parseAsync(bytes, "");
    }).then((asset) => {
      root = asset.scene;
      if (controller.signal.aborted) { disposeObject(root); return; }
      if (wireframe) root.traverse((object) => {
        if (object instanceof THREE.Mesh) for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
          if ("wireframe" in material) material.wireframe = true;
        }
      });
      setState({ url, root });
    }).catch((error: unknown) => { if (!controller.signal.aborted) setState({ url, error: String(error) }); });
    return () => { controller.abort(); if (root) disposeObject(root); };
  }, [url, wireframe]);
  if (!state || state.url !== url) return null;
  if (state.error) return <Html><p role="alert">{state.error}</p></Html>;
  return state.root ? <primitive object={state.root} position={layer.transform.translation_xyz}
    quaternion={layer.transform.rotation_quaternion_xyzw} dispose={null} /> : null;
}
