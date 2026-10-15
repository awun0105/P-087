"""Seal bounded producer traces without publishing a scene or suppressing its failures."""

import base64
import hashlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.object_diagnostics import ObjectPipelineEvidence
from src.services.process_control import ProcessCancelledError

logger = logging.getLogger(__name__)
T = TypeVar("T")
MAX_EVIDENCE_BYTES = 16 * 1024**2


def safe_message(message: str) -> str:
    """Do not export local paths, credentials or signed queries in provider text."""
    message = re.sub(r"(?i)authorization\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+", "Authorization=[redacted]", message)
    message = re.sub(
        r"(?i)(token|password|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", message
    )
    message = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[redacted]", message)
    return re.sub(r"/(?:[^\s\"']+)", "[local-path]", message)


def _safe_values(value: object) -> object:
    if isinstance(value, dict):
        return {key: item if key == "key" else _safe_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_values(item) for item in value]
    if isinstance(value, str) and not value.startswith("artifact://jobs/"):
        return safe_message(value)
    return value


def seal_attempt(
    job: object,
    bundle: object,
    workspace: Path,
    publish: Callable,
    input_revision: str,
    status: str,
    error: BaseException | None = None,
) -> ProductArtifactRef:
    directory = workspace / "evidence"
    events, coverage, samples, errors = [], [], {}, []
    budget = MAX_EVIDENCE_BYTES // 2  # base64 and JSON overhead must fit the sealed artifact limit
    truncated = False
    paths = sorted(directory.glob("*"), key=lambda path: (path.name.endswith(".bits.zlib"), path.name))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        if size > budget:
            truncated = True
            continue
        payload = path.read_bytes()
        budget -= len(payload)
        try:
            if path.name.endswith(".coverage.json"):
                item = json.loads(payload)
                coverage.append(item)
                truncated |= bool(item.get("events_dropped") or item.get("masks_dropped"))
            elif path.suffix == ".jsonl":
                for line in payload.splitlines():
                    try:
                        events.append(_safe_values(json.loads(line)))
                    except ValueError:
                        errors.append(f"{path.name}: incomplete event")
            elif path.name.endswith(".bits.zlib"):
                samples[path.name] = base64.b64encode(payload).decode("ascii")
        except ValueError:
            errors.append(f"{path.name}: invalid JSON")
    if error is not None:
        events.append(
            dict(
                stage="pipeline", kind="failure", error_type=type(error).__name__, reason=safe_message(str(error))[:500]
            )
        )
    refs = [
        value
        for name in ("visual_artifact_ref", "canonical_geometry_ref")
        if isinstance(value := getattr(bundle, name, None), ProductArtifactRef)
    ]
    refs.extend(getattr(bundle, "camera_pose_refs", []))
    for event in events:
        if event.get("kind") == "source_binding":
            refs.append(ProductArtifactRef.model_validate(event["source_visual_ref"]))
    bundle_json = bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else json.dumps(str(type(bundle)))
    tails = {}
    tail_budget = 256 * 1024
    for root in (workspace, workspace / "sampro3d", workspace / "objectgs-producer/runtime"):
        for path in sorted(root.glob("*.log")):
            if path.is_symlink() or not tail_budget:
                continue
            size = min(8192, tail_budget)
            try:
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - size))
                    tail = stream.read(size)
                tails[str(path.relative_to(workspace))] = safe_message(tail.decode("utf-8", errors="replace"))
                tail_budget -= len(tail)
            except OSError:
                errors.append(f"{path.name}: log unavailable")
    if status == "produced":
        for stage in ("inputs", "seeds", "sam2", "segmentation", "lift", "membership", "collider", "object_binding"):
            if not (directory / f"{stage}.coverage.json").is_file():
                errors.append(f"{stage}: missing trace; producer evidence is incomplete")
    manifest = ObjectPipelineEvidence(
        job_id=job.job_id,
        run_id="run-" + uuid4().hex,
        input_revision=input_revision,
        status=status,
        config_checksum=getattr(job, "config_checksum", None),
        bundle_checksum=getattr(
            bundle, "artifact_checksum", "sha256:" + hashlib.sha256(bundle_json.encode()).hexdigest()
        ),
        source_refs=refs,
        events=events,
        coverage=coverage,
        samples=samples,
        log_tails=tails,
        truncated=truncated or bool(errors),
        collection_errors=errors,
    )
    payload = manifest.model_dump_json().encode()
    if len(payload) > MAX_EVIDENCE_BYTES:
        raise ValueError("diagnostic artifact exceeded its sealed byte limit")
    digest = hashlib.sha256(payload).hexdigest()
    reference = ProductArtifactRef(
        artifact_type="ObjectPipelineEvidence",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/scene/diagnostics/{digest}.json",
        artifact_checksum="sha256:" + digest,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=job.job_id,
    )
    published = publish(reference, payload)
    if published != reference:
        raise ValueError("evidence publisher changed content identity")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "evidence-ref.json").write_text(reference.model_dump_json(indent=2))
    logger.info(
        "Object evidence job=%s run=%s ref=%s checksum=%s",
        job.job_id,
        manifest.run_id,
        reference.artifact_uri,
        reference.artifact_checksum,
    )
    return reference


def capture_attempt(
    call: Callable[[], T],
    *,
    job: object,
    bundle: object,
    workspace: Path,
    publish: Callable,
    input_revision: str,
) -> T:
    """Evidence publication cannot turn failure into success or change an algorithm result."""
    error = None
    result = None
    try:
        result = call()
        return result
    except BaseException as caught:
        error = caught
        raise
    finally:
        if getattr(job, "job_id", None) and callable(publish):
            try:
                reference = seal_attempt(
                    job,
                    bundle,
                    workspace,
                    publish,
                    input_revision,
                    "cancelled" if isinstance(error, ProcessCancelledError) else "failed" if error else "produced",
                    error,
                )
                if isinstance(getattr(result, "provenance", None), dict):
                    result.provenance["object_pipeline_evidence"] = reference.model_dump(mode="json")
                if error is not None:
                    error.diagnostics_ref = reference
            except (OSError, ValueError, RuntimeError) as evidence_error:
                logger.warning("Object evidence unavailable job=%s cause=%s", job.job_id, type(evidence_error).__name__)
                if isinstance(getattr(result, "provenance", None), dict):
                    result.provenance["object_pipeline_evidence_status"] = "unavailable"
