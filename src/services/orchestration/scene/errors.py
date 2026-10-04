"""Scene revision errors exposed at the orchestration boundary."""


class SceneError(RuntimeError):
    """Base scene-revision failure."""


class SceneNotAvailableError(SceneError):
    """Job chưa publish SceneIR; không được thay bằng scene fixture."""


class SceneObjectNotFoundError(SceneError):
    """Raised when an edit targets an object id that is not in the revision."""


class SceneRevisionConflictError(SceneError):
    """Raised when an edit is based on a revision that is no longer current.

    Optimistic concurrency: hai tab cùng sửa một scene thì tab sau phải bị từ
    chối, không được ghi đè thay đổi của tab trước.
    """


class SceneEditRejectedError(SceneError):
    """Raised when a command is well-formed but cannot be applied to the revision."""
