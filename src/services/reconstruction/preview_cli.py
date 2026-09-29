"""CLI ổn định cho prepared RGB preview; runtime settings chỉ đọc tại composition root."""

import argparse
import json
import logging
import signal
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.manifests import StageArtifact
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings, VisualProcess
from src.services.reconstruction.adapters.colmap_runtime import ColmapProcess, ColmapRuntimeSettings
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor, SplatRuntimeSettings
from src.services.reconstruction.preview_models import PreparedPreviewRequest
from src.services.reconstruction.preview_worker import PreparedPreviewWorker, PreviewDependencies
from src.services.reconstruction.rgb.frame_set import FrameSetResolver


def create_cli_parser() -> argparse.ArgumentParser:
    """Request không chứa private runtime path hoặc environment secrets."""
    parser = argparse.ArgumentParser(description="EX-REC prepared RGB preview (not final bundle)")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="Append một dòng JSON StageArtifact cho mỗi stage event (orchestrator đọc để hiện tiến trình)",
    )
    return parser


def _progress_writer(path: Path | None) -> Callable[[StageArtifact], None] | None:
    """Ghi từng event thành một dòng và flush ngay để tiến trình hiện theo thời gian thực."""
    if path is None:
        return None

    def write(stage: StageArtifact) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(stage.model_dump_json() + "\n")
            stream.flush()

    return write


def _execute(args: argparse.Namespace) -> int:
    # Chỉ CLI composition root dùng public storage facade; core giữ injected ports.
    from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore

    request = PreparedPreviewRequest.model_validate_json(args.request.read_bytes())
    resolver = ArtifactResolver(args.store_root)
    brush = VisualProcess(BrushRuntimeSettings())
    dependencies = PreviewDependencies(
        frames=FrameSetResolver(resolver.require, resolver.require),
        writer=FilesystemArtifactStore(resolver),
        resolve=resolver.require,
        colmap=ColmapProcess(ColmapRuntimeSettings()),
        brush=brush,
        splat=SplatArtifactProcessor(SplatRuntimeSettings(), brush),
        on_event=_progress_writer(args.progress_file),
    )
    result, reference = PreparedPreviewWorker(dependencies).run(request, args.workspace)
    print(json.dumps({"result": result.model_dump(mode="json"), "result_ref": reference.model_dump(mode="json")}))
    return 0 if result.preview_complete else 1


def main(argv: list[str] | None = None) -> int:
    """Exit 0 = preview ready/HITL pending; 1 = stage failure; 2 = invalid setup."""
    args = create_cli_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    previous_handler = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Để runtime adapter cleanup trainer có process group riêng."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        return _execute(args)
    except KeyboardInterrupt:
        print(json.dumps({"error_code": "PREVIEW_INTERRUPTED"}))
        return 130
    except (ValueError, OSError, RuntimeError) as error:
        logging.getLogger(__name__).error("Preview setup/publication failed cause=%s", type(error).__name__)
        print(json.dumps({"error_code": "PREVIEW_SETUP_OR_PUBLICATION_FAILED", "error_type": type(error).__name__}))
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
