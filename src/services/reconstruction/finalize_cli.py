"""CLI hoàn tất EX-REC sau xác nhận tỉ lệ; runtime settings chỉ đọc tại composition root."""

import argparse
import json
import logging
import signal
from pathlib import Path

from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings, VisualProcess
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor, SplatRuntimeSettings
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings
from src.services.reconstruction.finalize import FinalizeDependencies, FinalizeRequest, FinalizeWorker
from src.services.reconstruction.preview_cli import _progress_writer


def create_cli_parser() -> argparse.ArgumentParser:
    """Request không chứa private runtime path hoặc environment secrets."""
    parser = argparse.ArgumentParser(description="EX-REC finalize: canonical metric → geometry → bundle")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--progress-file", type=Path, default=None)
    return parser


class _ReuseIdenticalWriter:
    """Chạy lại bước hoàn tất: artifact theo nội dung đã có đúng checksum thì dùng lại.

    Nội dung khác vẫn bị store từ chối (immutable); không bao giờ ghi đè.
    """

    def __init__(self, resolver: object, store: object) -> None:
        self.resolver = resolver
        self.store = store

    def publish(self, reference: object, payload: bytes) -> object:
        """Ref đã tồn tại với đúng checksum → trả lại ref; chưa có → publish."""
        from src.services.orchestration.artifacts import ArtifactNotFoundError

        try:
            self.resolver.require(reference)  # type: ignore[attr-defined]
        except ArtifactNotFoundError:
            return self.store.publish(reference, payload)  # type: ignore[attr-defined]
        return reference


def _execute(args: argparse.Namespace) -> int:
    from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore

    request = FinalizeRequest.model_validate_json(args.request.read_bytes())
    resolver = ArtifactResolver(args.store_root)
    brush = VisualProcess(BrushRuntimeSettings())
    worker = FinalizeWorker(
        FinalizeDependencies(
            resolve=resolver.require,
            writer=_ReuseIdenticalWriter(resolver, FilesystemArtifactStore(resolver)),  # type: ignore[arg-type]
            voxel=VoxelProcess(VoxelRuntimeSettings()),
            splat=SplatArtifactProcessor(SplatRuntimeSettings(), brush),
            on_event=_progress_writer(args.progress_file),
        )
    )
    result, reference = worker.run(request, args.workspace)
    print(json.dumps({"result_ref": reference.model_dump(mode="json")}))
    return 0 if result.error is None else 1


def main(argv: list[str] | None = None) -> int:
    """Exit 0 = bundle published; 1 = stage failure (đã ghi result); 2 = setup lỗi."""
    args = create_cli_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    previous_handler = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Để adapter dừng process group của splat-transform."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        return _execute(args)
    except KeyboardInterrupt:
        print(json.dumps({"error_code": "FINALIZE_INTERRUPTED"}))
        return 130
    except (ValueError, OSError, RuntimeError) as error:
        logging.getLogger(__name__).error("Finalize setup failed cause=%s", type(error).__name__)
        print(json.dumps({"error_code": "FINALIZE_SETUP_FAILED", "error_type": type(error).__name__}))
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
