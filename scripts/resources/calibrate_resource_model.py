"""Đối chiếu số đo tài nguyên trong r2s_resource_usage với ước lượng của ResourceModel (AUD-26.S1).

Script chỉ đọc: không ghi database, không ghi artifact.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402
from src.models.contracts.artifacts import ProductArtifactRef  # noqa: E402
from src.models.contracts.manifests import StageId  # noqa: E402
from src.services.orchestration.jobs.database import RuntimeDatabase  # noqa: E402
from src.services.orchestration.processing import load_presets  # noqa: E402
from src.services.orchestration.processing.models import ParamValue  # noqa: E402
from src.services.orchestration.processing.observed import _vram, load_usages  # noqa: E402
from src.services.orchestration.processing.resources import estimate_gb  # noqa: E402
from src.services.orchestration.projects import ProjectRegistry  # noqa: E402
from src.services.orchestration.projects.errors import JobNotFoundError  # noqa: E402
from src.services.reconstruction.quality import pose_quality, visual_quality  # noqa: E402


def _extract_artifact_metrics(registry: ProjectRegistry, job_id: str) -> tuple[int | None, int | None, int | None]:
    """Lấy (registered_frames, training_frames, gaussians) từ artifact của job."""
    try:
        job = registry.get_job(job_id)
    except (JobNotFoundError, Exception):
        return None, None, None

    registered_frames: int | None = None
    training_frames: int | None = None
    gaussians: int | None = None

    def _resolver(ref: ProductArtifactRef) -> Path:
        try:
            return registry.resolve_artifact(job_id, ref)
        except Exception:
            return registry.runtime_resolver.require(ref)

    for stage in job.stage_artifacts:
        if stage.artifact_uri is None or stage.artifact_checksum is None or stage.data_class is None:
            continue
        try:
            ref = registry._to_product_ref(job_id, stage)
            if stage.stage_id == StageId.CAMERA_POSE:
                pq = pose_quality(ref, _resolver)
                registered_frames = pq.registered_frames
            elif stage.stage_id == StageId.VISUAL_RECON:
                vq = visual_quality(ref, _resolver)
                if vq.training_frames > 0:
                    training_frames = vq.training_frames
                if vq.gaussians is not None:
                    gaussians = vq.gaussians
        except Exception:
            continue

    return registered_frames, training_frames, gaussians


def main() -> None:
    parser = argparse.ArgumentParser(description="Đối chiếu số đo tài nguyên và mô hình ước lượng")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Đường dẫn DB SQLite (mặc định lấy từ Settings hoặc data/studio_local/runtime.db)",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_url = args.db
    if not db_url:
        default_db = ROOT / "data/studio_local/runtime.db"
        if default_db.exists():
            db_url = f"sqlite:///{default_db}"
        else:
            db_url = settings.database_url

    if not db_url.startswith("sqlite:///"):
        db_path = Path(db_url).resolve()
        db_url = f"sqlite:///{db_path}"

    db = RuntimeDatabase(db_url)
    db_file = Path(db_url.removeprefix("sqlite:///"))
    candidate_artifacts = db_file.parent / "artifacts"
    artifact_root = candidate_artifacts if candidate_artifacts.exists() else settings.artifact_root
    registry = ProjectRegistry(runtime_root=artifact_root, database=db)

    config_path = settings.product_processing_config or (ROOT / "configs/product/processing_presets_v1.json")
    presets, _ = load_presets(config_path)
    model = presets.resource_model

    usages = load_usages(db)
    if not usages:
        print("Không tìm thấy bản ghi r2s_resource_usage nào.")
        return

    # Sắp xếp theo started_at
    usages.sort(key=lambda u: u.started_at)

    rows = []
    headers = [
        "Job ID",
        "Tool",
        "Outcome",
        "GPU",
        "Frames thật (Pose/Train)",
        "Gaussians",
        "Peak RAM (GB)",
        "Est RAM (GB)",
        "Peak VRAM (GB)",
        "Est VRAM (GB)",
        "Đạt",
    ]

    cache: dict[str, tuple[int | None, int | None, int | None]] = {}

    for u in usages:
        if u.job_id not in cache:
            cache[u.job_id] = _extract_artifact_metrics(registry, u.job_id)
        reg_f, train_f, g_count = cache[u.job_id]

        # Định dạng frame thật
        if reg_f is not None or train_f is not None:
            f_str = f"{reg_f or '—'} / {train_f or '—'}"
        else:
            f_str = "—"

        g_str = f"{g_count:,}" if g_count is not None else "—"

        # Tính estimate với frame thật nếu có (ưu tiên số frame pose mà COLMAP xử lý)
        real_frame = reg_f or train_f
        est_params: dict[str, ParamValue] = dict(u.params or {})
        if real_frame is not None:
            est_params["sampling.max_frames"] = real_frame

        try:
            est = estimate_gb(model, est_params)
            est_ram = est["ram"]
            est_vram = est["vram"]
            est_ram_str = f"{est_ram:.2f}"
            est_vram_str = f"{est_vram:.2f}"
        except Exception:
            est_ram = None
            est_vram = None
            est_ram_str = "—"
            est_vram_str = "—"

        peak_vram = _vram(u)
        peak_vram_str = f"{peak_vram:.2f}" if peak_vram is not None else "—"
        peak_ram_str = f"{u.peak_ram_gb:.2f}" if u.peak_ram_gb is not None else "—"

        # Cột đạt chỉ tính cho lượt completed của tool preview
        dat_str = "—"
        if u.tool == "preview" and u.outcome == "completed":
            # Dung sai 0.15 GB cho nhiễu bộ nhớ nền hệ thống khi chạy local
            ram_ok = (
                est_ram is not None
                and u.peak_ram_gb is not None
                and (est_ram >= u.peak_ram_gb or (u.peak_ram_gb - est_ram <= 0.15))
            ) or (u.peak_ram_gb is None)
            vram_ok = (est_vram is not None and peak_vram is not None and est_vram >= peak_vram) or (peak_vram is None)
            dat_str = "đúng" if (ram_ok and vram_ok) else "KHÔNG"

        gpu_name = u.gpu_name or "—"
        if len(gpu_name) > 20:
            gpu_name = gpu_name[:17] + "..."

        rows.append(
            [
                u.job_id[:12],
                u.tool,
                u.outcome,
                gpu_name,
                f_str,
                g_str,
                peak_ram_str,
                est_ram_str,
                peak_vram_str,
                est_vram_str,
                dat_str,
            ]
        )

    # In bảng định dạng markdown
    col_widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths, strict=True))
    separator_line = "-|-".join("-" * w for w in col_widths)

    print(f"| {header_line} |")
    print(f"| {separator_line} |")
    for r in rows:
        line = " | ".join(str(cell).ljust(w) for cell, w in zip(r, col_widths, strict=True))
        print(f"| {line} |")


if __name__ == "__main__":
    main()
