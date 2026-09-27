"""Job lifecycle errors exposed at the orchestration boundary."""


class JobLifecycleError(RuntimeError):
    """Base job-lifecycle failure."""


class InvalidTransitionError(JobLifecycleError):
    """Raised when a job status transition is not on the allowed transition table."""


class JobNotResolvableError(JobLifecycleError):
    """Raised when a job cannot be recorded as SUCCEEDED because its artifacts do not verify."""
