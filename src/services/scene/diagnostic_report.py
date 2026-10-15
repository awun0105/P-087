"""Read-only, checksum-verified reports; a rejection is evidence, not ground truth."""

import base64
import hashlib
import json
import zlib
from collections import Counter
from pathlib import Path

from src.models.contracts.object_diagnostics import ObjectPipelineEvidence


def load_evidence(payload: bytes, *, checksum: str, job_id: str | None = None) -> ObjectPipelineEvidence:
    if "sha256:" + hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("evidence checksum mismatch")
    if len(payload) > 16 * 1024**2:
        raise ValueError("evidence exceeds supported byte limit")
    manifest = ObjectPipelineEvidence.model_validate_json(payload)
    if job_id is not None and manifest.job_id != job_id:
        raise ValueError("evidence job mismatch")
    return manifest


def trace_object(manifest: ObjectPipelineEvidence, object_id: str) -> list[dict]:
    seeds = {
        event["seed"]
        for event in manifest.events
        if event.get("kind") == "object_binding" and event.get("object_id") == object_id
    }
    if not seeds:
        raise ValueError("object has no binding in this attempt; inspect the run-level report")
    keys = {
        event["instance_key"]
        for event in manifest.events
        if event.get("kind") == "seed_decision" and event.get("seed") in seeds
    }
    prompts = {
        prompt for event in manifest.events if event.get("instance_key") in keys for prompt in event.get("prompts", [])
    }
    labels = {
        label
        for event in manifest.events
        if event.get("kind") == "configured"
        for label, bound in event.get("label_to_object_id", {}).items()
        if bound == object_id
    }
    selected = [
        event
        for event in manifest.events
        if event.get("object_id") == object_id
        or event.get("seed") in seeds
        or event.get("instance_key") in keys
        or event.get("prompt") in prompts
        or event.get("kind") in {"failure", "stage_started", "stage_failed", "stage_completed", "configured"}
    ]
    return [
        event
        for event in selected
        if not (str(event.get("phase", "")).startswith("export-") and str(event["phase"])[7:] not in labels)
    ]


def render_report(manifest: ObjectPipelineEvidence, object_id: str | None = None) -> str:
    events = trace_object(manifest, object_id) if object_id else manifest.events
    lines = [
        f"# Chẩn đoán tách vật — {manifest.job_id}",
        f"Lần chạy: {manifest.run_id}; revision đầu vào: {manifest.input_revision}; trạng thái: {manifest.status}.",
        "Đây là kết quả producer; không tự chứng minh SceneIR đã được publish hay chất lượng vật thể đúng.",
        f"Evidence bị giới hạn/cắt bớt: {'có' if manifest.truncated else 'không'}.",
    ]
    if object_id:
        lines.append(f"Vật thể: {object_id}.")
    decisions = sorted(events, key=lambda event: int(event.get("time_ns", 2**63)))
    first = next(
        (
            event
            for event in decisions
            if event.get("accepted") is False
            or event.get("reasons")
            or event.get("kind") in {"failure", "stage_failed"}
            or event.get("fallback_reason")
        ),
        None,
    )
    if first:
        lines.append(
            f"Quyết định loại/cảnh báo đầu tiên đã ghi: {first['stage']} / {first['kind']}. Đây chưa phải kết luận nguyên nhân lỗi."
        )
    lines.extend(["", "## Các giai đoạn", "", "| Giai đoạn | Số sự kiện đã lưu |", "|---|---:|"])
    for stage, count in Counter(str(event["stage"]) for event in events).items():
        lines.append(f"| {stage} | {count} |")
    lines.extend(["", "## Quyết định và kết quả", ""])
    for event in sorted(events, key=lambda e: int(e.get("time_ns", 2**63))):
        if event["kind"] in {"mask_sample", "mask_generated"}:
            continue
        values = {key: value for key, value in event.items() if key not in {"time_ns", "stage"}}
        lines.append(f"- **{event['stage']}**: `{json.dumps(values, ensure_ascii=False, sort_keys=True)}`")
    lines.extend(
        [
            "",
            "Các quyết định loại/gộp không tự chứng minh thuật toán sai. Đối chiếu ảnh/mask và dữ liệu chuẩn để kết luận.",
            "Vật bị loại trước khi cấp object ID phải truy vết bằng prompt, instance_key hoặc seed trong báo cáo toàn lần chạy.",
            "",
            "## Phạm vi evidence",
            "",
            f"Số mask mẫu đã lưu: {len(manifest.samples)}. Mẫu là packbits big-endian nén zlib, mã hóa base64 trong artifact.",
        ]
    )
    for item in manifest.coverage:
        lines.append("- `" + json.dumps(item, sort_keys=True) + "`")
    for error in manifest.collection_errors:
        lines.append(f"- Evidence chưa đầy đủ: {error}")
    if manifest.log_tails:
        lines.extend(["", "## Cuối log provider (đã giới hạn và che thông tin nhạy cảm)", ""])
        for name, tail in manifest.log_tails.items():
            lines.extend([name, "", *["    " + line for line in tail.splitlines()], ""])
    return "\n".join(lines) + "\n"


def export_masks(manifest: ObjectPipelineEvidence, destination: Path) -> int:
    """Restore retained masks, checking decompression size and packed-bit digest."""
    import numpy as np
    from PIL import Image

    descriptions = {
        event["file"]: event for event in manifest.events if event.get("kind") == "mask_sample" and event.get("file")
    }
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for filename, encoded in manifest.samples.items():
        if filename not in descriptions:
            continue
        if Path(filename).name != filename:
            raise ValueError("invalid evidence sample filename")
        info = descriptions[filename]
        shape = info["shape"]
        if len(shape) != 2 or any(not isinstance(value, int) or value <= 0 for value in shape):
            raise ValueError("invalid evidence mask shape")
        pixels = shape[0] * shape[1]
        if pixels > 64 * 1024**2:
            raise ValueError("mask export exceeds pixel limit")
        size = (pixels + 7) // 8
        decoder = zlib.decompressobj()
        packed = decoder.decompress(base64.b64decode(encoded, validate=True), size + 1)
        if len(packed) != size or not decoder.eof or decoder.unused_data:
            raise ValueError("invalid packed mask size")
        if "sha256:" + hashlib.sha256(packed).hexdigest() != info["packed_checksum"]:
            raise ValueError("mask checksum mismatch")
        bits = np.unpackbits(np.frombuffer(packed, dtype=np.uint8))[:pixels].reshape(shape)
        Image.fromarray(bits * 255).save(destination / (filename + ".png"))
        count += 1
    return count
