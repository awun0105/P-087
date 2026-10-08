"""Deterministic recipe resolution for one checksummed grouped-upload assembly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from itertools import product

from src.models.contracts.input_assembly import (
    CandidateState,
    ClockRelation,
    CloudObservationState,
    GaussianViewCandidate,
    GaussianViewFormat,
    InputAssemblySnapshot,
    InputAssetFormat,
    InputBinding,
    InputResolutionCandidate,
    InputResolutionReport,
    InputResolutionState,
    InputRole,
    MissingInputFact,
    RecipeGroup,
    ResolutionDiagnostic,
    RuntimeCapabilityKey,
    RuntimeCapabilityRecord,
    RuntimeQualificationRegistry,
    RuntimeQualificationStatus,
    TrajectoryConvention,
    TrajectoryOrigin,
    VideoRecipeCandidate,
    seal_input_resolution,
    verify_input_assembly_checksum,
    verify_runtime_registry_checksum,
)
from src.services.reconstruction.inputs.input_probe import InputProbe

_RESOLVER_VERSION = "assembly-input-resolver-v1"
_MAX_MASTER_CHOICES = 12


@dataclass
class _CandidateDraft:
    kind: str
    route: RecipeGroup | None
    bindings: list[InputBinding]
    excluded_file_ids: list[str]
    trajectory_origin: TrajectoryOrigin | None
    runtime: RuntimeCapabilityRecord
    required_facts: list[MissingInputFact] = field(default_factory=list)
    diagnostics: list[ResolutionDiagnostic] = field(default_factory=list)
    gaussian_source_id: str | None = None
    gaussian_format: GaussianViewFormat | None = None
    force_pending: bool = False


def resolve_input_assembly(
    assembly: InputAssemblySnapshot,
    runtime_registry: RuntimeQualificationRegistry,
    probes: list[InputProbe] | tuple[InputProbe, ...],
) -> InputResolutionReport:
    """Resolve exact staged refs into deterministic recipes; never infer geometry QA."""
    verify_input_assembly_checksum(assembly)
    verify_runtime_registry_checksum(runtime_registry)
    probe_map, identity_errors = _validate_probes(assembly, probes)
    if identity_errors:
        return _report(
            assembly,
            runtime_registry,
            InputResolutionState.INVALID,
            [],
            [],
            identity_errors,
        )

    probe_errors = [diagnostic for probe in probe_map.values() for diagnostic in _probe_diagnostics(probe)]
    if probe_errors:
        return _report(assembly, runtime_registry, InputResolutionState.INVALID, [], [], probe_errors)

    binding_errors = _validate_explicit_bindings(assembly, probe_map)
    declaration_errors = _validate_declaration_conflicts(assembly)
    if binding_errors or declaration_errors:
        return _report(
            assembly,
            runtime_registry,
            InputResolutionState.INVALID,
            [],
            [],
            [*binding_errors, *declaration_errors],
        )

    by_id = {item.file_id: item for item in assembly.files}
    by_format: dict[InputAssetFormat, list[str]] = {}
    for item in assembly.files:
        by_format.setdefault(item.observed_format, []).append(item.file_id)
    for file_ids in by_format.values():
        file_ids.sort()

    explicit = {binding.role: list(binding.file_ids) for binding in assembly.bindings}
    videos = explicit.get(InputRole.RGB_VIDEO) or by_format.get(InputAssetFormat.VIDEO_MP4, []) + by_format.get(
        InputAssetFormat.VIDEO_MOV, []
    )
    videos = sorted(videos)
    gaussian_ids = explicit.get(InputRole.GAUSSIAN_SCENE) or sorted(
        file_id
        for fmt in (InputAssetFormat.GAUSSIAN_PLY, InputAssetFormat.GAUSSIAN_PLY_COLMAP, InputAssetFormat.GAUSSIAN_SOG)
        for file_id in by_format.get(fmt, [])
    )
    cloud_ids = sorted(
        file_id
        for fmt in (InputAssetFormat.POINT_CLOUD_PLY, InputAssetFormat.POINT_CLOUD_PCD)
        for file_id in by_format.get(fmt, [])
    )
    calibration_ids = explicit.get(InputRole.CAMERA_LIDAR_CALIBRATION) or sorted(
        file_id
        for fmt in (InputAssetFormat.CALIBRATION_JSON, InputAssetFormat.CALIBRATION_TORWIC_TEXT)
        for file_id in by_format.get(fmt, [])
    )
    frame_time_ids = explicit.get(InputRole.RGB_FRAME_TIMES) or by_format.get(InputAssetFormat.RGB_FRAME_TIMES, [])
    camera_trajectory_ids = explicit.get(InputRole.CAMERA_TRAJECTORY) or []
    trajectory_ids = explicit.get(InputRole.SENSOR_TRAJECTORY) or sorted(
        set(by_format.get(InputAssetFormat.TUM_TRAJECTORY, [])) - set(camera_trajectory_ids)
    )
    frame_time_ids = sorted(frame_time_ids)
    trajectory_ids = sorted(trajectory_ids)
    camera_trajectory_ids = sorted(camera_trajectory_ids)
    facts: list[MissingInputFact] = []
    diagnostics: list[ResolutionDiagnostic] = []
    drafts: list[_CandidateDraft] = []

    both_workflows = bool(videos and gaussian_ids) and assembly.requested_intent is None
    if assembly.requested_intent != "gaussian_view_import":
        if not videos and assembly.requested_intent == "video_reconstruction":
            facts.append(
                _fact(
                    "RGB_VIDEO_REQUIRED",
                    "Add one RGB video to run a video reconstruction recipe.",
                    gaussian_ids,
                )
            )
        elif not videos and not gaussian_ids:
            if cloud_ids or calibration_ids or trajectory_ids or frame_time_ids:
                facts.append(_fact("RGB_VIDEO_REQUIRED", "Add one RGB video to run a video reconstruction recipe."))
        elif videos:
            video_choices = _bounded_choices(videos)
            for video_id in video_choices:
                video_binding = _binding(InputRole.RGB_VIDEO, [video_id])
                if len(videos) > 1:
                    video_fact = _fact(
                        "VIDEO_SELECTION_REQUIRED",
                        "Choose the RGB video for this recipe; upload order and filenames do not select it.",
                        videos,
                    )
                else:
                    video_fact = None
                if both_workflows:
                    intent_fact = _fact(
                        "WORKFLOW_INTENT_REQUIRED",
                        "Choose video reconstruction or Gaussian view import before resolving this mixed upload.",
                        [video_id, *gaussian_ids],
                    )
                else:
                    intent_fact = None
                if not cloud_ids:
                    required = [fact for fact in (video_fact, intent_fact) if fact is not None]
                    _add_candidate(
                        drafts,
                        assembly,
                        runtime_registry,
                        RecipeGroup.RGB_ONLY,
                        [video_binding],
                        TrajectoryOrigin.NOT_REQUIRED,
                        required,
                    )
                elif assembly.requested_intent == "video_reconstruction":
                    _add_candidate(
                        drafts,
                        assembly,
                        runtime_registry,
                        RecipeGroup.RGB_ONLY,
                        [video_binding],
                        TrajectoryOrigin.NOT_REQUIRED,
                        [fact for fact in (video_fact, intent_fact) if fact is not None],
                    )

    cloud_variants, cloud_facts, cloud_diagnostics = _cloud_variants(assembly, cloud_ids, explicit)
    facts.extend(cloud_facts)
    diagnostics.extend(cloud_diagnostics)
    if videos and assembly.requested_intent != "gaussian_view_import":
        for video_id, variant in product(_bounded_choices(videos), cloud_variants):
            video_binding = _binding(InputRole.RGB_VIDEO, [video_id])
            variant_bindings = [video_binding, *variant["bindings"]]
            required = list(variant["required_facts"])
            if len(videos) > 1:
                required.append(_fact("VIDEO_SELECTION_REQUIRED", "Choose the RGB video for this recipe.", videos))
            if both_workflows:
                required.append(
                    _fact(
                        "WORKFLOW_INTENT_REQUIRED",
                        "Choose video reconstruction or Gaussian view import before running.",
                        [video_id, *gaussian_ids],
                    )
                )
            group = variant["group"]
            if group in {RecipeGroup.REGISTERED_MAP, RecipeGroup.SINGLE_STATIC_CLOUD}:
                required.extend(_map_facts(assembly, variant["cloud_ids"]))
                _add_candidate(
                    drafts,
                    assembly,
                    runtime_registry,
                    group,
                    variant_bindings,
                    TrajectoryOrigin.NOT_REQUIRED,
                    required,
                )
                if calibration_ids and frame_time_ids and trajectory_ids:
                    _add_r6_candidates(
                        drafts,
                        assembly,
                        runtime_registry,
                        video_id,
                        variant["cloud_bindings"],
                        calibration_ids,
                        trajectory_ids,
                        frame_time_ids,
                        probes=probe_map,
                        trajectory_estimated=False,
                        base_required=variant["required_facts"],
                        workflow_fact=intent_fact if both_workflows else None,
                        video_fact=video_fact if len(videos) > 1 else None,
                    )
            elif group == RecipeGroup.SUPPLIED_TRAJECTORY:
                if trajectory_ids:
                    for trajectory_id in _bounded_choices(trajectory_ids):
                        _add_supplied_scan_candidate(
                            drafts,
                            assembly,
                            runtime_registry,
                            video_id,
                            variant,
                            trajectory_id,
                            probe_map,
                            required,
                            intent_fact if both_workflows else None,
                            video_fact if len(videos) > 1 else None,
                        )
                        if calibration_ids and frame_time_ids:
                            _add_r6_candidates(
                                drafts,
                                assembly,
                                runtime_registry,
                                video_id,
                                variant["cloud_bindings"],
                                calibration_ids,
                                [trajectory_id],
                                frame_time_ids,
                                probes=probe_map,
                                trajectory_estimated=False,
                                base_required=variant["required_facts"],
                                workflow_fact=intent_fact if both_workflows else None,
                                video_fact=video_fact if len(videos) > 1 else None,
                            )
                else:
                    _add_candidate(
                        drafts,
                        assembly,
                        runtime_registry,
                        RecipeGroup.ESTIMATED_TRAJECTORY,
                        variant_bindings,
                        TrajectoryOrigin.ESTIMATED,
                        required,
                    )
                    if calibration_ids and frame_time_ids:
                        _add_r6_candidates(
                            drafts,
                            assembly,
                            runtime_registry,
                            video_id,
                            variant["cloud_bindings"],
                            calibration_ids,
                            [],
                            frame_time_ids,
                            probes=probe_map,
                            trajectory_estimated=True,
                            base_required=variant["required_facts"],
                            workflow_fact=intent_fact if both_workflows else None,
                            video_fact=video_fact if len(videos) > 1 else None,
                        )

    if assembly.requested_intent != "video_reconstruction":
        if gaussian_ids:
            for gaussian_id in _bounded_choices(gaussian_ids):
                file = by_id[gaussian_id]
                source_format = _gaussian_view_format(file.observed_format)
                required: list[MissingInputFact] = []
                if len(gaussian_ids) > 1:
                    required.append(
                        _fact(
                            "GAUSSIAN_MASTER_SELECTION_REQUIRED",
                            "Choose one exact PLY/SOG master; files from separate exports are not merged.",
                            gaussian_ids,
                        )
                    )
                if both_workflows:
                    required.append(
                        _fact(
                            "WORKFLOW_INTENT_REQUIRED",
                            "Choose video reconstruction or Gaussian view import before resolving this mixed upload.",
                            [*videos, *gaussian_ids],
                        )
                    )
                excluded = sorted(set(by_id) - {gaussian_id})
                if excluded:
                    required.append(_file_disposition_fact(excluded))
                runtime_key = (
                    RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW
                    if source_format == GaussianViewFormat.SOG
                    else RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW
                )
                runtime = _runtime(runtime_registry, runtime_key)
                state, runtime = _candidate_status(required, runtime)
                drafts.append(
                    _CandidateDraft(
                        "gaussian_view_import",
                        None,
                        [],
                        excluded,
                        None,
                        runtime,
                        required,
                        [],
                        gaussian_id,
                        source_format,
                        state == CandidateState.PENDING_VERIFICATION,
                    )
                )
        elif assembly.requested_intent == "gaussian_view_import":
            facts.append(_fact("GAUSSIAN_SCENE_REQUIRED", "Add one validated Gaussian PLY or SOG source."))

    if camera_trajectory_ids and assembly.declarations.trajectory_convention is not None:
        if assembly.declarations.trajectory_convention.value == TrajectoryConvention.WORLD_FROM_CAMERA:
            diagnostics.append(
                _diagnostic(
                    "CAMERA_TRAJECTORY_NOT_SENSOR_TRAJECTORY",
                    "warning",
                    "A camera trajectory cannot substitute for the sensor trajectory required by R4/R6.",
                    camera_trajectory_ids,
                )
            )

    if not drafts and not facts:
        diagnostics.append(
            _diagnostic(
                "UNSUPPORTED_INPUT_CONTENT",
                "warning",
                "No supported video, LiDAR, calibration, trajectory, frame-time, or Gaussian scene content was found.",
                sorted(by_id),
            )
        )
        return _report(assembly, runtime_registry, InputResolutionState.UNSUPPORTED, [], [], diagnostics)

    # A recipe is only directly ready when it is the sole complete route. Equal-quality
    # routes stay explicit choices; the resolver never ranks metadata volume as accuracy.
    preliminary = [_materialize(draft, assembly) for draft in drafts]
    ready_indices = [
        index for index, candidate in enumerate(preliminary) if _candidate_state(candidate) == CandidateState.READY
    ]
    if len(ready_indices) > 1:
        for index in ready_indices:
            drafts[index].required_facts.append(
                _fact("ROUTE_SELECTION_REQUIRED", "Choose which compatible processing route to run.")
            )
    candidates = [_materialize(draft, assembly) for draft in drafts]
    candidates.sort(key=lambda item: item.candidate_id)
    candidate_facts = [fact for candidate in candidates for fact in candidate.required_facts]
    all_facts = _unique_facts([*facts, *candidate_facts])
    diagnostics.extend(item for candidate in candidates for item in candidate.diagnostics)
    diagnostics = _unique_diagnostics([*diagnostics, *_probe_warnings(probe_map)])

    if not candidates:
        state = InputResolutionState.NEEDS_INPUT if all_facts else InputResolutionState.UNSUPPORTED
        if state == InputResolutionState.UNSUPPORTED and not diagnostics:
            diagnostics.append(
                _diagnostic("UNSUPPORTED_INPUT_CONTENT", "warning", "No compatible input recipe was found.")
            )
        return _report(assembly, runtime_registry, state, [], all_facts, diagnostics)

    ready = [candidate for candidate in candidates if _candidate_state(candidate) == CandidateState.READY]
    if (
        len(ready) == 1
        and not all_facts
        and all(
            _candidate_state(candidate) in {CandidateState.READY, CandidateState.UNSUPPORTED}
            for candidate in candidates
        )
    ):
        return _report(
            assembly,
            runtime_registry,
            InputResolutionState.READY,
            candidates,
            [],
            diagnostics,
            recommended_candidate_id=ready[0].candidate_id,
        )
    if any(_candidate_state(candidate) == CandidateState.NEEDS_INPUT for candidate in candidates) or all_facts:
        state = InputResolutionState.NEEDS_INPUT
    elif any(_candidate_state(candidate) == CandidateState.PENDING_VERIFICATION for candidate in candidates):
        state = InputResolutionState.PENDING_VERIFICATION
    elif all(_candidate_state(candidate) == CandidateState.UNSUPPORTED for candidate in candidates):
        state = InputResolutionState.UNSUPPORTED
    else:
        state = InputResolutionState.NEEDS_INPUT
        all_facts = [_fact("ROUTE_SELECTION_REQUIRED", "Choose one compatible processing route.")]
    if state == InputResolutionState.UNSUPPORTED and not any(
        item.severity in {"warning", "error"} for item in diagnostics
    ):
        diagnostics.append(
            _diagnostic("UNSUPPORTED_RUNTIME", "warning", "No compatible qualified runtime is registered.")
        )
    return _report(assembly, runtime_registry, state, candidates, all_facts, diagnostics)


def _validate_probes(
    assembly: InputAssemblySnapshot, probes: list[InputProbe] | tuple[InputProbe, ...]
) -> tuple[dict[str, InputProbe], list[ResolutionDiagnostic]]:
    result: dict[str, InputProbe] = {}
    diagnostics: list[ResolutionDiagnostic] = []
    for probe in probes:
        if probe.file_id in result:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_PROBE", "error", "More than one probe describes the same staged file.", [probe.file_id]
                )
            )
        result[probe.file_id] = probe
    expected = {item.file_id: item for item in assembly.files}
    if set(result) != set(expected):
        diagnostics.append(
            _diagnostic(
                "PROBE_INVENTORY_MISMATCH",
                "error",
                "Probe inventory must cover exactly the staged assembly files.",
                sorted(set(result) ^ set(expected)),
            )
        )
    for file_id in sorted(set(expected) & set(result)):
        staged, probe = expected[file_id], result[file_id]
        if probe.source_checksum != staged.source_file.checksum:
            diagnostics.append(
                _diagnostic(
                    "PROBE_SOURCE_CHECKSUM_MISMATCH",
                    "error",
                    "Probe does not bind the staged upload checksum.",
                    [file_id],
                )
            )
        member_checksum = staged.archive_member.member_checksum if staged.archive_member else None
        if probe.member_checksum != member_checksum:
            diagnostics.append(
                _diagnostic(
                    "PROBE_MEMBER_CHECKSUM_MISMATCH",
                    "error",
                    "Probe does not bind the staged archive member checksum.",
                    [file_id],
                )
            )
        if probe.observed_format != staged.observed_format:
            diagnostics.append(
                _diagnostic(
                    "PROBE_FORMAT_MISMATCH", "error", "Probe format differs from the staged-file contract.", [file_id]
                )
            )
    return result, diagnostics


def _probe_diagnostics(probe: InputProbe) -> list[ResolutionDiagnostic]:
    return [
        _diagnostic(code, severity, description, [probe.file_id])
        for code, severity, description in probe.diagnostics
        if severity == "error"
    ]


def _probe_warnings(probes: dict[str, InputProbe]) -> list[ResolutionDiagnostic]:
    return [
        _diagnostic(code, severity, description, [probe.file_id])
        for probe in probes.values()
        for code, severity, description in probe.diagnostics
        if severity != "error"
    ]


def _validate_explicit_bindings(
    assembly: InputAssemblySnapshot, probes: dict[str, InputProbe]
) -> list[ResolutionDiagnostic]:
    accepted = {
        InputRole.RGB_VIDEO: {InputAssetFormat.VIDEO_MP4, InputAssetFormat.VIDEO_MOV},
        InputRole.REGISTERED_LIDAR_MAP: {InputAssetFormat.POINT_CLOUD_PLY, InputAssetFormat.POINT_CLOUD_PCD},
        InputRole.STATIC_LIDAR_CLOUD: {InputAssetFormat.POINT_CLOUD_PLY, InputAssetFormat.POINT_CLOUD_PCD},
        InputRole.LIDAR_SCAN: {InputAssetFormat.POINT_CLOUD_PLY, InputAssetFormat.POINT_CLOUD_PCD},
        InputRole.CAMERA_LIDAR_CALIBRATION: {
            InputAssetFormat.CALIBRATION_JSON,
            InputAssetFormat.CALIBRATION_TORWIC_TEXT,
        },
        InputRole.SENSOR_TRAJECTORY: {InputAssetFormat.TUM_TRAJECTORY},
        InputRole.CAMERA_TRAJECTORY: {InputAssetFormat.TUM_TRAJECTORY},
        InputRole.RGB_FRAME_TIMES: {InputAssetFormat.RGB_FRAME_TIMES},
        InputRole.GAUSSIAN_SCENE: {
            InputAssetFormat.GAUSSIAN_PLY,
            InputAssetFormat.GAUSSIAN_PLY_COLMAP,
            InputAssetFormat.GAUSSIAN_SOG,
        },
    }
    diagnostics: list[ResolutionDiagnostic] = []
    cloud_roles = [
        binding.role
        for binding in assembly.bindings
        if binding.role in {InputRole.REGISTERED_LIDAR_MAP, InputRole.STATIC_LIDAR_CLOUD, InputRole.LIDAR_SCAN}
    ]
    declared_cloud = assembly.declarations.cloud_state.value if assembly.declarations.cloud_state else None
    role_state = {
        InputRole.REGISTERED_LIDAR_MAP: CloudObservationState.REGISTERED_MAP,
        InputRole.STATIC_LIDAR_CLOUD: CloudObservationState.SINGLE_STATIC_CLOUD,
        InputRole.LIDAR_SCAN: CloudObservationState.RAW_SCAN_SEQUENCE,
    }
    if len(cloud_roles) > 1 and len(set(role_state[role] for role in cloud_roles)) > 1:
        diagnostics.append(
            _diagnostic(
                "CONFLICTING_CLOUD_BINDINGS",
                "error",
                "Assembly binds incompatible LiDAR cloud states.",
                [
                    file_id
                    for binding in assembly.bindings
                    if binding.role in cloud_roles
                    for file_id in binding.file_ids
                ],
            )
        )
    elif declared_cloud is not None and cloud_roles and any(role_state[role] != declared_cloud for role in cloud_roles):
        diagnostics.append(
            _diagnostic(
                "CONFLICTING_CLOUD_STATE",
                "error",
                "Declared cloud state conflicts with an explicit LiDAR role binding.",
                [
                    file_id
                    for binding in assembly.bindings
                    if binding.role in cloud_roles
                    for file_id in binding.file_ids
                ],
            )
        )
    for binding in assembly.bindings:
        incompatible = [
            file_id for file_id in binding.file_ids if probes[file_id].observed_format not in accepted[binding.role]
        ]
        if incompatible:
            diagnostics.append(
                _diagnostic(
                    "ROLE_FORMAT_MISMATCH",
                    "error",
                    f"{binding.role.value} binding contains content with an incompatible format.",
                    incompatible,
                )
            )
    return diagnostics


def _validate_declaration_conflicts(assembly: InputAssemblySnapshot) -> list[ResolutionDiagnostic]:
    declarations = assembly.declarations
    video_and_cloud = any(
        item.observed_format in {InputAssetFormat.VIDEO_MP4, InputAssetFormat.VIDEO_MOV} for item in assembly.files
    ) and any(
        item.observed_format in {InputAssetFormat.POINT_CLOUD_PLY, InputAssetFormat.POINT_CLOUD_PCD}
        for item in assembly.files
    )
    diagnostics: list[ResolutionDiagnostic] = []
    if video_and_cloud and declarations.same_scene is not None and not declarations.same_scene.value:
        diagnostics.append(
            _diagnostic(
                "SCENE_MISMATCH",
                "error",
                "RGB and LiDAR are declared to describe different scenes.",
                [
                    item.file_id
                    for item in assembly.files
                    if item.observed_format
                    in {
                        InputAssetFormat.VIDEO_MP4,
                        InputAssetFormat.VIDEO_MOV,
                        InputAssetFormat.POINT_CLOUD_PLY,
                        InputAssetFormat.POINT_CLOUD_PCD,
                    }
                ],
            )
        )
    convention = declarations.trajectory_convention.value if declarations.trajectory_convention else None
    sensor_bound = any(binding.role == InputRole.SENSOR_TRAJECTORY for binding in assembly.bindings)
    camera_bound = any(binding.role == InputRole.CAMERA_TRAJECTORY for binding in assembly.bindings)
    if sensor_bound and convention == TrajectoryConvention.WORLD_FROM_CAMERA:
        diagnostics.append(
            _diagnostic(
                "TRAJECTORY_CONVENTION_CONFLICT",
                "error",
                "Sensor trajectory binding conflicts with a world_from_camera declaration.",
            )
        )
    if camera_bound and convention == TrajectoryConvention.WORLD_FROM_SENSOR:
        diagnostics.append(
            _diagnostic(
                "TRAJECTORY_CONVENTION_CONFLICT",
                "error",
                "Camera trajectory binding conflicts with a world_from_sensor declaration.",
            )
        )
    return diagnostics


def _cloud_variants(
    assembly: InputAssemblySnapshot, cloud_ids: list[str], explicit: dict[InputRole, list[str]]
) -> tuple[list[dict[str, object]], list[MissingInputFact], list[ResolutionDiagnostic]]:
    facts: list[MissingInputFact] = []
    diagnostics: list[ResolutionDiagnostic] = []
    if not cloud_ids:
        return [], facts, diagnostics
    explicit_role = next(
        (
            role
            for role in (InputRole.REGISTERED_LIDAR_MAP, InputRole.STATIC_LIDAR_CLOUD, InputRole.LIDAR_SCAN)
            if role in explicit
        ),
        None,
    )
    declared = assembly.declarations.cloud_state.value if assembly.declarations.cloud_state else None
    if explicit_role == InputRole.LIDAR_SCAN or declared == CloudObservationState.RAW_SCAN_SEQUENCE:
        scan_ids = explicit.get(InputRole.LIDAR_SCAN) or cloud_ids
        if len(scan_ids) < 2:
            facts.append(
                _fact(
                    "SCAN_SEQUENCE_NEEDS_MULTIPLE_FILES",
                    "A raw-scan sequence requires at least two LiDAR scans.",
                    scan_ids,
                )
            )
            return [], facts, diagnostics
        required = []
        if InputRole.LIDAR_SCAN not in explicit:
            required.append(
                _fact(
                    "SCAN_SEQUENCE_ORDER_REQUIRED",
                    "Confirm the chronological LiDAR scan order; filenames and upload order are not evidence.",
                    scan_ids,
                )
            )
        if declared is None and explicit_role is None:
            required.append(
                _fact("CLOUD_STATE_REQUIRED", "Confirm that these clouds are an ordered raw-scan sequence.", scan_ids)
            )
        return (
            [
                {
                    "group": RecipeGroup.SUPPLIED_TRAJECTORY,
                    "cloud_ids": scan_ids,
                    "cloud_bindings": [_binding(InputRole.LIDAR_SCAN, scan_ids)],
                    "bindings": [_binding(InputRole.LIDAR_SCAN, scan_ids)],
                    "required_facts": required,
                }
            ],
            facts,
            diagnostics,
        )

    if explicit_role in {InputRole.REGISTERED_LIDAR_MAP, InputRole.STATIC_LIDAR_CLOUD}:
        role = explicit_role
        ids = explicit[role]
        group = (
            RecipeGroup.REGISTERED_MAP if role == InputRole.REGISTERED_LIDAR_MAP else RecipeGroup.SINGLE_STATIC_CLOUD
        )
        return (
            [
                {
                    "group": group,
                    "cloud_ids": ids,
                    "cloud_bindings": [_binding(role, ids)],
                    "bindings": [_binding(role, ids)],
                    "required_facts": [],
                }
            ],
            facts,
            diagnostics,
        )

    if declared in {CloudObservationState.REGISTERED_MAP, CloudObservationState.SINGLE_STATIC_CLOUD}:
        role = (
            InputRole.REGISTERED_LIDAR_MAP
            if declared == CloudObservationState.REGISTERED_MAP
            else InputRole.STATIC_LIDAR_CLOUD
        )
        group = (
            RecipeGroup.REGISTERED_MAP if role == InputRole.REGISTERED_LIDAR_MAP else RecipeGroup.SINGLE_STATIC_CLOUD
        )
        variants = []
        selected_ids = _bounded_choices(cloud_ids)
        for cloud_id in selected_ids:
            required = []
            if len(cloud_ids) > 1:
                required.append(
                    _fact("MAP_FILE_SELECTION_REQUIRED", "Choose the one cloud file used as the map.", cloud_ids)
                )
            variants.append(
                {
                    "group": group,
                    "cloud_ids": [cloud_id],
                    "cloud_bindings": [_binding(role, [cloud_id])],
                    "bindings": [_binding(role, [cloud_id])],
                    "required_facts": required,
                }
            )
        if len(cloud_ids) > _MAX_MASTER_CHOICES:
            diagnostics.append(
                _diagnostic(
                    "CLOUD_CHOICES_TRUNCATED",
                    "warning",
                    "Map alternatives are capped; select a cloud explicitly.",
                    cloud_ids,
                )
            )
        return variants, facts, diagnostics

    if len(cloud_ids) == 1:
        cloud_id = cloud_ids[0]
        facts.append(
            _fact(
                "CLOUD_STATE_REQUIRED",
                "Declare whether this cloud is a registered map or one static observation.",
                [cloud_id],
            )
        )
        return (
            [
                {
                    "group": RecipeGroup.REGISTERED_MAP,
                    "cloud_ids": [cloud_id],
                    "cloud_bindings": [_binding(InputRole.REGISTERED_LIDAR_MAP, [cloud_id])],
                    "bindings": [_binding(InputRole.REGISTERED_LIDAR_MAP, [cloud_id])],
                    "required_facts": [
                        _fact(
                            "CLOUD_STATE_REQUIRED", "Confirm that this cloud is already a registered map.", [cloud_id]
                        )
                    ],
                },
                {
                    "group": RecipeGroup.SINGLE_STATIC_CLOUD,
                    "cloud_ids": [cloud_id],
                    "cloud_bindings": [_binding(InputRole.STATIC_LIDAR_CLOUD, [cloud_id])],
                    "bindings": [_binding(InputRole.STATIC_LIDAR_CLOUD, [cloud_id])],
                    "required_facts": [
                        _fact("CLOUD_STATE_REQUIRED", "Confirm that this is one static cloud observation.", [cloud_id])
                    ],
                },
            ],
            facts,
            diagnostics,
        )

    facts.append(
        _fact(
            "CLOUD_STATE_REQUIRED", "Declare whether these clouds are a map choice or a raw scan sequence.", cloud_ids
        )
    )
    sequence_facts = [
        _fact("CLOUD_STATE_REQUIRED", "Confirm that these clouds form a raw-scan sequence.", cloud_ids),
        _fact(
            "SCAN_SEQUENCE_ORDER_REQUIRED",
            "Confirm the chronological scan order; filenames and upload order are not evidence.",
            cloud_ids,
        ),
    ]
    variants = [
        {
            "group": RecipeGroup.SUPPLIED_TRAJECTORY,
            "cloud_ids": cloud_ids,
            "cloud_bindings": [_binding(InputRole.LIDAR_SCAN, cloud_ids)],
            "bindings": [_binding(InputRole.LIDAR_SCAN, cloud_ids)],
            "required_facts": sequence_facts,
        }
    ]
    for cloud_id in _bounded_choices(cloud_ids):
        for group, role in (
            (RecipeGroup.REGISTERED_MAP, InputRole.REGISTERED_LIDAR_MAP),
            (RecipeGroup.SINGLE_STATIC_CLOUD, InputRole.STATIC_LIDAR_CLOUD),
        ):
            variants.append(
                {
                    "group": group,
                    "cloud_ids": [cloud_id],
                    "cloud_bindings": [_binding(role, [cloud_id])],
                    "bindings": [_binding(role, [cloud_id])],
                    "required_facts": [
                        _fact("CLOUD_STATE_REQUIRED", "Confirm the cloud state for this map alternative.", cloud_ids),
                        _fact("MAP_FILE_SELECTION_REQUIRED", "Choose the exact cloud file used as the map.", cloud_ids),
                    ],
                }
            )
    if len(cloud_ids) > _MAX_MASTER_CHOICES:
        diagnostics.append(
            _diagnostic(
                "CLOUD_CHOICES_TRUNCATED",
                "warning",
                "Map alternatives are capped; select a cloud explicitly.",
                cloud_ids,
            )
        )
    return variants, facts, diagnostics


def _map_facts(assembly: InputAssemblySnapshot, file_ids: list[str]) -> list[MissingInputFact]:
    declarations = assembly.declarations
    facts = []
    if declarations.same_scene is None:
        facts.append(
            _fact("SAME_SCENE_REQUIRED", "Confirm that RGB and LiDAR describe the same physical scene.", file_ids)
        )
    if declarations.coordinate_unit is None:
        facts.append(
            _fact(
                "COORDINATE_UNIT_REQUIRED",
                "Declare the LiDAR coordinate unit; do not infer metres from scale or filename.",
                file_ids,
            )
        )
    if declarations.lidar_frame_id is None:
        facts.append(
            _fact("LIDAR_FRAME_REQUIRED", "Declare the coordinate frame represented by this LiDAR cloud.", file_ids)
        )
    return facts


def _scan_facts(assembly: InputAssemblySnapshot, file_ids: list[str], *, supplied: bool) -> list[MissingInputFact]:
    declarations = assembly.declarations
    facts = []
    if declarations.same_scene is None:
        facts.append(
            _fact("SAME_SCENE_REQUIRED", "Confirm that RGB and LiDAR describe the same physical scene.", file_ids)
        )
    if declarations.coordinate_unit is None:
        facts.append(_fact("COORDINATE_UNIT_REQUIRED", "Declare the LiDAR coordinate unit.", file_ids))
    if declarations.lidar_frame_id is None:
        facts.append(
            _fact("LIDAR_FRAME_REQUIRED", "Declare the coordinate frame represented by these scans.", file_ids)
        )
    convention = declarations.trajectory_convention.value if declarations.trajectory_convention else None
    if supplied and convention != TrajectoryConvention.WORLD_FROM_SENSOR:
        facts.append(
            _fact(
                "SENSOR_TRAJECTORY_CONVENTION_REQUIRED",
                "Confirm the supplied TUM trajectory is world_from_sensor.",
                file_ids,
            )
        )
    return facts


def _add_supplied_scan_candidate(
    drafts: list[_CandidateDraft],
    assembly: InputAssemblySnapshot,
    registry: RuntimeQualificationRegistry,
    video_id: str,
    variant: dict[str, object],
    trajectory_id: str,
    probes: dict[str, InputProbe],
    base_required: list[MissingInputFact],
    workflow_fact: MissingInputFact | None,
    video_fact: MissingInputFact | None,
) -> None:
    scan_ids = list(variant["cloud_ids"])
    trajectory_probe = probes[trajectory_id]
    required = [*base_required, *_scan_facts(assembly, scan_ids, supplied=True)]
    if trajectory_probe.record_count != len(scan_ids):
        required.append(
            _fact(
                "SCAN_POSE_PAIRING_REQUIRED",
                "Confirm a scan-to-pose mapping; the TUM row count does not match the selected ordered scans.",
                [*scan_ids, trajectory_id],
            )
        )
    if workflow_fact is not None:
        required.append(workflow_fact)
    if video_fact is not None:
        required.append(video_fact)
    bindings = [
        _binding(InputRole.RGB_VIDEO, [video_id]),
        *list(variant["bindings"]),
        _binding(InputRole.SENSOR_TRAJECTORY, [trajectory_id]),
    ]
    _add_candidate(
        drafts,
        assembly,
        registry,
        RecipeGroup.SUPPLIED_TRAJECTORY,
        bindings,
        TrajectoryOrigin.SUPPLIED,
        required,
    )


def _add_r6_candidates(
    drafts: list[_CandidateDraft],
    assembly: InputAssemblySnapshot,
    registry: RuntimeQualificationRegistry,
    video_id: str,
    cloud_bindings: list[InputBinding],
    calibration_ids: list[str],
    trajectory_ids: list[str],
    frame_time_ids: list[str],
    *,
    probes: dict[str, InputProbe],
    trajectory_estimated: bool,
    base_required: list[MissingInputFact],
    workflow_fact: MissingInputFact | None,
    video_fact: MissingInputFact | None,
) -> None:
    trajectory_choices: list[str | None] = _bounded_choices(trajectory_ids) if trajectory_ids else [None]
    for calibration_id, trajectory_id, frame_time_id in product(
        _bounded_choices(calibration_ids), trajectory_choices, _bounded_choices(frame_time_ids)
    ):
        if trajectory_estimated and trajectory_id is not None:
            continue
        if not trajectory_estimated and trajectory_id is None:
            continue
        bindings = [
            _binding(InputRole.RGB_VIDEO, [video_id]),
            *cloud_bindings,
            _binding(InputRole.CAMERA_LIDAR_CALIBRATION, [calibration_id]),
            _binding(InputRole.RGB_FRAME_TIMES, [frame_time_id]),
        ]
        if trajectory_id is not None:
            bindings.append(_binding(InputRole.SENSOR_TRAJECTORY, [trajectory_id]))
        required = [
            *base_required,
            *_map_facts(assembly, [file_id for binding in cloud_bindings for file_id in binding.file_ids]),
        ]
        if trajectory_id is not None:
            scan_ids = [
                file_id
                for binding in cloud_bindings
                if binding.role == InputRole.LIDAR_SCAN
                for file_id in binding.file_ids
            ]
            if scan_ids and probes[trajectory_id].record_count != len(scan_ids):
                required.append(
                    _fact(
                        "SCAN_POSE_PAIRING_REQUIRED",
                        "Confirm a scan-to-pose mapping; the TUM row count does not match the selected ordered scans.",
                        [*scan_ids, trajectory_id],
                    )
                )
        declarations = assembly.declarations
        convention = declarations.trajectory_convention.value if declarations.trajectory_convention else None
        if trajectory_id is None and convention not in (None, TrajectoryConvention.WORLD_FROM_SENSOR):
            required.append(
                _fact(
                    "SENSOR_TRAJECTORY_CONVENTION_REQUIRED",
                    "Estimated trajectory output must use world_from_sensor coordinates.",
                )
            )
        elif trajectory_id is not None and convention != TrajectoryConvention.WORLD_FROM_SENSOR:
            required.append(
                _fact(
                    "SENSOR_TRAJECTORY_CONVENTION_REQUIRED",
                    "Confirm the supplied TUM trajectory is world_from_sensor.",
                    [trajectory_id],
                )
            )
        if declarations.clock_relation is None or declarations.clock_relation.value == ClockRelation.UNKNOWN:
            required.append(
                _fact(
                    "CLOCK_RELATION_REQUIRED",
                    "Declare whether the sensor and RGB timestamps share a clock or have a known offset.",
                    [frame_time_id, *([trajectory_id] if trajectory_id else [])],
                )
            )
        elif (
            declarations.clock_relation.value == ClockRelation.KNOWN_OFFSET
            and declarations.clock_offset_seconds is None
        ):
            required.append(
                _fact(
                    "CLOCK_OFFSET_REQUIRED",
                    "Provide the declared sensor-to-RGB clock offset in seconds.",
                    [frame_time_id, *([trajectory_id] if trajectory_id else [])],
                )
            )
        if assembly.video_preparation_verification is None:
            required.append(
                _fact(
                    "VERIFIED_RGB_FRAME_MAP_REQUIRED",
                    "Server-verified prepared-to-source frame mapping is required for sensor-guided RGB priors.",
                )
            )
        if workflow_fact is not None:
            required.append(workflow_fact)
        if video_fact is not None:
            required.append(video_fact)
        runtime_override = None
        force_pending = False
        extra_diagnostics: list[ResolutionDiagnostic] = []
        if trajectory_estimated:
            odometry_runtime = _runtime(registry, RuntimeCapabilityKey.R5)
            cloud_file_ids = [file_id for binding in cloud_bindings for file_id in binding.file_ids]
            if odometry_runtime.status == RuntimeQualificationStatus.WIRED_UNQUALIFIED:
                force_pending = True
                extra_diagnostics.append(
                    _diagnostic(
                        "ODOMETRY_RUNTIME_UNQUALIFIED",
                        "warning",
                        "R6 depends on an odometry runtime that is wired but not qualified.",
                        cloud_file_ids,
                    )
                )
            elif odometry_runtime.status in {
                RuntimeQualificationStatus.UNAVAILABLE,
                RuntimeQualificationStatus.INCOMPATIBLE,
            }:
                runtime_override = RuntimeCapabilityRecord(
                    capability_key=RuntimeCapabilityKey.R6,
                    status=odometry_runtime.status,
                    reason_codes=["odometry_dependency_" + reason for reason in odometry_runtime.reason_codes],
                )
                extra_diagnostics.append(
                    _diagnostic(
                        "ODOMETRY_RUNTIME_UNAVAILABLE",
                        "warning",
                        "R6 estimated-trajectory alternative is blocked by the R5 runtime.",
                        cloud_file_ids,
                    )
                )
        _add_candidate(
            drafts,
            assembly,
            registry,
            RecipeGroup.SENSOR_GUIDED,
            bindings,
            TrajectoryOrigin.ESTIMATED if trajectory_estimated else TrajectoryOrigin.SUPPLIED,
            required,
            runtime_override=runtime_override,
            force_pending=force_pending,
            extra_diagnostics=extra_diagnostics,
        )


def _add_candidate(
    drafts: list[_CandidateDraft],
    assembly: InputAssemblySnapshot,
    registry: RuntimeQualificationRegistry,
    group: RecipeGroup,
    bindings: list[InputBinding],
    origin: TrajectoryOrigin,
    required: list[MissingInputFact],
    *,
    runtime_override: RuntimeCapabilityRecord | None = None,
    force_pending: bool = False,
    extra_diagnostics: list[ResolutionDiagnostic] | None = None,
) -> None:
    used = {file_id for binding in bindings for file_id in binding.file_ids}
    excluded = sorted({item.file_id for item in assembly.files} - used)
    if excluded:
        required = [*required, _file_disposition_fact(excluded)]
    runtime = runtime_override or _runtime(registry, RuntimeCapabilityKey(group.value))
    candidate = VideoRecipeCandidate(
        candidate_kind="video_recipe",
        candidate_id=_candidate_id(
            {
                "kind": "video_recipe",
                "route": group.value,
                "bindings": [_binding_identity(binding) for binding in bindings],
                "origin": origin.value,
            }
        ),
        recipe_group=group,
        state=_candidate_status(required, runtime, force_pending=force_pending)[0],
        bindings=bindings,
        excluded_file_ids=excluded,
        trajectory_origin=origin,
        required_facts=_unique_facts(required),
        runtime=runtime,
        diagnostics=[],
    )
    if excluded:
        drafts.append(
            _CandidateDraft(
                "video_recipe",
                group,
                bindings,
                excluded,
                origin,
                runtime,
                _unique_facts(required),
                [
                    _diagnostic(
                        "UNUSED_INPUTS_RETAINED",
                        "warning",
                        "These files remain outside this candidate until explicitly disposed.",
                        excluded,
                    ),
                    *(extra_diagnostics or []),
                ],
                force_pending=force_pending,
            )
        )
    else:
        drafts.append(
            _CandidateDraft(
                "video_recipe",
                group,
                bindings,
                [],
                origin,
                runtime,
                _unique_facts(required),
                extra_diagnostics or [],
                force_pending=force_pending,
            )
        )
    del candidate


def _materialize(draft: _CandidateDraft, assembly: InputAssemblySnapshot) -> InputResolutionCandidate:
    if draft.kind == "gaussian_view_import":
        if draft.gaussian_source_id is None or draft.gaussian_format is None:
            raise ValueError("Gaussian candidate draft is incomplete")
        state, runtime = _candidate_status(draft.required_facts, draft.runtime, force_pending=draft.force_pending)
        return GaussianViewCandidate(
            candidate_kind="gaussian_view_import",
            candidate_id=_candidate_id(
                {
                    "kind": draft.kind,
                    "source_file_id": draft.gaussian_source_id,
                    "source_format": draft.gaussian_format.value,
                }
            ),
            source_file_id=draft.gaussian_source_id,
            source_format=draft.gaussian_format,
            state=state,
            excluded_file_ids=draft.excluded_file_ids,
            required_facts=_unique_facts(draft.required_facts),
            diagnostics=draft.diagnostics,
            runtime=runtime,
        )
    if draft.route is None or draft.trajectory_origin is None:
        raise ValueError("Video candidate draft is incomplete")
    state, runtime = _candidate_status(draft.required_facts, draft.runtime, force_pending=draft.force_pending)
    return VideoRecipeCandidate(
        candidate_kind="video_recipe",
        candidate_id=_candidate_id(
            {
                "kind": draft.kind,
                "route": draft.route.value,
                "bindings": [_binding_identity(binding) for binding in draft.bindings],
                "origin": draft.trajectory_origin.value,
            }
        ),
        recipe_group=draft.route,
        state=state,
        bindings=draft.bindings,
        excluded_file_ids=draft.excluded_file_ids,
        trajectory_origin=draft.trajectory_origin,
        required_facts=_unique_facts(draft.required_facts),
        diagnostics=draft.diagnostics,
        runtime=runtime,
    )


def _candidate_status(
    required: list[MissingInputFact], runtime: RuntimeCapabilityRecord, *, force_pending: bool = False
) -> tuple[CandidateState, RuntimeCapabilityRecord]:
    if required:
        return CandidateState.NEEDS_INPUT, runtime
    if force_pending:
        return CandidateState.PENDING_VERIFICATION, runtime
    if runtime.status == RuntimeQualificationStatus.QUALIFIED:
        return CandidateState.READY, runtime
    if runtime.status == RuntimeQualificationStatus.WIRED_UNQUALIFIED:
        return CandidateState.PENDING_VERIFICATION, runtime
    return CandidateState.UNSUPPORTED, runtime


def _runtime(registry: RuntimeQualificationRegistry, key: RuntimeCapabilityKey) -> RuntimeCapabilityRecord:
    return next(
        (record for record in registry.capabilities if record.capability_key == key),
        RuntimeCapabilityRecord(
            capability_key=key,
            status=RuntimeQualificationStatus.UNAVAILABLE,
            reason_codes=["runtime_not_registered"],
        ),
    )


def _candidate_state(candidate: InputResolutionCandidate) -> CandidateState:
    return candidate.state


def _binding(role: InputRole, file_ids: list[str]) -> InputBinding:
    ordered_ids = list(file_ids) if role == InputRole.LIDAR_SCAN else sorted(file_ids)
    identity = hashlib.sha256((role.value + "\0" + "\0".join(ordered_ids)).encode("utf-8")).hexdigest()[:16]
    return InputBinding(binding_id=f"bind-{identity}", role=role, file_ids=ordered_ids)


def _binding_identity(binding: InputBinding) -> dict[str, object]:
    return {"role": binding.role.value, "file_ids": binding.file_ids}


def _candidate_id(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"candidate-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _bounded_choices(values: list[str]) -> list[str]:
    return sorted(values)[:_MAX_MASTER_CHOICES]


def _gaussian_view_format(fmt: InputAssetFormat) -> GaussianViewFormat:
    if fmt == InputAssetFormat.GAUSSIAN_SOG:
        return GaussianViewFormat.SOG
    if fmt == InputAssetFormat.GAUSSIAN_PLY_COLMAP:
        return GaussianViewFormat.PLY_COLMAP
    return GaussianViewFormat.PLY


def _file_disposition_fact(file_ids: list[str]) -> MissingInputFact:
    return _fact(
        "UNUSED_INPUT_DISPOSITION_REQUIRED",
        "Choose whether to retain these uploaded files for another route or explicitly exclude them from this candidate.",
        file_ids,
    )


def _fact(code: str, description: str, related_file_ids: list[str] | None = None) -> MissingInputFact:
    return MissingInputFact(code=code, description=description, related_file_ids=sorted(set(related_file_ids or [])))


def _diagnostic(
    code: str, severity: str, description: str, related_file_ids: list[str] | None = None
) -> ResolutionDiagnostic:
    return ResolutionDiagnostic(
        code=code,
        severity=severity,
        description=description,
        related_file_ids=sorted(set(related_file_ids or [])),
    )


def _unique_facts(facts: list[MissingInputFact]) -> list[MissingInputFact]:
    keyed = {(fact.code, tuple(fact.related_file_ids)): fact for fact in facts}
    return [keyed[key] for key in sorted(keyed)]


def _unique_diagnostics(diagnostics: list[ResolutionDiagnostic]) -> list[ResolutionDiagnostic]:
    keyed = {(item.code, item.severity, tuple(item.related_file_ids)): item for item in diagnostics}
    return [keyed[key] for key in sorted(keyed)]


def _report(
    assembly: InputAssemblySnapshot,
    registry: RuntimeQualificationRegistry,
    state: InputResolutionState,
    candidates: list[InputResolutionCandidate],
    missing_facts: list[MissingInputFact],
    diagnostics: list[ResolutionDiagnostic],
    *,
    recommended_candidate_id: str | None = None,
) -> InputResolutionReport:
    return seal_input_resolution(
        InputResolutionReport(
            schema_version="1.0",
            assembly_id=assembly.assembly_id,
            assembly_revision=assembly.revision,
            assembly_checksum=assembly.assembly_checksum,
            resolver_version=_RESOLVER_VERSION,
            runtime_registry_checksum=registry.registry_checksum,
            state=state,
            candidates=candidates,
            recommended_candidate_id=recommended_candidate_id,
            missing_facts=_unique_facts(missing_facts),
            diagnostics=_unique_diagnostics(diagnostics),
            report_checksum="sha256:" + "0" * 64,
        )
    )
