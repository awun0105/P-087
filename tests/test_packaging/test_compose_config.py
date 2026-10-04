"""Focused static checks for the portable Studio container boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.studio import container_entrypoint

ROOT = Path(__file__).resolve().parents[2]


def _compose(name: str) -> dict:
    with (ROOT / name).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_studio_compose_mounts_persisted_data_and_requires_auth() -> None:
    assert not (ROOT / "Dockerfile.studio").exists()
    assert not (ROOT / "docker-compose.studio.yml").exists()
    assert not (ROOT / "docker-compose.studio.gpu.yml").exists()
    document = _compose("docker-compose.yml")
    api = document["services"]["api"]
    environment = api["environment"]
    volumes = api["volumes"]

    assert api["platform"] == "linux/amd64"
    assert api["image"] == "real2sim-studio-api"
    assert api["build"]["dockerfile"] == "Dockerfile"
    assert document["services"]["data-init"]["platform"] == api["platform"]
    assert document["services"]["data-restore"]["platform"] == api["platform"]
    assert document["services"]["data-init"]["image"] == api["image"]
    assert document["services"]["data-restore"]["image"] == api["image"]
    assert document["services"]["data-init"]["user"] == "0:0"
    assert document["services"]["data-init"]["entrypoint"] == [
        "python",
        "-m",
        "scripts.studio.container_entrypoint",
    ]
    assert document["services"]["data-init"]["command"] == ["prepare-data"]
    assert document["services"]["data-restore"]["entrypoint"] == [
        "python",
        "-m",
        "scripts.studio.container_entrypoint",
    ]
    assert document["services"]["data-restore"]["command"] == [
        "restore-if-needed",
        "/package/r2s-studio-data.zip",
    ]
    assert document["services"]["data-restore"]["volumes"][1]["source"] == (
        "${STUDIO_DATA_ARCHIVE:-./r2s-studio-data.zip}"
    )
    assert api["depends_on"]["data-restore"]["condition"] == "service_completed_successfully"
    assert environment["AUTH_REQUIRED"] == "true"
    assert environment["PRODUCT_PRIVACY_MODE"] == "self_attested"
    assert environment["R2S_REQUIRE_DATA"] == "true"
    assert environment["DATABASE_URL"] == "sqlite:////app/data/studio_local/runtime.db"
    assert environment["ARTIFACT_ROOT"] == "/app/data/studio_local/artifacts"
    assert {item["target"] for item in volumes} == {"/app/data"}
    assert volumes[0]["source"] == "${STUDIO_DATA_DIR:-./data}"


def test_frontend_build_uses_internal_api_rewrite() -> None:
    document = _compose("docker-compose.yml")
    web = document["services"]["web"]
    assert web["build"]["context"] == "./frontend"
    assert web["build"]["args"]["REAL2SIM_API_URL"] == "http://api:8000"
    assert web["depends_on"]["api"]["condition"] == "service_healthy"
    assert web["healthcheck"]["test"][:3] == ["CMD", "node", "-e"]
    assert "127.0.0.1:3000" in web["healthcheck"]["test"][3]
    assert "response.status >= 400" in web["healthcheck"]["test"][3]


def test_gpu_override_uses_same_host_data_and_nvidia_runtime() -> None:
    document = _compose("docker-compose.gpu.yml")
    worker = document["services"]["gpu-worker"]
    init = document["services"]["gpu-runtime-init"]
    environment = worker["environment"]
    volume = worker["volumes"][0]

    assert worker["platform"] == "linux/amd64"
    assert init["platform"] == worker["platform"]
    assert worker["build"]["dockerfile"] == "Dockerfile.gpu"
    assert worker["gpus"] == "all"
    assert volume["source"] == "${STUDIO_DATA_DIR:-./data}"
    assert volume["target"] == "/data"
    assert environment["DATABASE_URL"] == "sqlite:////data/studio_local/runtime.db"
    assert environment["ARTIFACT_ROOT"] == "/data/studio_local/artifacts"
    assert environment["REC03_COLMAP_COMMAND"] == '["colmap"]'
    assert environment["REC04_BRUSH_COMMAND"] == '["/opt/real2sim/runtime/brush/brush_app"]'
    assert environment["REC04_SPLAT_MODULE_PATH"].startswith("/opt/real2sim/runtime/")
    assert environment["PRODUCT_SCENE_RUNTIME_PYTHON"].startswith("/opt/real2sim/scene_runtime/")
    assert init["command"][:2] == ["bash", "-lc"]
    init_command = init["command"][2]
    assert 'manifest_backup="$${PRODUCT_RUNTIME_MANIFEST}.previous-' in init_command
    assert "date -u +%Y%m%dT%H%M%S%N" in init_command
    assert 'mv -- "$$PRODUCT_RUNTIME_MANIFEST" "$$manifest_backup"' in init_command
    assert "rm -f" not in init_command
    assert ".venv/bin/python -m scripts.gpu.make_runtime_manifest" in init_command
    assert '--out "$$PRODUCT_RUNTIME_MANIFEST"' in init_command
    assert ".venv/bin/python -m scripts.kaggle.preflight" in init_command
    assert init["env_file"] == ["${STUDIO_ENV_FILE:-.env.studio}"]
    assert init["gpus"] == "all"
    assert init["environment"]["PRODUCT_RUNTIME_MANIFEST"] == "/data/studio_local/runtime_manifest.json"
    assert init["environment"]["REC03_COLMAP_COMMAND"] == '["colmap"]'
    assert document["services"]["api"]["environment"]["PRODUCT_PROCESSING_CONFIG"] == (
        "/app/configs/product/processing_presets_v1.json"
    )
    assert document["services"]["api"]["environment"]["PRODUCT_OBJECTIFY_REMOTE_WORKER"] == "true"


def test_frontend_and_backend_entrypoints_are_declared() -> None:
    frontend = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    frontend_ignore = (ROOT / "frontend" / ".dockerignore").read_text(encoding="utf-8")
    frontend_lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    backend = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "scripts" / "studio" / "container_entrypoint.py").read_text(encoding="utf-8")

    assert "ARG REAL2SIM_API_URL" in frontend
    assert "npm run build:editor" in frontend
    assert ".env.*" in frontend_ignore
    assert "!.env*.example" in frontend_ignore
    assert frontend_lock["packages"]["node_modules/@emnapi/core"]["version"] == "1.11.3"
    assert frontend_lock["packages"]["node_modules/@emnapi/runtime"]["version"] == "1.11.3"
    assert "apt-get install -y --no-install-recommends" in backend
    assert "ffmpeg" in backend
    assert 'ENTRYPOINT ["python", "-m", "scripts.studio.container_entrypoint"]' in backend
    assert "data_package" in entrypoint
    assert "R2S_REQUIRE_DATA" in entrypoint
    assert "R2S_PREPARE_VOLUME" in entrypoint
    assert "prepare-data" in entrypoint
    assert "os.setgroups([])" in entrypoint


def test_module_entrypoint_bootstraps_and_execs_server_without_secret_output(
    tmp_path: Path,
) -> None:
    """The image invocation keeps the checkout root on sys.path for bootstrap imports."""
    database = tmp_path / "runtime.db"
    database_url = f"sqlite:///{database}"
    from src.services.orchestration.jobs.database import RuntimeDatabase

    RuntimeDatabase(database_url)
    password = "a-subprocess-only-password"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "DATABASE_URL": database_url,
            "AUTH_REQUIRED": "true",
            "R2S_REQUIRE_DATA": "true",
            "R2S_BOOTSTRAP_EMAIL": "module-reviewer@example.com",
            "R2S_BOOTSTRAP_NAME": "Module reviewer",
            "R2S_BOOTSTRAP_ROLE": "reviewer",
            "R2S_BOOTSTRAP_PASSWORD": password,
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.studio.container_entrypoint",
            "--root",
            str(tmp_path),
            "serve",
            sys.executable,
            "-c",
            "print('server-started')",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "server-started"
    assert password not in result.stdout
    assert password not in result.stderr


def test_entrypoint_fails_closed_when_sqlite_data_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/studio_local/runtime.db")
    monkeypatch.setenv("R2S_REQUIRE_DATA", "true")

    with pytest.raises(container_entrypoint.StartupError, match="runtime database"):
        container_entrypoint._require_database(tmp_path)


def test_require_database_rejects_sqlite_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "real-runtime.db"
    target.write_bytes(b"database")
    linked = tmp_path / "runtime.db"
    linked.symlink_to(target)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{linked}")
    monkeypatch.setenv("R2S_REQUIRE_DATA", "true")

    with pytest.raises(container_entrypoint.StartupError, match="symlink"):
        container_entrypoint._require_database(tmp_path)


def test_prepare_data_volume_only_owns_canonical_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The restore preflight cannot chown any payload family or arbitrary file."""
    chown_calls: list[tuple[Path, int, int, bool]] = []
    monkeypatch.setattr(container_entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        container_entrypoint.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000),
    )
    monkeypatch.setattr(
        container_entrypoint.os,
        "chown",
        lambda path, uid, gid, follow_symlinks: chown_calls.append((Path(path), uid, gid, follow_symlinks)),
    )

    container_entrypoint._prepare_data_volume(tmp_path)

    data_root = tmp_path / "data"
    assert (data_root / "studio_local").is_dir()
    assert {path for path, *_ in chown_calls} == {data_root, data_root / "studio_local"}
    assert all(uid == 1000 and gid == 1000 and follow_symlinks is False for _, uid, gid, follow_symlinks in chown_calls)


def test_prepare_data_volume_rejects_studio_local_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_root / "studio_local").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(container_entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        container_entrypoint.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000),
    )
    monkeypatch.setattr(container_entrypoint.os, "chown", lambda *args, **kwargs: None)

    with pytest.raises(container_entrypoint.StartupError, match="symlink"):
        container_entrypoint._prepare_data_volume(tmp_path)


def test_prepare_volume_chowns_managed_dirs_then_drops_to_appuser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root-mounted production volumes become writable without chowning files."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    for variable, relative in container_entrypoint.MANAGED_VOLUME_PATHS.items():
        monkeypatch.setenv(variable, str(data_root / relative))

    identity_calls: list[tuple[str, object]] = []
    chown_calls: list[tuple[Path, int, int, bool]] = []
    monkeypatch.setattr(container_entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        container_entrypoint.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000),
    )
    monkeypatch.setattr(
        container_entrypoint.os,
        "chown",
        lambda path, uid, gid, follow_symlinks: chown_calls.append((Path(path), uid, gid, follow_symlinks)),
    )
    monkeypatch.setattr(
        container_entrypoint.os, "setgroups", lambda groups: identity_calls.append(("setgroups", groups))
    )
    monkeypatch.setattr(container_entrypoint.os, "setgid", lambda gid: identity_calls.append(("setgid", gid)))
    monkeypatch.setattr(container_entrypoint.os, "setuid", lambda uid: identity_calls.append(("setuid", uid)))

    container_entrypoint._prepare_volume_and_drop(tmp_path)

    assert all((data_root / relative).is_dir() for relative in container_entrypoint.MANAGED_VOLUME_DIRS)
    assert chown_calls
    assert all(uid == 1000 and gid == 1000 and follow_symlinks is False for _, uid, gid, follow_symlinks in chown_calls)
    assert {path for path, *_ in chown_calls} == {
        data_root / relative for relative in container_entrypoint.MANAGED_VOLUME_DIRS
    }
    assert identity_calls == [("setgroups", []), ("setgid", 1000), ("setuid", 1000)]


def test_prepare_volume_rejects_path_outside_canonical_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A production env cannot redirect a managed root to an arbitrary path."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path / "outside"))
    monkeypatch.setattr(container_entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        container_entrypoint.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000),
    )

    with pytest.raises(container_entrypoint.StartupError, match="ARTIFACT_ROOT"):
        container_entrypoint._prepare_volume_and_drop(tmp_path)


def test_prepare_volume_rejects_symlinked_managed_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlink must never be followed by the ownership preparation step."""
    data_root = tmp_path / "data"
    managed_root = data_root / "studio_local"
    managed_root.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    managed_root.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(container_entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        container_entrypoint.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000),
    )

    with pytest.raises(container_entrypoint.StartupError, match="symlink"):
        container_entrypoint._prepare_volume_and_drop(tmp_path)


def test_restore_if_needed_never_overwrites_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "data" / "studio_local" / "runtime.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"existing")

    # A missing archive is acceptable only because the already-restored DB is
    # deliberately left untouched; the direct `restore` action still fails.
    container_entrypoint._restore_if_needed(tmp_path, tmp_path / "missing.zip")
    assert database.read_bytes() == b"existing"


def test_restore_if_needed_rejects_symlinked_runtime_database(tmp_path: Path) -> None:
    state = tmp_path / "data" / "studio_local"
    state.mkdir(parents=True)
    target = tmp_path / "outside-runtime.db"
    target.write_bytes(b"outside")
    (state / "runtime.db").symlink_to(target)

    with pytest.raises(container_entrypoint.StartupError, match="symlink"):
        container_entrypoint._restore_if_needed(tmp_path, tmp_path / "missing.zip")


def test_restore_if_needed_rejects_symlinked_runtime_parent(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside_state = tmp_path / "outside" / "studio_local"
    outside_state.mkdir(parents=True)
    (outside_state / "runtime.db").write_bytes(b"outside")
    (data_root / "studio_local").symlink_to(outside_state, target_is_directory=True)

    with pytest.raises(container_entrypoint.StartupError, match="symlink"):
        container_entrypoint._restore_if_needed(tmp_path, tmp_path / "missing.zip")


def test_serve_rejects_archive_before_restore_when_volume_drop_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("R2S_DATA_ARCHIVE", "/package/data.zip")
    monkeypatch.setenv("R2S_RESTORE_DATA", "true")
    monkeypatch.setenv("R2S_PREPARE_VOLUME", "true")
    restore_called = False

    def unexpected_restore(root: Path, archive: Path) -> None:
        nonlocal restore_called
        restore_called = True

    monkeypatch.setattr(container_entrypoint, "_restore", unexpected_restore)
    with pytest.raises(container_entrypoint.StartupError, match="không thể dùng cùng"):
        container_entrypoint._serve(tmp_path, ["true"])
    assert restore_called is False


def test_bootstrap_reviewer_uses_secret_file_without_printing_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "runtime.db"
    secret = tmp_path / "bootstrap-password"
    secret.write_text("a-private-password\n", encoding="utf-8")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("R2S_BOOTSTRAP_EMAIL", "reviewer@example.com")
    monkeypatch.setenv("R2S_BOOTSTRAP_NAME", "Team reviewer")
    monkeypatch.setenv("R2S_BOOTSTRAP_ROLE", "reviewer")
    monkeypatch.setenv("R2S_BOOTSTRAP_PASSWORD_FILE", str(secret))
    monkeypatch.delenv("R2S_BOOTSTRAP_PASSWORD", raising=False)

    container_entrypoint._bootstrap_reviewer(f"sqlite:///{database}")

    from src.services.orchestration.auth import AuthService
    from src.services.orchestration.jobs.database import RuntimeDatabase

    users = AuthService(RuntimeDatabase(f"sqlite:///{database}")).list_users()
    assert [(user.email, user.role, user.display_name) for user in users] == [
        ("reviewer@example.com", "reviewer", "Team reviewer")
    ]


def test_bootstrap_refuses_disabled_packaged_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "runtime.db"

    from src.services.orchestration.auth import AuthService
    from src.services.orchestration.jobs.database import RuntimeDatabase

    service = AuthService(RuntimeDatabase(f"sqlite:///{database}"))
    disabled = service.create_user("packaged@example.com", "Packaged actor", "password-one", "editor")
    reviewer = service.create_user("owner@example.com", "Current reviewer", "password-two", "reviewer")
    service.update_user(reviewer, disabled.user_id, active=False)

    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("R2S_BOOTSTRAP_EMAIL", "packaged@example.com")
    monkeypatch.setenv("R2S_BOOTSTRAP_NAME", "Replacement")
    monkeypatch.setenv("R2S_BOOTSTRAP_PASSWORD", "password-three")
    with pytest.raises(container_entrypoint.StartupError, match="vô hiệu hóa"):
        container_entrypoint._bootstrap_reviewer(f"sqlite:///{database}")
