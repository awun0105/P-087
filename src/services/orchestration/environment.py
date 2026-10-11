"""Environment fingerprinting for the Core runtime."""

import hashlib
import platform
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]


class CoreEnvironmentFingerprint(BaseModel):
    python_version: str
    platform_system: str
    platform_release: str
    platform_machine: str
    core_lock_checksum: str | None


def get_lockfile_checksum() -> str | None:
    lock_path = ROOT / "requirements.lock.txt"
    if not lock_path.exists():
        return None
    sha256 = hashlib.sha256()
    sha256.update(lock_path.read_bytes())
    return sha256.hexdigest()


def get_core_environment_fingerprint() -> CoreEnvironmentFingerprint:
    return CoreEnvironmentFingerprint(
        python_version=sys.version,
        platform_system=platform.system(),
        platform_release=platform.release(),
        platform_machine=platform.machine(),
        core_lock_checksum=get_lockfile_checksum(),
    )
