"""Project and job registry errors exposed at the orchestration boundary."""


class ProjectRegistryError(RuntimeError):
    """Base project-registry failure."""


class ProjectNotFoundError(ProjectRegistryError):
    """Raised when a project id is not present in the registry."""


class JobNotFoundError(ProjectRegistryError):
    """Raised when a job id is not present in the registry."""


class PrivacyGateBlockedError(ProjectRegistryError):
    """Raised when privacy state forbids dispatching a job into the pipeline."""
