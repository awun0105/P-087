"""T-058: one pure function decides who must do what next."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus, StageId
from src.models.contracts.scene import SceneIR
from src.services.orchestration.pipeline.next_action import (
    NextActionFacts,
    PackageFacts,
    SceneOperationFacts,
    next_action,
    pending_candidates,
)

_DONE = NextActionFacts(
    job_status=JobStatus.SUCCEEDED,
    waiting_for=None,
    failure_retryable=None,
    awaiting_object_choice=False,
    object_geometry="ready",
    scene_operation=None,
    pending_candidates=0,
    package=PackageFacts(exists_for_revision=False, preflight_failed=False),
    review_status=None,
)


def _op(status: str, mode: str = "geometry", current: bool = True) -> SceneOperationFacts:
    return SceneOperationFacts(status=status, mode=mode, on_current_revision=current)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("facts", "kind", "step", "owner"),
    [
        (replace(_DONE, job_status=JobStatus.QUEUED), "wait_system", None, "system"),
        (replace(_DONE, job_status=JobStatus.RUNNING), "wait_system", None, "system"),
        (
            replace(_DONE, job_status=JobStatus.RUNNING, waiting_for="anonymization_review"),
            "review_anonymization",
            StageId.ANONYMIZATION_REVIEW,
            "user",
        ),
        (
            replace(_DONE, job_status=JobStatus.RUNNING, waiting_for="metric_confirmation"),
            "confirm_metric",
            StageId.METRIC_CANONICALIZE,
            "user",
        ),
        (replace(_DONE, job_status=JobStatus.FAILED, failure_retryable=True), "retry_job", None, "user"),
        (replace(_DONE, job_status=JobStatus.FAILED, failure_retryable=False), "job_failed", None, "user"),
        (replace(_DONE, job_status=JobStatus.CANCELLED), "job_cancelled", None, "user"),
        (replace(_DONE, scene_operation=_op("running")), "wait_system", StageId.SCENE_DECOMPOSE, "system"),
        (replace(_DONE, scene_operation=_op("queued", "boxes")), "wait_system", StageId.OBJECT_EXTRACT, "system"),
        (
            replace(_DONE, object_geometry="awaiting_review", scene_operation=_op("failed")),
            "retry_geometry",
            StageId.SCENE_DECOMPOSE,
            "user",
        ),
        (
            replace(_DONE, object_geometry="awaiting_review", pending_candidates=3),
            "review_objects",
            StageId.OBJECT_CONFIRM,
            "user",
        ),
        (
            replace(_DONE, object_geometry=None, awaiting_object_choice=True),
            "choose_object_method",
            StageId.OBJECT_EXTRACT,
            "user",
        ),
        (replace(_DONE, pending_candidates=2), "confirm_objects", StageId.OBJECT_CONFIRM, "user"),
        (replace(_DONE, package=None), "scene_ready", None, "user"),
        (replace(_DONE, review_status="RELEASED"), "released", None, "user"),
        (replace(_DONE, review_status="READY_FOR_REVIEW"), "await_review", None, "user"),
        (replace(_DONE, package=PackageFacts(True, False)), "review_package", None, "user"),
        (replace(_DONE, package=PackageFacts(False, True)), "fix_preflight", None, "user"),
        (_DONE, "create_package", None, "user"),
    ],
)
def test_each_rule(facts: NextActionFacts, kind: str, step: StageId | None, owner: str) -> None:
    action = next_action(facts)
    assert (action.kind, action.step_id, action.owner) == (kind, step, owner)


def test_review_objects_carries_pending_count() -> None:
    action = next_action(replace(_DONE, object_geometry="awaiting_review", pending_candidates=0))
    assert action.kind == "review_objects" and action.pending_count == 0


def test_running_geometry_beats_draft() -> None:
    facts = replace(_DONE, object_geometry="awaiting_review", scene_operation=_op("running"))
    assert next_action(facts).kind == "wait_system"


def test_failed_geometry_on_old_revision_is_review_objects() -> None:
    facts = replace(_DONE, object_geometry="awaiting_review", scene_operation=_op("failed", current=False))
    assert next_action(facts).kind == "review_objects"


def test_draft_beats_object_choice() -> None:
    facts = replace(_DONE, object_geometry="awaiting_review", awaiting_object_choice=True)
    assert next_action(facts).kind == "review_objects"


def test_list_without_package_facts_returns_scene_ready() -> None:
    facts = replace(_DONE, pending_candidates=None, package=None)
    assert next_action(facts).kind == "scene_ready"


def test_released_beats_package() -> None:
    facts = replace(_DONE, review_status="RELEASED", package=PackageFacts(True, False))
    assert next_action(facts).kind == "released"


def test_pending_candidates_ignores_ignored_and_deleted() -> None:
    fixture = Path(__file__).parents[2] / "fixtures/scene_ir/scene.json"
    scene = SceneIR.model_validate_json(fixture.read_bytes())
    candidates = [obj for obj in scene.objects if obj.state == "CANDIDATE"]
    assert pending_candidates(scene) == len(candidates)
    if candidates:
        first = candidates[0]
        ignored = first.model_copy(update={"provenance": {**first.provenance, "review": "IGNORED"}})
        objects = [ignored if obj.id == first.id else obj for obj in scene.objects]
        assert pending_candidates(scene.model_copy(update={"objects": objects})) == len(candidates) - 1
