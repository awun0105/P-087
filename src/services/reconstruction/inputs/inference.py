"""Suy khai báo từ bằng chứng nằm sẵn trong chính file người dùng nộp. Hàm thuần, không I/O.

Nguyên tắc: chỉ suy khi bằng chứng cho đúng một đáp án; mơ hồ thì trả None để hệ thống hỏi người dùng.
Mọi giá trị suy ra được ghi `provenance="estimated"` kèm tên phương pháp, nên luôn truy vết và sửa được.

Không suy (không có bằng chứng trong file): cùng một cảnh, quan hệ đồng hồ camera ↔ LiDAR, chiều quỹ đạo,
đơn vị toạ độ (thang đo của một đám mây không phân biệt được m với cm) và tên frame LiDAR/camera.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.models.contracts.input_assembly import (
    EvidenceProvenance,
    EvidenceValue,
    InputAssemblyDeclarations,
    InputAssetFormat,
    InputBinding,
    InputRole,
    StagedInputFile,
    TimestampUnit,
)
from src.services.reconstruction.inputs.input_probe import InputProbe

#: Tên phương pháp ghi vào `EvidenceValue.method` của giá trị suy ra.
UNIT_METHOD = "timestamp_rate_window_v1"

#: Dải tần số lấy mẫu *khả dĩ* (Hz), áp cho cả camera và LiDAR: từ một mẫu mỗi giờ đến 1 kHz. Dải này rộng hơn
#: 1000 lần nên đơn vị liền kề thường cùng cho tần số khả dĩ; khi đó dữ liệu mơ hồ thật sự (5 đơn vị mỗi mẫu là 0,2 Hz
#: theo giây hay 200 Hz theo mili giây) và hệ thống phải hỏi, không được chọn cái "đẹp hơn". Hệ quả có chủ ý: chỉ suy
#: được khi đơn vị thô hơn cho tần số vô lý, tức thực tế là giây ở tần số trên 1 Hz (LiDAR 5-20 Hz, camera
#: 15-60 Hz, dữ liệu như TorWIC). Dữ liệu mili/micro/nano giây gần như luôn được hỏi lại; đó là cái giá của việc không đoán sai.
_RATE_WINDOW_HZ: tuple[float, float] = (1.0 / 3600.0, 1000.0)
#: Cần ít nhất hai khoảng cách để coi tần số là đo được; một khoảng duy nhất không chứng minh tần số đều.
_MIN_SAMPLES = 3
_SECONDS_PER_UNIT: dict[TimestampUnit, float] = {
    TimestampUnit.SECONDS: 1.0,
    TimestampUnit.MILLISECONDS: 1e-3,
    TimestampUnit.MICROSECONDS: 1e-6,
    TimestampUnit.NANOSECONDS: 1e-9,
}
#: Thời gian của file timestamp không được dài hơn video quá mức này (video quay xong mới có timestamp).
_DURATION_SLACK = 1.05
_DURATION_SLACK_SECONDS = 1.0


@dataclass(frozen=True)
class UnitInference:
    unit: TimestampUnit
    rate_hz: float
    span_seconds: float


def infer_timestamp_unit(
    *,
    count: int | None,
    first: float | None,
    last: float | None,
    video_duration_seconds: float | None = None,
) -> UnitInference | None:
    """Đơn vị của một file timestamp từ tần số lấy mẫu trung bình, hoặc None khi không suy được duy nhất.

    Dữ liệu thực tế (ví dụ TorWIC) dùng thời gian tương đối bắt đầu từ 0, nên độ lớn của số không nói lên đơn vị;
    tần số thì có. Chỉ trả đơn vị khi đúng MỘT đơn vị cho tần số khả dĩ (xem `_RATE_WINDOW_HZ`). `video_duration_seconds`
    (nếu biết) loại thêm đáp án khiến file dài hơn video.
    """
    if count is None or first is None or last is None or count < _MIN_SAMPLES:
        return None
    if not (math.isfinite(first) and math.isfinite(last)) or last <= first:
        return None
    low, high = _RATE_WINDOW_HZ
    step = (last - first) / (count - 1)
    matches: list[UnitInference] = []
    for unit, scale in _SECONDS_PER_UNIT.items():
        rate = 1.0 / (step * scale)
        if low <= rate <= high:
            matches.append(UnitInference(unit=unit, rate_hz=rate, span_seconds=(last - first) * scale))
    if len(matches) != 1:
        return None
    found = matches[0]
    if video_duration_seconds is not None and found.span_seconds > (
        video_duration_seconds * _DURATION_SLACK + _DURATION_SLACK_SECONDS
    ):
        return None
    return found


def infer_timestamp_roles(
    files: Sequence[StagedInputFile],
    probes: Mapping[str, InputProbe],
    *,
    bound_file_ids: set[str],
    pose_count: int | None,
    scan_count: int | None,
) -> dict[InputRole, str]:
    """Gán vai trò cho file `timestamp_rows` chưa được bind, theo số dòng khớp số pose hoặc số scan.

    - Có quỹ đạo: chỉ file có đúng số dòng bằng số pose mới là thời điểm frame RGB (luồng quỹ đạo có sẵn
      cần một dòng cho mỗi pose). Khi đó thời điểm scan không cần nên không gán.
    - Không có quỹ đạo: file có đúng số dòng bằng số scan là thời điểm scan LiDAR (luồng ước lượng).
    Chỉ gán khi khớp đúng một file; nhiều file cùng khớp thì để người dùng chọn.
    """
    candidates = [
        item
        for item in files
        if item.observed_format == InputAssetFormat.TIMESTAMP_ROWS
        and item.file_id not in bound_file_ids
        and probes.get(item.file_id) is not None
        and probes[item.file_id].record_count
    ]
    if pose_count is not None:
        matching = [item for item in candidates if probes[item.file_id].record_count == pose_count]
        return {InputRole.RGB_FRAME_TIMES: matching[0].file_id} if len(matching) == 1 else {}
    if scan_count is not None and scan_count >= 2:
        matching = [item for item in candidates if probes[item.file_id].record_count == scan_count]
        return {InputRole.LIDAR_SCAN_TIMES: matching[0].file_id} if len(matching) == 1 else {}
    return {}


def timestamp_files_by_role(
    files: Sequence[StagedInputFile],
    probes: Mapping[str, InputProbe],
    bindings: Sequence[InputBinding],
) -> dict[InputRole, str]:
    """File thời điểm frame RGB / thời điểm scan LiDAR: theo bind tường minh, rồi suy theo số dòng.

    Dùng chung cho resolver (ứng viên mang binding suy ra) và cho bước ghi lời khai (đơn vị theo đúng file),
    nên hai nơi không thể hiểu khác nhau file nào là file nào.
    """
    explicit: dict[InputRole, list[str]] = {}
    for binding in bindings:
        explicit.setdefault(binding.role, []).extend(binding.file_ids)
    result: dict[InputRole, str] = {}
    for role in (InputRole.RGB_FRAME_TIMES, InputRole.LIDAR_SCAN_TIMES):
        if len(explicit.get(role, [])) == 1:
            result[role] = explicit[role][0]
    if InputRole.RGB_FRAME_TIMES not in result:
        bound_elsewhere = {file_id for ids in explicit.values() for file_id in ids}
        legacy = [
            item.file_id
            for item in files
            if item.observed_format == InputAssetFormat.RGB_FRAME_TIMES and item.file_id not in bound_elsewhere
        ]
        if len(legacy) == 1:
            result[InputRole.RGB_FRAME_TIMES] = legacy[0]

    trajectories = explicit.get(InputRole.SENSOR_TRAJECTORY) or [
        item.file_id
        for item in files
        if item.observed_format == InputAssetFormat.TUM_TRAJECTORY
        and item.file_id not in explicit.get(InputRole.CAMERA_TRAJECTORY, [])
    ]
    pose_count = probes[trajectories[0]].record_count if len(trajectories) == 1 and trajectories[0] in probes else None
    # Mọi file quỹ đạo TUM (kể cả quỹ đạo camera): số dòng của chúng cũng là số dòng đáng ngờ khi suy vai trò scan.
    trajectory_row_counts = {
        probes[item.file_id].record_count
        for item in files
        if item.observed_format == InputAssetFormat.TUM_TRAJECTORY
        and item.file_id in probes
        and probes[item.file_id].record_count
    }
    scans = explicit.get(InputRole.LIDAR_SCAN) or [
        item.file_id
        for item in files
        if item.observed_format in {InputAssetFormat.POINT_CLOUD_PCD, InputAssetFormat.POINT_CLOUD_PLY}
    ]
    bound = {file_id for ids in explicit.values() for file_id in ids} | set(result.values())
    inferred = infer_timestamp_roles(
        files,
        probes,
        bound_file_ids=bound,
        pose_count=pose_count if InputRole.RGB_FRAME_TIMES not in result else None,
        # Có file quỹ đạo cùng số dòng với số scan thì file timestamp cùng số dòng có thể là của frame RGB: hỏi.
        scan_count=(
            len(scans)
            if InputRole.LIDAR_SCAN_TIMES not in result
            and pose_count is None
            and len(scans) not in trajectory_row_counts
            else None
        ),
    )
    for role, file_id in inferred.items():
        result.setdefault(role, file_id)
    return result


def enrich_timestamp_units(
    declarations: InputAssemblyDeclarations,
    files: Sequence[StagedInputFile],
    probes: Mapping[str, InputProbe],
    bindings: Sequence[InputBinding],
    *,
    video_duration_seconds: float | None,
) -> InputAssemblyDeclarations:
    """Điền đơn vị timestamp còn thiếu bằng giá trị suy ra (`estimated`).

    Không đè giá trị người dùng đã khai hoặc đã xác minh. Giá trị `estimated` cũ được tính lại theo dữ liệu hiện
    tại và bị bỏ nếu không còn suy được, để một ước lượng đã lỗi thời không tồn tại mãi qua các lần sửa assembly.
    """
    if declarations.timestamp_unit is not None:
        return declarations  # lời khai dùng chung kiểu cũ đã phủ cả hai cảm biến
    roles = timestamp_files_by_role(files, probes, bindings)
    updates: dict[str, EvidenceValue[TimestampUnit] | None] = {}
    for role, field in (
        (InputRole.RGB_FRAME_TIMES, "rgb_timestamp_unit"),
        (InputRole.LIDAR_SCAN_TIMES, "lidar_timestamp_unit"),
    ):
        current = getattr(declarations, field)
        if current is not None and current.provenance != EvidenceProvenance.ESTIMATED:
            continue
        file_id = roles.get(role)
        found = None
        if file_id is not None and file_id in probes:
            probe = probes[file_id]
            found = infer_timestamp_unit(
                count=probe.record_count,
                first=probe.first_timestamp,
                last=probe.last_timestamp,
                video_duration_seconds=video_duration_seconds if role == InputRole.RGB_FRAME_TIMES else None,
            )
        if found is not None:
            updates[field] = EvidenceValue(
                value=found.unit, provenance=EvidenceProvenance.ESTIMATED, method=UNIT_METHOD
            )
        elif current is not None:
            updates[field] = None
    return declarations.model_copy(update=updates) if updates else declarations
