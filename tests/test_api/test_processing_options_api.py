"""HTTP scenario catalog, recommendations and sealed scene configuration."""

import json
from itertools import product
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.services.orchestration.processing import job_config_reference
from tests.test_api.test_studio_routes import _ATTESTATION, _record_machine, _upload
from tests.test_api.test_studio_routes import client as client  # noqa: F401
from tests.test_api.test_studio_routes import studio as studio  # noqa: F401


@pytest.mark.asyncio
async def test_options_return_complete_scenario_catalog(client: AsyncClient, studio: SimpleNamespace) -> None:
    response = await client.get("/api/v1/processing/options")
    assert response.status_code == 200
    body = response.json()
    assert set(body["presets"]) == {
        "minimum_quality",
        "maximum",
        "machine_maximum",
        "video_indoor_walkthrough",
        "video_indoor_orbital_360",
        "video_single_object",
        "video_outdoor_forward",
        "photo_collection_indoor",
        "photo_collection_outdoor",
    }
    assert {spec["group"] for spec in body["parameters"]} == {
        "sampling",
        "colmap",
        "brush",
        "geometry",
        "scene",
        "simulation",
    }
    keys = {spec["key"] for spec in body["parameters"]}
    assert all(set(values) == keys for values in body["presets"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_type,environment,scope,target",
    list(
        product(
            ["video_continuous", "video_loop_360", "photo_set"],
            ["indoor", "outdoor"],
            ["single_object", "full_room"],
            ["minimum_quality", "balanced", "machine_maximum"],
        )
    ),
)
async def test_suggestion_preserves_scenario_intent_and_evaluation(
    client: AsyncClient, studio: SimpleNamespace, input_type: str, environment: str, scope: str, target: str
) -> None:
    _record_machine(studio, 24)
    response = await client.post(
        "/api/v1/processing/suggest",
        json={
            "input_type": input_type,
            "environment": environment,
            "subject_scope": scope,
            "target_capacity": target,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    params = body["params"]
    assert (
        params["colmap.matching_mode"]
        == {
            "video_continuous": "sequential",
            "video_loop_360": "sequential_vocab_tree",
            "photo_set": "exhaustive",
        }[input_type]
    )
    if scope == "single_object":
        assert params["scene.max_objects"] == 1
    assert params["simulation.ground_plane"] == ("enabled" if environment == "indoor" else "disabled")
    evaluated = await client.post("/api/v1/processing/evaluate", json={"params": params})
    assert evaluated.status_code == 200
    assert body["evaluation"] == evaluated.json()
    assert body["evaluation"]["blocking"] is False


@pytest.mark.asyncio
async def test_suggestion_handles_unknown_and_inadequate_worker(client: AsyncClient, studio: SimpleNamespace) -> None:
    request = dict(
        input_type="video_continuous", environment="indoor", subject_scope="full_room", target_capacity="balanced"
    )
    unknown = await client.post("/api/v1/processing/suggest", json=request)
    assert unknown.status_code == 200
    assert {resource["status"] for resource in unknown.json()["evaluation"]["resources"]} == {"unknown"}
    _record_machine(studio, 0)
    unavailable = await client.post("/api/v1/processing/suggest", json=request)
    assert unavailable.status_code == 409 and "GPU" in unavailable.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch", [{"input_type": "unknown"}, {"environment": "studio"}, {"target_capacity": "unlimited"}, {"extra": True}]
)
async def test_invalid_scenario_is_rejected(client: AsyncClient, studio: SimpleNamespace, patch: dict) -> None:
    request = dict(
        input_type="video_continuous", environment="indoor", subject_scope="full_room", target_capacity="balanced"
    )
    response = await client.post("/api/v1/processing/suggest", json=request | patch)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_suggested_controls_are_saved_when_creating_scene(client: AsyncClient, studio: SimpleNamespace) -> None:
    _record_machine(studio, 24)
    suggested = await client.post(
        "/api/v1/processing/suggest",
        json={
            "input_type": "video_loop_360",
            "environment": "outdoor",
            "subject_scope": "single_object",
            "target_capacity": "balanced",
        },
    )
    assert suggested.status_code == 200
    params = suggested.json()["params"]
    upload = await _upload(client)
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={
            "upload_id": upload["upload_id"],
            "name": "Scenario fixture",
            "attestation": _ATTESTATION,
            "processing": params,
        },
    )
    assert created.status_code == 201, created.text
    job = created.json()["job"]
    path = studio.registry.runtime_resolver.require(job_config_reference(job["job_id"], job["config_checksum"]))
    stored = json.loads(path.read_bytes())
    assert stored["params"] == params
    for group in ("geometry", "scene", "simulation"):
        assert stored[group] == {
            key.split(".", 1)[1]: value for key, value in params.items() if key.startswith(group + ".")
        }
    assert stored["colmap"]["matching_mode"] == "sequential_vocab_tree"
