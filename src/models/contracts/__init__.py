"""Shared Real2Sim artifact contracts for every execution track."""

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, Transform
from src.models.contracts.manifests import (
    ExecutionError,
    InputConfiguration,
    InputManifest,
    JobManifest,
    JobStatus,
    PrivacyValidationReport,
    RuntimeManifest,
    StageId,
    StageStatus,
)
from src.models.contracts.reconstruction import (
    AlignmentRecord,
    DependencyOrigin,
    DepthFrameSet,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
    ReconstructionBundle,
    VisualArtifact,
)
from src.models.contracts.release import (
    ApprovalRecord,
    ReleaseManifest,
    SceneRevisionRecord,
)
from src.models.contracts.scene import ColliderSpec, SceneIR, SceneObject
from src.models.contracts.validation import (
    CandidatePackage,
    EvaluationReport,
    PreflightReport,
    ValidationReport,
)

__all__ = [
    "AlignmentRecord",
    "ApprovalRecord",
    "ArtifactRef",
    "ArtifactDataClass",
    "CandidatePackage",
    "ColliderSpec",
    "ContractModel",
    "CoordinateSystem",
    "DependencyOrigin",
    "DepthFrameSet",
    "EvaluationReport",
    "ExecutionError",
    "InputConfiguration",
    "InputManifest",
    "JobManifest",
    "JobStatus",
    "LiDARGeometryArtifact",
    "MetricScale",
    "PreprocessingDependency",
    "PreprocessingProvenance",
    "PreflightReport",
    "PrivacyValidationReport",
    "ProductArtifactRef",
    "ReconstructionBundle",
    "ReleaseManifest",
    "RuntimeManifest",
    "SceneIR",
    "SceneObject",
    "SceneRevisionRecord",
    "StageId",
    "StageStatus",
    "Transform",
    "ValidationReport",
    "VisualArtifact",
]
