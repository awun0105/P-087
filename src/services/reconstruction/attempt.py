"""Namespace nội bộ cho retry; giữ job identity và artifact của attempt trước."""

from typing import Annotated

from pydantic import Field, TypeAdapter

from src.models.contracts.artifacts import ArtifactUri, ContractModel

PathSegment = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class PublicationNamespace(ContractModel):
    """Attempt optional giữ URI legacy cho caller cũ, worker mới luôn khai báo."""

    job_id: PathSegment
    attempt_id: PathSegment | None = None

    def uri(self, stage: str, name: str) -> str:
        """Không cho path traversal hoặc đổi job qua tên payload."""
        suffix = f"attempts/{self.attempt_id}/" if self.attempt_id is not None else ""
        return TypeAdapter(ArtifactUri).validate_python(f"artifact://jobs/{self.job_id}/{suffix}{stage}/{name}")

    def provenance(self) -> dict[str, str]:
        """Attempt identity bổ sung; không sửa schema shared ArtifactRef."""
        return {} if self.attempt_id is None else {"attempt_id": self.attempt_id}
