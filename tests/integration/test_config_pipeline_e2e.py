"""HTTP preferences → sealed job → resolved tool controls → native CLI arguments.

This is the requested simulated configuration E2E; no GPU process is executed.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.services.orchestration.jobs.dispatch import resolve_job_processing
from src.services.reconstruction.adapters.colmap_runtime import reconstruction_commands
from src.services.reconstruction.finalize import build_voxel_config, load_geometry_profile
from src.services.reconstruction.rgb.geometry.voxel import collision_command, occupancy_command
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig
from tests.test_api.test_studio_routes import _ATTESTATION, _record_machine, _upload
from tests.test_api.test_studio_routes import client as client  # noqa: F401
from tests.test_api.test_studio_routes import studio as studio  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["indoor", "outdoor"])
@pytest.mark.parametrize("mesh", ["smooth", "faces"])
async def test_scenario_job_compiles_exact_native_commands(
    client: AsyncClient, studio: SimpleNamespace, environment: str, mesh: str
) -> None:
    _record_machine(studio, 24)
    recommendation = await client.post(
        "/api/v1/processing/suggest",
        json={
            "input_type": "video_loop_360",
            "environment": environment,
            "subject_scope": "full_room",
            "target_capacity": "standard",
        },
    )
    assert recommendation.status_code == 200, recommendation.text
    suggested = recommendation.json()
    assert suggested["preset_name"] == (
        "video_indoor_orbital_360" if environment == "indoor" else "video_outdoor_forward"
    )
    assert suggested["evaluation"]["blocking"] is False
    params = suggested["params"] | {"geometry.collision_mesh": mesh}
    upload = await _upload(client)
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={
            "upload_id": upload["upload_id"],
            "name": "Configuration E2E fixture",
            "attestation": _ATTESTATION,
            "processing": params,
        },
    )
    assert created.status_code == 201, created.text
    job = studio.registry.get_job(created.json()["job"]["job_id"])
    resolved = resolve_job_processing(
        job,
        studio.registry.execution_profile,
        studio.settings.product_processing_config,
        studio.registry.runtime_resolver,
        240,
    )
    colmap = ColmapConfig.model_validate(resolved.colmap)
    for flags in [("SiftExtraction", "SiftMatching"), ("FeatureExtraction", "FeatureMatching")]:
        matching = reconstruction_commands(colmap, flags)[1]
        assert matching[matching.index("--SequentialMatching.loop_detection") + 1] == "1"
        assert matching[matching.index("--SequentialMatching.vocab_tree_path") + 1] == "vocab_tree.bin"
    geometry = load_geometry_profile(ROOT / "configs/product/geometry_v1.json", overrides=resolved.geometry)
    voxel = build_voxel_config(geometry, ((-1, -1, -0.5), (1, 1, 3)), (0, 0, 0.5))
    collision = collision_command(voxel)
    assert collision[collision.index("--collision-mesh") + 1] == mesh
    for command in (collision, occupancy_command(voxel)):
        enabled = "--voxel-external-fill" if environment == "indoor" else "--voxel-floor-fill"
        disabled = "--voxel-floor-fill" if environment == "indoor" else "--voxel-external-fill"
        assert command[command.index(enabled) + 1] == "1.6"
        assert disabled not in command
    assert resolved.scene["max_objects"] == params["scene.max_objects"]
    assert resolved.simulation["ground_plane"] == ("enabled" if environment == "indoor" else "disabled")
