"""Artifact-store errors exposed at the orchestration boundary."""


class ArtifactStoreError(RuntimeError):
    """Base artifact-store failure."""


class InvalidArtifactUriError(ArtifactStoreError):
    """Raised when a logical artifact URI is malformed or unsafe."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when a referenced artifact does not exist."""


class ArtifactAlreadyExistsError(ArtifactStoreError):
    """Raised when immutable publication targets an existing artifact."""


class ArtifactChecksumError(ArtifactStoreError):
    """Raised when artifact bytes do not match their declared SHA-256."""


class ArtifactSchemaError(ArtifactStoreError):
    """Raised when a JSON artifact does not validate against its contract."""


class ArtifactTooLargeError(ArtifactStoreError):
    """Streamed payload vượt giới hạn cấu hình; không có file nào được publish."""
