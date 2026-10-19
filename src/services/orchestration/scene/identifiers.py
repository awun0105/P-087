"""Stable logical identifiers for immutable scene artifacts."""


def scene_artifact_uri(job_id: str, scene_revision: str) -> str:
    """Return the logical URI for a SceneIR revision without exposing disk paths."""
    return f"artifact://jobs/{job_id}/scene/scene_ir.{scene_revision}.json"
