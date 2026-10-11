"""Build source-bound registration QA reports from measured ICP evidence."""

from collections.abc import Sequence

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import artifact_model_checksum
from src.models.contracts.rgb_lidar_registration import (
    RegistrationFindingCode,
    RegistrationInputMode,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationQAReport,
    RegistrationQAStatus,
    RegistrationRequest,
    seal_registration_qa_report,
    validate_registration_qa_binding,
)
from src.services.reconstruction.alignment.constrained_icp import RefinedRegistrationCandidate

_INCONCLUSIVE_FINDINGS = frozenset(
    {
        RegistrationFindingCode.AMBIGUOUS_CANDIDATES,
        RegistrationFindingCode.DIFFERENT_SCENE,
        RegistrationFindingCode.FLOOR_UNSUPPORTED,
        RegistrationFindingCode.METRIC_CONFIRMATION_REQUIRED,
        RegistrationFindingCode.SAME_SCENE_CONTEXT_MISSING,
        RegistrationFindingCode.TARGET_FLOOR_EVIDENCE_REQUIRED,
        RegistrationFindingCode.UNQUALIFIED_PROFILE,
    }
)


def build_registration_qa_report(
    request: RegistrationRequest,
    proposal: RegistrationProposal,
    proposal_ref: ProductArtifactRef,
    refined: RefinedRegistrationCandidate | None,
    *,
    candidate_margin: float | None,
    floor_difference_m: float | None,
    same_scene_verified: bool | None,
    server_qualification_verified: bool = False,
    evidence_refs: Sequence[ProductArtifactRef] = (),
) -> RegistrationQAReport:
    """Seal QA evidence for one exact proposal; unqualified inputs cannot PASS.

    ``same_scene_verified`` must come from the server's resolved assembly/job
    lineage, and ``server_qualification_verified`` must mean that the exact
    qualification record bytes were resolved and verified. Client declarations
    copied into the request are not sufficient for either gate.
    """
    if (
        proposal_ref.artifact_type != "RegistrationProposalArtifact"
        or proposal_ref.artifact_checksum != artifact_model_checksum(proposal)
        or proposal_ref.job_id != request.target_job_id
        or not proposal_ref.artifact_uri.startswith(f"artifact://jobs/{request.target_job_id}/")
    ):
        raise ValueError("proposal reference does not identify the exact proposal for this target job")

    findings = list(proposal.findings)
    metrics = refined
    candidate_id: str | None = None
    if proposal.state == RegistrationProposalState.PROPOSED:
        if proposal.selected_candidate_id is None or refined is None:
            raise ValueError("a selected proposal needs its exact measured ICP candidate")
        selected = next(
            (
                candidate
                for candidate in proposal.candidates
                if candidate.candidate_id == proposal.selected_candidate_id
            ),
            None,
        )
        if selected is None or refined.candidate != selected:
            raise ValueError("ICP measurements do not belong to the selected proposal candidate")
        candidate_id = selected.candidate_id
    elif refined is not None:
        raise ValueError("ambiguous or incomplete proposals cannot bind measurements to a selected candidate")
    elif not findings:
        findings.append(RegistrationFindingCode.AMBIGUOUS_CANDIDATES)

    if (
        request.profile.qualification_state != "qualified"
        or request.profile.qualification_record_ref is None
        or not server_qualification_verified
    ):
        findings.append(RegistrationFindingCode.UNQUALIFIED_PROFILE)
    if request.metric_state != "confirmed" or (metrics is not None and metrics.candidate.rgb_scale_factor is not None):
        findings.append(RegistrationFindingCode.METRIC_CONFIRMATION_REQUIRED)
    if request.floor_state == "unsupported":
        findings.append(RegistrationFindingCode.FLOOR_UNSUPPORTED)
    elif request.floor_state != "supported":
        findings.append(RegistrationFindingCode.FLOOR_UNCERTAIN)
    elif floor_difference_m is None:
        findings.append(RegistrationFindingCode.FLOOR_UNCERTAIN)
        missing_floor_evidence = True
    else:
        missing_floor_evidence = False
    if request.floor_state == "unsupported":
        missing_floor_evidence = False
    elif request.floor_state != "supported":
        missing_floor_evidence = True

    if request.source.mode != RegistrationInputMode.SENSOR_PACKAGE:
        if same_scene_verified is True and request.source.same_scene_attestation is not True:
            raise ValueError("server-verified same-scene context is not bound into the sealed request")
        if same_scene_verified is False:
            findings.append(RegistrationFindingCode.DIFFERENT_SCENE)
        elif same_scene_verified is None:
            findings.append(RegistrationFindingCode.SAME_SCENE_CONTEXT_MISSING)

    if metrics is not None:
        profile = request.profile
        if not metrics.converged:
            findings.append(RegistrationFindingCode.ICP_NOT_CONVERGED)
        if (
            metrics.source_coverage_ratio < profile.minimum_source_coverage_ratio
            or metrics.target_coverage_ratio < profile.minimum_target_coverage_ratio
        ):
            findings.append(RegistrationFindingCode.LOW_COVERAGE)
        if metrics.overlap_ratio < profile.minimum_overlap_ratio:
            findings.append(RegistrationFindingCode.LOW_OVERLAP)
        if metrics.bidirectional_p95_residual_m > profile.maximum_bidirectional_p95_residual_m:
            findings.append(RegistrationFindingCode.HIGH_RESIDUAL)
        if metrics.observable_dof < profile.minimum_observable_dof:
            findings.append(RegistrationFindingCode.UNOBSERVABLE)
        if candidate_margin is None or candidate_margin < profile.minimum_candidate_margin:
            findings.append(RegistrationFindingCode.AMBIGUOUS_CANDIDATES)
        if floor_difference_m is not None and floor_difference_m > profile.maximum_floor_difference_m:
            findings.append(RegistrationFindingCode.FLOOR_UNCERTAIN)
        if not metrics.regions:
            findings.append(RegistrationFindingCode.LOW_COVERAGE)
        for region in metrics.regions:
            if (
                region.correspondence_count == 0
                or region.source_coverage_ratio < profile.minimum_source_coverage_ratio
                or region.target_coverage_ratio < profile.minimum_target_coverage_ratio
            ):
                findings.append(RegistrationFindingCode.LOW_COVERAGE)
            if region.p95_residual_m is None or region.p95_residual_m > profile.maximum_bidirectional_p95_residual_m:
                findings.append(RegistrationFindingCode.HIGH_RESIDUAL)

    findings = list(dict.fromkeys(findings))
    has_inconclusive_gate = (
        proposal.state != RegistrationProposalState.PROPOSED
        or missing_floor_evidence
        or any(finding in _INCONCLUSIVE_FINDINGS for finding in findings)
    )
    if has_inconclusive_gate:
        result = RegistrationQAStatus.INCONCLUSIVE
    elif findings:
        result = RegistrationQAStatus.FAIL
    else:
        result = RegistrationQAStatus.PASS

    report_evidence = [
        proposal_ref,
        proposal.source_geometry_ref,
        proposal.target_rgb_geometry_ref,
        *request.floor_evidence_refs,
        *evidence_refs,
    ]
    if request.metric_confirmation_ref is not None:
        report_evidence.append(request.metric_confirmation_ref)
    if request.profile.qualification_record_ref is not None:
        report_evidence.append(request.profile.qualification_record_ref)
    unique_evidence: list[ProductArtifactRef] = []
    seen: set[tuple[str, str, str]] = set()
    for reference in report_evidence:
        if reference.job_id != request.target_job_id or not reference.artifact_uri.startswith(
            f"artifact://jobs/{request.target_job_id}/"
        ):
            raise ValueError("registration QA evidence must resolve inside the target job")
        identity = (reference.artifact_type, reference.artifact_uri, reference.artifact_checksum)
        if identity not in seen:
            seen.add(identity)
            unique_evidence.append(reference)

    report = seal_registration_qa_report(
        {
            "job_id": request.target_job_id,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "proposal_ref": proposal_ref,
            "proposal_checksum": proposal.proposal_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_checksum": proposal.source_geometry_ref.artifact_checksum,
            "target_geometry_checksum": request.target_rgb_geometry_ref.artifact_checksum,
            "target_scene_revision": request.expected_scene_revision,
            "profile": request.profile,
            "profile_checksum": request.profile_checksum,
            "metric_state": request.metric_state,
            "floor_state": request.floor_state,
            "same_scene_attestation": request.source.same_scene_attestation,
            "result": result,
            "candidate_id": candidate_id,
            "source_coverage_ratio": metrics.source_coverage_ratio if metrics is not None else None,
            "target_coverage_ratio": metrics.target_coverage_ratio if metrics is not None else None,
            "overlap_ratio": metrics.overlap_ratio if metrics is not None else None,
            "bidirectional_p95_residual_m": metrics.bidirectional_p95_residual_m if metrics is not None else None,
            "floor_difference_m": floor_difference_m,
            "observable_dof": metrics.observable_dof if metrics is not None else None,
            "candidate_margin": candidate_margin,
            "regions": list(metrics.regions) if metrics is not None else [],
            "evidence_refs": unique_evidence,
            "findings": findings,
            "report_checksum": "sha256:" + "0" * 64,
        }
    )
    validate_registration_qa_binding(request, proposal, report)
    return report
