"""Subprocess proof: executable module phải thực sự chạy CLI, không no-op exit 0."""

import subprocess
import sys
from pathlib import Path


def test_module_without_request_fails(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.services.reconstruction.worker",
            "--job-id",
            "audit",
            "--store-root",
            str(tmp_path / "store"),
            "--workspace",
            str(tmp_path / "work"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--request" in result.stderr


def test_module_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.services.reconstruction.worker", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--request" in result.stdout
