"""SceneIR revision service for the product viewer (PRODUCT-06)."""

from src.services.orchestration.scene.editor import SceneEditor, scene_artifact_uri
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.models import (
    SceneEditCommand,
    SceneEditResult,
    SceneObjectVisibility,
    SceneRevision,
    TransformEdit,
    VisualBinding,
)

__all__ = [
    "SceneEditCommand",
    "SceneEditRejectedError",
    "SceneEditResult",
    "SceneEditor",
    "SceneError",
    "SceneObjectNotFoundError",
    "SceneObjectVisibility",
    "SceneRevision",
    "SceneRevisionConflictError",
    "TransformEdit",
    "VisualBinding",
    "scene_artifact_uri",
]
