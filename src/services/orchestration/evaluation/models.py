"""Model của bảng đánh giá một job. Product-level, không phải shared contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: `self_check`: đo từ chính dữ liệu của scene, có cho mọi scene. `reference`: so với dữ liệu đối chứng (chỉ dataset).
MetricSource = Literal["self_check", "reference"]
#: Chỉ gán khi có ngưỡng được chấp nhận trong repo (cấu hình pipeline, REC-06…); không có ngưỡng thì để trống.
Verdict = Literal["ok", "warn", "fail"]
GroupStatus = Literal["measured", "pending", "unavailable"]


class Metric(BaseModel):
    """Một chỉ số: giá trị đo được, ý nghĩa của nó và (nếu có) kết luận theo ngưỡng."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    #: None = chưa đo được; khi đó `display` nêu lý do, không điền số ước lượng.
    value: float | int | str | None
    unit: str | None = None
    display: str
    meaning: str
    source: MetricSource = "self_check"
    verdict: Verdict | None = None
    #: Ngưỡng dùng cho `verdict` và nơi định nghĩa nó.
    threshold: str | None = None


class StageEvaluation(BaseModel):
    """Chỉ số của một bước pipeline (hoặc nhóm tổng hợp như hệ thống)."""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    title: str
    #: `pending`: bước chưa chạy xong. `unavailable`: bước xong nhưng artifact không đọc được.
    status: GroupStatus
    note: str | None = None
    metrics: list[Metric] = []


class JobEvaluation(BaseModel):
    """Bảng đánh giá của một scene tại thời điểm tạo; tính lại mỗi lần đọc từ artifact bất biến."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    project_id: str
    scene_name: str
    job_status: str
    scene_revision: str | None
    generated_at: datetime
    groups: list[StageEvaluation]
