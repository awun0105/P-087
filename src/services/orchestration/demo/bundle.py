"""Đọc demo bundle đã export; chỉ phục vụ file nằm trong allow-list và đúng checksum."""

from pathlib import Path

from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.demo.models import DemoFile, DemoManifest


class DemoUnavailableError(LookupError):
    """Deployment chưa có demo bundle (hoặc bundle hỏng); UI ẩn kịch bản demo."""


class DemoBundle:
    """Bundle read-only tại `<root>/manifest.json` + `<root>/files/<name>`."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def manifest(self) -> DemoManifest:
        """Đọc và validate manifest; thiếu/hỏng → DemoUnavailableError."""
        path = self.root / "manifest.json"
        if not path.is_file():
            raise DemoUnavailableError("Chưa có demo bundle trên deployment này")
        try:
            return DemoManifest.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise DemoUnavailableError("Demo bundle manifest không hợp lệ") from error

    def file(self, name: str) -> tuple[DemoFile, Path]:
        """Resolve file theo tên trong allow-list, kiểm size + checksum trước khi trả."""
        entry = next((item for item in self.manifest().files() if item.name == name), None)
        if entry is None:
            raise DemoUnavailableError("File không thuộc demo bundle")
        path = (self.root / "files" / entry.name).resolve()
        if not path.is_relative_to(self.root / "files") or not path.is_file():
            raise DemoUnavailableError("File demo bị thiếu")
        if path.stat().st_size != entry.size_bytes or sha256_file(path) != entry.checksum:
            raise DemoUnavailableError("File demo sai checksum; export lại bundle")
        return entry, path
