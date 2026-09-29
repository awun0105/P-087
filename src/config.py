from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    llm_provider: Literal["openai", "anthropic", "google", "openrouter", "nvidia_nim", "mistral"] = "openai"
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
    database_url: str = Field(default="sqlite:///./data/app.db", repr=False)
    product_fixture_mode: bool = False
    product_processing_config: Path | None = None
    product_runtime_manifest: Path | None = None
    product_seed: int | None = None
    product_worker_root: Path = Path("./data/product_workers")
    product_preview_timeout_seconds: float = Field(default=21600, gt=0, allow_inf_nan=False)
    product_queue_poll_seconds: float = Field(default=3, ge=0.1, le=60, allow_inf_nan=False)
    # MVP 2026-09-29: `self_attested` cho phép video upload chạy với lời tự khai
    # không có khuôn mặt/biển số; mặc định giữ cổng QA `VERIFIED_ANONYMIZED`.
    product_privacy_mode: Literal["qa_verified", "self_attested"] = "qa_verified"
    product_upload_max_bytes: int = Field(default=2 * 1024**3, ge=1024)
    product_upload_quality_profile: Path = Path("./configs/product/upload_quality_v1.json")
    product_target_frame_count: int = Field(default=240, ge=2, le=5000)
    product_prepare_timeout_seconds: float = Field(default=3600, gt=0, allow_inf_nan=False)
    # Thư viện video mẫu đã xử lý sẵn: mỗi thư mục con là một bundle export từ job
    # thật (scripts/demo/export_demo_bundle.py); thư mục chứa manifest.json = một mẫu.
    product_demo_dir: Path = Path("./data/demo/library")

    # Kho vector
    chroma_persist_dir: str = "./data/chroma"

    # Artifact root được resolve thành absolute path tại runtime; contracts chỉ giữ URI.
    artifact_root: Path = Path("./data/artifacts")
    # Kho file S3-compatible (Cloudflare R2 / MinIO, ADR 0003). Để trống bucket thì chỉ
    # dùng filesystem local; khi có bucket, `artifact_root` là cache cục bộ của máy này.
    artifact_s3_bucket: str | None = None
    artifact_s3_endpoint: str | None = None
    artifact_s3_region: str = "auto"
    artifact_s3_access_key_id: str | None = Field(default=None, repr=False)
    artifact_s3_secret_access_key: SecretStr | None = None
    artifact_s3_prefix: str = ""
    artifact_presign_seconds: int = Field(default=900, ge=60, le=86400)

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
        if self.app_env in {"staging", "production"} and not self.artifact_root.is_absolute():
            raise ValueError("ARTIFACT_ROOT must be absolute outside development/test")
        if (self.product_processing_config is None) != (self.product_runtime_manifest is None):
            raise ValueError("PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST phải khai báo cùng nhau")
        if self.artifact_s3_bucket and not (self.artifact_s3_access_key_id and self.artifact_s3_secret_access_key):
            raise ValueError("ARTIFACT_S3_BUCKET cần ARTIFACT_S3_ACCESS_KEY_ID và ARTIFACT_S3_SECRET_ACCESS_KEY")
        if self.product_fixture_mode and self.app_env in {"staging", "production"}:
            raise ValueError("PRODUCT_FIXTURE_MODE chỉ dùng cho development/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
