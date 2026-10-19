"""Copy legacy project input frames into a job without rewriting reconstruction lineage."""

from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver, NormalizedRGBFrameSet, frame_image_name
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter


def bundle_frame_references(frames: NormalizedRGBFrameSet, job_id: str) -> list[ProductArtifactRef]:
    """Derive exact job-owned aliases; retain the original ordered image checksums."""
    references = []
    for frame in frames.frames:
        source = frame.image
        if source.job_id != job_id or source.artifact_type != "RGBFrame":
            raise ValueError("source frame belongs to another job or artifact type")
        if source.artifact_uri.startswith(f"artifact://jobs/{job_id}/"):
            references.append(source)
            continue
        if source.data_class.value != "product_input" or source.producer_stage != "ST-INPUT-VALIDATE":
            raise ValueError("only legacy input frames can be copied into the bundle job")
        name = frame_image_name(frame.frame_id, Path(source.artifact_uri))
        references.append(
            ProductArtifactRef(
                schema_version="1.0",
                artifact_type="RGBFrame",
                artifact_uri=f"artifact://jobs/{job_id}/rec02a/frames/{name}",
                artifact_checksum=source.artifact_checksum,
                data_class="derived",
                producer_stage="ST-FRAME-EXTRACT",
                job_id=job_id,
            )
        )
    return references


def publish_bundle_frames(
    frames: NormalizedRGBFrameSet, job_id: str, resolver: FrameSetResolver, writer: ArtifactWriter
) -> list[ProductArtifactRef]:
    """Verify source bytes before publishing copies; never change the source frame set."""
    references = bundle_frame_references(frames, job_id)
    materialized = resolver.materialize(frames)
    for frame, reference, (_, path, _) in zip(frames.frames, references, materialized, strict=True):
        if reference != frame.image and writer.publish(reference, path.read_bytes()) != reference:
            raise ValueError("artifact writer changed bundle frame identity")
    return references
