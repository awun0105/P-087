"""Server-only lifecycle policy. No implicit spending approval."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GpuSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GPU_", extra="ignore", populate_by_name=True)

    autoprov_enabled: bool = Field(default=False, validation_alias="GPU_AUTOPROVISION_ENABLED")
    autoprov_dry_run: bool = Field(default=True, validation_alias="GPU_AUTOPROVISION_DRY_RUN")
    deployment_id: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]{0,64}$")
    runpod_api_key: SecretStr | None = Field(default=None, validation_alias="RUNPOD_API_KEY")
    release_catalog: Path | None = None
    worker_env_file: Path | None = None
    # Exactly one managed pod; an int field (not Literal[1]) so the documented env value "1" parses.
    max_pods: int = Field(default=1, ge=1, le=1)
    poll_seconds: float = Field(default=15, ge=1, le=300)
    idle_seconds: int = Field(default=240, ge=1)
    startup_timeout_seconds: int = Field(default=1200, ge=60)
    max_lifetime_seconds: int = Field(default=43200, ge=60)
    max_provision_attempts: int = Field(default=3, ge=1, le=10)
    max_hourly_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    project_budget_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    container_disk_gb: int = Field(default=100, ge=10)
    registry_auth_id: str | None = None
    cloud_type: Literal["SECURE", "COMMUNITY"] = "SECURE"
    outage_policy: Literal["blocked", "operator_accepted", "external_watchdog"] = "blocked"
    outage_policy_reference: str = ""
    cpu_lane_enabled: bool = False
    cpu_lane_qualification_reference: str = ""
    cpu_lane_ram_gb: float = Field(default=2, gt=0)

    @model_validator(mode="after")
    def require_approved_configuration(self) -> "GpuSettings":
        if self.cpu_lane_enabled and not self.cpu_lane_qualification_reference.strip():
            raise ValueError("CPU lane requires a qualification reference before enablement")
        if self.autoprov_enabled:
            if not all((self.deployment_id, self.release_catalog, self.worker_env_file, self.runpod_api_key)):
                raise ValueError("GPU provisioning requires deployment, catalog, worker env and provider credential")
            if self.max_hourly_usd is None or self.project_budget_usd is None:
                raise ValueError("GPU provisioning requires explicit hourly and project spending limits")
            if not self.autoprov_dry_run and (
                self.outage_policy == "blocked" or not self.outage_policy_reference.strip()
            ):
                raise ValueError("Live provisioning requires an accepted control-plane outage policy reference")
        return self
