"""Scene 3DGS người dùng tải lên (ADR 0004 §3, gói 5): nén PLY → SOG để xem/chỉnh sửa.

Chỉ xem/chỉnh sửa (owner chốt 2026-09-30): không vào pipeline REC-06/05 vì contract
`ReconstructionPreview` yêu cầu camera + producer Brush. Tái dùng splat-transform 3.6.6 đã
qualify (cùng runtime REC-05) để nén; file gốc giữ nguyên bất biến.
"""

import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings


def extract_member(archive: Path, member: str, destination: Path, *, max_uncompressed_bytes: int = 4 * 1024**3) -> Path:
    """Chép đúng một PLY đã nhận diện trong ZIP ra workspace (không giải nén cả file)."""
    name = PurePosixPath(member)
    if max_uncompressed_bytes < 1:
        raise ValueError("ZIP uncompressed limit must be positive")
    if name.is_absolute() or ".." in name.parts or "\\" in member or "\x00" in member:
        raise ValueError("đường dẫn PLY trong ZIP không an toàn")
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [info.filename for info in infos if not info.is_dir()]
        if len(infos) > 20_000 or len(names) != len(set(names)):
            raise ValueError("ZIP có quá nhiều file hoặc tên thành viên bị lặp")
        if sum(info.file_size for info in infos if not info.is_dir()) > max_uncompressed_bytes:
            raise ValueError("ZIP vượt giới hạn giải nén")
        info = bundle.getinfo(member)
        mode = info.external_attr >> 16
        if info.is_dir() or stat.S_ISLNK(mode) or info.flag_bits & 0x1:
            raise ValueError("thành viên PLY trong ZIP không phải file thường")
        written = 0
        with bundle.open(info) as source, destination.open("xb") as target:
            while chunk := source.read(1 << 20):
                written += len(chunk)
                if written > info.file_size or written > max_uncompressed_bytes:
                    raise ValueError("thành viên PLY vượt kích thước đã khai báo")
                target.write(chunk)
        if written != info.file_size:
            raise ValueError("thành viên PLY bị cắt cụt")
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


def validate_sog_runtime(source_sog: Path, workspace: Path, *, expected_count: int, expected_sh_bands: int) -> None:
    """Decode a SOG through the pinned splat-transform reader before publication."""
    if expected_count < 1 or expected_sh_bands not in {0, 1, 2, 3}:
        raise ValueError("SOG expected Gaussian inventory is invalid")
    workspace.mkdir(parents=True, exist_ok=True)
    process = VoxelProcess(VoxelRuntimeSettings())
    script = Path(__file__).with_name("adapters") / "voxel_inspect.mjs"
    inspection = workspace / "sog-inspection.json"
    process.run(
        (
            str(script.resolve()),
            str(process.settings.module_path.resolve()),
            str(source_sog.resolve()),
            str(inspection),
            "sog",
        ),
        (workspace, "validate-sog"),
    )
    report = json.loads(inspection.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("splat-transform SOG decoder returned an invalid inspection report")
    info = report.get("info") if isinstance(report, dict) else None
    if (
        report.get("version") != "3.6.6"
        or report.get("revision") != "afbc281"
        or not isinstance(info, dict)
        or info.get("gaussian") is not True
        or info.get("numLods") != 1
        or info.get("numGaussians") != expected_count
        or info.get("shBands") != expected_sh_bands
    ):
        raise ValueError("splat-transform SOG decoder inventory differs from validated metadata")
