"""Revision-checked commands for user-authored collision surface planes."""

import hashlib
from typing import Literal, Self

from pydantic import model_validator

from src.models.contracts.artifacts import Checksum, ContractModel
from src.models.contracts.floor_model import Vector3
from src.models.contracts.scene import SceneIR
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.orchestration.scene.models import SceneEditResult
from src.services.scene.collision_surfaces import CollisionSurfacePlane, surface_planes


class CollisionSurfaceCommand(ContractModel):
    expected_scene_revision: str
    source_checksum: Checksum
    action: Literal["mark", "remove", "fill"] = "mark"
    kind: Literal["floor", "wall"] | None = None
    points: tuple[Vector3, Vector3, Vector3] | None = None
    plane_id: str | None = None

    @model_validator(mode="after")
    def require_inputs(self) -> Self:
        if self.action == "mark" and (self.kind is None or self.points is None):
            raise ValueError("mark requires surface kind and triangle points")
        if self.action in {"remove", "fill"} and self.plane_id is None:
            raise ValueError("remove/fill requires plane_id")
        return self


def edit_collision_surfaces(scene: SceneIR, command: CollisionSurfaceCommand) -> SceneIR:
    if command.expected_scene_revision != scene.scene_revision:
        raise SceneRevisionConflictError("surface annotation requires the current SceneIR revision")
    if command.action != "remove" and (
        scene.coordinate_system.unit != "meter"
        or scene.coordinate_system.up_axis != "Z"
        or scene.coordinate_system.world_frame != "world"
        or scene.metric_scale.status != "CONFIRMED"
    ):
        raise SceneEditRejectedError("surface authoring requires confirmed canonical Z-up meters")
    source = scene.environment.collision_source_ref or scene.environment.geometry_ref
    if command.source_checksum != source.artifact_checksum:
        raise SceneEditRejectedError("surface annotation does not bind the selected collision source")
    planes = (
        surface_planes(scene.provenance, source.artifact_checksum)
        if command.action == "mark"
        else [
            CollisionSurfacePlane.model_validate(value)
            for value in scene.provenance.get("collision_surface_planes", [])
        ]
    )
    if command.action == "mark":
        digest = hashlib.sha256(command.model_dump_json(exclude={"expected_scene_revision"}).encode()).hexdigest()[:16]
        plane = CollisionSurfacePlane(
            id=f"surface-{digest}", kind=command.kind, points=command.points, source_checksum=command.source_checksum
        )
        if plane.id not in {value.id for value in planes}:
            planes.append(plane)
        if len(planes) > 32:
            raise SceneEditRejectedError("at most 32 collision surface planes are supported")
    else:
        if command.plane_id not in {value.id for value in planes}:
            raise SceneEditRejectedError("surface plane is missing")
        if command.action == "fill":
            if any(plane.source_checksum != source.artifact_checksum for plane in planes):
                raise SceneEditRejectedError("remove stale surface labels before filling another source")
            planes = [
                value.model_copy(update={"fill_regions": True}) if value.id == command.plane_id else value
                for value in planes
            ]
        else:
            planes = [value for value in planes if value.id != command.plane_id]
    provenance = dict(scene.provenance)
    provenance["collision_surface_planes"] = [plane.model_dump(mode="json") for plane in planes]
    return scene.model_copy(update={"provenance": provenance})


def publish_collision_surface(editor: SceneEditor, job_id: str, command: CollisionSurfaceCommand) -> SceneEditResult:
    updated = edit_collision_surfaces(editor.current(job_id).scene, command)
    return editor.publish_next(job_id, command.expected_scene_revision, updated, "collision_surface")
