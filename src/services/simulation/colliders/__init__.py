"""Collider generation and validation utilities for EX-SIM."""

from src.models.contracts.scene import ColliderSpec, ColliderType
from src.services.simulation.colliders.generator import (
    BoxSpecRequest,
    create_box_collider,
    create_ground_plane_collider,
    generate_collider_from_geometry,
    generate_object_collider,
)

__all__ = [
    "ColliderSpec",
    "ColliderType",
    "BoxSpecRequest",
    "create_box_collider",
    "create_ground_plane_collider",
    "generate_collider_from_geometry",
    "generate_object_collider",
]
