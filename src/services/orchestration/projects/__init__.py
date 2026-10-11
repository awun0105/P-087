"""Public project/job boundary for the product API (EX-PRODUCT)."""

from src.services.orchestration.projects.errors import (
    JobNotFoundError,
    PrivacyGateBlockedError,
    ProjectNotFoundError,
    ProjectRegistryError,
)
from src.services.orchestration.projects.models import (
    DataOrigin,
    JobCreateInput,
    ProjectCreateInput,
    ProjectRecord,
    SourceRightsAttestation,
)
from src.services.orchestration.projects.privacy import (
    block_reason,
    dispatch_allowed,
    require_dispatch_allowed,
)
from src.services.orchestration.projects.registry import (
    ProjectRegistry,
    get_project_registry,
)

__all__ = [
    "DataOrigin",
    "JobCreateInput",
    "JobNotFoundError",
    "PrivacyGateBlockedError",
    "ProjectCreateInput",
    "ProjectNotFoundError",
    "ProjectRecord",
    "ProjectRegistry",
    "ProjectRegistryError",
    "SourceRightsAttestation",
    "block_reason",
    "dispatch_allowed",
    "get_project_registry",
    "require_dispatch_allowed",
]
