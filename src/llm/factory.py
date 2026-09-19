from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from src.config import get_settings


@lru_cache
def get_llm() -> BaseChatModel:
    """Khởi tạo mô hình chat LangChain theo cấu hình hiện tại."""
    settings = get_settings()
    provider = settings.llm_provider

    kwargs = {
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "api_key": getattr(settings, f"{provider}_api_key"),
        "model": getattr(settings, f"{provider}_model"),
    }

    provider_overrides = {
        "openai": {"model_provider": "openai"},
        "anthropic": {"model_provider": "anthropic"},
        "google": {"model_provider": "google_genai"},
        "mistral": {"model_provider": "mistralai"},
        "openrouter": {
            "model_provider": "openai",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "nvidia_nim": {
            "model_provider": "openai",
            "base_url": "https://integrate.api.nvidia.com/v1",
        },
    }

    kwargs.update(provider_overrides[provider])
    return init_chat_model(**kwargs)
