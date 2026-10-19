"""Bundle the current deployable source and selected demo data, without secrets or dev state."""

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.jobs.database import LATEST_SCHEMA_VERSION
from src.services.orchestration.samples.release import pack_library, verify_archive

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = ("src/", "scripts/", "configs/", "frontend/", "vendor/", "tests/", "deploy/studio/", ".github/workflows/")
ROOT_FILES = {
    "Dockerfile",
    "Dockerfile.gpu",
    ".dockerignore",
    ".env.example",
    "ruff.toml",
    "LICENSE",
    "README.md",
    "docker-compose.yml",
    "docker-compose.gpu.yml",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--sample", action="append", default=[])
    parser.add_argument(
        "--demo-archive", type=Path, help="Reuse an existing verified library ZIP without repacking data"
    )
    args = parser.parse_args()
    output = args.out.expanduser().resolve()
    if output.exists():
        raise ValueError("Release destination must not already exist")
    output.mkdir(parents=True)
    names = (
        subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    source_files = []
    for name in sorted(set(names)):
        if not name or not (
            name.startswith(PREFIXES)
            or name in ROOT_FILES
            or ("/" not in name and name.startswith("requirements") and name.endswith((".txt", ".in")))
        ):
            continue
        path = ROOT / name
        if not path.exists():
            continue
        if (
            not path.is_file()
            or path.is_symlink()
            or any(part in {"node_modules", "__pycache__", ".next"} for part in path.parts)
        ):
            raise ValueError("Unexpected non-source entry in tracked source")
        if ".env" in path.name and not path.name.endswith(".example") and name != "configs/runtime/pins.env":
            raise ValueError("Environment file cannot enter source release")
        source_files.append((name, path))
    library = ROOT / "data/demo/library"
    reused = verify_archive(args.demo_archive) if args.demo_archive else None
    if reused and args.sample and set(args.sample) != set(reused["samples"]):
        raise ValueError("Reused archive must contain exactly the requested samples")
    selected = (reused["samples"] if reused else args.sample) or [
        p.name for p in library.iterdir() if (p / "manifest.json").is_file() and not (p / ".unpublished").exists()
    ]
    same_disk = args.demo_archive and args.demo_archive.stat().st_dev == output.stat().st_dev
    input_bytes = (
        (0 if same_disk else args.demo_archive.stat().st_size)
        if args.demo_archive
        else sum(p.stat().st_size for sample in selected for p in (library / sample).rglob("*") if p.is_file())
    )
    if shutil.disk_usage(output).free < input_bytes + 512 * 1024**2:
        raise ValueError("Insufficient free disk for a release bundle; use another output volume")
    records = []
    source_zip = output / "studio-source.zip"
    with zipfile.ZipFile(
        source_zip, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
    ) as archive:
        for name, path in source_files:
            before = path.stat()
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_DEFLATED
            digest = hashlib.sha256()
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    target.write(chunk)
            checksum = "sha256:" + digest.hexdigest()
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError("Source changed during release packaging")
            records.append({"path": name, "checksum": checksum, "size_bytes": after.st_size})
    (output / "SOURCE_MANIFEST.json").write_text(json.dumps(records, indent=2))
    if args.demo_archive:
        if same_disk:
            (output / "demo-library.zip").hardlink_to(args.demo_archive)
        else:
            shutil.copyfile(args.demo_archive, output / "demo-library.zip")
        data = {
            "release_id": reused["release_id"],
            "samples": selected,
            "files": len(reused["files"]),
            "checksum": sha256_file(output / "demo-library.zip"),
        }
    else:
        data = pack_library(library, output / "demo-library.zip", args.release, selected)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    manifest = {
        "release_id": args.release,
        "base_commit": sha,
        "worktree_dirty": dirty,
        "source_bundle_checksum": sha256_file(source_zip),
        "source_manifest_checksum": sha256_file(output / "SOURCE_MANIFEST.json"),
        "schema_version": LATEST_SCHEMA_VERSION,
        "demo_library": data,
        "api_image_digest": None,
        "gpu_image_digest": None,
        "isaac_image_digest": None,
        "verification": "static checks only; images and cloud execution are not certified by this bundle",
    }
    (output / "RELEASE.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    for filename in (
        "DEMO_RUNBOOK.md",
        "production.env.example",
        "api.env.example",
        "worker.env.example",
        "web.env.example",
        "PACKAGING.md",
        "RUNPOD_AUTOPROVISION.md",
    ):
        shutil.copyfile(ROOT / "deploy/studio" / filename, output / filename)
    sums = []
    for path in sorted(output.iterdir()):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            sums.append(f"{digest.hexdigest()}  {path.name}\n")
    (output / "SHA256SUMS").write_text("".join(sums))
    print(json.dumps({"release": str(output), **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
