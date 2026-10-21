"""Đọc nhẹ artifact REC để hiển thị từng bước (ADR 0005); không tính toán, không publish.

Chỉ trả ref ảnh frame và vị trí/hướng camera (vài KB) để trình duyệt không phải đọc
file nội bộ nặng của REC.
"""

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from pydantic import FiniteFloat

from src.models.contracts.artifacts import ContractModel, ProductArtifactRef
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class CameraMarker(ContractModel):
    """Tâm và hướng một camera (parent_from_camera); đơn vị theo artifact nguồn."""

    frame_id: int
    center: Vector3
    rotation_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]


class PoseRegistration(ContractModel):
    """Kết quả đăng ký ảnh của bước dựng pose để giao diện báo thử lại và vùng thiếu ảnh (T-071 C3, D6)."""

    registered_ratio: FiniteFloat
    retry_count: int
    registration_warning: bool


def pose_registration(poses: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]) -> PoseRegistration:
    """Đọc tỉ lệ ảnh đăng ký, số bậc thử lại và cờ cảnh báo từ CameraPoseArtifact; artifact cũ không có thì 0/False."""
    document = json.loads(resolve(poses).read_bytes())
    return PoseRegistration(
        registered_ratio=float(document["registered_ratio"]),
        retry_count=len(document.get("retry_ladder") or []),
        registration_warning=document.get("registration_warning") is True,
    )


def frame_images(
    frame_set: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]
) -> list[ProductArtifactRef]:
    """Ref ảnh của frame set đã publish (checksum do REC kiểm khi nạp)."""
    return [frame.image for frame in FrameSetResolver(resolve, resolve).load(frame_set).frames]


def camera_markers(poses: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]) -> list[CameraMarker]:
    """Tâm camera từ artifact pose (raw SfM hoặc canonical mét), sắp theo frame."""
    document = json.loads(resolve(poses).read_bytes())
    if document.get("transform_semantics") != "parent_from_local":
        raise ValueError("camera pose artifact phải là parent_from_camera")
    markers = [
        CameraMarker(
            frame_id=pose["frame_id"], center=tuple(pose["translation"]), rotation_xyzw=tuple(pose["rotation_xyzw"])
        )
        for pose in document["poses"]
    ]
    return sorted(markers, key=lambda marker: marker.frame_id)


class CameraView(ContractModel):
    """Một frame để chiếu điểm 3D: intrinsics COLMAP, pose world_from_camera (OpenCV) và ảnh."""

    frame_id: int
    image: ProductArtifactRef
    model: str
    width: int
    height: int
    parameters: list[FiniteFloat]
    center: Vector3
    rotation_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]


def camera_views(
    poses: ProductArtifactRef, frames: list[ProductArtifactRef], resolve: Callable[[ProductArtifactRef], Path]
) -> list[CameraView]:
    """Ghép pose canonical (mét) với ảnh frame theo tên file; frame không có pose bị bỏ qua."""
    document = json.loads(resolve(poses).read_bytes())
    if document.get("transform_semantics") != "parent_from_local" or document.get("camera_axes") not in (
        None,
        "x_right_y_down_z_forward",
    ):
        raise ValueError("pose phải là world_from_camera trục OpenCV")
    cameras = {camera["camera_id"]: camera for camera in document["cameras"]}
    images = {ref.artifact_uri.rsplit("/", 1)[-1]: ref for ref in frames}
    views = []
    for pose in document["poses"]:
        image = images.get(pose["image_name"])
        if image is None:
            continue
        camera = cameras[pose["camera_id"]]
        views.append(
            CameraView(
                frame_id=pose["frame_id"],
                image=image,
                model=camera["model"],
                width=camera["width"],
                height=camera["height"],
                parameters=camera["parameters"],
                center=tuple(pose["translation"]),
                rotation_xyzw=tuple(pose["rotation_xyzw"]),
            )
        )
    return sorted(views, key=lambda view: view.frame_id)


def metric_gaussian_points(
    confirmation: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path], min_opacity: float = 0.3
) -> np.ndarray:
    """Tâm Gaussian (đủ đục) của master Brush, đổi sang mét bằng transform đã xác nhận (REC-06).

    Đọc bytes đã kiểm checksum; authority của bản xác nhận đã được kiểm khi xác nhận và ở bước
    hoàn tất. Chỉ phục vụ tách vật thể, không publish artifact mét mới.
    """
    from src.services.reconstruction.lidar.cloud_header import read_header
    from src.services.reconstruction.rgb.canonical.metric_models import MetricConfirmation
    from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
    from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

    record = MetricConfirmation.model_validate_json(resolve(confirmation).read_bytes())
    frame_resolver = FrameSetResolver(resolve, resolve)
    visual = VisualResolver(resolve, CameraPoseResolver(resolve, frame_resolver)).load(
        record.preview.request.source_visual
    )
    path = resolve(visual.master)
    with path.open("rb") as stream:
        header = read_header(stream)
        offset = stream.tell()
    dtype = np.dtype([(name, "<" + code) for name, code in zip(header.fields, header.codes, strict=True)])
    rows = np.frombuffer(path.read_bytes()[offset:], dtype=dtype, count=header.point_count)
    xyz = np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(float)
    if "opacity" in header.fields:
        xyz = xyz[1 / (1 + np.exp(-rows["opacity"].astype(float))) >= min_opacity]
    transform = record.preview.transform
    from src.services.reconstruction.alignment.similarity import rotation_matrix

    return transform.scale_m_per_sfm_unit * xyz @ rotation_matrix(transform.rotation_xyzw).T + np.asarray(
        transform.translation_m
    )


def metric_visual_master(bundle: object, resolve: Callable[[ProductArtifactRef], Path]) -> ProductArtifactRef:
    """Ref tới PLY 3DGS hệ mét (bản gốc đầy đủ) của một bundle RGB — đầu vào tách vật pipeline v2.

    Đi theo chuỗi đã publish: bundle.provenance.metric_verification_ref → `request.canonical_visual_ref`
    (CanonicalVisualManifest) → `master_ref`. Mỗi bước đọc qua `resolve` (kiểm checksum); không dò thư mục.
    """
    provenance = getattr(bundle, "provenance", None) or {}
    verification = provenance.get("metric_verification_ref")
    if not verification:
        raise ValueError("bundle không có metric_verification_ref (chưa có 3DGS hệ mét)")
    record = json.loads(resolve(ProductArtifactRef.model_validate(verification)).read_bytes())
    manifest_ref = (record.get("request") or {}).get("canonical_visual_ref")
    if not manifest_ref:
        raise ValueError("bản kiểm metric không tham chiếu CanonicalVisualManifest")
    manifest = json.loads(resolve(ProductArtifactRef.model_validate(manifest_ref)).read_bytes())
    master = ProductArtifactRef.model_validate(manifest["master_ref"])
    if master.artifact_type != "GaussianPLY":
        raise ValueError("master của CanonicalVisualManifest không phải GaussianPLY")
    return master


#: Số điểm tối đa của lớp LiDAR gửi cho trình duyệt (float32 xyz → khoảng 3,6 MB); đủ để thấy hình dạng không gian.
LIDAR_OVERLAY_MAX_POINTS = 300_000
_LIDAR_OVERLAY_VOXEL_M = 0.05
_LIDAR_READ_LIMIT = 50_000_000


def lidar_overlay_points(
    bundle: object, resolve: Callable[[ProductArtifactRef], Path], max_points: int = LIDAR_OVERLAY_MAX_POINTS
) -> np.ndarray | None:
    """Đám mây LiDAR của bundle trong hệ `world` (mét, Z-up) đã thu gọn để vẽ chồng lên scene; `(N, 3)` float32.

    None khi bundle không có LiDAR đã căn chỉnh (job chỉ có video, hoặc căn chỉnh chưa được xác nhận). Phép đặt vào
    scene là `transform_target_from_source` của `AlignmentRecord` — đúng phép mà người dùng đã xác nhận, không khớp lại.
    Thu gọn bằng lưới voxel, tăng dần cỡ ô tới khi vừa `max_points`, nên hình dạng giữ đều ở mọi vùng.
    """
    from src.models.contracts.reconstruction import AlignmentStatus, ReconstructionBundle
    from src.services.reconstruction.alignment.similarity import rotation_matrix
    from src.services.reconstruction.lidar.fusion import read_points, voxel_downsample

    if not isinstance(bundle, ReconstructionBundle):
        raise TypeError("cần ReconstructionBundle")
    record, reference = bundle.alignment_record, bundle.lidar_geometry_ref
    if record is None or reference is None or record.status != AlignmentStatus.CONFIRMED:
        return None
    with resolve(reference).open("rb") as stream:
        points = read_points(stream, _LIDAR_READ_LIMIT)
    transform = record.transform_target_from_source
    world = points @ rotation_matrix(transform.rotation_quaternion_xyzw).T + np.asarray(transform.translation_xyz)
    voxel = _LIDAR_OVERLAY_VOXEL_M
    while len(world) > max_points:
        voxel *= 1.5
        world = voxel_downsample(world, voxel)
    return world.astype("<f4")
