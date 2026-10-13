"""Ma trận quyền của toàn bộ route API.

Mỗi route phải nằm đúng một nhóm: công khai, Guest trở lên (đã đăng nhập) hoặc Reviewer. Route mới thêm vào mà quên
khai báo ở đây sẽ làm test đỏ, nên không thể vô tình để lọt một route không có guard. Ownership của Guest (chỉ sửa
resource của mình) được kiểm riêng trong `test_guest_ownership.py`.
"""

import inspect
import re

import pytest

from src.api import auth
from src.main import app

#: Không cần đăng nhập (đọc cấu hình, thư viện mẫu, các bước đăng nhập/đăng ký).
PUBLIC = {
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("POST", "/auth/register"),
    ("POST", "/auth/register/guest"),
    ("POST", "/processing/evaluate"),
    ("POST", "/processing/suggest"),
    ("GET", "/processing/options"),
    ("GET", "/samples"),
    ("GET", "/samples/{sample_id}"),
    ("GET", "/samples/{sample_id}/files/{name}"),
}

#: Chỉ Reviewer: quản lý thành viên, audit, mốc demo, phát hành, xoá hẳn thùng rác.
REVIEWER = {
    ("GET", "/auth/audit"),
    ("POST", "/auth/invites"),
    ("GET", "/auth/users"),
    ("PATCH", "/auth/users/{user_id}"),
    ("DELETE", "/jobs/{job_id}/demo/baseline"),
    ("POST", "/jobs/{job_id}/demo/publish"),
    ("POST", "/jobs/{job_id}/demo/baseline"),
    ("POST", "/jobs/{job_id}/release"),
    ("POST", "/jobs/{job_id}/review/{action}"),
    ("POST", "/trash/purge"),
}

#: Đã đăng nhập (Guest trở lên). Quyền sửa resource của người khác do `src/api/ownership.py` quyết định.
AUTHENTICATED = {
    ("GET", "/imports"),
    ("POST", "/imports"),
    ("DELETE", "/imports/{import_id}"),
    ("GET", "/imports/{import_id}"),
    ("PATCH", "/imports/{import_id}/camera"),
    ("DELETE", "/imports/{import_id}/camera"),
    ("POST", "/imports/{import_id}/cancel"),
    ("GET", "/imports/{import_id}/content/{filename}"),
    ("POST", "/imports/{import_id}/retry"),
    ("POST", "/input-assemblies"),
    ("POST", "/input-assemblies/uploads"),
    ("GET", "/input-assemblies/uploads/{upload_id}"),
    ("POST", "/input-assemblies/uploads/{upload_id}/stage"),
    ("GET", "/input-assemblies/{assembly_id}"),
    ("PUT", "/input-assemblies/{assembly_id}"),
    ("POST", "/input-assemblies/{assembly_id}/import"),
    ("POST", "/input-assemblies/{assembly_id}/resolve"),
    ("POST", "/input-assemblies/{assembly_id}/run"),
    ("GET", "/jobs/{job_id}"),
    ("GET", "/jobs/{job_id}/anonymization"),
    ("POST", "/jobs/{job_id}/anonymization/accept"),
    ("GET", "/jobs/{job_id}/anonymization/frames/{frame_name}"),
    ("GET", "/jobs/{job_id}/artifacts"),
    ("GET", "/jobs/{job_id}/artifacts/content"),
    ("GET", "/jobs/{job_id}/artifacts/content/{filename}"),
    ("GET", "/jobs/{job_id}/attempts"),
    ("GET", "/jobs/{job_id}/demo"),
    ("POST", "/jobs/{job_id}/demo/reset"),
    ("GET", "/jobs/{job_id}/evaluation"),
    ("GET", "/jobs/{job_id}/evaluation/report.md"),
    ("GET", "/jobs/{job_id}/lidar-overlay"),
    ("GET", "/jobs/{job_id}/metric/assist"),
    ("GET", "/jobs/{job_id}/metric/comparison"),
    ("POST", "/jobs/{job_id}/metric/confirm"),
    ("GET", "/jobs/{job_id}/metric/demo-points"),
    ("POST", "/jobs/{job_id}/metric/lidar"),
    ("POST", "/jobs/{job_id}/metric/preview"),
    ("GET", "/jobs/{job_id}/metric/proposal"),
    ("GET", "/jobs/{job_id}/preview"),
    ("GET", "/jobs/{job_id}/progress"),
    ("GET", "/jobs/{job_id}/release-download"),
    ("POST", "/jobs/{job_id}/release-seal"),
    ("POST", "/jobs/{job_id}/retry"),
    ("GET", "/jobs/{job_id}/review"),
    ("POST", "/jobs/{job_id}/review-decision"),
    ("GET", "/jobs/{job_id}/review-state"),
    ("POST", "/jobs/{job_id}/rgb-lidar-registration/operations"),
    ("GET", "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}"),
    ("POST", "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}/cancel"),
    ("POST", "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}/confirm"),
    ("GET", "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}/inspection"),
    ("POST", "/jobs/{job_id}/rgb-lidar-registration/prepare"),
    ("GET", "/jobs/{job_id}/scene"),
    ("POST", "/jobs/{job_id}/scene/catalog-objects"),
    ("POST", "/jobs/{job_id}/scene/collider"),
    ("POST", "/jobs/{job_id}/scene/collision-source/lidar"),
    ("POST", "/jobs/{job_id}/scene/corrections/merge"),
    ("POST", "/jobs/{job_id}/scene/corrections/reassign"),
    ("POST", "/jobs/{job_id}/scene/edits"),
    ("GET", "/jobs/{job_id}/scene/objectify"),
    ("POST", "/jobs/{job_id}/scene/objectify"),
    ("POST", "/jobs/{job_id}/scene/objectify/cancel"),
    ("POST", "/jobs/{job_id}/scene/objects"),
    ("GET", "/jobs/{job_id}/scene/objects/{object_id}/label-suggestions"),
    ("POST", "/jobs/{job_id}/scene/objects/{object_id}/{action}"),
    ("POST", "/jobs/{job_id}/scene/restore"),
    ("GET", "/jobs/{job_id}/simulation-package"),
    ("POST", "/jobs/{job_id}/simulation-package"),
    ("GET", "/jobs/{job_id}/simulation-package/download"),
    ("GET", "/jobs/{job_id}/stage-views"),
    ("GET", "/jobs/{job_id}/thumbnail.jpg"),
    ("GET", "/jobs/{job_id}/training-recording"),
    ("GET", "/jobs/{job_id}/training-recording.rrd"),
    ("POST", "/jobs/{job_id}/transitions"),
    ("GET", "/jobs/{job_id}/validation"),
    ("GET", "/jobs/{job_id}/validation-runs"),
    ("POST", "/jobs/{job_id}/validation-runs"),
    ("GET", "/jobs/{job_id}/validation-runs/{run_id}"),
    ("GET", "/jobs/{job_id}/validation-runs/{run_id}/artifacts/{artifact_name}"),
    ("POST", "/jobs/{job_id}/validation-runs/{run_id}/cancel"),
    ("POST", "/jobs/{job_id}/validation-runs/{run_id}/retry"),
    ("POST", "/jobs/{job_id}/validation-runs/{run_id}/select"),
    ("GET", "/jobs/{job_id}/walk-collision/{filename}"),
    ("GET", "/projects"),
    ("POST", "/projects"),
    ("GET", "/projects/{project_id}"),
    ("GET", "/projects/{project_id}/jobs"),
    ("POST", "/projects/{project_id}/jobs"),
    ("GET", "/projects/{project_id}/privacy"),
    ("GET", "/scene/catalog"),
    ("GET", "/scene/catalog/{family}/preview.glb"),
    ("GET", "/scenes"),
    ("POST", "/scenes/from-upload"),
    ("DELETE", "/scenes/{project_id}"),
    ("GET", "/trash"),
    ("POST", "/trash/restore"),
    ("GET", "/uploads"),
    ("POST", "/uploads"),
    ("POST", "/uploads/temporary/{action}"),
    ("GET", "/uploads/config"),
    ("POST", "/uploads/direct"),
    ("GET", "/uploads/direct/{upload_id}"),
    ("POST", "/uploads/direct/{upload_id}/abort"),
    ("POST", "/uploads/direct/{upload_id}/complete"),
    ("POST", "/uploads/direct/{upload_id}/urls"),
    ("PUT", "/uploads/{upload_id}/video-preparation/frame-map"),
    ("PUT", "/uploads/{upload_id}/video-preparation/manifest"),
}

#: Quyết định duyệt/phát hành kiểm Reviewer trong handler (cần phiên thật kể cả khi tắt đăng nhập).
HANDLER_REVIEWER = {
    ("POST", "/jobs/{job_id}/review-decision"),
    ("POST", "/jobs/{job_id}/release-seal"),
}

_LEVEL_BY_GUARD = {id(auth.require_contributor): "AUTHENTICATED", id(auth.require_reviewer): "REVIEWER"}
_RANK = {"PUBLIC": 0, "AUTHENTICATED": 1, "REVIEWER": 2}
PREFIX = "/api/v1"


def _contexts():  # noqa: ANN202
    included = [route for route in app.routes if type(route).__name__ == "_IncludedRouter"]
    assert included, "FastAPI đổi cách gắn router: cập nhật cách liệt kê route trong test_role_matrix.py"
    return list(included[0].effective_route_contexts())


def _walk(dependant, found: list[int]) -> None:  # noqa: ANN001
    for sub in dependant.dependencies:
        found.append(id(sub.call))
        _walk(sub, found)


def _level(context) -> str:  # noqa: ANN001
    found: list[int] = []
    _walk(context.dependant, found)
    found += [id(item.dependency) for item in (context.dependencies or [])]
    levels = [_LEVEL_BY_GUARD[call] for call in found if call in _LEVEL_BY_GUARD]
    return max(levels, key=_RANK.__getitem__) if levels else "PUBLIC"


def _actual() -> dict[tuple[str, str], tuple[str, object]]:
    table: dict[tuple[str, str], tuple[str, object]] = {}
    for context in _contexts():
        for method in context.methods - {"HEAD", "OPTIONS"}:
            table[(method, context.path.removeprefix(PREFIX))] = (_level(context), context.endpoint)
    return table


def test_every_route_is_classified_exactly_once() -> None:
    groups = {"PUBLIC": PUBLIC, "AUTHENTICATED": AUTHENTICATED, "REVIEWER": REVIEWER}
    declared = [route for routes in groups.values() for route in routes]
    assert len(declared) == len(set(declared)), "route nằm trong nhiều nhóm"
    actual = _actual()
    assert set(actual) == set(declared), {
        "route mới chưa khai báo": sorted(set(actual) - set(declared)),
        "khai báo nhưng không còn route": sorted(set(declared) - set(actual)),
    }


@pytest.mark.parametrize("group", ["PUBLIC", "AUTHENTICATED", "REVIEWER"])
def test_each_route_has_the_declared_guard(group: str) -> None:
    expected = {"PUBLIC": PUBLIC, "AUTHENTICATED": AUTHENTICATED, "REVIEWER": REVIEWER}[group]
    actual = _actual()
    wrong = {route: actual[route][0] for route in expected if route in actual and actual[route][0] != group}
    assert wrong == {}


def test_review_decision_and_release_seal_check_reviewer_in_the_handler() -> None:
    actual = _actual()
    for route in HANDLER_REVIEWER:
        assert route in AUTHENTICATED
        assert re.search(r"_reviewer\(", inspect.getsource(actual[route][1])), f"{route} phải gọi _reviewer()"


def test_mutating_routes_are_never_public_except_login_flow_and_stateless_calculation() -> None:
    allowed = {
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/register"),
        ("POST", "/auth/register/guest"),
        ("POST", "/processing/evaluate"),
        ("POST", "/processing/suggest"),
    }
    mutating = {route for route in PUBLIC if route[0] in {"POST", "PUT", "PATCH", "DELETE"}}
    assert mutating == allowed
