"""Scene revision errors exposed at the orchestration boundary."""


class SceneError(RuntimeError):
    """Base scene-revision failure."""


class SceneNotAvailableError(SceneError):
    """Job chưa publish SceneIR; không được thay bằng scene fixture."""


class SceneHeadNotReadyError(SceneNotAvailableError):
    """SceneIR có trên đĩa nhưng chưa có head đã commit (chưa chuẩn bị, hoặc đang ghi).

    Không phải "không tìm thấy": API trả 409 với `user_message` dành cho người dùng. Thông điệp vận hành (lệnh
    repair) nằm trong `str(error)` để ghi log và không bao giờ hiện ra UI.
    """

    def __init__(self, operator_message: str, user_message: str) -> None:
        super().__init__(operator_message)
        self.user_message = user_message


class SceneObjectNotFoundError(SceneError):
    """Raised when an edit targets an object id that is not in the revision."""


class SceneRevisionConflictError(SceneError):
    """Raised when an edit is based on a revision that is no longer current.

    Optimistic concurrency: hai tab cùng sửa một scene thì tab sau phải bị từ
    chối, không được ghi đè thay đổi của tab trước.
    """


class SceneEditRejectedError(SceneError):
    """Raised when a command is well-formed but cannot be applied to the revision."""
