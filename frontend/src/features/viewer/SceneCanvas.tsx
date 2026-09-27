"use client";

/**
 * Canvas Three.js của viewer.
 *
 * Transform của mỗi layer lấy thẳng từ SceneIR (qua `layers.ts`), không lấy từ
 * state nội bộ của Three.js — kéo gizmo chỉ tạo ra một **command**, và canonical
 * transform chỉ đổi sau khi backend publish revision mới.
 */

import { Canvas } from "@react-three/fiber";
import { GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import { layerKey, type LayerTransform, type ViewerLayer } from "@/features/viewer/layers";
import type { PlyCloud } from "@/features/viewer/ply";

export interface SceneCanvasProps {
  layers: ViewerLayer[];
  clouds: Record<string, PlyCloud>;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  mode: string;
}

/** Quaternion canonical (xyzw) → Euler của Three.js, không tự đảo thứ tự. */
export function toEuler(quaternion: readonly [number, number, number, number]): [number, number, number] {
  const [x, y, z, w] = quaternion;
  return new THREE.Euler().setFromQuaternion(new THREE.Quaternion(x, y, z, w), "XYZ").toArray() as [
    number,
    number,
    number,
  ];
}

function layerPosition(layer: LayerTransform): [number, number, number] {
  return [...layer.translation_xyz];
}

function ColliderBox({ layer, selected }: { layer: ViewerLayer; selected: boolean }) {
  if (layer.kind !== "collider") {
    return null;
  }
  return (
    <mesh position={layerPosition(layer.transform)} rotation={toEuler(layer.transform.rotation_quaternion_xyzw)}>
      <boxGeometry args={[...layer.dimensions_xyz_m]} />
      <meshBasicMaterial
        color={selected ? "#f59e0b" : "#38bdf8"}
        wireframe
        transparent
        opacity={selected ? 0.95 : 0.55}
      />
    </mesh>
  );
}

function PointCloud({ layer, cloud }: { layer: ViewerLayer; cloud: PlyCloud | undefined }) {
  const geometry = useMemo(() => {
    if (!cloud) {
      return null;
    }
    const built = new THREE.BufferGeometry();
    built.setAttribute("position", new THREE.BufferAttribute(cloud.positions, 3));
    return built;
  }, [cloud]);

  if (layer.kind === "collider" || !geometry) {
    return null;
  }
  return (
    <points
      geometry={geometry}
      position={layerPosition(layer.transform)}
      rotation={toEuler(layer.transform.rotation_quaternion_xyzw)}
    >
      <pointsMaterial size={0.08} color="#e879f9" sizeAttenuation />
    </points>
  );
}

export function SceneCanvas({ layers, clouds, selectedKey, onSelect, mode }: SceneCanvasProps) {
  return (
    <Canvas camera={{ position: [6, 6, 6], fov: 50 }} data-testid="scene-canvas" data-mode={mode}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[5, 8, 5]} intensity={0.9} />
      <Grid args={[20, 20]} cellColor="#334155" sectionColor="#475569" infiniteGrid />
      {layers.map((layer) => {
        // Dùng chung `layerKey` với panel: tự dựng key ở đây thì khoá của canvas
        // và khoá của danh sách layer lệch nhau, chọn layer sẽ không ăn.
        const key = layerKey(layer);
        const selected = key === selectedKey;
        return (
          <group key={key} onClick={() => onSelect(selected ? null : key)}>
            {layer.kind === "collider" ? (
              <ColliderBox layer={layer} selected={selected} />
            ) : (
              <PointCloud layer={layer} cloud={clouds[key] ?? clouds[layer.checksum]} />
            )}
          </group>
        );
      })}
      <OrbitControls makeDefault enablePan enableZoom enableRotate />
      <GizmoHelper alignment="bottom-right" margin={[70, 70]}>
        <GizmoViewport axisColors={["#ef4444", "#22c55e", "#3b82f6"]} labelColor="#e2e8f0" />
      </GizmoHelper>
    </Canvas>
  );
}
