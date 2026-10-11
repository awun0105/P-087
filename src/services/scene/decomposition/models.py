"""Scene decomposition bindings before SceneIR construction."""

from dataclasses import dataclass

from src.models.contracts.artifacts import JsonObject, ProductArtifactRef


@dataclass(frozen=True)
class ObjectBinding:
    """Binding from a confirmed candidate to object-level representations."""

    object_id: str
    name: str
    geometry_ref: ProductArtifactRef
    source_candidate_id: str
    provenance: JsonObject


@dataclass(frozen=True)
class DecompositionResult:
    """Environment plus independent object bindings."""

    environment_geometry_ref: ProductArtifactRef
    visual_ref: ProductArtifactRef | None
    object_bindings: tuple[ObjectBinding, ...]
    provenance: JsonObject

    def __post_init__(self) -> None:
        if not self.object_bindings:
            raise ValueError("decomposition requires at least one object binding")
