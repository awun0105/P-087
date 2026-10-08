/** Contracts for the planned grouped-upload boundary; they do not enable recipes. */

import type { ProductArtifactRef } from "@/lib/contracts/api";
import type { ClientVideoPreparationManifest, VideoStreamMetadata } from "@/lib/contracts/videoPreparation";

export type InputRole =
  | "rgb_video"
  | "registered_lidar_map"
  | "static_lidar_cloud"
  | "lidar_scan"
  | "camera_lidar_calibration"
  | "sensor_trajectory"
  | "camera_trajectory"
  | "rgb_frame_times"
  | "gaussian_scene";

export type InputAssetFormat =
  | "video_mp4"
  | "video_mov"
  | "point_cloud_ply"
  | "point_cloud_pcd"
  | "gaussian_ply"
  | "gaussian_ply_colmap"
  | "gaussian_sog"
  | "zip_unknown"
  | "calibration_json"
  | "tum_trajectory"
  | "rgb_frame_times"
  | "unknown";

export type GaussianViewFormat = "gaussian_ply" | "gaussian_ply_colmap" | "gaussian_sog";
export type InputWorkflowIntent = "video_reconstruction" | "gaussian_view_import";
export type RecipeGroup = "R1" | "R2" | "R3" | "R4" | "R5" | "R6";
export type InputResolutionState = "ready" | "needs_input" | "pending_verification" | "unsupported" | "invalid";
export type EvidenceProvenance = "declared" | "observed" | "estimated" | "verified";
export type CloudObservationState = "registered_map" | "single_static_cloud" | "raw_scan_sequence";
export type DistanceUnit = "m" | "cm" | "mm";
export type TrajectoryConvention = "world_from_sensor" | "world_from_camera" | "unknown";
export type ClockRelation = "same_clock" | "known_offset" | "unknown";
export type TrajectoryOrigin = "not_required" | "supplied" | "estimated";
export type RuntimeCapabilityKey = RecipeGroup | "gaussian_ply_view" | "gaussian_sog_view";
export type RuntimeQualificationStatus = "qualified" | "wired_unqualified" | "unavailable" | "incompatible";
export type CandidateState = "ready" | "needs_input" | "pending_verification" | "unsupported" | "invalid";

export interface ArchiveMemberRef {
  container_checksum: string;
  member_path: string;
  member_checksum: string;
  uncompressed_size_bytes: number;
}

export interface InputSourceFile {
  original_name: string;
  media_type: string;
  size_bytes: number;
  checksum: string;
  artifact_uri: string;
  data_class: "product_input" | "derived";
}

export interface InputRoleEvidence {
  role: InputRole;
  provenance: EvidenceProvenance;
  method: string | null;
  evidence_checksum: string | null;
}

export interface StagedInputFile {
  file_id: string;
  upload_id: string;
  source_file: InputSourceFile;
  observed_format: InputAssetFormat;
  archive_member: ArchiveMemberRef | null;
  role_evidence: InputRoleEvidence[];
}

export interface EvidenceValue<T> {
  value: T;
  provenance: EvidenceProvenance;
  method: string | null;
  evidence_checksum: string | null;
}

export interface InputAssemblyDeclarations {
  same_scene: EvidenceValue<boolean> | null;
  cloud_state: EvidenceValue<CloudObservationState> | null;
  coordinate_unit: EvidenceValue<DistanceUnit> | null;
  lidar_frame_id: EvidenceValue<string> | null;
  world_frame_id: EvidenceValue<string> | null;
  trajectory_convention: EvidenceValue<TrajectoryConvention> | null;
  clock_relation: EvidenceValue<ClockRelation> | null;
  clock_offset_seconds: EvidenceValue<number> | null;
}

export interface InputBinding {
  binding_id: string;
  role: InputRole;
  /** The order of IDs is significant for a scan sequence. */
  file_ids: string[];
}

export interface ServerVideoPreparationVerification {
  schema_version: "1.0";
  status: "server_verified";
  uploaded_checksum: string;
  uploaded_size_bytes: number;
  client_manifest: ClientVideoPreparationManifest;
  observed_video: VideoStreamMetadata;
  frame_map_ref: ProductArtifactRef;
  original_source_status: "client_declared_unverified";
  verification_checksum: string;
}

export interface InputAssemblySnapshot {
  schema_version: "1.0";
  assembly_id: string;
  revision: number;
  owner_id: string;
  created_at: string;
  requested_intent: InputWorkflowIntent | null;
  files: StagedInputFile[];
  bindings: InputBinding[];
  declarations: InputAssemblyDeclarations;
  video_preparation_verification: ServerVideoPreparationVerification | null;
  assembly_checksum: string;
}

export interface RuntimeCapabilityRecord {
  capability_key: RuntimeCapabilityKey;
  status: RuntimeQualificationStatus;
  runtime_id: string | null;
  runtime_version: string | null;
  qualification_evidence_checksum: string | null;
  reason_codes: string[];
}

export interface RuntimeQualificationRegistry {
  schema_version: "1.0";
  registry_version: string;
  capabilities: RuntimeCapabilityRecord[];
  registry_checksum: string;
}

export interface MissingInputFact {
  code: string;
  description: string;
  related_file_ids: string[];
}

export interface ResolutionDiagnostic {
  code: string;
  severity: "info" | "warning" | "error";
  description: string;
  related_file_ids: string[];
}

export interface VideoRecipeCandidate {
  candidate_kind: "video_recipe";
  candidate_id: string;
  recipe_group: RecipeGroup;
  state: CandidateState;
  bindings: InputBinding[];
  excluded_file_ids: string[];
  trajectory_origin: TrajectoryOrigin;
  required_facts: MissingInputFact[];
  diagnostics: ResolutionDiagnostic[];
  runtime: RuntimeCapabilityRecord;
}

export interface GaussianViewCandidate {
  candidate_kind: "gaussian_view_import";
  candidate_id: string;
  source_file_id: string;
  source_format: GaussianViewFormat;
  state: CandidateState;
  excluded_file_ids: string[];
  required_facts: MissingInputFact[];
  diagnostics: ResolutionDiagnostic[];
  runtime: RuntimeCapabilityRecord;
}

export type InputResolutionCandidate = VideoRecipeCandidate | GaussianViewCandidate;

export interface InputResolutionReport {
  schema_version: "1.0";
  assembly_id: string;
  assembly_revision: number;
  assembly_checksum: string;
  resolver_version: string;
  runtime_registry_checksum: string;
  state: InputResolutionState;
  candidates: InputResolutionCandidate[];
  recommended_candidate_id: string | null;
  missing_facts: MissingInputFact[];
  diagnostics: ResolutionDiagnostic[];
  report_checksum: string;
}

export interface RecipeComponentVersion {
  component_id: string;
  version: string;
  config_checksum: string | null;
}

export interface InputRecipe {
  schema_version: "1.0";
  recipe_id: string;
  assembly_id: string;
  assembly_revision: number;
  assembly_checksum: string;
  resolution_checksum: string;
  candidate_id: string;
  recipe_group: RecipeGroup;
  selected_by: string;
  accepted_at: string;
  bindings: InputBinding[];
  excluded_file_ids: string[];
  trajectory_origin: TrajectoryOrigin;
  component_versions: RecipeComponentVersion[];
  config_checksum: string;
  recipe_checksum: string;
}

export interface GaussianViewImportIntent {
  schema_version: "1.0";
  intent_id: string;
  assembly_id: string;
  assembly_revision: number;
  assembly_checksum: string;
  resolution_checksum: string;
  candidate_id: string;
  source_file_id: string;
  source_format: GaussianViewFormat;
  source_checksum: string;
  selected_by: string;
  selected_at: string;
  intent_checksum: string;
}

export interface InputAssemblyBindingMatrixCase {
  case_id: string;
  supplied_roles: InputRole[];
  unresolved_role_candidates: InputRole[];
  conditional_recipe_groups: RecipeGroup[];
  required_facts: string[];
  requires_user_choice: boolean;
  notes: string;
}

export interface InputAssemblyBindingMatrix {
  schema_version: "1.0";
  cases: InputAssemblyBindingMatrixCase[];
}
