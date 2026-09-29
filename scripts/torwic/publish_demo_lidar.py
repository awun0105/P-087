"""Chuẩn bị offline: đưa LiDAR (REC-08) + căn chỉnh quỹ đạo (REC-09) vào store của một job demo.

ADR 0004 §6: trên dataset mẫu, số đo A/B, C/D lấy từ LiDAR. Script này chỉ chạy cho
job dựng từ dữ liệu Aisle_CW, sau `align_sfm_to_world`. Kết quả là bản ghi
`jobs/<job>/rec09/demo_lidar_support.json`; job không có bản ghi này (video người dùng)
thì Studio vẫn yêu cầu nhập tay.

Ví dụ:
    python -m scripts.torwic.publish_demo_lidar --store-root data/studio_local/artifacts \\
        --job job-ac2bfd924cc6 \\
        --rec07-dir data/torwic_slam/derived/aisle_cw/rec07_prefusion_sub100_119 \\
        --alignment data/torwic_slam/derived/aisle_cw/rec09_alignment_job-ac2bfd924cc6/alignment.json \\
        --bridge configs/datasets/torwic_aisle_cw/coordinate_bridge.json
"""

import argparse
import hashlib
import json
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_file,
)
from src.services.reconstruction.lidar import (
    LiDARIngestService,
    build_request_from_rec07_manifest,
    load_bridge_decision,
)
from src.services.reconstruction.rgb.canonical.lidar_assist import DemoLidarSupport, support_uri


def _json_ref(job_id: str, uri: str, payload: bytes, artifact_type: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id=job_id,
        source_provenance={"ground_truth_assisted": True, "purpose": "dataset_demo_measurement"},
    )


class _IdempotentWriter:
    """Chạy lại script an toàn: artifact đã có cùng checksum thì dùng lại, khác thì từ chối."""

    def __init__(self, resolver: ArtifactResolver) -> None:
        self.resolver = resolver
        self.store = FilesystemArtifactStore(resolver)

    def publish(self, reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        """Publish một lần; không bao giờ ghi đè nội dung khác."""
        path = self.resolver.resolve(reference.artifact_uri)
        if path.is_file():
            if sha256_file(path) == reference.artifact_checksum:
                return reference
            raise ArtifactAlreadyExistsError(f"{reference.artifact_uri} đã có với nội dung khác")
        return self.store.publish(reference, payload)


def publish(
    store_root: Path, job_id: str, rec07_dir: Path, alignment_path: Path, bridge_path: Path
) -> ProductArtifactRef:
    """REC-08 ingest + publish căn chỉnh + bản ghi hỗ trợ; trả ref bản ghi hỗ trợ."""
    writer = _IdempotentWriter(ArtifactResolver(store_root))
    request = build_request_from_rec07_manifest(
        rec07_dir / "preparation_manifest.json",
        rec07_dir / "registered_lidar.ply",
        job_id,
        load_bridge_decision(bridge_path),
    )
    lidar = LiDARIngestService(writer).ingest_with_metadata(request)

    alignment_bytes = alignment_path.read_bytes()
    alignment = json.loads(alignment_bytes)
    digest = hashlib.sha256(alignment_bytes).hexdigest()
    alignment_ref = writer.publish(
        _json_ref(
            job_id,
            f"artifact://jobs/{job_id}/rec09/trajectory/{digest}.json",
            alignment_bytes,
            alignment["artifact_type"],
        ),
        alignment_bytes,
    )
    support = DemoLidarSupport(
        job_id=job_id,
        # Checksum bytes của file pose = `artifact_checksum` của ref mà viewer/REC-04 trỏ tới;
        # không dùng self-checksum bên trong JSON (khác loại, không bao giờ khớp ref).
        camera_poses_checksum=alignment["inputs"]["camera_poses_checksum"],
        alignment_ref=alignment_ref,
        lidar_geometry_ref=lidar.geometry_ref,
        lidar_metadata_ref=lidar.metadata_ref,
    )
    payload = support.model_dump_json(indent=2).encode() + b"\n"
    return writer.publish(_json_ref(job_id, support_uri(job_id), payload, support.artifact_type), payload)


def main(argv: list[str] | None = None) -> int:
    """CLI offline; in ref bản ghi hỗ trợ đã publish."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--rec07-dir", type=Path, required=True)
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    args = parser.parse_args(argv)
    reference = publish(args.store_root, args.job, args.rec07_dir, args.alignment, args.bridge)
    print(reference.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
