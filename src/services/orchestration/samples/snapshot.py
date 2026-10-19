"""Copy an immutable, checksummed artifact graph without rewriting its identities."""

import errno
import json
import os
import shutil

from src.services.orchestration.artifacts import ArtifactResolver, sha256_file
from src.services.orchestration.samples.bundle import DemoUnavailableError


def copy_artifact_graph(resolver: ArtifactResolver, target: ArtifactResolver, roots: list[object]) -> list[str]:
    """Copy the referenced product graph only; never inventory a source job's private history.

    Existing artifact bytes are immutable under FilesystemArtifactStore. Hard links share
    those bytes; new revisions and worker output use independent paths in the session.
    Cleanup only unlinks entries below the session root.
    """
    pending = list(roots)
    copied: dict[str, str] = {}
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
            continue
        if not isinstance(value, dict):
            continue
        uri = value.get("artifact_uri")
        checksum = value.get("artifact_checksum", value.get("checksum"))
        if isinstance(uri, str) and isinstance(checksum, str):
            if uri in copied:
                if copied[uri] != checksum:
                    raise DemoUnavailableError(
                        f"Snapshot chứa reference khác checksum: {uri}, {copied[uri]}, {checksum}"
                    )
                continue
            if value.get("data_class") in {"ground_truth", "evaluation_only"}:
                continue
            source = resolver.require_uri(uri, checksum)
            destination = target.resolve(uri)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if sha256_file(destination) != checksum:
                    raise DemoUnavailableError("Artifact của snapshot trùng tên nhưng khác checksum")
            else:
                try:
                    os.link(source, destination)
                except OSError as error:
                    if error.errno not in {errno.EXDEV, errno.EPERM, errno.ENOTSUP}:
                        raise
                    with source.open("rb") as incoming, destination.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
            copied[uri] = checksum
            if source.suffix.lower() == ".json" and not value.get("_demo_shallow"):
                payload = json.loads(source.read_bytes())
                # Product artifact envelopes carry their own content checksum, while the
                # incoming reference binds serialized file bytes. That envelope is not a dependency.
                if isinstance(payload, dict) and payload.get("artifact_uri") == uri:
                    payload = {
                        key: item
                        for key, item in payload.items()
                        if key not in {"artifact_uri", "artifact_checksum", "checksum"}
                    }
                pending.append(payload)
        pending.extend(value.values())
    return list(copied)
