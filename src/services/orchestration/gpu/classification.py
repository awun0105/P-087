"""Pure CPU/GPU classification shared with queue execution."""


def scene_gpu(mode: str, boxes_gpu: bool) -> bool:
    return mode in {"objectify", "membership", "geometry", "region"} or boxes_gpu


def import_gpu(input_kind: str, gpu_index: int | None) -> bool:
    return input_kind != "sog" and gpu_index is not None
