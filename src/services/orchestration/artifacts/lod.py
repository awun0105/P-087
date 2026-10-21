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
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from src.runtime_env import runtime_env
from src.services.orchestration.artifacts.errors import ArtifactStoreError

logger = logging.getLogger(__name__)

#: SOG từ mức này trở xuống đã nhẹ, không cần LOD.
MIN_LOD_SPLATS = 600_000
INDEX = "lod-meta.json"
_TIMEOUT_SECONDS = 3600
_BUNDLE_PATH = re.compile(r"^(lod-meta\.json|(b[0-9a-f]{12}/)?\d+_\d+/(meta\.json|[A-Za-z0-9_]+\.webp))$")


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


def _chunk_files(meta: Path) -> list[str]:
    """Tên các file dữ liệu mà `meta.json` của một khối khai (means, scales, quats, sh0, shN…)."""
    document = json.loads(meta.read_text(encoding="utf-8"))
    names: list[str] = []
    for value in document.values():
        listed = value.get("files") if isinstance(value, dict) else None
        if isinstance(listed, list):
            names.extend(name for name in listed if isinstance(name, str))
    if not names:
        raise LodBuildError(f"{meta.parent.name}/meta.json lists no files")
    return names


def copy_lod_bundle(source_root: Path, remote: object | None, target_root: Path, job_id: str, checksum: str) -> bool:
    """Chép một bộ LOD đã đủ sang kho artifact khác (bản chụp workspace mẫu, phiên demo) bằng hard link.

    Chỉ chép file mục lục và các khối nó trỏ tới (lần tạo thua cuộc bị bỏ). Bộ chỉ có trong kho file thì tải về cache
    nguồn trước. Trả False khi SOG chưa có bộ LOD đủ; giao diện khi đó mở SOG gốc như trước.
    """
    relative = lod_relative_dir(job_id, checksum)
    source = source_root / relative
    index = source / INDEX
    if not index.is_file():
        head = getattr(remote, "head", None)
        if head is None or head(f"{relative}/{INDEX}") is None:
            return False
        remote.fetch(f"{relative}/{INDEX}", index)  # type: ignore[union-attr]
    names = json.loads(index.read_text(encoding="utf-8")).get("filenames")
    if not isinstance(names, list) or not names:
        raise LodBuildError("lod-meta.json lists no chunks")
    chunks: dict[str, None] = {}
    for name in names:
        if not isinstance(name, str) or not valid_bundle_path(name) or "/" not in name:
            raise LodBuildError(f"unexpected bundle file {name!r}")
        chunks[name.rsplit("/", 1)[0]] = None
    files: list[Path] = []
    for chunk in chunks:
        folder = source / chunk
        meta = folder / "meta.json"
        if not meta.is_file() and remote is not None:
            remote.pull_tree(f"{relative}/{chunk}", folder)  # type: ignore[attr-defined]
        if not meta.is_file():
            raise LodBuildError(f"chunk {chunk} is missing")
        # Cache cục bộ có thể chỉ có vài file của khối (trình xem tải lẻ từng file): đủ theo meta.json mới chép.
        needed = [meta]
        for name in _chunk_files(meta):
            path = folder / name
            if not valid_bundle_path(path.relative_to(source).as_posix()):
                raise LodBuildError(f"unexpected bundle file {path.relative_to(source).as_posix()}")
            if not path.is_file() and remote is not None:
                remote.fetch(f"{relative}/{chunk}/{name}", path)  # type: ignore[attr-defined]
            if not path.is_file():
                raise LodBuildError(f"chunk {chunk} is missing {name}")
            needed.append(path)
        files.extend(needed)
    files.append(index)  # mục lục chép sau cùng: có nó nghĩa là bộ đã đủ
    target = target_root / relative
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            continue
        try:
            os.link(path, destination)
        except OSError:
            shutil.copyfile(path, destination)
    return True


def copy_view_lods(
    source_root: Path, remote: object | None, target_root: Path, job_id: str, references: list[dict]
) -> int:
    """Bộ LOD của mọi SOG trong danh sách artifact (`artifact_uri`, `artifact_checksum`) đã chép; trả số bộ đã chép.

    Bộ LOD là bản dẫn xuất ngoài đồ thị artifact, nên bản chụp workspace mẫu và phiên demo phải chép riêng; thiếu nó
    thì scene lớn của mẫu luôn mở SOG gốc (không có LOD).
    """
    checksums = dict.fromkeys(
        str(item["artifact_checksum"]) for item in references if str(item.get("artifact_uri", "")).endswith(".sog")
    )
    copied = 0
    for checksum in checksums:
        try:
            copied += copy_lod_bundle(source_root, remote, target_root, job_id, checksum)
        except (LodBuildError, OSError, ArtifactStoreError) as error:
            # Bộ LOD hỏng hoặc thiếu khối: bỏ qua để giao diện mở SOG gốc, không làm hỏng mẫu hay phiên demo.
            logger.warning("skip LOD bundle %s of %s: %s", checksum, job_id, error)
            shutil.rmtree(target_root / lod_relative_dir(job_id, checksum), ignore_errors=True)
    return copied


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


def publish_lod_bundle(artifact_root: Path, remote: _Pusher | None, job_id: str, checksum: str, bundle: Path) -> bool:
    """Chép bộ LOD vào cache cục bộ và kho file; trả False khi một lần tạo khác đã công bố trước.

    Mỗi lần tạo ghi các khối vào thư mục riêng `b<id>/` và file mục lục trỏ vào thư mục đó; mục lục ghi sau cùng, lần nào
    ghi được mục lục trước thì thắng. Hai worker cùng tạo một SOG không bao giờ trộn khối của nhau.
    """
    from src.services.orchestration.artifacts.remote import ArtifactAlreadyExistsError

    relative = lod_relative_dir(job_id, checksum)
    target = artifact_root / relative
    build = f"b{uuid4().hex[:12]}"
    index = json.loads((bundle / INDEX).read_text(encoding="utf-8"))
    index["filenames"] = [f"{build}/{name}" for name in index["filenames"]]
    files = sorted(path for path in bundle.rglob("*") if path.is_file() and path.name != INDEX)
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        name = f"{build}/{path.relative_to(bundle).as_posix()}"
        if not valid_bundle_path(name):
            raise LodBuildError(f"unexpected bundle file {name}")
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if remote is not None:
            remote.push(f"{relative}/{name}", destination)
    staged = target / f".{build}.{INDEX}"
    staged.write_text(json.dumps(index), encoding="utf-8")
    if remote is not None:
        try:
            remote.push(f"{relative}/{INDEX}", staged)
        except ArtifactAlreadyExistsError:
            staged.unlink(missing_ok=True)
            logger.info("Bộ LOD job=%s đã được lần tạo khác công bố trước", job_id)
            return False
    staged.replace(target / INDEX)
    return True


#: Lần tạo lỗi được thử lại sau khoảng này (lỗi có thể do máy, không phải do SOG).
_RETRY_FAILED_SECONDS = 86400


class _LodRegistry(Protocol):
    runtime_resolver: object

    def lod_candidates(self) -> list[tuple[str, object]]: ...

    def resolve_artifact(self, job_id: str, reference: object) -> Path: ...


class LodBuilder:
    """Worker GPU rảnh thì tạo bộ LOD cho một SOG còn thiếu mỗi lượt; scene nhỏ và lần lỗi được ghi dấu.

    Danh sách ứng viên (đọc mọi job trong DB) chỉ dựng lại mỗi `refresh_seconds`; SOG đã xong / đã bỏ qua được nhớ trong
    tiến trình. Job đang có lease (runner đang chạy, gồm bước LOD chính thức) thuộc về runner, không đụng tới.
    """

    def __init__(
        self,
        registry: _LodRegistry,
        cli: Path,
        workspace: Path,
        skip_root: Path,
        *,
        busy: Callable[[str], bool] | None = None,
        now: Callable[[], float] = time.monotonic,
        refresh_seconds: float = 900.0,
    ) -> None:
        self.registry = registry
        self.cli = cli
        self.workspace = workspace
        self.skip_root = skip_root
        self.busy = busy or (lambda job_id: False)
        self.now = now
        self.refresh_seconds = refresh_seconds
        self._candidates: list[tuple[str, object]] | None = None
        self._fetched_at = 0.0
        self._settled: set[str] = set()

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

    def _candidates_now(self) -> list[tuple[str, object]]:
        if self._candidates is None or self.now() - self._fetched_at >= self.refresh_seconds:
            self._candidates = self.registry.lod_candidates()
            self._fetched_at = self.now()
        return self._candidates

    def tick(self) -> bool:
        """True khi lượt này đã xử lý một SOG (tạo xong, ghi dấu nhỏ hoặc lỗi)."""
        resolver = self.registry.runtime_resolver
        root = resolver.artifact_root  # type: ignore[attr-defined]
        remote = getattr(resolver, "remote", None)
        for job_id, reference in self._candidates_now():
            checksum = reference.artifact_checksum  # type: ignore[attr-defined]
            if checksum in self._settled or self.busy(job_id):
                continue
            if small_marked(remote, job_id, checksum) or lod_ready(root, remote, job_id, checksum):
                self._settled.add(checksum)
                continue
            if self._skipped(checksum):
                continue  # scene nhỏ (cục bộ) hoặc lần lỗi còn trong hạn 24 giờ
            work = self.workspace / checksum.removeprefix("sha256:")
            try:
                bundle = build_lod_bundle(self.cli, self.registry.resolve_artifact(job_id, reference), work)
                if bundle is None:
                    self._mark(checksum, "small")
                    mark_small(remote, root, job_id, checksum)
                else:
                    publish_lod_bundle(root, remote, job_id, checksum, bundle)  # type: ignore[arg-type]
                    logger.info("Đã tạo bộ LOD job=%s sog=%s", job_id, checksum[:19])
                self._settled.add(checksum)
            except Exception as error:  # noqa: BLE001 - một SOG lỗi không được chặn worker; thử lại sau một ngày
                logger.warning("Không tạo được bộ LOD job=%s cause=%s", job_id, type(error).__name__)
                self._mark(checksum, f"failed:{type(error).__name__}")
            finally:
                shutil.rmtree(work, ignore_errors=True)
            return True
        return False


#: Dấu "SOG đủ nhẹ, không cần LOD" trong kho file, để máy GPU khác (pod mới) không tải lại SOG chỉ để đếm điểm.
SMALL_MARKER = "small"


def small_marked(remote: object | None, job_id: str, checksum: str) -> bool:
    head = getattr(remote, "head", None)
    return head is not None and head(f"{lod_relative_dir(job_id, checksum)}/{SMALL_MARKER}") is not None


def mark_small(remote: object | None, artifact_root: Path, job_id: str, checksum: str) -> None:
    push = getattr(remote, "push", None)
    if push is None:
        return
    path = artifact_root / lod_relative_dir(job_id, checksum) / SMALL_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("small", encoding="utf-8")
    try:
        push(f"{lod_relative_dir(job_id, checksum)}/{SMALL_MARKER}", path)
    except Exception as error:  # noqa: BLE001 - dấu chỉ để tiết kiệm; thiếu thì máy khác kiểm lại
        logger.warning("Không ghi được dấu SOG nhỏ cause=%s", type(error).__name__)


def lod_cli() -> Path | None:
    """CLI splat-transform khi máy này tạo được bộ LOD (có GPU — `nvidia-smi`); None nếu không."""
    value = runtime_env(os.environ, "R2S_VOXEL_CLI")
    if not value or not Path(value).is_file() or shutil.which("nvidia-smi") is None:
        return None
    return Path(value)


def idle_lod_builder(registry: _LodRegistry, worker_root: Path) -> LodBuilder | None:
    """Bộ dựng LOD chạy lúc rảnh cho worker này (bù job cũ và SOG tạo sau khi job xong); None khi máy không tạo được."""
    cli = lod_cli()
    if cli is None:
        return None
    root = registry.runtime_resolver.artifact_root  # type: ignore[attr-defined]
    persistence = getattr(registry, "persistence", None)
    busy = None
    if persistence is not None:
        from src.services.orchestration.jobs.lease import has_lease

        def busy(job_id: str) -> bool:
            return has_lease(persistence.database, job_id)

    return LodBuilder(registry, cli, worker_root / "lod", Path(root).parent / "cache" / "lod-skip", busy=busy)


def build_job_view_lods(resolver: object, job_id: str, references: list, cli: Path, workspace: Path) -> int:
    """Bước pipeline T-070: tạo bộ LOD cho các SOG lớn của job vừa xong; trả số bộ đã tạo. Lỗi để bên gọi xử lý."""
    root = resolver.artifact_root  # type: ignore[attr-defined]
    remote = getattr(resolver, "remote", None)
    built = 0
    for checksum in dict.fromkeys(reference.artifact_checksum for reference in references):
        if lod_ready(root, remote, job_id, checksum):
            continue
        reference = next(item for item in references if item.artifact_checksum == checksum)
        work = workspace / checksum.removeprefix("sha256:")
        try:
            bundle = build_lod_bundle(cli, resolver.require(reference), work)  # type: ignore[attr-defined]
            if bundle is not None:
                publish_lod_bundle(root, remote, job_id, checksum, bundle)
                built += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return built
