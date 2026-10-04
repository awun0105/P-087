"""Full Gaussian similarity qua SplatTransform 3.6.6 MIT, không tự patch PLY bytes."""

import json
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.models.contracts.artifacts import Checksum, ContractModel
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess
from src.services.reconstruction.rgb.canonical.metric_math import SimilarityTransform
from src.services.reconstruction.rgb.frames.frame_set import _sha256


class GaussianTransformRequest(ContractModel):
    """Derivative riêng từ immutable raw PLY; không có identity/silent-copy bypass."""

    source: Path
    source_checksum: Checksum
    transform: SimilarityTransform


class GaussianTransformReceipt(ContractModel):
    """Receipt của qualified codec, không tự cấp metric confirmation."""

    version: Literal["3.6.6"]
    revision: Literal["afbc281"]
    transform: SimilarityTransform
    num_gaussians: int = Field(gt=0)
    sh_bands: int = Field(ge=0, le=3)
    storage_mapping: Literal["PLY_inverse_times_PLY_times_metric"]


class SplatTransformSimilarityAdapter:
    """Isolated streaming transform áp cả position/covariance/SH, giữ source bytes."""

    def __init__(self, process: VoxelProcess) -> None:
        self.process = process

    def transform(self, request: GaussianTransformRequest, workspace: Path) -> GaussianTransformReceipt:
        """New attempt bắt buộc; malformed input không tạo success receipt."""
        request = GaussianTransformRequest.model_validate(request.model_dump())
        if _sha256(request.source) != request.source_checksum:
            raise ValueError("Gaussian transform source checksum mismatch")
        workspace.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(request.source, workspace / "source.ply")
        if _sha256(workspace / "source.ply") != request.source_checksum:
            raise ValueError("Gaussian source changed during copy")
        (workspace / "metric-transform.json").write_text(request.transform.model_dump_json())
        script = Path(__file__).with_name("splat_similarity.mjs").resolve()
        self.process.run(
            (str(script), str(self.process.settings.module_path.resolve())), (workspace, "metric-transform")
        )
        receipt = GaussianTransformReceipt.model_validate_json(
            (workspace / "metric-transform-receipt.json").read_text()
        )
        if receipt.transform != request.transform:
            raise ValueError("Gaussian transform receipt differs from requested similarity")
        if not (workspace / "input.ply").is_file() or _sha256(request.source) != request.source_checksum:
            raise ValueError("Gaussian derivative missing or immutable source changed")
        evidence = {
            "source_checksum": request.source_checksum,
            "output_checksum": _sha256(workspace / "input.ply"),
            "receipt": receipt.model_dump(mode="json"),
        }
        (workspace / "metric-derivative.json").write_text(json.dumps(evidence, sort_keys=True) + "\n")
        return receipt
