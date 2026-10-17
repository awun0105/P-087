"""So mirror TypeScript trong `frontend/src/lib/contracts/api.ts` với Pydantic thật.

Đây là cơ chế chống drift: trước đây mirror được gõ tay nên lệch 16 field và 7 enum
mà không ai biết, và TypeScript không bắt được vì union bị nới rộng thành `string`.

Không thay `frontend/src/lib/contracts/api.ts` bằng codegen: backend là Pydantic,
frontend là TypeScript, không có ngôn ngữ chung. Thay vào đó, script này so từng
enum và field rồi fail, để CI bắt được lệch ngay tại lần đổi.

Chạy: `python -m scripts.check_contract_mirror`
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "frontend/src/lib/contracts/api.ts"

sys.path.insert(0, str(ROOT))

from pydantic import BaseModel  # noqa: E402

from src.models.contracts.artifacts import ArtifactDataClass  # noqa: E402
from src.models.contracts.coordinates import Transform  # noqa: E402
from src.models.contracts.floor_model import FloorFitEvidence  # noqa: E402
from src.models.contracts.manifests import (  # noqa: E402
    JobStatus,
    PrivacyResult,
    StageId,
    StageStatus,
)
from src.models.contracts.object_membership import ObjectRegionCommand, RegionBox  # noqa: E402
from src.models.contracts.scene import ColliderSpec, SceneEnvironment, SceneObject, SourceCollisionRegion  # noqa: E402
from src.services.orchestration.jobs.progress import StageProgress  # noqa: E402
from src.services.orchestration.jobs.transitions import ALLOWED_TRANSITIONS  # noqa: E402

# TS constant -> giá trị backend tương ứng
ENUM_MIRRORS: dict[str, list[str]] = {
    "STAGE_IDS": [item.value for item in StageId],
    "STAGE_STATUSES": [item.value for item in StageStatus],
    "ARTIFACT_DATA_CLASSES": [item.value for item in ArtifactDataClass],
    "JOB_STATUSES": [item.value for item in JobStatus],
    "PRIVACY_RESULTS": [item.value for item in PrivacyResult],
}

# TS interface -> Pydantic model
MODEL_MIRRORS: list[tuple[str, type[BaseModel]]] = [
    ("FloorFitEvidence", FloorFitEvidence),
    ("SceneObject", SceneObject),
    ("SourceCollisionRegion", SourceCollisionRegion),
    ("SceneEnvironment", SceneEnvironment),
    ("ColliderSpec", ColliderSpec),
    ("Transform", Transform),
    ("RegionBox", RegionBox),
    ("ObjectRegionCommand", ObjectRegionCommand),
]

PLACEHOLDERS = {
    "ArtifactRef",
    "ProductArtifactRef",
    "SceneIR",
    "VisualBinding",
    "ExecutionError",
    "SceneObjectCommand",
}


def _read() -> str:
    if not MIRROR.is_file():
        raise SystemExit(f"không tìm thấy {MIRROR}")
    return MIRROR.read_text(encoding="utf-8")


def _ts_enum_values(source: str, name: str) -> list[str] | None:
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.S)
    if not match:
        return None
    return re.findall(r'"([^"]+)"', match.group(1))


def _ts_interface_fields(source: str, name: str) -> set[str] | None:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", source, re.S)
    if not match:
        return None
    return {field for field in re.findall(r"^\s{2}(\w+)\??:", match.group(1), re.M)}


def _check_enums(source: str) -> list[str]:
    problems = []
    for name, expected in ENUM_MIRRORS.items():
        actual = _ts_enum_values(source, name)
        if actual is None:
            problems.append(f"{name}: không tìm thấy const trong api.ts")
        elif actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            problems.append(f"{name}: thiếu {missing or '—'} | thừa {extra or '—'} | sai thứ tự")
    return problems


def _check_models(source: str, mirrors: list[tuple[str, type[BaseModel]]] = MODEL_MIRRORS) -> list[str]:
    problems = []
    for name, model in mirrors:
        expected = set(model.model_fields)
        actual = _ts_interface_fields(source, name)
        if actual is None:
            problems.append(f"{name}: không tìm thấy interface trong mirror TypeScript")
            continue
        for missing in sorted(expected - actual):
            problems.append(f"{name}.{missing}: có trong Pydantic, thiếu ở TypeScript")
        for extra in sorted(actual - expected):
            problems.append(f"{name}.{extra}: có ở TypeScript, không có trong Pydantic")
    return problems


def _check_transitions(source: str) -> list[str]:
    """Bảng transition là hợp đồng với backend; lệch thì UI cho phép chuyển trạng thái
    mà backend từ chối, và ngược lại là nút chết cho người dùng."""
    problems = []
    match = re.search(
        r"export const JOB_TRANSITIONS: Record<JobStatus, readonly JobStatus\[\]> = \{(.*?)\n\};",
        source,
        re.S,
    )
    if not match:
        return ["JOB_TRANSITIONS: không tìm thấy trong api.ts"]
    for status, allowed in re.findall(r"(\w+): \[([^\]]*)\]", match.group(1)):
        actual = set(re.findall(r'"([^"]+)"', allowed))
        expected = {item.value for item in ALLOWED_TRANSITIONS[JobStatus(status)]}
        if actual != expected:
            problems.append(f"JOB_TRANSITIONS.{status}: TS {sorted(actual)} | backend {sorted(expected)}")
    return problems


def _check_no_widening(source: str) -> list[str]:
    """Union bị nới thành `string` là nguyên nhân gốc khiến TypeScript không bắt lỗi."""
    problems = []
    # `ArtifactRef.producer_stage` là `Identifier` tự do ở Pydantic nên `string` là
    # đúng; chỉ các field có enum/Literal mới bị cấm nới.
    for field in (
        "stage_id",
        "current_stage",
        "up_axis",
        "handedness",
        "unit",
        "result",
        "decision",
        "scope",
        "source_type",
    ):
        for match in re.finditer(rf"^\s{{2}}{field}\??: ([^;]+);", source, re.M):
            declared = match.group(1).strip()
            if declared in {"string", "string | null"}:
                problems.append(f"{field}: khai {declared!r} — hẹp lại theo enum backend")
    return problems


def main() -> int:
    source = _read()
    problems = _check_enums(source) + _check_models(source) + _check_transitions(source) + _check_no_widening(source)
    studio = (ROOT / "frontend/src/lib/contracts/studio.ts").read_text(encoding="utf-8")
    problems += _check_models(studio, [("StageProgress", StageProgress)])
    if problems:
        print("FAIL — mirror TypeScript lệch với Pydantic:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nSửa cả hai bên rồi chạy lại. Đừng nới union để cho TypeScript im lặng.")
        return 1
    print(
        f"PASS — {len(ENUM_MIRRORS)} enum, {len(MODEL_MIRRORS) + 1} model khớp Pydantic; "
        "không có union nào bị nới thành `string`."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
