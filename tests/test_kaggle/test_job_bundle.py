"""Gói job (scripts/kaggle/job_bundle.py): xuất → nạp giữa hai máy, phát hiện gói hỏng và job rẽ nhánh."""

import json
from pathlib import Path

import pytest

from scripts.kaggle.job_bundle import BundleError, export_bundle, import_bundle, load_bundle
from src.services.orchestration.jobs.database import RuntimeDatabase

JOB, PROJECT, UPLOAD = "job-a", "project-a", "upload-a"


class Machine:
    """Một máy: DB runtime SQLite + thư mục `jobs/` của artifact store."""

    def __init__(self, root: Path) -> None:
        self.database = RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}")
        self.jobs = root / "artifacts" / "jobs"
        self.jobs.mkdir(parents=True)

    def write(self, relative: str, text: str) -> None:
        path = self.jobs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def set_job(self, events: list[str]) -> None:
        """Ghi project/upload/job với chuỗi event cho trước (version 1..n)."""
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_projects(project_id,payload) VALUES (?,?) ON CONFLICT(project_id) DO NOTHING",
                (PROJECT, json.dumps({"project_id": PROJECT})),
            )
            tx.execute(
                "INSERT INTO r2s_uploads(upload_id,payload) VALUES (?,?) ON CONFLICT(upload_id) DO NOTHING",
                (UPLOAD, json.dumps({"upload_id": UPLOAD, "project_ids": [PROJECT]})),
            )
            tx.execute(
                "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?) "
                "ON CONFLICT(job_id) DO NOTHING",
                (JOB, PROJECT, 0, ""),
            )
            tx.execute("UPDATE r2s_jobs SET version=?, manifest_ref=? WHERE job_id=?", (len(events), events[-1], JOB))
            tx.execute("DELETE FROM r2s_job_events WHERE job_id=?", (JOB,))
            for version, payload in enumerate(events, start=1):
                tx.execute("INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)", (JOB, version, payload))

    def job_row(self) -> tuple[int, str, int]:
        with self.database.transaction() as tx:
            row = tx.execute("SELECT version, manifest_ref FROM r2s_jobs WHERE job_id=?", (JOB,)).fetchone()
            count = tx.execute("SELECT COUNT(*) FROM r2s_job_events WHERE job_id=?", (JOB,)).fetchone()
        assert row is not None and count is not None
        return int(row[0]), str(row[1]), int(count[0])


@pytest.fixture
def source(tmp_path: Path) -> Machine:
    machine = Machine(tmp_path / "gpu")
    machine.write(f"{JOB}/manifests/job_manifest.001.json", "m1")
    machine.write(f"{JOB}/scene/rev-001.json", "scene")
    machine.write(f"{PROJECT}/input/input_manifest.json", "input")
    machine.write(f"{UPLOAD}/input/source.mp4", "video")
    machine.set_job(["e1", "e2"])
    return machine


def test_export_then_import_reproduces_job_on_clean_machine(source: Machine, tmp_path: Path) -> None:
    bundle = export_bundle(source.database, source.jobs, JOB, tmp_path / "out")
    target = Machine(tmp_path / "studio")

    assert "thêm mới" in import_bundle(target.database, target.jobs, bundle)
    assert target.job_row() == (2, "e2", 2)
    assert (target.jobs / UPLOAD / "input/source.mp4").read_text() == "video"
    assert (target.jobs / JOB / "scene/rev-001.json").read_text() == "scene"
    # Nạp lại cùng gói: không đổi gì.
    assert "không đổi" in import_bundle(target.database, target.jobs, bundle)


def test_import_advances_job_when_bundle_continues_it(source: Machine, tmp_path: Path) -> None:
    target = Machine(tmp_path / "studio")
    import_bundle(target.database, target.jobs, export_bundle(source.database, source.jobs, JOB, tmp_path / "first"))
    source.write(f"{JOB}/manifests/job_manifest.002.json", "m2")
    source.set_job(["e1", "e2", "e3"])

    later = export_bundle(source.database, source.jobs, JOB, tmp_path / "second")

    assert "đã cập nhật" in import_bundle(target.database, target.jobs, later)
    assert target.job_row() == (3, "e3", 3)


def test_import_refuses_diverged_job_and_leaves_database_untouched(source: Machine, tmp_path: Path) -> None:
    bundle = export_bundle(source.database, source.jobs, JOB, tmp_path / "out")
    target = Machine(tmp_path / "studio")
    target.set_job(["e1", "khác"])

    with pytest.raises(BundleError, match="rẽ nhánh"):
        import_bundle(target.database, target.jobs, bundle)
    assert target.job_row() == (2, "khác", 2)


def test_import_refuses_bundle_older_than_local_job(source: Machine, tmp_path: Path) -> None:
    bundle = export_bundle(source.database, source.jobs, JOB, tmp_path / "out")
    target = Machine(tmp_path / "studio")
    target.set_job(["e1", "e2", "e3"])

    with pytest.raises(BundleError, match="mới hơn gói"):
        import_bundle(target.database, target.jobs, bundle)


def test_tampered_or_incomplete_bundle_is_rejected(source: Machine, tmp_path: Path) -> None:
    bundle = export_bundle(source.database, source.jobs, JOB, tmp_path / "out")
    # Đổi nội dung bằng file mới (không sửa hardlink dùng chung với máy nguồn).
    scene = bundle / "artifacts/jobs" / JOB / "scene/rev-001.json"
    scene.unlink()
    scene.write_text("sửa tay", encoding="utf-8")

    with pytest.raises(BundleError, match="sai checksum"):
        load_bundle(bundle)


def test_export_does_not_overwrite_and_reports_unknown_job(source: Machine, tmp_path: Path) -> None:
    export_bundle(source.database, source.jobs, JOB, tmp_path / "out")
    with pytest.raises(BundleError, match="Đã có gói"):
        export_bundle(source.database, source.jobs, JOB, tmp_path / "out")
    with pytest.raises(BundleError, match="Không có job"):
        export_bundle(source.database, source.jobs, "job-none", tmp_path / "other")
