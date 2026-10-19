"""Đo xem trước vùng (T-025) trên scene có N Gaussian đủ SH: cold/warm, 1 và 16 box, p50/p95 và RSS.

Chạy một việc nặng một lúc trên máy phát triển, khi không có tải khác:
    .venv/bin/python scripts/scene/bench_region_preview.py --rows 2000000 --runs 5

Dùng đúng đường đi của dịch vụ (membership, nhãn, PLY, floor fit, vỏ) qua fixture của test; chỉ không đo HTTP/trình duyệt.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FLOOR_FRACTION = 0.25
TARGET = "candidate-001"


def _rss_mib() -> float:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return float("nan")


def _rows(count: int, sh_degree: int) -> tuple[np.ndarray, np.ndarray]:
    """Đám Gaussian có sàn, một vật (nhãn 0) quanh pose candidate-001, phần còn lại là nền (-1)."""
    rest = (sh_degree + 1) ** 2 * 3 - 3
    names = ["x", "y", "z", "opacity", *(f"scale_{i}" for i in range(3)), *(f"rot_{i}" for i in range(4))]
    names += [*(f"f_dc_{i}" for i in range(3)), *(f"f_rest_{i}" for i in range(rest))]
    rows = np.zeros(count, dtype=[(name, "<f4") for name in names])
    rng = np.random.default_rng(25)
    floor_count = int(count * FLOOR_FRACTION)
    object_count = int((count - floor_count) * 0.8)
    xyz = np.empty((count, 3))
    xyz[:floor_count] = np.column_stack(
        [rng.uniform(-3, 3, floor_count), rng.uniform(-2, 2, floor_count), rng.normal(0, 0.004, floor_count)]
    )
    xyz[floor_count : floor_count + object_count] = rng.uniform(-0.2, 0.2, (object_count, 3)) + (1.5, 0.1, 1.1)
    rest_count = count - floor_count - object_count
    xyz[floor_count + object_count :] = rng.uniform(-0.5, 0.5, (rest_count, 3)) + (2.6, 0.1, 1.1)
    for axis, name in enumerate(("x", "y", "z")):
        rows[name] = xyz[:, axis]
    rows["opacity"] = 2.0
    rows["scale_0"] = rows["scale_1"] = rows["scale_2"] = np.log(0.05)
    rows["rot_0"] = 1.0
    rows["f_dc_0"] = rng.normal(0, 0.5, count)
    if rest:
        rows["f_rest_0"] = rng.normal(0, 0.05, count)
    labels = np.full(count, -1, dtype=np.int32)
    labels[floor_count : floor_count + object_count] = 0
    labels[floor_count + object_count :] = 2
    return rows, labels


def _boxes(count: int):
    from src.models.contracts.object_membership import RegionBox

    if count == 1:
        return [RegionBox(op="add", center_m=(0, 0, 0), half_extents_m=(0.3, 0.3, 0.3), yaw_rad=0)]
    side = int(round(count**0.5))
    offsets = np.linspace(-0.2, 0.2, side)
    return [
        RegionBox(op="add", center_m=(float(dx), float(dy), 0.0), half_extents_m=(0.12, 0.12, 0.3), yaw_rad=0)
        for dx in offsets
        for dy in offsets
    ][:count]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=2_000_000)
    parser.add_argument("--sh-degree", type=int, default=3)
    parser.add_argument("--runs", type=int, default=5, help="số lần warm cho mỗi cấu hình")
    parser.add_argument("--boxes", type=int, nargs="+", default=[1, 16])
    parser.add_argument("--json", type=Path, help="ghi mọi số đo (JSON lines) vào file này")
    parser.add_argument("--profile", action="store_true", help="thêm một lần warm có cProfile cho mỗi cấu hình box")
    args = parser.parse_args()

    from src.models.contracts.object_membership import ObjectRegionCommand
    from src.services.orchestration.scene import membership_regeneration
    from src.services.orchestration.scene.object_region import preview_region
    from tests.test_scene import test_object_correction as correction

    records: list[dict] = []

    def emit(record: dict) -> None:
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

    with tempfile.TemporaryDirectory(prefix="bench-region-") as scratch:
        tmp = Path(scratch)
        rows, labels = _rows(args.rows, args.sh_degree)
        started = perf_counter()
        fixture = correction._fixture(tmp, source_rows=rows, source_labels=labels)
        emit(
            {
                "stage": "fixture",
                "rows": args.rows,
                "sh_degree": args.sh_degree,
                "seconds": round(perf_counter() - started, 3),
            }
        )
        registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
        # Vật cần pose nguồn để đổi world → object-local; fixture chưa ghi, nên ghi như test vùng làm.
        objects = [
            item.model_copy(
                update={"provenance": {**item.provenance, "source_transform": item.transform.model_dump(mode="json")}}
            )
            for item in fixture.scene.objects
        ]
        scene = fixture.editor.publish_next(
            correction._JOB_ID,
            fixture.scene.scene_revision,
            fixture.scene.model_copy(update={"objects": objects}),
            "bench-fixture",
        ).revision.scene

        for boxes in args.boxes:
            command = ObjectRegionCommand(
                expected_scene_revision=scene.scene_revision,
                membership_checksum=fixture.membership.labels_ref.artifact_checksum,
                boxes=_boxes(boxes),
            )
            membership_regeneration._SOURCE_CACHE.clear()
            started = perf_counter()
            result = preview_region(registry, correction._JOB_ID, TARGET, command)
            cold = perf_counter() - started
            emit(
                {
                    "stage": "cold",
                    "boxes": boxes,
                    "seconds": round(cold, 4),
                    "rss_mib": round(_rss_mib(), 1),
                    "object_gaussian_count": result["object_gaussian_count"],
                    "shell_ok": result["shell_error"] is None,
                }
            )
            warm: list[float] = []
            for run in range(args.runs):
                started = perf_counter()
                preview_region(registry, correction._JOB_ID, TARGET, command)
                warm.append(perf_counter() - started)
                emit(
                    {
                        "stage": "warm",
                        "boxes": boxes,
                        "run": run,
                        "seconds": round(warm[-1], 4),
                        "rss_mib": round(_rss_mib(), 1),
                    }
                )
            if args.profile:
                import cProfile
                import io
                import pstats

                profiler = cProfile.Profile()
                profiler.enable()
                preview_region(registry, correction._JOB_ID, TARGET, command)
                profiler.disable()
                text = io.StringIO()
                pstats.Stats(profiler, stream=text).sort_stats("cumulative").print_stats(18)
                print(f"--- cProfile warm boxes={boxes} ---\n{text.getvalue()}", flush=True)
            ordered = sorted(warm)
            p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
            emit(
                {
                    "stage": "summary",
                    "boxes": boxes,
                    "cold_s": round(cold, 4),
                    "warm_p50_s": round(statistics.median(warm), 4),
                    "warm_p95_s": round(p95, 4),
                    "rss_mib": round(_rss_mib(), 1),
                }
            )

    if args.json:
        args.json.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
