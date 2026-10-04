"""Stable EX-SCENE worker boundary for fixture-first processing."""

from dataclasses import dataclass

from src.models.contracts.artifacts import ArtifactRef, JsonObject
from src.models.contracts.manifests import ExecutionError, StageId
from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts.store import ArtifactResolver
from src.services.scene.association.baseline import associate_masks
from src.services.scene.bundle_consumer import load_reconstruction_bundle
from src.services.scene.candidates.builder import build_candidates
from src.services.scene.candidates.operations import confirm_candidate
from src.services.scene.decomposition.baseline import decompose_scene
from src.services.scene.extraction.deterministic import extract_fixture_masks
from src.services.scene.publisher import build_scene_ir


@dataclass(frozen=True)
class SceneWorkerResult:
    """Worker result with either SceneIR or structured stage error."""

    status: str
    scene_ir: SceneIR | None
    error: ExecutionError | None
    diagnostics: JsonObject


def run_fixture_scene_worker(reference: ArtifactRef, resolver: ArtifactResolver) -> SceneWorkerResult:
    """Run the local deterministic scene path from bundle ref to SceneIR."""
    try:
        scene_ir = _run_pipeline(reference, resolver)
    except (ValueError, OSError) as error:
        return _failed(str(error))
    return SceneWorkerResult(
        status="SUCCEEDED",
        scene_ir=scene_ir,
        error=None,
        diagnostics={"mode": "deterministic_fixture", "scene_ir_checksum": scene_ir.scene_ir_checksum},
    )


def _run_pipeline(reference: ArtifactRef, resolver: ArtifactResolver) -> SceneIR:
    view = load_reconstruction_bundle(reference, resolver)
    mask_set = extract_fixture_masks(view)
    groups = associate_masks(mask_set, view)
    candidates = tuple(confirm_candidate(item, "scene-worker")[0] for item in build_candidates(groups))
    decomposition = decompose_scene(candidates, view)
    return build_scene_ir(decomposition, view)


def _failed(message: str) -> SceneWorkerResult:
    error = ExecutionError(
        error_code="SCENE_WORKER_FAILED",
        stage_id=StageId.SCENE_DECOMPOSE,
        human_message=message,
        retryable=True,
    )
    return SceneWorkerResult(status="FAILED", scene_ir=None, error=error, diagnostics={"mode": "deterministic_fixture"})
