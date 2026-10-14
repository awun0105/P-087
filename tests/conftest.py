import os
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient

load_dotenv()

# Thiết lập dummy API key để Settings không báo lỗi khi chạy unit tests
os.environ.setdefault("OPENAI_API_KEY", "sk-mock-testing-key")

from src.main import app  # noqa: E402
from src.services.orchestration.projects.registry import DEFAULT_RUNTIME_ROOT  # noqa: E402


@pytest.fixture(autouse=True)
def _no_writes_to_default_artifact_store() -> Iterator[None]:
    """Test không được để lại job trong kho artifact mặc định của repo (`data/artifacts`).

    Registry và Settings mặc định trỏ vào thư mục thật đó; test nào tạo job mà quên truyền `runtime_root`/
    `artifact_root` tạm sẽ để rác tích lại sau mỗi lượt chạy. Kiểm theo từng test để lỗi chỉ đúng thủ phạm.
    """
    jobs = DEFAULT_RUNTIME_ROOT / "jobs"
    before = {path.name for path in jobs.iterdir()} if jobs.is_dir() else set()
    yield
    leaked = sorted({path.name for path in jobs.iterdir()} - before) if jobs.is_dir() else []
    assert not leaked, f"test ghi {leaked} vào {jobs}; dùng tmp_path cho runtime_root/artifact_root"


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock
