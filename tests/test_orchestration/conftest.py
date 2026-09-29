"""Fixture dùng chung cho test orchestration."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

#: URL tới database quản trị PostgreSQL (vd `postgresql://r2s:r2s-test@127.0.0.1:15432/postgres`);
#: không đặt thì các test tham số `postgres` bị bỏ qua.
POSTGRES_ADMIN = os.environ.get("R2S_TEST_POSTGRES_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def runtime_database_url(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[str]:
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'runtime.db'}"
        return
    if POSTGRES_ADMIN is None:
        pytest.skip("cần R2S_TEST_POSTGRES_URL để chạy trên PostgreSQL")
    import psycopg

    name = f"r2s_test_{uuid4().hex[:12]}"
    with psycopg.connect(POSTGRES_ADMIN, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    base = POSTGRES_ADMIN.rsplit("/", 1)[0]
    yield f"{base}/{name}"
    with psycopg.connect(POSTGRES_ADMIN, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
