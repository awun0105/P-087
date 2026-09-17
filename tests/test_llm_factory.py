from unittest.mock import Mock, patch

import pytest

from src.config import Settings
from src.llm.factory import get_llm


@pytest.mark.parametrize(
    ("provider", "expected_provider", "expected_base_url"),
    [
        ("openai", "openai", None),
        ("anthropic", "anthropic", None),
        ("google", "google_genai", None),
        ("mistral", "mistralai", None),
        ("openrouter", "openai", "https://openrouter.ai/api/v1"),
        ("nvidia_nim", "openai", "https://integrate.api.nvidia.com/v1"),
    ],
)
def test_get_llm_maps_provider(
    provider: str,
    expected_provider: str,
    expected_base_url: str | None,
) -> None:
    api_key_field = f"{provider}_api_key"
    model_field = f"{provider}_model"
    settings = Settings(
        _env_file=None,
        llm_provider=provider,
        **{api_key_field: "test-key", model_field: "test-model"},
    )
    model = Mock()

    get_llm.cache_clear()
    with (
        patch("src.llm.factory.get_settings", return_value=settings),
        patch("src.llm.factory.init_chat_model", return_value=model) as init_model,
    ):
        assert get_llm() is model

    expected_kwargs = {
        "temperature": 0.7,
        "max_tokens": 2048,
        "api_key": "test-key",
        "model": "test-model",
        "model_provider": expected_provider,
    }
    if expected_base_url:
        expected_kwargs["base_url"] = expected_base_url
    init_model.assert_called_once_with(**expected_kwargs)
    get_llm.cache_clear()
