"""Cầu nối tọa độ LiDAR gốc → canonical `world` theo quyết định đã ghi của owner.

Output REC-07 giữ nguyên `coordinate_status="UNVERIFIED"` vì bytes vẫn ở frame gốc
của dataset. Chỉ khi có một bản ghi quyết định tường minh (file cấu hình dataset, có
checksum bằng chứng đo đạc) thì REC-08 mới khai phép biến đổi sang `world`.

Nguồn từng quyết định được ghi rõ: handedness là **owner decision** (không có datasheet
xác nhận), up-axis/đơn vị là **đo đạc**, quy tắc gốc là **owner decision** (dịch sàn về
z=0 để khớp analytic ground plane của EX-SIM). Số liệu cụ thể nằm trong file cấu hình,
không nhúng vào `src/` (REC-06.md, commit 01305c9).
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier
from src.models.contracts.coordinates import Transform


class BridgeEvidence(ContractModel):
    """Một file bằng chứng (ảnh/đo đạc) được tham chiếu bằng checksum."""

    name: str = Field(min_length=1, max_length=200)
    checksum: Checksum


class CoordinateBridgeDecision(ContractModel):
    """Quyết định chuyển frame gốc của một dataset sang canonical `world`."""

    schema_version: Literal["1.0"] = "1.0"
    dataset: Identifier
    #: Nhãn frame mà manifest REC-07 ghi (`request.target_frame`), vd "world" của map GT.
    rec07_target_frame: Identifier
    #: Tên tường minh của frame gốc sau cầu nối (không trùng canonical `world`).
    source_frame: Identifier
    unit: Literal["meter"] = "meter"
    up_axis: Literal["Z"] = "Z"
    handedness: Literal["right"] = "right"
    handedness_source: Literal["owner_decision"]
    up_axis_source: Literal["measured"]
    origin_rule: Literal["floor_to_zero"]
    origin_rule_source: Literal["owner_decision"]
    #: Cao độ sàn đo được trong frame gốc (mét); phép biến đổi dịch về z=0.
    floor_z_in_source_m: float = Field(ge=-10, le=10, allow_inf_nan=False)
    decided_by: str = Field(min_length=1, max_length=100)
    decision_ref: str = Field(min_length=1, max_length=300)
    evidence: list[BridgeEvidence] = Field(min_length=1)

    def transform(self) -> Transform:
        """`world_from_source`: chỉ tịnh tiến theo Z (thuận tay, Z-up nên không xoay)."""
        if self.source_frame == "world":
            raise ValueError("source_frame phải là tên frame gốc, không phải canonical world")
        return Transform(
            parent_frame="world",
            local_frame=self.source_frame,
            translation_xyz=(0.0, 0.0, -self.floor_z_in_source_m),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        )

    def checksum(self) -> Checksum:
        """Checksum canonical của bản ghi, đưa vào provenance của artifact."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_bridge_decision(path: Path, evidence_root: Path | None = None) -> CoordinateBridgeDecision:
    """Đọc bản ghi; nếu có `evidence_root` thì kiểm checksum từng file bằng chứng có mặt."""
    decision = CoordinateBridgeDecision.model_validate_json(path.read_bytes())
    if evidence_root is not None:
        for item in decision.evidence:
            file = evidence_root / item.name
            if file.is_file():
                observed = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()
                if observed != item.checksum:
                    raise ValueError(f"bằng chứng {item.name} không khớp checksum đã ghi")
    return decision
