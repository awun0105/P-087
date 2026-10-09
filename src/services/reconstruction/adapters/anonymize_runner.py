"""Phát hiện và che khuôn mặt/biển số trên một thư mục frame — chạy trong `scene_runtime` (AUD-18).

Dùng EgoBlur Gen2 của Meta (Apache-2.0; gói `egoblur` 2.0.1 cài `--no-deps`, hai file TorchScript). Không
import code app (runtime không có pydantic). Đọc request JSON, ghi result JSON.

    <scene_runtime>/bin/python src/services/reconstruction/adapters/anonymize_runner.py --request r.json --result out.json

Nguyên tắc: frame nào không đọc, không suy luận hoặc không ghi được thì nằm trong `failures` và **không** có
file ở thư mục đích; runner thoát mã 2. Không bao giờ chép frame gốc sang khi bước che lỗi.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sanitization_regions import fill_regions, propagate_regions  # noqa: E402

MODEL_FILES = {"face": "ego_blur_face_gen2.jit", "license_plate": "ego_blur_lp_gen2.jit"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _detectors(weights: Path, config: dict):  # noqa: ANN202 - kiểu của egoblur chỉ có trong runtime
    from gen2.script.predictor import ClassID, EgoblurDetector

    resize = {"min_size_test": config["resize_short_edge"], "max_size_test": config["resize_max"]}
    return {
        kind: EgoblurDetector(
            str(weights / MODEL_FILES[kind]),
            config["device"],
            ClassID.FACE if kind == "face" else ClassID.LICENSE_PLATE,
            config[f"{kind}_threshold"],
            config["nms_iou"],
            resize_aug=resize,
        )
        for kind in MODEL_FILES
    }


def _detect(detectors: dict, bgr) -> list[dict]:  # noqa: ANN001 - numpy chỉ có trong runtime
    import numpy as np
    import torch

    tensor = torch.from_numpy(np.ascontiguousarray(np.transpose(bgr, (2, 0, 1)))).unsqueeze(0)
    regions: list[dict] = []
    for kind, detector in detectors.items():
        batch, original, model_input = detector.pre_process(tensor.to(detector.device))
        frame = detector.get_detections(
            output_tensor=detector.inference(batch),
            timestamp_s=0.0,
            stream_id="",
            rotation_angle=0.0,
            model_input_hw_list=model_input,
            target_img_hw_list=original,
        )[0]
        if frame is None:
            continue
        boxes = frame.face_bboxes if kind == "face" else frame.lp_bboxes
        scores = frame.face_scores if kind == "face" else frame.lp_scores
        for box, score in zip(boxes, scores, strict=True):
            regions.append(
                {
                    "kind": kind,
                    "box": [float(value) for value in box],
                    "score": float(np.ravel(score)[0]),
                    "origin": "detected",
                }
            )
    return regions


def run(request: dict) -> dict:
    """Che mọi frame trong request; trả kết quả kèm danh sách frame lỗi."""
    import cv2
    import torch
    import torchvision
    from gen2.script.detectron2.export.torchscript_patch import patch_instances
    from gen2.script.predictor import PATCH_INSTANCES_FIELDS

    source, target, weights = Path(request["frames_dir"]), Path(request["output_dir"]), Path(request["weights_dir"])
    config = request["config"]
    names = request.get("frame_names") or sorted(
        path.name for path in source.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not names:
        raise SystemExit("không có frame nào để xử lý")
    target.mkdir(parents=True, exist_ok=False)

    detected: list[list[dict]] = []
    readable: list[bool] = []
    with patch_instances(fields=PATCH_INSTANCES_FIELDS):
        detectors = _detectors(weights, config)
        for name in names:
            image = cv2.imread(str(source / name), cv2.IMREAD_COLOR)
            try:
                if image is None:
                    raise ValueError("unreadable frame")
                detected.append(_detect(detectors, image))
                readable.append(True)
            except (ValueError, RuntimeError):
                detected.append([])
                readable.append(False)

    # Frame không đọc được không cho và không nhận vùng lan: nó sẽ không có file đích.
    planned = propagate_regions(detected, config["propagate_radius"], config["propagate_growth"])
    frames, failures = [], []
    for name, regions, usable in zip(names, planned, readable, strict=True):
        source_path, target_path = source / name, target / name
        if not usable:
            failures.append(name)
            continue
        try:
            if regions:
                image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
                fill_regions(image, regions, config["expand_scale"], config["fill_bgr"])
                if not cv2.imwrite(str(target_path), image):
                    raise OSError("frame write failed")
                height, width = image.shape[:2]
            else:
                shutil.copyfile(source_path, target_path)
                height, width = cv2.imread(str(source_path), cv2.IMREAD_COLOR).shape[:2]
        except (OSError, ValueError):
            target_path.unlink(missing_ok=True)
            failures.append(name)
            continue
        for region in regions:
            region.pop("extra_scale", None)
        frames.append(
            {
                "frame_name": name,
                "width": width,
                "height": height,
                "source_checksum": sha256_file(source_path),
                "sanitized_checksum": sha256_file(target_path),
                "regions": regions,
            }
        )
    from importlib.metadata import version

    return {
        "detector": {
            "name": "egoblur-gen2",
            "package_version": version("egoblur"),
            "torch_version": torch.__version__,
            "torchvision_version": torchvision.__version__,
            "face_weights_checksum": sha256_file(weights / MODEL_FILES["face"]),
            "plate_weights_checksum": sha256_file(weights / MODEL_FILES["license_plate"]),
        },
        "config": {key: value for key, value in config.items() if key != "device"},
        "requested_frame_count": len(names),
        "frames": frames,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Che khuôn mặt và biển số trên frame bằng EgoBlur Gen2")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.request.read_text(encoding="utf-8")))
    args.result.write_text(json.dumps(result), encoding="utf-8")
    return 2 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
