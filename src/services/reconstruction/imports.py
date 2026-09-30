"""Scene 3DGS người dùng tải lên (ADR 0004 §3, gói 5): nén PLY → SOG để xem/chỉnh sửa.

Chỉ xem/chỉnh sửa (owner chốt 2026-09-30): không vào pipeline REC-06/05 vì contract
`ReconstructionPreview` yêu cầu camera + producer Brush. Tái dùng splat-transform 3.6.6 đã
qualify (cùng runtime REC-05) để nén; file gốc giữ nguyên bất biến.
"""

import zipfile
from pathlib import Path, PurePosixPath

from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings


def extract_member(archive: Path, member: str, destination: Path) -> Path:
    """Chép đúng một PLY đã nhận diện trong ZIP ra workspace (không giải nén cả file)."""
    name = PurePosixPath(member)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError("đường dẫn PLY trong ZIP không an toàn")
    with zipfile.ZipFile(archive) as bundle, bundle.open(member) as source, destination.open("xb") as target:
        while chunk := source.read(1 << 20):
            target.write(chunk)
    return destination


def package_splat(source_ply: Path, workspace: Path, gpu_index: int | None = None) -> Path:
    """PLY 3DGS → `scene.sog` trong workspace; kiểm runtime đúng bản đã qualify trước khi chạy."""
    process = VoxelProcess(VoxelRuntimeSettings())
    workspace.mkdir(parents=True, exist_ok=True)
    process.qualify(workspace)
    output = workspace / "scene.sog"
    gpu = ("-g", str(gpu_index)) if gpu_index is not None else ()
    process.cli(("-w", *gpu, str(source_ply.resolve()), str(output)), (workspace, "import-sog"))
    if not output.is_file() or output.stat().st_size == 0:
        raise ValueError("splat-transform không tạo được scene.sog")
    return output
