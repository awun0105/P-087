"""Runtime do worker công bố vào DB (T-040): API chọn runtime cho job mới từ đây.

Khoá là checksum phần mềm (quyết định Q3): mọi máy cùng image ghi vào cùng một dòng. Phần cứng
(GPU, VRAM, driver) của lần công bố gần nhất chỉ được lưu để ghi nhận, không tham gia khớp job.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.models.contracts.manifests import RuntimeManifest
from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import (
    HARDWARE_COMPONENTS,
    ExecutionProfile,
    load_runtime_manifest,
    software_runtime_checksum,
)

#: Worker không công bố lại sau mức này thì API không coi runtime đó là đang sống.
RUNTIME_TTL = timedelta(minutes=15)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerRuntime:
    """Một runtime phần mềm mà ít nhất một worker đã công bố."""

    software_runtime_checksum: str
    runtime_manifest_checksum: str
    config_checksum: str
    seed: int | None
    gpu_name: str | None
    hardware: dict[str, str | None]
    first_seen_at: datetime
    last_seen_at: datetime

    def is_live(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) - self.last_seen_at <= RUNTIME_TTL

    def profile(self) -> ExecutionProfile:
        """Profile để dựng job mới; worker của runtime này vẫn kiểm lại khi claim."""
        return ExecutionProfile(
            config_checksum=self.config_checksum,
            runtime_manifest_checksum=self.runtime_manifest_checksum,
            software_runtime_checksum=self.software_runtime_checksum,
            seed=self.seed,
        )


def publish(
    database: RuntimeDatabase, profile: ExecutionProfile, manifest: RuntimeManifest, *, now: datetime | None = None
) -> None:
    """Upsert theo checksum phần mềm; manifest phải chính là manifest đã khoá trong profile."""
    if (
        profile.software_runtime_checksum != software_runtime_checksum(manifest)
        or profile.runtime_manifest_checksum != manifest.runtime_manifest_checksum
    ):
        raise ValueError("RuntimeManifest không khớp profile đã khoá của worker")
    observed = (now or datetime.now(UTC)).isoformat()
    hardware = {
        name: manifest.components[name].version for name in sorted(HARDWARE_COMPONENTS) if name in manifest.components
    }
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_worker_runtimes(software_runtime_checksum, runtime_manifest_checksum, config_checksum, "
            "seed, gpu_name, hardware, manifest, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(software_runtime_checksum) DO UPDATE SET "
            "runtime_manifest_checksum=excluded.runtime_manifest_checksum, config_checksum=excluded.config_checksum, "
            "seed=excluded.seed, gpu_name=excluded.gpu_name, hardware=excluded.hardware, "
            "manifest=excluded.manifest, last_seen_at=excluded.last_seen_at",
            (
                profile.software_runtime_checksum,
                manifest.runtime_manifest_checksum,
                profile.config_checksum,
                profile.seed,
                hardware.get("gpu_model"),
                json.dumps(hardware, sort_keys=True),
                manifest.model_dump_json(),
                observed,
                observed,
            ),
        )


def publisher(config_path: Path, manifest_path: Path, profile: ExecutionProfile) -> Callable[[RuntimeDatabase], None]:
    """Hàm công bố cho heartbeat: chỉ ghi khi file config vẫn là bản worker đã khoá lúc khởi động."""

    def publish_current(database: RuntimeDatabase) -> None:
        if sha256_file(config_path) != profile.config_checksum:
            logger.warning("Không công bố runtime: file cấu hình đã đổi so với lúc worker khởi động")
            return
        publish(database, profile, load_runtime_manifest(manifest_path))

    return publish_current


_COLUMNS = (
    "software_runtime_checksum, runtime_manifest_checksum, config_checksum, seed, gpu_name, hardware, "
    "first_seen_at, last_seen_at"
)


def _query(database: RuntimeDatabase, where: str, parameters: tuple) -> list[WorkerRuntime]:
    with database.transaction() as tx:
        rows = tx.execute(f"SELECT {_COLUMNS} FROM r2s_worker_runtimes {where}", parameters).fetchall()
    return [
        WorkerRuntime(
            software_runtime_checksum=row[0],
            runtime_manifest_checksum=row[1],
            config_checksum=row[2],
            seed=row[3],
            gpu_name=row[4],
            hardware=json.loads(row[5]),
            first_seen_at=datetime.fromisoformat(row[6]),
            last_seen_at=datetime.fromisoformat(row[7]),
        )
        for row in rows
    ]


def select(
    database: RuntimeDatabase, *, config_checksum: str, seed: int | None, now: datetime | None = None
) -> WorkerRuntime | None:
    """Runtime cho job mới: đang sống trước, rồi mới nhất. None khi chưa có worker nào công bố."""
    current = now or datetime.now(UTC)
    candidates = [item for item in _query(database, "WHERE config_checksum=?", (config_checksum,)) if item.seed == seed]
    return max(candidates, key=lambda item: (item.is_live(current), item.last_seen_at), default=None)


def find(database: RuntimeDatabase, software_checksum: str) -> WorkerRuntime | None:
    """Runtime theo checksum phần mềm, không lọc hạn; để biết job đang trỏ tới runtime nào."""
    return next(iter(_query(database, "WHERE software_runtime_checksum=?", (software_checksum,))), None)
