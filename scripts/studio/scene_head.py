"""Inspect or incrementally backfill one job's verified SceneIR revision head.

Read-only dry run::

    python -m scripts.studio.scene_head --job-id <job-id>

Apply one bounded page and repeat the command until status is COMPLETE::

    python -m scripts.studio.scene_head --job-id <job-id> --apply --page-size 250

Use the same DATABASE_URL, ARTIFACT_ROOT and optional ARTIFACT_S3_* settings as
the Studio API. The default invocation validates the whole legacy chain without
writing repair state. Apply writes resumable progress and never rewrites artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.config import Settings, get_settings
from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver, S3ObjectStore
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.heads import (
    SceneHeadBackfill,
    SceneHeadBackfillError,
    SceneHeadBackfillResult,
    SceneHeadRepository,
)


def _resolver(settings: Settings) -> ArtifactResolver:
    """Build the same local-cache/optional-S3 resolver used by the Studio runtime."""
    if not settings.artifact_s3_bucket:
        return ArtifactResolver(settings.artifact_root)
    if not settings.artifact_s3_access_key_id or not settings.artifact_s3_secret_access_key:
        raise ValueError("ARTIFACT_S3_BUCKET requires both ARTIFACT_S3_ACCESS_KEY_ID and ARTIFACT_S3_SECRET_ACCESS_KEY")
    store = S3ObjectStore(
        settings.artifact_s3_bucket,
        endpoint_url=settings.artifact_s3_endpoint,
        region=settings.artifact_s3_region,
        access_key_id=settings.artifact_s3_access_key_id,
        secret_access_key=settings.artifact_s3_secret_access_key.get_secret_value(),
    )
    return ArtifactResolver(settings.artifact_root, ArtifactRemote(store, settings.artifact_s3_prefix))


def _result_payload(result: SceneHeadBackfillResult, mode: str) -> dict[str, Any]:
    """Serialize only stable state and safe diagnostics for operator output."""
    head = result.head
    return {
        "job_id": result.job_id,
        "mode": mode,
        "status": result.status,
        "verified_count": result.verified_count,
        "phase": result.phase,
        "cursor_revision": result.cursor_revision,
        "diagnostic_code": result.diagnostic_code,
        "head": (
            {
                "scene_id": head.scene_id,
                "scene_revision": head.scene_revision,
                "scene_ir_checksum": head.scene_ir_checksum,
                "scene_reference": head.scene_reference.model_dump(mode="json"),
                "generation": head.generation,
                "allocation_sequence": head.allocation_sequence,
                "head_checksum": head.head_checksum,
            }
            if head is not None
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Run a read-only inspection or a bounded number of repair pages."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job-id", required=True, help="job whose immutable scene/ revisions are verified")
    parser.add_argument("--apply", action="store_true", help="persist resumable progress and commit the head")
    parser.add_argument("--page-size", type=int, default=250, help="maximum revisions checked per page (default: 250)")
    parser.add_argument(
        "--apply-pages", type=int, default=1, help="bounded pages to run in this invocation (default: 1)"
    )
    args = parser.parse_args(argv)
    if args.page_size < 1 or args.apply_pages < 1:
        parser.error("--page-size and --apply-pages must be positive")

    try:
        settings = get_settings()
        database = RuntimeDatabase(settings.database_url)
        resolver = _resolver(settings)
        editor = SceneEditor(Path(__file__).resolve().parents[2] / "tests" / "fixtures", resolver)
        backfill = SceneHeadBackfill(resolver, editor, SceneHeadRepository(database))
        if args.apply:
            result = None
            for _ in range(args.apply_pages):
                result = backfill.backfill_page(args.job_id, page_size=args.page_size)
                if result.status != "IN_PROGRESS":
                    break
            if result is None:
                raise RuntimeError("no backfill page was executed")
            mode = "apply"
        else:
            result = backfill.inspect(args.job_id)
            mode = "inspect"
    except SceneHeadBackfillError as error:
        print(
            json.dumps(
                {
                    "job_id": args.job_id,
                    "mode": "apply" if args.apply else "inspect",
                    "status": "BLOCKED",
                    "diagnostic_code": error.diagnostic_code,
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Scene head repair failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print(json.dumps(_result_payload(result, mode), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
