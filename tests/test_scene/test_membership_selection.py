"""Source-row edits must never infer ownership from a moved display pose."""

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.object_membership import ObjectMembershipReassignCommand
from src.services.scene.decomposition.gaussian_split import positions
from src.services.scene.editing.membership import ObjectMembershipValidationError, select_source_gaussians
from tests.test_scene.test_object_correction import _fixture


def _command(fixture, indices, **changes):
    return ObjectMembershipReassignCommand.model_validate(
        {
            "expected_scene_revision": fixture.scene.scene_revision,
            "membership_checksum": fixture.membership.labels_ref.artifact_checksum,
            "source_visual_checksum": fixture.membership.source_visual_ref.artifact_checksum,
            "source_gaussian_indices": indices,
            "source_object_id": "candidate-001",
            "target_object_id": "candidate-002",
            **changes,
        }
    )


def test_exact_source_rows_preview_excludes_other_owners_and_protected_floor(tmp_path):
    fixture = _fixture(tmp_path)
    original = fixture.source_labels.copy()
    protected = np.zeros(9, dtype=bool)
    protected[1] = True
    command = _command(fixture, [0, 1, 2, 4, 8])
    selected, preview = select_source_gaussians(
        positions(fixture.source_rows), fixture.source_labels, fixture.membership, command, protected=protected
    )
    assert np.flatnonzero(selected).tolist() == [0, 2]
    assert preview["source_gaussian_indices"] == [0, 2]
    assert preview["wrong_owner_count"] == 2
    assert preview["protected_count"] == 1
    assert preview["affected_object_ids"] == ["candidate-001", "candidate-002"]
    np.testing.assert_array_equal(fixture.source_labels, original)
    assert fixture.editor.current("job-fixture-001").scene == fixture.scene


@pytest.mark.parametrize("indices", [[1, 0], [1, 1], [-1], [], [1.5], [True]])
def test_reject_ambiguous_or_invalid_source_indices(tmp_path, indices):
    fixture = _fixture(tmp_path)
    with pytest.raises(ValidationError):
        _command(fixture, indices)


def test_wrong_source_checksum_and_out_of_bounds_fail(tmp_path):
    fixture = _fixture(tmp_path)
    for command in (_command(fixture, [9]), _command(fixture, [0], source_visual_checksum="sha256:" + "a" * 64)):
        with pytest.raises(ObjectMembershipValidationError):
            select_source_gaussians(positions(fixture.source_rows), fixture.source_labels, fixture.membership, command)


def test_background_add_and_object_remove_use_exclusive_source_owner(tmp_path):
    fixture = _fixture(tmp_path)
    for source, target, indices in ((None, "candidate-001", [8]), ("candidate-001", None, [0, 2])):
        command = _command(fixture, indices, source_object_id=source, target_object_id=target)
        selected, preview = select_source_gaussians(
            positions(fixture.source_rows), fixture.source_labels, fixture.membership, command
        )
        assert np.flatnonzero(selected).tolist() == indices
        assert preview["gaussian_count"] == len(indices)
