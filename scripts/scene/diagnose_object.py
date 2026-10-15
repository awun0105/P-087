"""Read stored evidence without invoking SAM2, ObjectGS or collider generation."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.contracts.artifacts import ProductArtifactRef  # noqa: E402
from src.services.scene.diagnostic_report import export_masks, load_evidence, render_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--reference", type=Path, help="evidence-ref.json written by the producer")
    inputs.add_argument("--job-id", help="list or inspect stored attempts using the configured artifact resolver")
    parser.add_argument("--object-id")
    parser.add_argument("--checksum", help="select an immutable attempt from --job-id; absent means list only")
    parser.add_argument("--output", type=Path, help="write Markdown instead of stdout")
    parser.add_argument("--export-masks", type=Path, help="restore retained masks as checksum-verified PNGs")
    args = parser.parse_args()
    from src.services.orchestration.projects import get_project_registry

    registry = get_project_registry()
    resolver = registry.runtime_resolver
    if args.reference:
        reference = ProductArtifactRef.model_validate_json(args.reference.read_bytes())
        if reference.artifact_type != "ObjectPipelineEvidence":
            parser.error("reference is not ObjectPipelineEvidence")
        path = resolver.require(reference)
        checksum, job_id = reference.artifact_checksum, reference.job_id
    else:
        registry.get_job(args.job_id)  # validate that this is a known job before resolving its directory
        directory = resolver.resolve(f"artifact://jobs/{args.job_id}/scene/diagnostics/placeholder.json").parent
        if not args.checksum:
            for path in sorted(directory.glob("*.json")):
                checksum = "sha256:" + path.stem
                manifest = load_evidence(path.read_bytes(), checksum=checksum, job_id=args.job_id)
                print(f"{checksum} {manifest.run_id} {manifest.status} {manifest.input_revision}")
            return 0
        checksum, job_id = args.checksum, args.job_id
        # A checksum is a content selector, never an arbitrary filesystem component.
        if (
            not checksum.startswith("sha256:")
            or len(checksum) != 71
            or any(c not in "0123456789abcdef" for c in checksum[7:])
        ):
            parser.error("invalid SHA-256 checksum")
        path = directory / (checksum[7:] + ".json")
    manifest = load_evidence(path.read_bytes(), checksum=checksum, job_id=job_id)
    if args.export_masks:
        export_masks(manifest, args.export_masks)
    report = render_report(manifest, args.object_id)
    if args.output:
        args.output.write_text(report)
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
