"""Preflight inspection and audit subsystem for EX-SIM."""

from src.models.contracts.validation import PreflightReport, PreflightRule, PreflightRuleId, RuleResult
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.preflight.rules import (
    check_collider_presence,
    check_collision_source_coverage,
    check_metric_scale,
    check_object_bounds,
    check_object_confirmation,
    check_required_artifacts,
    check_transforms,
)

__all__ = [
    "PreflightReport",
    "PreflightRule",
    "PreflightRuleId",
    "RuleResult",
    "run_preflight",
    "check_metric_scale",
    "check_collider_presence",
    "check_transforms",
    "check_object_bounds",
    "check_object_confirmation",
    "check_required_artifacts",
    "check_collision_source_coverage",
]
