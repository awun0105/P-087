"""Contract metadata dùng chung cho Real2Sim artifacts."""

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue


def _validate_artifact_uri(value: str) -> str:
    """Chỉ chấp nhận logical URI, không chấp nhận local filesystem path."""
    prefix = "artifact://jobs/"
    if not value.startswith(prefix) or "\\" in value:
        raise ValueError("artifact URI must use artifact://jobs/<job_id>/<artifact-path>")
    relative = value.removeprefix(prefix)
    raw_parts = relative.split("/")
    parts = PurePosixPath(relative).parts
    if len(parts) < 2 or any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("artifact URI must contain a safe job ID and artifact path")
    if relative.startswith("/") or "//" in relative:
        raise ValueError("artifact URI cannot contain absolute or empty path segments")
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) is None for part in raw_parts):
        raise ValueError("artifact URI contains an unsupported path segment")
    return value


Checksum = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1)]
ArtifactUri = Annotated[str, Field(min_length=1), AfterValidator(_validate_artifact_uri)]
SchemaVersion = Annotated[str, Field(pattern=r"^1\.0$")]
JsonObject = dict[str, JsonValue]


class ArtifactDataClass(StrEnum):
    """Explicit usage class; a logical URI does not grant product access."""

    PRODUCT_INPUT = "product_input"
    DERIVED = "derived"
    GROUND_TRUTH = "ground_truth"
    EVALUATION_ONLY = "evaluation_only"


ProductDataClass = Literal[ArtifactDataClass.PRODUCT_INPUT, ArtifactDataClass.DERIVED]


class ContractModel(BaseModel):
    """Base model nghiêm ngặt cho shared contracts giữa các track."""

    model_config = ConfigDict(extra="forbid")


class ArtifactRef(ContractModel):
    """Tham chiếu artifact bằng URI và checksum thay vì local path."""

    artifact_type: Identifier
    schema_version: SchemaVersion
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    data_class: ArtifactDataClass
    producer_stage: Identifier
    job_id: Identifier | None = None
    source_provenance: JsonObject | None = None


class ProductArtifactRef(ArtifactRef):
    """Artifact reference allowed in product prediction/runtime boundaries."""

    data_class: ProductDataClass
