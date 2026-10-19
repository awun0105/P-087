"""Versioned demo-library archives and startup provisioning, without importing a dev DB."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from threading import Lock
from uuid import uuid4

from src.config import Settings
from src.services.orchestration.artifacts import ArtifactResolver, sha256_file
from src.services.orchestration.samples.bundle import DemoBundle, DemoLibrary
from src.services.orchestration.samples.workspace import load_workspace
from src.services.orchestration.storage import artifact_remote

INDEX = "DEMO_RELEASE.json"


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or "\\" in name
        or path.as_posix() != name
        or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
        or len(path.parts) < 3
        or path.parts[0] != "library"
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", path.parts[1]) is None
    ):
        raise ValueError("Unsafe demo archive member")
    return name


def _validate_bundle(bundle: DemoBundle) -> None:
    snapshot = load_workspace(bundle)
    if any(
        snapshot.project.source_rights_attestation.get(key) is not True
        for key in ("rights_to_use_confirmed", "anonymization_confirmed")
    ):
        raise ValueError("Demo baseline lacks publication rights attestation")
    resolver = ArtifactResolver(bundle.root / "workspace/artifacts")
    for ref in snapshot.files:
        resolver.require_uri(str(ref["artifact_uri"]), str(ref["artifact_checksum"]))
    for entry in bundle.manifest().files():
        bundle.file(entry.name)


def pack_library(library: Path, output: Path, release_id: str, sample_ids: list[str]) -> dict:
    """Stream selected immutable samples to a checksummed archive; leave source untouched."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", release_id) is None:
        raise ValueError("Invalid release ID")
    bundles = DemoLibrary(library).bundles()
    selected = sample_ids or list(bundles)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one distinct published sample")
    if output.exists() or output.resolve().is_relative_to(library.resolve()):
        raise ValueError("Archive must be new and outside the source library")
    from scripts.studio.data_package import _scan_text_credentials

    entries: list[tuple[str, Path]] = []
    for sample_id in selected:
        bundle = bundles.get(sample_id)
        if bundle is None:
            raise ValueError("Selected sample is not published")
        _validate_bundle(bundle)
        for path in sorted(bundle.root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Demo library contains a symlink")
            if path.is_file():
                relative = path.relative_to(bundle.root).as_posix()
                name = _safe_name(f"library/{sample_id}/{relative}")
                entries.append((name, path))
    _scan_text_credentials(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + f".{uuid4().hex}.partial")
    records: list[dict] = []
    try:
        with zipfile.ZipFile(
            partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
        ) as archive:
            for name, path in entries:
                before = path.stat()
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
                after = path.stat()
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError("Demo source changed while packing")
                records.append({"path": name, "size_bytes": size, "checksum": f"sha256:{digest.hexdigest()}"})
            manifest = {"format": 1, "release_id": release_id, "samples": selected, "files": records}
            archive.writestr(INDEX, json.dumps(manifest, ensure_ascii=False, sort_keys=True))
        os.link(partial, output)  # Do not overwrite another release produced concurrently.
    finally:
        partial.unlink(missing_ok=True)
    return {"release_id": release_id, "samples": selected, "files": len(records), "checksum": sha256_file(output)}


def archive_index(archive: zipfile.ZipFile) -> dict:
    infos = archive.infolist()
    if len(infos) > 100000 or len({entry.filename for entry in infos}) != len(infos):
        raise ValueError("Duplicate or excessive archive members")
    if archive.getinfo(INDEX).file_size > 16 * 1024**2:
        raise ValueError("Demo release index is too large")
    manifest = json.loads(archive.read(INDEX))
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("Unsupported demo release format")
    records = manifest["files"]
    names = [_safe_name(record["path"]) for record in records]
    if len(set(names)) != len(names) or set(names) | {INDEX} != {entry.filename for entry in infos}:
        raise ValueError("Archive inventory does not match release index")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples or len(set(samples)) != len(samples):
        raise ValueError("Invalid demo sample catalog")
    if set(samples) != {PurePosixPath(name).parts[1] for name in names} or any(
        f"library/{sample}/{suffix}" not in names
        for sample in samples
        for suffix in ("manifest.json", "workspace/snapshot.json")
    ):
        raise ValueError("Demo catalog is missing a manifest or workspace")
    total = 0
    for record in records:
        info = archive.getinfo(record["path"])
        if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.file_size != record["size_bytes"]:
            raise ValueError("Invalid demo archive entry")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", record["checksum"]) is None:
            raise ValueError("Invalid demo checksum")
        total += info.file_size
    if total > 64 * 1024**3:
        raise ValueError("Demo archive exceeds the provisioning limit")
    return manifest


def verify_archive(package: Path) -> dict:
    with zipfile.ZipFile(package) as archive:
        manifest = archive_index(archive)
        for record in manifest["files"]:
            digest = hashlib.sha256()
            with archive.open(record["path"]) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if f"sha256:{digest.hexdigest()}" != record["checksum"]:
                raise ValueError("Demo archive checksum mismatch")
    return manifest


def publish_library(settings: Settings, package: Path) -> dict:
    """Publish a verified library and archive to private R2; never import user accounts."""
    manifest = verify_archive(package)
    remote = artifact_remote(settings)
    if remote is None:
        raise ValueError("Publishing requires ARTIFACT_S3_* credentials")
    prefix = settings.product_demo_object_prefix.strip("/")
    if not prefix or any(part in {"", ".", ".."} for part in prefix.split("/")):
        raise ValueError("Invalid PRODUCT_DEMO_OBJECT_PREFIX")
    with zipfile.ZipFile(package) as archive, tempfile.TemporaryDirectory(prefix="r2s-demo-publish-") as temporary:
        extraction_lock = Lock()

        def publish_member(record: dict) -> None:
            key = prefix + "/" + record["path"].removeprefix("library/")
            existing = remote.store.head(key)
            if existing is not None:
                if existing.checksum != record["checksum"]:
                    raise ValueError("Immutable demo object already exists with different bytes")
                return
            path = Path(temporary) / hashlib.sha256(record["path"].encode()).hexdigest()
            try:
                with extraction_lock:
                    with archive.open(record["path"]) as source, path.open("xb") as target:
                        shutil.copyfileobj(source, target)
                remote.store.put_file(key, path, record["checksum"])
            finally:
                path.unlink(missing_ok=True)

        # Bound temporary extraction and connections while publishing thousands of objects.
        with ThreadPoolExecutor(max_workers=4) as executor:
            for _ in executor.map(publish_member, manifest["files"]):
                pass
    archive_key = settings.product_demo_archive_key or prefix + ".zip"
    checksum = sha256_file(package)
    existing = remote.store.head(archive_key)
    if existing is not None and existing.checksum != checksum:
        raise ValueError("Immutable demo archive key already exists")
    if existing is None:
        remote.store.put_file(archive_key, package, checksum)
    return {
        "PRODUCT_DEMO_OBJECT_PREFIX": prefix,
        "PRODUCT_DEMO_ARCHIVE_KEY": archive_key,
        "PRODUCT_DEMO_ARCHIVE_CHECKSUM": checksum,
        "samples": manifest["samples"],
    }


def bootstrap_library(settings: Settings) -> None:
    """Provision a pinned archive before serving API requests; refuse unpinned downloads."""
    if not settings.product_demo_archive_key:
        return
    expected = settings.product_demo_archive_checksum
    if expected is None or re.fullmatch(r"sha256:[a-f0-9]{64}", expected) is None:
        raise ValueError("PRODUCT_DEMO_ARCHIVE_KEY requires PRODUCT_DEMO_ARCHIVE_CHECKSUM")
    root = settings.product_demo_dir.expanduser().absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("Demo bootstrap destination contains a symlink")
    root.parent.mkdir(parents=True, exist_ok=True)
    with (root.parent / ".demo-bootstrap.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = root / "DEMO_RELEASE.json"
        if marker.is_file():
            manifest = json.loads(marker.read_text())
            if manifest.get("archive_checksum") != expected:
                raise ValueError("Demo volume contains another release; use a new PRODUCT_DEMO_DIR")
            for record in manifest["files"]:
                path = root / PurePosixPath(_safe_name(record["path"])).relative_to("library")
                if not path.is_file() or path.is_symlink() or sha256_file(path) != record["checksum"]:
                    raise ValueError("Provisioned demo library failed verification")
            return
        if root.exists() and any(root.iterdir()):
            raise ValueError("Demo destination is not empty and has no release receipt")
        remote = artifact_remote(settings)
        if remote is None:
            raise ValueError("Demo bootstrap requires object storage")
        download_dir = settings.product_demo_download_dir
        if download_dir is not None:
            download_dir.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory(prefix="r2s-demo-download-", dir=download_dir) as download,
            tempfile.TemporaryDirectory(prefix=".demo-bootstrap-", dir=root.parent) as temporary,
        ):
            staging = Path(temporary)
            package = Path(download) / "library.zip"
            head = remote.store.head(settings.product_demo_archive_key)
            if head is None:
                raise ValueError("Demo archive does not exist in object storage")
            reserve = 256 * 1024**2
            if shutil.disk_usage(download).free < head.size_bytes + reserve:
                raise ValueError("Insufficient download disk for demo archive")
            remote.store.get_file(settings.product_demo_archive_key, package)
            if sha256_file(package) != expected:
                raise ValueError("Demo archive checksum mismatch")
            with zipfile.ZipFile(package) as archive:
                manifest = archive_index(archive)
                required = sum(record["size_bytes"] for record in manifest["files"])
                if shutil.disk_usage(staging).free < required + reserve:
                    raise ValueError("Insufficient persistent disk for extracted demo library")
                target = staging / "library"
                target.mkdir()
                for record in manifest["files"]:
                    path = target / PurePosixPath(record["path"]).relative_to("library")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with archive.open(record["path"]) as source, path.open("xb") as destination:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                            destination.write(chunk)
                    if f"sha256:{digest.hexdigest()}" != record["checksum"]:
                        raise ValueError("Demo member checksum mismatch")
            for bundle in DemoLibrary(target).bundles().values():
                _validate_bundle(bundle)
            manifest["archive_checksum"] = expected
            (target / INDEX).write_text(json.dumps(manifest, sort_keys=True))
            if root.exists():
                root.rmdir()  # Only the empty, managed destination can reach this line.
            target.rename(root)
