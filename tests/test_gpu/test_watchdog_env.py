"""Off-VM GPU watchdog env: container paths rewritten, provisioning forced off, worker secrets dropped."""

from pathlib import Path

from scripts.cloud.watchdog_env import render

API_ENV = {
    "DATABASE_URL": "postgresql://user:secret@db.example:6543/postgres",
    "ARTIFACT_ROOT": "/app/data/studio_local/artifacts",
    "PRODUCT_PROCESSING_CONFIG": "/app/configs/product/processing_presets_v1.json",
    "PRODUCT_INPUT_RUNTIME_REGISTRY": "/app/data/input_runtime_registry.json",
    "GPU_AUTOPROVISION_ENABLED": "true",
    "GPU_CONTROLLER_RUN": "true",
    "GPU_WORKER_ENV_FILE": "/run/r2s/worker.env",
    "GPU_RELEASE_CATALOG": "/run/r2s/gpu-catalog.json",
    "PRODUCT_DEMO_REQUIRED": "true",
    "R2S_BOOTSTRAP_DISPLAY_NAME": "Real2Sim Administrator",
    "EMPTY": None,
}


def test_render_rewrites_paths_and_never_provisions() -> None:
    out = render(API_ENV, Path("/w/catalog.json"), Path("/w/repo"), Path("/w/scratch"))
    assert out["ARTIFACT_ROOT"] == "/w/scratch/data/studio_local/artifacts"
    assert out["PRODUCT_PROCESSING_CONFIG"] == "/w/repo/configs/product/processing_presets_v1.json"
    assert out["GPU_RELEASE_CATALOG"] == out["PRODUCT_GPU_RELEASE_CATALOG"] == "/w/catalog.json"
    assert out["GPU_AUTOPROVISION_ENABLED"] == "false"
    assert out["PRODUCT_DEMO_REQUIRED"] == "false"
    assert out["DATABASE_URL"] == API_ENV["DATABASE_URL"]
    assert out["R2S_BOOTSTRAP_DISPLAY_NAME"] == "Real2Sim Administrator"
    for dropped in ("GPU_WORKER_ENV_FILE", "GPU_CONTROLLER_RUN", "PRODUCT_INPUT_RUNTIME_REGISTRY", "EMPTY"):
        assert dropped not in out
