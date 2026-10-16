"""Measure preview verification with temporary opaque payloads, not real 3D/GPU assets.

Run: python -m scripts.benchmark.preview_readiness --out /tmp/preview-readiness.json
The fixture excludes database, HTTP, remote storage and browser rendering costs.
"""

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageArtifact
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import ArtifactResolver, sha256_file, with_canonical_checksum
from src.services.orchestration.artifacts import store as store_module
from src.services.orchestration.projects.preview import load_job_preview
from src.services.orchestration.projects.registry import ProjectRegistry

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _payload(resolver: ArtifactResolver, name: str, artifact_type: str, mib: int) -> ProductArtifactRef:
    uri = f"artifact://jobs/benchmark-preview/attempts/first/{name}"
    path = resolver.resolve(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        for _ in range(mib):
            stream.write(b"x" * 1024 * 1024)
        if mib == 0:
            stream.write(b"{}")
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum=sha256_file(path),
        data_class="derived",
        producer_stage="ST-CAMERA-POSE" if artifact_type == "CameraPoseArtifact" else "ST-VISUAL-RECON",
        job_id="benchmark-preview",
    )


def benchmark(source_mib: int, delivery_mib: int, repeats: int) -> dict[str, object]:
    """Compare strict consumption and repeated registry reads on the same local files."""
    if source_mib < 1 or delivery_mib < 1 or repeats < 2:
        raise ValueError("source/delivery must be at least 1 MiB and repeats at least 2")
    with TemporaryDirectory(prefix="r2s-preview-benchmark-") as temporary:
        registry = ProjectRegistry(runtime_root=Path(temporary))
        resolver = registry.runtime_resolver
        job = JobManifest.model_validate_json((_REPOSITORY_ROOT / "fixtures/mock_job/job_manifest.json").read_bytes())
        preview = ReconstructionPreview(
            job_id="benchmark-preview",
            attempt_id="first",
            source_input_checksum=job.input_manifest_checksum,
            source_visual_ref=_payload(resolver, "scene.ply", "BrushVisualArtifact", source_mib),
            camera_pose_ref=_payload(resolver, "poses.json", "CameraPoseArtifact", 0),
            delivery_ref=_payload(resolver, "scene.sog", "GaussianSOG", delivery_mib),
            producer_version="opaque-performance-fixture",
        )
        uri = "artifact://jobs/benchmark-preview/attempts/first/rec11/preview.json"
        path = resolver.resolve(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(preview.model_dump_json(), encoding="utf-8")
        stage = StageArtifact(
            stage_id="ST-VISUAL-RECON",
            status="SUCCEEDED",
            artifact_type="ReconstructionPreview",
            artifact_uri=uri,
            artifact_checksum=sha256_file(path),
            data_class="derived",
            completed_at=datetime.now(UTC),
        )
        job = with_canonical_checksum(
            job.model_copy(update={"job_id": preview.job_id, "stage_artifacts": [stage]}), "job_manifest_checksum"
        )
        verify = store_module.verify_file_checksum
        results: dict[str, object] = {
            "scope": "synthetic local filesystem; excludes DB, HTTP, remote storage and GPU/browser rendering",
            "source_mib": source_mib,
            "delivery_mib": delivery_mib,
            "repeats": repeats,
        }
        for mode in ("strict_consumer", "registry_reads"):
            samples: list[dict[str, int | float]] = []
            hashed_bytes = 0

            def counted_verify(target: Path, checksum: str) -> None:
                nonlocal hashed_bytes
                hashed_bytes += target.stat().st_size
                verify(target, checksum)

            with patch.object(store_module, "verify_file_checksum", counted_verify):
                with patch.object(registry, "get_job", return_value=job):
                    for _ in range(repeats):
                        hashed_bytes = 0
                        start = perf_counter()
                        loaded = (
                            load_job_preview(job, resolver)
                            if mode == "strict_consumer"
                            else registry.get_preview(job.job_id)
                        )
                        elapsed = (perf_counter() - start) * 1000
                        if loaded != preview:
                            raise RuntimeError("preview identity changed during benchmark")
                        samples.append({"elapsed_ms": round(elapsed, 3), "bytes_hashed": hashed_bytes})
            results[mode] = {
                "samples": samples,
                "first_ms": samples[0]["elapsed_ms"],
                "repeated_median_ms": statistics.median(sample["elapsed_ms"] for sample in samples[1:]),
                "repeated_bytes_hashed": [sample["bytes_hashed"] for sample in samples[1:]],
            }
        return results


def main(argv: list[str] | None = None) -> int:
    """Print JSON and optionally save it to the requested output path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-mib", type=int, default=128)
    parser.add_argument("--delivery-mib", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = benchmark(args.source_mib, args.delivery_mib, args.repeats)
    except ValueError as error:
        parser.error(str(error))
    payload = json.dumps(result, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
