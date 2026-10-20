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
    product_colmap_use_gpu: bool = False
    #: Từ điển COLMAP chuẩn, tải bằng scripts/assets/download_vocab_tree.py; None dùng vị trí chuẩn trong repo.
    product_colmap_vocab_tree: Path | None = None
    product_runtime_manifest: Path | None = None
    #: T-040: API không cần manifest; job mới lấy runtime mà GPU worker đã công bố vào DB (cần PRODUCT_PROCESSING_CONFIG).
    product_runtime_from_workers: bool = False
    product_gpu_release_catalog: Path | None = None
    #: Runtime qualification registry for grouped input recipes; absent means no new recipe dispatch is enabled.
    product_input_runtime_registry: Path | None = None
    #: Server-owned policy/profile for durable Isaac validation; not accepted from request payloads.
    product_isaac_validation_config: Path | None = None
    product_isaac_validation_profile: Path | None = None
    #: Worker-only Isaac launcher and resource profile used by AUD-07 admission.
    product_isaac_validation_launcher: Path | None = None
    product_isaac_validation_resources: Path | None = None
    product_seed: int | None = None
    product_worker_root: Path = Path("./data/product_workers")
    #: Giữ scratch để chẩn đoán; mặc định chỉ dọn attempt đã publish và commit thành công.
    product_worker_keep_scratch: bool = False
    #: Giới hạn bao ngoài của bước preview (COLMAP 14400 + Brush 21600 chạy trong một lượt; T-043 round 2).
    product_preview_timeout_seconds: float = Field(default=36000, gt=0, allow_inf_nan=False)
    #: Thông số REC-05 (voxel/capsule) cho bước hoàn tất sau xác nhận tỉ lệ (owner chốt 2026-09-29).
    product_geometry_config: Path = Path("configs/product/geometry_v1.json")
    product_evaluation_reference: Path = Path("configs/product/evaluation_reference_v1.json")
    #: Giới hạn bao ngoài của bước hoàn tất: splat-process (Brush 21600) + 6 lần voxel (T-043 round 2).
    product_finalize_timeout_seconds: float = Field(default=36000, gt=0, allow_inf_nan=False)
    #: GPU adapter cho splat-transform, theo từng máy (`--list-gpus`); None = dùng giá trị trong profile.
    product_geometry_gpu_index: int | None = Field(default=None, ge=0)
    #: Runtime SAM2 cho tách vật thể (ADR 0006); thiếu thì dùng fallback hình học.
    product_scene_runtime_python: Path | None = None
    #: ObjectGS runs in its own pinned runtime; never install its gsplat into scene/Brush environments.
    product_objectgs_runtime_python: Path | None = None
    product_objectgs_repository: Path | None = None
    product_objectgs_gsplat_repository: Path | None = None
    product_objectgs_timeout_seconds: float = Field(default=14400, gt=0, allow_inf_nan=False)
    product_objectgs_stall_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    #: Trần giờ GPU mỗi scene (T-043). Không đặt = không giới hạn; máy phòng thí nghiệm không đặt.
    product_job_gpu_hours_max: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    product_objectgs_gpu_device: int = Field(default=0, ge=0)
    product_objectgs_cuda_home: Path | None = None
    product_objectgs_cxx: Path | None = None
    product_objectgs_glm_repository: Path | None = None
    #: Cache biên dịch dùng chung của gsplat-object (dựng sẵn bởi setup_objectgs_runtime.sh); None = biên dịch trong workspace.
    product_objectgs_extension_cache_dir: Path | None = None
    #: Che khuôn mặt/biển số trên frame trước khi dựng 3D (AUD-18). Cần `product_scene_runtime_python` và
    #: `product_egoblur_weights`; bật mà thiếu thì job lỗi ở bước tách frame, không chạy trên frame gốc.
    product_anonymize_input: bool = False
    #: Thư mục chứa `ego_blur_face_gen2.jit` và `ego_blur_lp_gen2.jit`.
    product_egoblur_weights: Path | None = None
    #: Đặt trên API khi bộ che chạy ở worker máy khác (API không có scene runtime hay trọng số để tự kiểm).
    product_anonymize_remote_worker: bool = False
    product_sam2_checkpoint: Path | None = None
    product_scene_timeout_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    #: Ngân sách bộ nhớ cho Gaussian nguồn đã đọc của xem trước vùng (MiB); mục cũ nhất bị bỏ khi vượt (T-025).
    product_region_source_cache_mib: int = Field(default=1024, ge=0)
    #: Pipeline v2 (ADR 0007): trọng số LaMa TorchScript cho vá nền; thiếu thì dùng cv2.inpaint.
    product_lama_checkpoint: Path | None = None
    #: Bật tách scene theo vật (Gaussian + collider từng vật, vá nền). Cần runtime có gsplat/coacd.
    product_objectify: bool = True
    #: Đặt trên API khi worker tách theo vật chạy ở máy khác (API không tự kiểm được runtime của worker).
    product_objectify_remote_worker: bool = False
    #: GLB xem trước của asset danh mục (sinh bằng scripts/scene/build_asset_previews.py); thiếu thì Studio vẽ hộp.
    product_asset_preview_dir: Path = Path("./data/asset_previews")
    #: Phục vụ bản xem trước chuyển từ asset Isaac Sim cho trình duyệt. Giấy phép asset Isaac không cho phân phối hay
    #: tạo bản chuyển đổi (ADR 0010 mục 3), nên mặc định chỉ bật ở development/test; None = theo APP_ENV. Gói xuất cho
    #: Isaac Sim không bị ảnh hưởng (chỉ trỏ tới asset gốc).
    product_isaac_asset_previews: bool | None = None
    #: Hình xem trước CC0/tự dựng của danh mục (scripts/scene/build_cc0_previews.py), commit trong repo; được ưu tiên
    #: hơn bản chuyển từ asset Isaac và dùng được ở mọi môi trường.
    product_catalog_preview_dir: Path = Path("configs/product/catalog_previews")
    #: Bản ghi Rerun của quá trình train 3DGS (`<job_id>.rrd`, sinh bằng eval/visual/brush_quality.py --rerun-save).
    #: Là dữ liệu soi/đánh giá tuỳ chọn, không phải artifact của pipeline; thiếu thì Studio không hiện chế độ xem này.
    product_rerun_recording_dir: Path = Path("./data/rerun_recordings")
    #: Thư mục giữ file của scene đã vào thùng rác; None → `trash/` cạnh ARTIFACT_ROOT (cùng filesystem, dời là rename).
    product_trash_root: Path | None = None
    #: Mục nằm trong thùng rác quá số ngày này thì tự bị xoá hẳn (owner chốt 7 ngày, STUDIO_UX_SPEC D-15); 0 = tắt.
    product_trash_retention_days: int = Field(default=7, ge=0, le=365)
    #: Số lần thử tách theo vật trước khi dừng và để người dùng chọn (chạy lại / dùng hộp).
    product_objectify_attempts: int = Field(default=3, ge=1, le=10)
    product_queue_poll_seconds: float = Field(default=3, ge=0.1, le=60, allow_inf_nan=False)
    #: Chờ tài nguyên không phải vì máy bận quá mức này (giây) thì việc tách vật / kiểm định dừng, cho chạy lại (T-050).
    product_resource_wait_max_seconds: float = Field(default=1800, ge=60, le=86400, allow_inf_nan=False)
    # MVP 2026-09-29: `self_attested` cho phép video upload chạy với lời tự khai
    # không có khuôn mặt/biển số; mặc định giữ cổng QA `VERIFIED_ANONYMIZED`.
    product_privacy_mode: Literal["qa_verified", "self_attested"] = "qa_verified"
    product_upload_max_bytes: int = Field(default=2 * 1024**3, ge=1024)
    product_upload_quality_profile: Path = Path("./configs/product/upload_quality_v2.json")
    product_target_frame_count: int = Field(default=240, ge=2, le=5000)
    product_prepare_timeout_seconds: float = Field(default=3600, gt=0, allow_inf_nan=False)
    # Thư viện video mẫu đã xử lý sẵn: mỗi thư mục con là một bundle export từ job
    # thật (scripts/demo/export_demo_bundle.py); thư mục chứa manifest.json = một mẫu.
    product_demo_dir: Path = Path("./data/demo/library")
    product_demo_max_sessions: int = Field(default=32, ge=1, le=256)
    product_demo_session_seconds: int = Field(default=14400, ge=60, le=86400)
    product_demo_idle_seconds: int = Field(default=180, ge=60, le=3600)
    #: Child workers must not dispatch another demo session recursively.
    product_demo_session_worker: bool = False
    #: Immutable library objects, separate from normal job artifacts and disposable outputs.
    product_demo_object_prefix: str = "demo/library"
    #: Internal read-only fallback used only by a scoped demo runtime.
    product_demo_baseline_prefix: str | None = None
    product_demo_archive_key: str | None = None
    product_demo_archive_checksum: str | None = None
    #: Compressed bootstrap archive uses ephemeral disk; extracted data stays beside demo_dir.
    product_demo_download_dir: Path | None = None
    product_demo_required: bool = False

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

    # Khi bật đăng nhập, đăng ký không có mã mời tạo Guest; deployment có thể tắt rõ ràng.
    auth_required: bool = False
    auth_guest_signup_enabled: bool = True
    auth_session_days: int = Field(default=7, ge=1, le=90)
    auth_invite_days: int = Field(default=7, ge=1, le=30)
    # None → tự bật cookie Secure ngoài development/test.
    auth_cookie_secure: bool | None = None

    # Benchmark mỗi job (plan Cloud Studio mục 9): đơn giá GPU/giờ để ước tính chi phí.
    benchmark_gpu_hourly_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    benchmark_label: str | None = Field(default=None, max_length=100)

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
        if self.product_runtime_manifest is not None and self.product_processing_config is None:
            raise ValueError("PRODUCT_RUNTIME_MANIFEST cần PRODUCT_PROCESSING_CONFIG")
        if self.product_runtime_from_workers and self.product_processing_config is None:
            raise ValueError("PRODUCT_RUNTIME_FROM_WORKERS cần PRODUCT_PROCESSING_CONFIG")
        if not self.product_runtime_from_workers and (self.product_processing_config is None) != (
            self.product_runtime_manifest is None
        ):
            raise ValueError("PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST phải khai báo cùng nhau")
        if (self.product_isaac_validation_config is None) != (self.product_isaac_validation_profile is None):
            raise ValueError(
                "PRODUCT_ISAAC_VALIDATION_CONFIG và PRODUCT_ISAAC_VALIDATION_PROFILE phải khai báo cùng nhau"
            )
        if self.artifact_s3_bucket and not (self.artifact_s3_access_key_id and self.artifact_s3_secret_access_key):
            raise ValueError("ARTIFACT_S3_BUCKET cần ARTIFACT_S3_ACCESS_KEY_ID và ARTIFACT_S3_SECRET_ACCESS_KEY")
        if self.app_env in {"staging", "production"} and not self.auth_required:
            raise ValueError("AUTH_REQUIRED phải bật ở staging/production")
        if self.product_fixture_mode and self.app_env in {"staging", "production"}:
            raise ValueError("PRODUCT_FIXTURE_MODE chỉ dùng cho development/test")
        return self

    @property
    def isaac_asset_previews_enabled(self) -> bool:
        """Có phục vụ bản xem trước chuyển từ asset Isaac không: khai rõ thì theo khai báo, không thì chỉ ngoài production."""
        if self.product_isaac_asset_previews is not None:
            return self.product_isaac_asset_previews
        return self.app_env not in {"staging", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
