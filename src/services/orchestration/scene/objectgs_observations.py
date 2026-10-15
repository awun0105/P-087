"""Immutable ObjectGS observations: calibrated RGB, camera and extraction-time label masks for each accepted view.

The package is a plain tar without compression, so identical views always produce identical bytes and the artifact
checksum is stable. Only the names declared in the manifest may appear, which keeps unpacking away from the filesystem.
"""

import io
import json
import tarfile
from pathlib import Path

MANIFEST = "manifest.json"
SCHEMA_VERSION = "1.0"
_CAMERA_FIELDS = (
    "width",
    "height",
    "center",
    "rotation_xyzw",
    "parameters",
    "camera_model",
    "coordinate_frame",
    "distance_unit",
)


def package_observations(views: list[dict]) -> bytes:
    """Gói các quan sát của lift (`objectgs_views`); danh sách rỗng vẫn là gói hợp lệ, build sẽ từ chối sau."""
    members: dict[str, bytes] = {}
    entries = []
    for index, view in enumerate(views):
        stem = f"view-{index:06d}"
        members[f"{stem}.png"] = Path(view["image_path"]).read_bytes()
        members[f"{stem}.labels.npy"] = Path(view["mask_path"]).read_bytes()
        entries.append(
            {
                **{field: view[field] for field in _CAMERA_FIELDS},
                "image": f"{stem}.png",
                "labels": f"{stem}.labels.npy",
            }
        )
    members[MANIFEST] = json.dumps(
        {"schema_version": SCHEMA_VERSION, "views": entries}, sort_keys=True, allow_nan=False
    ).encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name in sorted(members):
            data = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def unpack_observations(payload: bytes, destination: Path) -> list[dict]:
    """Giải nén vào `destination` và trả các view (camera + đường dẫn tuyệt đối) theo đúng thứ tự đã đóng gói."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as archive:
        members = archive.getmembers()
        by_name = {member.name: member for member in members if member.isfile()}
        if len(by_name) != len(members) or MANIFEST not in by_name:
            raise ValueError("observation package must hold exactly one manifest and unique files")
        manifest = json.loads(archive.extractfile(by_name[MANIFEST]).read().decode("utf-8"))
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported observation package schema")
        declared = {MANIFEST}
        views = []
        for entry in manifest["views"]:
            names = (entry["image"], entry["labels"])
            if any(name != Path(name).name or name not in by_name for name in names):
                raise ValueError("observation view names must be plain members of the package")
            declared.update(names)
            for name in names:
                (destination / name).write_bytes(archive.extractfile(by_name[name]).read())
            views.append(
                {
                    **{field: entry[field] for field in _CAMERA_FIELDS},
                    "model": entry["camera_model"],
                    "image_path": str((destination / entry["image"]).resolve()),
                    "mask_path": str((destination / entry["labels"]).resolve()),
                }
            )
        if set(by_name) != declared:
            raise ValueError("observation package holds members its manifest does not declare")
    return views
