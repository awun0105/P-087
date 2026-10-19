"""Add a frozen interactive workspace to explicitly selected legacy demo bundles."""

import argparse

from src.config import get_settings
from src.services.orchestration.projects.registry import get_project_registry
from src.services.orchestration.samples.bundle import DemoLibrary
from src.services.orchestration.samples.workspace import freeze_workspace, load_workspace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample", action="append", required=True, help="Published sample ID; repeat for multiple samples"
    )
    args = parser.parse_args()
    settings, registry = get_settings(), get_project_registry()
    for sample_id in args.sample:
        bundle = DemoLibrary(settings.product_demo_dir).bundle(sample_id)
        freeze_workspace(registry, bundle, recording_dir=settings.product_rerun_recording_dir)
        snapshot = load_workspace(bundle)
        print(f"{sample_id}: {snapshot.job.job_id} {snapshot.head.scene_revision}, {len(snapshot.files)} artifacts")


if __name__ == "__main__":
    main()
