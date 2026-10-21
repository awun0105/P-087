"""Scenario coverage, video/worker facts, one shared resource bisection and impossible-budget rejection (T-071)."""

from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import pytest

from src.services.orchestration.processing.config import load_presets
from src.services.orchestration.processing.models import MachineCapability, ScenarioPreferences, VideoFacts
from src.services.orchestration.processing.recommender import RecommendationUnavailableError, recommend_preset
from src.services.orchestration.processing.resources import RESOURCE_KEYS, estimate_gb

PRESETS = Path("configs/product/processing_presets_v1.json")


def machine(vram: float, ram: float = 32, disk: float = 100, vocab: bool | None = True) -> MachineCapability:
    return MachineCapability(
        worker_id="fixture",
        measured_at=datetime.now(UTC),
        gpu_name="fixture GPU",
        vram_total_gb=vram,
        cpu_count=8,
        ram_total_gb=ram,
        disk_free_gb=disk,
        colmap_vocab_tree_available=vocab,
    )


def preferences(**changes: object) -> ScenarioPreferences:
    return ScenarioPreferences.model_validate(
        dict(input_type="video_continuous", environment="indoor", subject_scope="full_room", target_capacity="standard")
        | changes
    )


def video(seconds: float, width: int = 1920, height: int = 1080) -> dict[str, object]:
    return {"duration_seconds": seconds, "display_width": width, "display_height": height, "frame_rate": 30.0}


@pytest.mark.parametrize(
    "input_type,environment,scope,target",
    list(
        product(
            ["video_continuous", "video_loop_360", "photo_set"],
            ["indoor", "outdoor"],
            ["single_object", "full_room"],
            ["standard", "high_quality"],
        )
    ),
)
def test_every_scenario_has_a_valid_deterministic_catalog_entry(
    input_type: str, environment: str, scope: str, target: str
) -> None:
    presets, _ = load_presets(PRESETS)
    prefs = preferences(input_type=input_type, environment=environment, subject_scope=scope, target_capacity=target)
    worker = machine(24, ram=64, disk=200)
    original = presets.model_dump()
    recommendation = recommend_preset(prefs, worker, presets)
    name, params = recommendation.name, recommendation.params
    expected = (
        f"photo_collection_{environment}"
        if input_type == "photo_set"
        else "video_single_object"
        if scope == "single_object"
        else "video_outdoor_forward"
        if environment == "outdoor"
        else "video_indoor_orbital_360"
        if input_type == "video_loop_360"
        else "video_indoor_walkthrough"
    )
    assert name == expected
    assert presets.validate_params(params) == params
    # Video liên tục giữ cách ghép của kịch bản: đi bộ trong nhà dùng khép vòng (A5).
    expected_mode = {
        "photo_set": "exhaustive",
        "video_loop_360": "sequential_vocab_tree",
        "video_continuous": presets.presets[expected]["colmap.matching_mode"],
    }[input_type]
    assert params["colmap.matching_mode"] == expected_mode
    assert params["geometry.external_fill_size_m"] == (1.6 if environment == "indoor" and scope == "full_room" else 0)
    assert params["geometry.floor_fill_size_m"] == (1.6 if environment == "outdoor" and scope == "full_room" else 0)
    assert params["simulation.ground_plane"] == ("enabled" if environment == "indoor" else "disabled")
    if scope == "single_object":
        assert params["scene.max_objects"] == 1
    assert recommend_preset(prefs, worker, presets) == recommendation
    params["brush.max_splats"] = 0
    assert presets.model_dump() == original


def test_high_quality_multiplies_scenario_values_within_schema_and_viewer_caps() -> None:
    presets, _ = load_presets(PRESETS)
    worker = machine(48, ram=256, disk=1000)
    standard = recommend_preset(preferences(), worker, presets).params
    high = recommend_preset(preferences(target_capacity="high_quality"), worker, presets).params
    scenario = presets.presets["video_indoor_walkthrough"]
    assert standard["sampling.max_frames"] == scenario["sampling.max_frames"] == 800
    assert high["sampling.max_frames"] == 1200
    assert high["colmap.max_num_features"] == 16384  # 12288 × 1,5 kẹp ở trần 16.384
    assert high["brush.total_train_iters"] == 40000
    assert high["brush.max_splats"] == 3_000_000
    for key in ("sampling.sample_fps", "colmap.sequential_overlap", "brush.max_resolution", "brush.sog_iterations"):
        assert high[key] == standard[key]
    outdoor = recommend_preset(preferences(environment="outdoor", target_capacity="high_quality"), worker, presets)
    assert outdoor.params["brush.max_splats"] == 4_000_000  # 3 triệu × 1,5 kẹp ở trần viewer


def test_small_disk_worker_never_goes_below_minimum_and_keeps_stability_controls() -> None:
    """(a) + (b): máy 24 GB VRAM / 32 GB RAM / 20 GB đĩa từng ra 1.000 bước, 480 px, 100.000 Gaussian."""
    presets, _ = load_presets(PRESETS)
    minimum = presets.presets["minimum_quality"]
    worker = machine(24, ram=32, disk=20)
    for input_type, environment, scope, target in product(
        ["video_continuous", "video_loop_360", "photo_set"],
        ["indoor", "outdoor"],
        ["single_object", "full_room"],
        ["standard", "high_quality"],
    ):
        prefs = preferences(input_type=input_type, environment=environment, subject_scope=scope, target_capacity=target)
        recommendation = recommend_preset(prefs, worker, presets)
        params = recommendation.params
        for key in RESOURCE_KEYS:
            assert float(params[key]) >= float(minimum[key]), (recommendation.name, key, params[key])
        unscaled = recommend_preset(prefs, machine(80, ram=512, disk=4000), presets).params
        for key in (
            "sampling.sample_fps",
            "colmap.sequential_overlap",
            "brush.total_train_iters",
            "brush.sog_iterations",
        ):
            assert params[key] == unscaled[key], (recommendation.name, key)
        required = estimate_gb(presets.resource_model, params)
        assert required["disk"] < 20 * presets.resource_model.warn_ratio
    limited = recommend_preset(preferences(), worker, presets)
    assert "machine_limited" in limited.fallbacks
    assert any(note.startswith("Máy xử lý giới hạn ổ đĩa: giảm") for note in limited.notes)


def test_long_video_spreads_frames_and_keeps_scenario_overlap_as_floor() -> None:
    """(c): 300 s @3 fps với trần 800 → 800 frame; overlap = ceil(5 × 800/300) = 14 < 15 → giữ 15 của kịch bản.

    Kế hoạch ghi video 600 s → overlap 20, nhưng chính công thức của kế hoạch cho ceil(5 × 800/600) = 7 → giữ 15;
    test theo công thức (không bao giờ thấp hơn kịch bản, chỉ tăng khi số giây × fps hiệu dụng vượt kịch bản).
    """
    presets, _ = load_presets(PRESETS)
    worker = machine(48, ram=256, disk=1000)
    five = recommend_preset(preferences(video=video(300)), worker, presets)
    assert five.params["sampling.max_frames"] == 800
    assert five.params["colmap.sequential_overlap"] == 15
    assert "Video 5 phút 0 giây: lấy 2,7 khung hình mỗi giây (tối đa 800 ảnh)" in five.notes
    ten = recommend_preset(preferences(video=video(600)), worker, presets)
    assert ten.params["sampling.max_frames"] == 800
    assert ten.params["colmap.sequential_overlap"] == 15
    # Quay vòng: 7 giây × 600/240 = 17,5 → 18 thấp hơn 20 của kịch bản → 20; video ngoài trời 4 phút @4 fps:
    # 960 > 800 → 4 × 800/240 = 13,3 → 14 > 12 của kịch bản → 14.
    loop = recommend_preset(preferences(input_type="video_loop_360", video=video(240)), worker, presets)
    assert loop.params["colmap.sequential_overlap"] == 20
    outdoor = recommend_preset(preferences(environment="outdoor", video=video(240)), worker, presets)
    assert outdoor.params["sampling.max_frames"] == 800
    assert outdoor.params["colmap.sequential_overlap"] == 14


def test_short_video_uses_its_own_frame_count_below_the_minimum_preset() -> None:
    """(d): video 20 s @3 fps = 60 frame; sàn của bộ thu nhỏ không đẩy lên 300."""
    presets, _ = load_presets(PRESETS)
    for worker in (machine(24), None, machine(24, disk=12)):
        params = recommend_preset(preferences(video=video(20)), worker, presets).params
        assert params["sampling.max_frames"] == 60
    assert recommend_preset(preferences(video=video(7)), machine(24), presets).params["sampling.max_frames"] == 60
    assert recommend_preset(preferences(video=video(41)), machine(24), presets).params["sampling.max_frames"] == 130


def test_720p_video_caps_resolution_and_lowers_the_vram_estimate() -> None:
    """(e)"""
    presets, _ = load_presets(PRESETS)
    worker = machine(24, ram=64, disk=200)
    full = recommend_preset(preferences(video=video(60)), worker, presets)
    small = recommend_preset(preferences(video=video(60, 1280, 720)), worker, presets)
    portrait = recommend_preset(preferences(video=video(60, 720, 1280)), worker, presets)
    assert full.params["colmap.max_image_size"] == 1920 and full.params["brush.max_resolution"] == 1920
    assert small.params["colmap.max_image_size"] == 1280 and small.params["brush.max_resolution"] == 1280
    assert portrait.params == small.params
    assert "Video 1280×720: độ phân giải huấn luyện 1.280 px" in small.notes
    assert not any("độ phân giải" in note for note in full.notes)
    model = presets.resource_model
    assert estimate_gb(model, small.params)["vram"] < estimate_gb(model, full.params)["vram"]


@pytest.mark.parametrize("vocab", [False, None])
def test_worker_without_vocabulary_falls_back_to_sequential_with_a_note(vocab: bool | None) -> None:
    """(f): worker cũ (None) hoặc chưa có từ điển → không gửi job sẽ chết với VOCAB_TREE_MISSING."""
    presets, _ = load_presets(PRESETS)
    for input_type in ("video_continuous", "video_loop_360"):
        recommendation = recommend_preset(preferences(input_type=input_type), machine(24, vocab=vocab), presets)
        assert recommendation.params["colmap.matching_mode"] == "sequential"
        assert "vocab_tree_unavailable" in recommendation.fallbacks
        assert any("chưa có từ điển khép vòng" in note for note in recommendation.notes)
    with_vocab = recommend_preset(preferences(input_type="video_loop_360"), machine(24), presets)
    assert with_vocab.params["colmap.matching_mode"] == "sequential_vocab_tree"
    assert not with_vocab.fallbacks


def test_unknown_worker_uses_minimum_without_claiming_measurement() -> None:
    """(g)"""
    presets, _ = load_presets(PRESETS)
    recommendation = recommend_preset(preferences(target_capacity="high_quality"), None, presets)
    values = recommendation.params
    assert all(values[key] == presets.presets["minimum_quality"][key] for key in RESOURCE_KEYS)
    assert values["brush.total_train_iters"] == 40000  # chỉ khóa tài nguyên về sàn
    assert values["geometry.external_fill_size_m"] == 1.6
    assert values["colmap.matching_mode"] == "sequential"
    assert "Chưa có số đo máy xử lý; dùng mức an toàn" in recommendation.notes
    assert recommendation.fallbacks == ["vocab_tree_unavailable", "capability_unknown"]


def test_large_photo_set_is_flagged_without_changing_matching() -> None:
    presets, _ = load_presets(PRESETS)
    recommendation = recommend_preset(preferences(input_type="photo_set", photo_count=450), machine(24), presets)
    assert recommendation.params["colmap.matching_mode"] == "exhaustive"
    assert "Bộ ảnh 450 ảnh: ghép mọi cặp sẽ mất nhiều giờ; nên dưới 300 ảnh" in recommendation.notes
    # Bộ ảnh không đọc thời lượng video kể cả khi client gửi nhầm.
    ignored = recommend_preset(preferences(input_type="photo_set", video=video(20)), machine(24), presets)
    assert ignored.params["sampling.max_frames"] == presets.presets["photo_collection_indoor"]["sampling.max_frames"]


def test_four_and_twenty_four_gb_workers_scale_training_together_with_ram() -> None:
    """Một lần chia đôi chung: máy 4 GB VRAM vẫn nhỏ hơn máy 24 GB ở ba khóa Brush; số frame có thể khác."""
    presets, _ = load_presets(PRESETS)
    prefs = preferences(target_capacity="high_quality")
    small = recommend_preset(prefs, machine(4), presets).params
    large = recommend_preset(prefs, machine(24), presets).params
    for key in ("brush.max_splats", "brush.max_resolution"):
        assert small[key] < large[key]
    assert small["brush.total_train_iters"] == large["brush.total_train_iters"]  # không bao giờ hạ thầm
    for params, vram in ((small, 4), (large, 24)):
        required = estimate_gb(presets.resource_model, params)
        assert required["vram"] < vram * presets.resource_model.warn_ratio
        assert required["ram"] < 32 * presets.resource_model.warn_ratio
        assert required["disk"] < 100 * presets.resource_model.warn_ratio


@pytest.mark.parametrize("target", ["standard", "high_quality"])
def test_unusable_worker_is_not_recommended_as_safe(target: str) -> None:
    presets, _ = load_presets(PRESETS)
    for worker in (machine(0), machine(1), machine(4, ram=0.5), machine(4, disk=0.01)):
        with pytest.raises(RecommendationUnavailableError):
            recommend_preset(preferences(target_capacity=target), worker, presets)


def test_busy_worker_uses_recorded_idle_budget() -> None:
    presets, _ = load_presets(PRESETS)
    idle = machine(24).model_copy(
        update={
            "idle_measured_at": datetime.now(UTC),
            "idle_vram_free_gb": 20,
            "idle_ram_available_gb": 24,
            "idle_disk_free_gb": 80,
        }
    )
    busy = idle.model_copy(
        update={"headroom_measured": True, "vram_free_gb": 0.1, "ram_available_gb": 0.2, "disk_free_gb": 1}
    )
    prefs = preferences(target_capacity="high_quality")
    assert recommend_preset(prefs, busy, presets) == recommend_preset(prefs, idle, presets)


def test_incomplete_idle_measurement_fails_instead_of_guessing() -> None:
    presets, _ = load_presets(PRESETS)
    worker = machine(24).model_copy(update={"idle_measured_at": datetime.now(UTC)})
    with pytest.raises(RecommendationUnavailableError):
        recommend_preset(preferences(), worker, presets)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_type", "other"),
        ("environment", "space"),
        ("subject_scope", "none"),
        ("target_capacity", "balanced"),
        ("target_capacity", "machine_maximum"),
        ("unknown", "value"),
        ("photo_count", 0),
    ],
)
def test_scenario_schema_rejects_unknown_choices(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        preferences(**{field: value})


@pytest.mark.parametrize(
    "facts",
    [
        {"duration_seconds": 0, "display_width": 1920, "display_height": 1080},
        {"duration_seconds": float("inf"), "display_width": 1920, "display_height": 1080},
        {"duration_seconds": 10, "display_width": 8, "display_height": 1080},
        {"duration_seconds": 10, "display_width": 1920, "display_height": 1080, "frame_rate": 0},
        {"duration_seconds": 10, "display_width": 1920, "display_height": 1080, "codec": "h264"},
    ],
)
def test_video_facts_reject_impossible_values(facts: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        VideoFacts.model_validate(facts)
