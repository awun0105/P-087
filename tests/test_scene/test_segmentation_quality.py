"""Annotated synthetic quality regressions; these are not real-scene acceptance."""

import numpy as np
import pytest

from eval.fixtures.segmentation import cases, floor_model
from eval.object.segmentation_quality import instance_labels, ownership_metrics
from src.services.scene.sampro3d.consolidate import Proposal, Sampro3dConfig, segment


@pytest.mark.parametrize("case", cases(), ids=lambda c: c.name)
def test_legacy_quality_characterization(case):
    expected_missing = dict(
        prompt_switch=60,
        occluded_part=20,
        disconnected_part=20,
        nearby_fused_view=0,
        complementary_prompts=0,
        near_floor=30,
    )
    instances = segment(case.proposal, case.points, floor_model(case))
    metrics = ownership_metrics(case.truth, instance_labels(instances, len(case.points)))
    assert metrics["object_to_background"] == expected_missing[case.name]
    assert metrics["background_leakage"] == 0
    assert metrics["merge_errors"] == (1 if case.name == "nearby_fused_view" else 0)


def test_metrics_penalize_merge_split_and_background_instead_of_candidate_count():
    truth = np.array([0, 0, 1, 1, -1])
    merged = ownership_metrics(truth, np.array([0, 0, 0, 0, 0]))
    assert merged["merge_errors"] == 1 and merged["background_leakage"] == 1
    assert merged["completeness"] == 0.5 and merged["purity"] == 0.4
    split = ownership_metrics(truth, np.array([0, 2, 1, 1, -1]))
    assert split["split_errors"] == 1 and split["completeness"] == 0.75
    assert split["purity"] < 1
    with pytest.raises(ValueError, match="overlapping"):
        instance_labels([np.array([0, 1]), np.array([1, 2])], 5)


@pytest.mark.parametrize("case", cases(), ids=lambda c: c.name)
def test_multiview_refinement_recovers_annotation_without_purity_tradeoff(case, tmp_path):
    from src.services.scene.diagnostics import EvidenceRecorder

    config = Sampro3dConfig(refinement="multiview_v1")
    baseline = ownership_metrics(
        case.truth, instance_labels(segment(case.proposal, case.points, floor_model(case)), len(case.points))
    )
    refined = segment(
        case.proposal, case.points, floor_model(case), config, evidence=EvidenceRecorder(tmp_path, "segmentation")
    )
    metrics = ownership_metrics(case.truth, instance_labels(refined, len(case.points)))
    assert metrics["completeness"] == metrics["purity"] == 1
    assert metrics["completeness"] >= baseline["completeness"]
    assert metrics["purity"] >= baseline["purity"]
    assert metrics["split_errors"] == metrics["merge_errors"] == metrics["background_leakage"] == 0
    # Stable identity under reordered input records; one exclusive owner per Gaussian.
    order = np.arange(len(case.proposal.iou))[::-1]
    shuffled = Proposal(
        view=case.proposal.view[order],
        prompt=case.proposal.prompt[order],
        iou=case.proposal.iou[order],
        members=[case.proposal.members[i] for i in order],
        visible=case.proposal.visible,
    )
    actual = segment(shuffled, case.points, floor_model(case), config)
    assert all(np.array_equal(a, b) for a, b in zip(refined, actual, strict=True))


def test_refinement_requires_visibility_and_does_not_duplicate_single_view_evidence():
    c = cases()[0]
    config = Sampro3dConfig(refinement="multiview_v1")
    p = c.proposal
    with pytest.raises(ValueError, match="visibility"):
        segment(Proposal(p.view, p.prompt, p.iou, p.members), c.points, floor_model(c), config)
    repeated = Proposal(np.zeros(3, dtype=int), np.full(3, p.prompt[0]), np.ones(3), [p.members[0]] * 3, p.visible)
    assert segment(repeated, c.points, floor_model(c), config) == []
