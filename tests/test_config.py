import pytest
from pydantic import ValidationError

from src.config import Settings


def test_cors_origins_parses_csv() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        cors_origins="http://localhost:3000, http://localhost:5173,",
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]


def test_only_active_provider_api_key_is_required() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="mistral",
        mistral_api_key="test-key",
    )

    assert settings.llm_provider == "mistral"
    assert settings.openai_api_key is None


def test_active_provider_api_key_is_required() -> None:
    with pytest.raises(
        ValidationError, match="Missing API key for LLM provider: anthropic"
    ):
        Settings(_env_file=None, llm_provider="anthropic")
