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
    assert settings.mistral_api_key == "test-key"


def test_active_provider_api_key_is_required() -> None:
    with pytest.raises(ValidationError, match="Missing API key for LLM provider: anthropic"):
        Settings(_env_file=None, llm_provider="anthropic")


def test_guest_signup_stays_disabled_by_default_and_can_be_explicitly_enabled() -> None:
    defaults = Settings(_env_file=None, openai_api_key="test-key")
    enabled = Settings(_env_file=None, openai_api_key="test-key", auth_guest_signup_enabled=True)

    assert defaults.auth_guest_signup_enabled is False
    assert enabled.auth_guest_signup_enabled is True


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_auth_must_be_required_outside_development(app_env: str) -> None:
    with pytest.raises(ValidationError, match="AUTH_REQUIRED"):
        Settings(
            _env_file=None,
            openai_api_key="test-key",
            app_env=app_env,
            artifact_root="/data/artifacts",
            auth_required=False,
        )
    ok = Settings(
        _env_file=None,
        openai_api_key="test-key",
        app_env=app_env,
        artifact_root="/data/artifacts",
        auth_required=True,
    )
    assert ok.auth_required is True


def test_auth_can_stay_off_in_development_and_test() -> None:
    for app_env in ("development", "test"):
        assert Settings(_env_file=None, openai_api_key="test-key", app_env=app_env).auth_required is False
