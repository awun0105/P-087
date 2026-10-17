import { GEOMETRY_REVIEW_STAGE, GEOMETRY_REVIEW_STAGE_ID, stagesFor, type TimelineStageId, type TimelineStageMeta } from "@/features/studio/stages";
import type { DemoManifest, DemoStage } from "@/lib/contracts/studio";

export interface ReplayStage extends Omit<DemoStage, "stage_id"> { stage_id: TimelineStageId }

export function demoReplayStages(demo: DemoManifest): ReplayStage[] {
  const geometry = demo.object_geometry;
  if (!geometry) return demo.stages;
  const facts = [
    { label: "Bề mặt từ ObjectGS", value: geometry.objectgs_count },
    { label: "Bề mặt theo cách cũ (vỏ Gaussian)", value: geometry.shell_count },
    { label: "Lưới va chạm của vật", value: geometry.collider_count },
  ].filter((fact) => fact.value != null).map((fact) => ({ label: fact.label, value: String(fact.value) }));
  return [...demo.stages, {
    stage_id: GEOMETRY_REVIEW_STAGE_ID, state: geometry.state,
    duration_seconds: geometry.duration_seconds, summary: "",
    assets: facts.length ? [{ kind: "facts", facts }] : [],
  }];
}

export function demoStageList(demo: DemoManifest): readonly TimelineStageMeta[] {
  const list = stagesFor(demo.stages.map((stage) => stage.stage_id));
  return demo.object_geometry ? [...list, GEOMETRY_REVIEW_STAGE] : list;
}
