"""Bộ LOD (mức chi tiết) của SOG lớn (T-070): khung 3D hiện bản thô ngay rồi tự tải thêm chi tiết tới đủ chất lượng gốc.

Bộ LOD là bản dẫn xuất theo checksum của SOG nguồn, không phải artifact của pipeline (không đổi manifest, SceneIR hay
DB). Nó nằm dưới thư mục của job (`jobs/<job>/derived/lod/<checksum>/`) trong kho file, nên xoá job là xoá theo.
File mục lục `lod-meta.json` được ghi sau cùng: có file đó nghĩa là bộ đã đủ.

Tạo bộ LOD cần GPU (nén SOG): chỉ worker có GPU làm, lúc rảnh. Kiểm quyền xem do route làm (SOG nguồn phải thuộc
allow-list của job).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Protocol

from src.runtime_env import runtime_env

logger = logging.getLogger(__name__)

#: SOG từ mức này trở xuống đã nhẹ, không cần LOD.
MIN_LOD_SPLATS = 600_000
INDEX = "lod-meta.json"
_TIMEOUT_SECONDS = 3600
_BUNDLE_PATH = re.compile(r"^(lod-meta\.json|\d+_\d+/(meta\.json|[A-Za-z0-9_]+\.webp))$")


class LodBuildError(RuntimeError):
    """splat-transform không tạo được bộ LOD."""


class _Pusher(Protocol):
    def push(self, relative: str, path: Path) -> None: ...


def lod_relative_dir(job_id: str, checksum: str) -> str:
    return f"jobs/{job_id}/derived/lod/{checksum.removeprefix('sha256:')}"


def valid_bundle_path(path: str) -> bool:
    """Chỉ đúng dạng tên file của bộ LOD (`lod-meta.json`, `<lod>_<khối>/meta.json|*.webp`); không có `..`."""
    return bool(_BUNDLE_PATH.fullmatch(path))


def splat_count(sog: Path) -> int:
    with zipfile.ZipFile(sog) as bundle:
        return int(json.loads(bundle.read("meta.json"))["count"])


def lod_ready(artifact_root: Path, remote: object | None, job_id: str, checksum: str) -> bool:
    """Bộ LOD đã đủ (có file mục lục) ở cache cục bộ hoặc trong kho file."""
    relative = f"{lod_relative_dir(job_id, checksum)}/{INDEX}"
    if (artifact_root / relative).is_file():
        return True
    head = getattr(remote, "head", None)
    return head is not None and head(relative) is not None


def _run(cli: Path, *arguments: str, gpu: bool = False) -> None:
    device = () if gpu else ("-g", "cpu")
    try:
        subprocess.run(
            ("node", str(cli), "-q", "-w", *device, *arguments),
            check=True,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise LodBuildError(type(error).__name__) from error


def build_lod_bundle(cli: Path, source_sog: Path, workspace: Path) -> Path | None:
    """Ba mức: gốc, 1/2 và 1/4 số điểm. Trả thư mục bộ LOD, hoặc None khi SOG đủ nhẹ.

    splat-transform 3.6.6: đầu vào LOD phải là PLY; `--decimate` phải là bước cuối và ra PLY; các mức phải cùng số dải SH.
    Mức gốc giữ nguyên mọi điểm và màu của SOG đang xem.
    """
    if splat_count(source_sog) <= MIN_LOD_SPLATS:
        return None
    workspace.mkdir(parents=True, exist_ok=True)
    level0, level1, level2 = (workspace / f"lod{index}.ply" for index in range(3))
    _run(cli, str(source_sog), str(level0))
    _run(cli, str(level0), str(level1), "-d", "50%")
    _run(cli, str(level1), str(level2), "-d", "50%")
    out = workspace / "bundle"
    out.mkdir(exist_ok=True)
    index = out / INDEX
    _run(cli, str(level0), "-l", "0", str(level1), "-l", "1", str(level2), "-l", "2", str(index), gpu=True)
    if not index.is_file():
        raise LodBuildError("missing lod-meta.json")
    return out


def publish_lod_bundle(artifact_root: Path, remote: _Pusher | None, job_id: str, checksum: str, bundle: Path) -> None:
    """Chép bộ LOD vào cache cục bộ và kho file; file mục lục chép và đẩy sau cùng."""
    relative = lod_relative_dir(job_id, checksum)
    target = artifact_root / relative
    files = sorted(path for path in bundle.rglob("*") if path.is_file() and path.name != INDEX)
    target.mkdir(parents=True, exist_ok=True)
    for path in [*files, bundle / INDEX]:
        name = path.relative_to(bundle).as_posix()
        if not valid_bundle_path(name):
            raise LodBuildError(f"unexpected bundle file {name}")
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        shutil.copyfile(path, temporary)
        temporary.replace(destination)
        if remote is not None:
            remote.push(f"{relative}/{name}", destination)


#: Lần tạo lỗi được thử lại sau khoảng này (lỗi có thể do máy, không phải do SOG).
_RETRY_FAILED_SECONDS = 86400


class _LodRegistry(Protocol):
    runtime_resolver: object

    def lod_candidates(self) -> list[tuple[str, object]]: ...

    def resolve_artifact(self, job_id: str, reference: object) -> Path: ...


class LodBuilder:
    """Worker GPU rảnh thì tạo bộ LOD cho một SOG còn thiếu mỗi lượt; scene nhỏ và lần lỗi được ghi dấu."""

    def __init__(self, registry: _LodRegistry, cli: Path, workspace: Path, skip_root: Path) -> None:
        self.registry = registry
        self.cli = cli
        self.workspace = workspace
        self.skip_root = skip_root

    def _skipped(self, checksum: str) -> bool:
        marker = self.skip_root / checksum.removeprefix("sha256:")
        try:
            content = marker.read_text(encoding="utf-8")
            age = time.time() - marker.stat().st_mtime
        except OSError:
            return False
        return content == "small" or age < _RETRY_FAILED_SECONDS

    def _mark(self, checksum: str, reason: str) -> None:
        self.skip_root.mkdir(parents=True, exist_ok=True)
        (self.skip_root / checksum.removeprefix("sha256:")).write_text(reason, encoding="utf-8")

    def tick(self) -> bool:
        """True khi lượt này đã xử lý một SOG (tạo xong, ghi dấu nhỏ hoặc lỗi)."""
        resolver = self.registry.runtime_resolver
        root = resolver.artifact_root  # type: ignore[attr-defined]
        remote = getattr(resolver, "remote", None)
        for job_id, reference in self.registry.lod_candidates():
            checksum = reference.artifact_checksum  # type: ignore[attr-defined]
            if self._skipped(checksum) or lod_ready(root, remote, job_id, checksum):
                continue
            work = self.workspace / checksum.removeprefix("sha256:")
            try:
                bundle = build_lod_bundle(self.cli, self.registry.resolve_artifact(job_id, reference), work)
                if bundle is None:
                    self._mark(checksum, "small")
                else:
                    publish_lod_bundle(root, remote, job_id, checksum, bundle)  # type: ignore[arg-type]
                    logger.info("Đã tạo bộ LOD job=%s sog=%s", job_id, checksum[:19])
            except Exception as error:  # noqa: BLE001 - một SOG lỗi không được chặn worker; thử lại sau một ngày
                logger.warning("Không tạo được bộ LOD job=%s cause=%s", job_id, type(error).__name__)
                self._mark(checksum, f"failed:{type(error).__name__}")
            finally:
                shutil.rmtree(work, ignore_errors=True)
            return True
        return False


def idle_lod_builder(registry: _LodRegistry, worker_root: Path) -> LodBuilder | None:
    """Bộ dựng LOD cho worker này; None khi máy không có GPU (`nvidia-smi`) hoặc runtime splat-transform."""
    value = runtime_env(os.environ, "R2S_VOXEL_CLI")
    if not value or not Path(value).is_file() or shutil.which("nvidia-smi") is None:
        return None
    root = registry.runtime_resolver.artifact_root  # type: ignore[attr-defined]
    return LodBuilder(registry, Path(value), worker_root / "lod", Path(root).parent / "cache" / "lod-skip")
