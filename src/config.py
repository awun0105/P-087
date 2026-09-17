from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # Cấu hình ứng dụng
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1024, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Nhận danh sách CORS origin từ chuỗi CSV hoặc list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # Cấu hình LLM dùng chung
    llm_provider: Literal[
        "openai", "anthropic", "google", "openrouter", "nvidia_nim", "mistral"
    ] = "openai"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, ge=1)

    # Cấu hình riêng cho từng provider
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-latest"

    google_api_key: str | None = None
    google_model: str = "gemini-2.5-flash"

    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"

    nvidia_nim_api_key: str | None = None
    nvidia_nim_model: str = "meta/llama-3.1-70b-instruct"

    mistral_api_key: str | None = None
    mistral_model: str = "mistral-small-latest"

    # Cơ sở dữ liệu
    database_url: str = "sqlite:///./data/app.db"

    # Kho vector
    chroma_persist_dir: str = "./data/chroma"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_llm_provider(self) -> "Settings":
        """Chỉ yêu cầu thông tin xác thực của provider đang được chọn."""
        required_keys = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
            "openrouter": self.openrouter_api_key,
            "nvidia_nim": self.nvidia_nim_api_key,
            "mistral": self.mistral_api_key,
        }

        api_key = required_keys[self.llm_provider]
        if not api_key or not api_key.strip():
            raise ValueError(f"Missing API key for LLM provider: {self.llm_provider}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
