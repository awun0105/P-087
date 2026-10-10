"""Ma trận tổ hợp video + file LiDAR rời: resolver ra luồng nào, thiếu gì, loại gì.

Hai loại phép thử:
- Đặc tả hành vi hiện tại (pass): khoá các kết luận đang đúng để các pha sau không làm hỏng.
- Lỗ hổng đã biết (`xfail(strict=True)`): ghi lại điều đáng ra phải đúng. Khi sửa xong, test tự
  chuyển xanh và `strict` buộc phải bỏ dấu xfail, nên danh sách lỗ hổng không bị bỏ quên.
"""

from __future__ import annotations

import pytest

from tests.test_reconstruction.support.input_matrix import Capture, outcome, resolve

# ---------------------------------------------------------------------------
# Hành vi hiện tại cần giữ
# ---------------------------------------------------------------------------


def test_video_alone_is_ready_as_r1() -> None:
    result = outcome(Capture())
    assert result.state == "ready"
    assert result.recommended
    assert result.groups() == {"R1"}


def test_single_cloud_without_declared_state_offers_both_readings_and_asks() -> None:
    result = outcome(Capture(clouds=1))
    assert result.state == "needs_input"
    assert result.groups() == {"R2", "R3"}
    assert "CLOUD_STATE_REQUIRED" in result.facts("R2")
    assert "CLOUD_STATE_REQUIRED" in result.facts("R3")


@pytest.mark.parametrize(("state", "group"), [("registered_map", "R2"), ("single_static_cloud", "R3")])
def test_single_cloud_with_declared_state_is_ready(state: str, group: str) -> None:
    result = outcome(Capture(clouds=1, cloud_state=state))
    assert result.state == "ready"
    assert result.groups() == {group}


def test_cloud_never_falls_back_to_rgb_only_silently() -> None:
    """Có LiDAR mà chưa chọn ý định thì không được lặng lẽ dựng R1 và bỏ LiDAR."""
    for capture in (Capture(clouds=1), Capture(clouds=2), Capture(clouds=1, cloud_state="registered_map")):
        assert "R1" not in outcome(capture).groups()


def test_explicit_video_intent_is_the_only_way_to_run_rgb_only_beside_a_cloud() -> None:
    result = outcome(Capture(clouds=1, intent="video_reconstruction"))
    assert "R1" in result.groups()


def test_registered_map_with_calibration_and_times_has_no_sensor_guided_route_without_poses() -> None:
    """R6 cần pose cảm biến theo thời gian; map đã đăng ký không có, nên không có R6 mà không có quỹ đạo."""
    result = outcome(Capture(clouds=1, cloud_state="registered_map", calibration=True, rgb_times=True))
    assert "R6" not in result.groups()


def test_registered_map_with_full_sensor_set_offers_r6_blocked_only_by_frame_map() -> None:
    result = outcome(Capture(clouds=1, cloud_state="registered_map", calibration=True, rgb_times=True, trajectory=True))
    assert "R6" in result.groups()
    assert result.facts("R6") == {"VERIFIED_RGB_FRAME_MAP_REQUIRED"}


def test_raw_scans_without_times_are_asked_for_order_and_scan_times() -> None:
    result = outcome(Capture(clouds=2, cloud_state="raw_scan_sequence"))
    assert result.groups() == {"R5"}
    assert result.facts("R5") == {"SCAN_SEQUENCE_ORDER_REQUIRED", "LIDAR_SCAN_TIMESTAMPS_REQUIRED"}


def test_raw_scans_with_scan_times_only_need_the_order_confirmed() -> None:
    result = outcome(Capture(clouds=2, cloud_state="raw_scan_sequence", lidar_times=True))
    assert result.facts("R5") == {"SCAN_SEQUENCE_ORDER_REQUIRED"}


def test_scan_order_is_always_a_user_fact_never_inferred() -> None:
    for capture in (
        Capture(clouds=2, cloud_state="raw_scan_sequence", lidar_times=True),
        Capture(clouds=2, cloud_state="raw_scan_sequence", trajectory=True, calibration=True, rgb_times=True),
    ):
        report = resolve(capture)
        assert any(
            fact.code == "SCAN_SEQUENCE_ORDER_REQUIRED" for item in report.candidates for fact in item.required_facts
        )


def test_resolution_is_independent_of_runtime_ordering_of_equal_inputs() -> None:
    first = outcome(Capture(clouds=2, cloud_state="raw_scan_sequence", lidar_times=True))
    second = outcome(Capture(clouds=2, cloud_state="raw_scan_sequence", lidar_times=True))
    assert first == second


def test_missing_runtime_makes_every_complete_route_unsupported_not_ready() -> None:
    result = outcome(Capture(runtime="none"))
    assert result.state == "unsupported"
    assert not result.recommended


def test_unqualified_runtime_is_pending_verification_not_ready() -> None:
    result = outcome(Capture(runtime="wired"))
    assert result.state == "pending_verification"
    assert not result.recommended


def test_scene_mismatch_blocks_the_whole_assembly() -> None:
    result = outcome(Capture(clouds=1, cloud_state="registered_map", same_scene=False))
    assert result.state == "invalid"


# ---------------------------------------------------------------------------
# Chính sách chọn luồng tự động và loại file không dùng
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "capture",
    [
        Capture(clouds=1, cloud_state="registered_map", calibration=True),
        Capture(clouds=1, cloud_state="registered_map", rgb_times=True),
        Capture(clouds=1, cloud_state="single_static_cloud", calibration=True, rgb_times=True),
    ],
)
def test_unused_sidecars_are_excluded_with_a_warning_not_a_blocker(capture: Capture) -> None:
    report = resolve(capture)
    assert report.state.value == "ready"
    codes = {item.code for item in report.diagnostics}
    assert "UNUSED_INPUTS_EXCLUDED" in codes
    chosen = next(item for item in report.candidates if item.candidate_id == report.recommended_candidate_id)
    assert chosen.excluded_file_ids  # file bị loại được nêu tên, không biến mất


def test_better_route_wins_among_ready_candidates_and_the_reason_is_recorded() -> None:
    """Có LiDAR + ý định dựng video: R1 (bỏ cloud) và R2 cùng chạy được, R2 giữ cloud nên được ưu tiên."""
    report = resolve(Capture(clouds=1, cloud_state="registered_map", intent="video_reconstruction"))
    assert report.state.value == "ready"
    chosen = next(item for item in report.candidates if item.candidate_id == report.recommended_candidate_id)
    assert chosen.recipe_group.value == "R2"
    codes = {item.code for item in report.diagnostics}
    assert {"ROUTE_AUTO_SELECTED", "ALTERNATIVE_ROUTE_NOT_USED"} <= codes


def test_a_better_route_still_waiting_on_facts_is_never_silently_downgraded() -> None:
    """Đủ bộ cảm biến nhưng R6 còn thiếu bản đồ khung hình: không được lặng lẽ chạy R2 và bỏ calibration/quỹ đạo."""
    report = resolve(Capture(clouds=1, cloud_state="registered_map", calibration=True, rgb_times=True, trajectory=True))
    assert report.state.value == "needs_input"
    assert report.recommended_candidate_id is None
    assert "VERIFIED_RGB_FRAME_MAP_REQUIRED" in {fact.code for fact in report.missing_facts}


def test_a_wired_unqualified_better_route_is_reported_when_a_lower_route_runs() -> None:
    from src.models.contracts.input_assembly import (
        CandidateState,
        InputBinding,
        InputRole,
        MissingInputFact,
        RecipeGroup,
        RuntimeCapabilityKey,
        TrajectoryOrigin,
        VideoRecipeCandidate,
    )
    from src.services.reconstruction.inputs.input_resolver import _select_route
    from tests.test_reconstruction.test_input_assembly_resolution import _qualified, _wired

    def candidate(group: RecipeGroup, state: CandidateState, key: str, *, wired: bool = False) -> VideoRecipeCandidate:
        bindings = [InputBinding(binding_id=f"video-{key}", role=InputRole.RGB_VIDEO, file_ids=["video"])]
        if group == RecipeGroup.REGISTERED_MAP:
            bindings.append(
                InputBinding(binding_id=f"map-{key}", role=InputRole.REGISTERED_LIDAR_MAP, file_ids=["map"])
            )
        record = (_wired if wired else _qualified)(RuntimeCapabilityKey(group.value))
        return VideoRecipeCandidate(
            candidate_kind="video_recipe",
            candidate_id=f"cand-{key}",
            recipe_group=group,
            state=state,
            bindings=bindings,
            excluded_file_ids=[],
            trajectory_origin=TrajectoryOrigin.NOT_REQUIRED,
            required_facts=(
                [MissingInputFact(code="CLOCK_RELATION_REQUIRED", description="cần khai quan hệ đồng hồ")]
                if state == CandidateState.NEEDS_INPUT
                else []
            ),
            diagnostics=[],
            runtime=record,
        )

    pending_map = candidate(RecipeGroup.REGISTERED_MAP, CandidateState.PENDING_VERIFICATION, "r2", wired=True)
    ready_rgb = candidate(RecipeGroup.RGB_ONLY, CandidateState.READY, "r1")
    selection = _select_route([pending_map, ready_rgb])
    assert selection is not None
    chosen, notes = selection
    assert chosen.candidate_id == "cand-r1"
    assert "HIGHER_ROUTE_UNAVAILABLE" in {note.code for note in notes}

    # Luồng hạng cao hơn chỉ thiếu dữ kiện nhưng luồng được chọn đã dùng đủ file của nó: vẫn chạy, kèm ghi chú.
    needs_more = candidate(RecipeGroup.REGISTERED_MAP, CandidateState.NEEDS_INPUT, "r2-needs")
    same_files_lower = candidate(RecipeGroup.RGB_ONLY, CandidateState.READY, "r1-same")
    same_files_lower = same_files_lower.model_copy(update={"bindings": needs_more.bindings})
    upgraded = _select_route([needs_more, same_files_lower])
    assert upgraded is not None
    assert "HIGHER_ROUTE_NEEDS_MORE_FACTS" in {note.code for note in upgraded[1]}

    # Luồng thấp hơn bỏ file mà luồng cao hơn sẽ dùng thì không được lặng lẽ chạy.
    assert _select_route([needs_more, ready_rgb]) is None

    # Hai luồng ready cùng hạng thì không tự chọn.
    first = candidate(RecipeGroup.RGB_ONLY, CandidateState.READY, "a")
    second = candidate(RecipeGroup.RGB_ONLY, CandidateState.READY, "b")
    assert _select_route([first, second]) is None


# ---------------------------------------------------------------------------
# Lỗ hổng đã biết: đáng ra phải đúng, hiện chưa
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="R4 đòi mọi thành viên nằm trong một ZIP đã xác minh (LIDAR_PACKAGE_REQUIRED) dù file đã nộp rời; "
    "đáng ra nhận file rời. Sửa ở pha nhận file rời.",
)
def test_loose_files_must_satisfy_the_supplied_trajectory_route() -> None:
    result = outcome(
        Capture(clouds=2, cloud_state="raw_scan_sequence", trajectory=True, calibration=True, rgb_times=True)
    )
    assert "LIDAR_PACKAGE_REQUIRED" not in result.facts("R4")
