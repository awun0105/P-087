"""Revision-bound Studio/Walk environment bytes from shared collision composition."""

from functools import lru_cache

import numpy as np
import trimesh

from src.models.contracts.scene import SceneIR
from src.services.orchestration.jobs.display_glb import display_space_glb
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.effective_collision import (
    _job_simulation_config,
    _recover_legacy_source_ownership,
    effective_environment,
)
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.scene.effective_collision import CarvedBackground


def effective_collision_for_revision(
    registry: ProjectRegistry, job_id: str, revision: str, *, preview_pending: bool = False
) -> tuple[SceneIR, CarvedBackground]:
    scene = registry.scene.current(job_id).scene
    if scene.scene_revision != revision:
        raise SceneRevisionConflictError("collision request does not match current SceneIR revision")
    scene, _ = _recover_legacy_source_ownership(registry, job_id, scene)
    controls = _job_simulation_config(registry, job_id)
    return scene, effective_environment(
        registry,
        scene,
        margin_m=controls["carve_margin_m"],
        preview_pending=preview_pending,
        repair_surfaces=preview_pending,
    )


@lru_cache(maxsize=8)
def _mesh_bytes(identity: str, vertices: bytes, faces: bytes, display: bool) -> bytes:
    # Identity includes source checksum, removal mask and algorithm parameters; arrays bind exact output bytes.
    mesh = trimesh.Trimesh(
        np.frombuffer(vertices, dtype=np.float64).reshape(-1, 3),
        np.frombuffer(faces, dtype=np.int64).reshape(-1, 3),
        process=False,
    )
    payload = mesh.export(file_type="glb")
    return display_space_glb(payload) if display else payload


def effective_collision_bytes(background: CarvedBackground, *, display: bool) -> bytes:
    return _mesh_bytes(
        background.identity,
        np.asarray(background.vertices, dtype=np.float64).tobytes(),
        np.asarray(background.faces, dtype=np.int64).tobytes(),
        display,
    )
