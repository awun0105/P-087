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
    CapsuleFootprint,
    DependencyOrigin,
    DepthFrameSet,
    GeometryArtifact,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
    ReconstructionBundle,
    SeedDecision,
    VisualArtifact,
    VoxelGridSummary,
)
from src.models.contracts.release import (
    ApprovalRecord,
    ReleaseManifest,
    SceneRevisionRecord,
)
from src.models.contracts.scene import (
    ColliderSpec,
    SceneIR,
    SceneObject,
    SourceCollisionMembership,
    SourceCollisionRegion,
)
from src.models.contracts.validation import (
    CandidatePackage,
    EvaluationReport,
    PreflightReport,
    ValidationReport,
)
from src.models.contracts.validation_run import (
    ValidationConfig,
    ValidationRunRecord,
    ValidationRunSelection,
)

__all__ = [
    "AlignmentRecord",
    "ApprovalRecord",
    "ArtifactRef",
    "ArtifactDataClass",
    "CandidatePackage",
    "CapsuleFootprint",
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
    "GeometryArtifact",
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
    "SourceCollisionMembership",
    "SourceCollisionRegion",
    "SceneRevisionRecord",
    "StageId",
    "StageStatus",
    "Transform",
    "ValidationReport",
    "ValidationConfig",
    "ValidationRunRecord",
    "ValidationRunSelection",
    "SeedDecision",
    "VoxelGridSummary",
    "VisualArtifact",
]
