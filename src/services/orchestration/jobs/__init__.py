"""Public job-lifecycle boundary for the product API (EX-PRODUCT)."""

from src.services.orchestration.jobs.errors import (
    InvalidTransitionError,
    JobLifecycleError,
    JobNotResolvableError,
)
from src.services.orchestration.jobs.models import (
    JobAttemptRecord,
    JobDetail,
    TransitionRequest,
)
from src.services.orchestration.jobs.service import JobLifecycle
from src.services.orchestration.jobs.store import JobArtifactStore
from src.services.orchestration.jobs.transitions import (
    ALLOWED_TRANSITIONS,
    CLOSING_STATUSES,
    TERMINAL_STATUSES,
    can_transition,
    legal_targets,
    require_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "CLOSING_STATUSES",
    "TERMINAL_STATUSES",
    "InvalidTransitionError",
    "JobArtifactStore",
    "JobAttemptRecord",
    "JobDetail",
    "JobLifecycle",
    "JobLifecycleError",
    "JobNotResolvableError",
    "TransitionRequest",
    "can_transition",
    "legal_targets",
    "require_transition",
]
