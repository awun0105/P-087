"""Request-local demo runtime; never replace a process-global registry or settings."""

from contextvars import ContextVar
from dataclasses import dataclass

from src.config import Settings
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.projects.registry import ProjectRegistry


@dataclass(frozen=True)
class DemoRuntime:
    settings: Settings
    registry: ProjectRegistry
    actor: UserRecord


demo_runtime: ContextVar[DemoRuntime | None] = ContextVar("demo_runtime", default=None)
