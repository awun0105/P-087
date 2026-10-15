"""Bounded, append-only diagnostics shared with isolated Python runtimes (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path


class EvidenceRecorder:
    """One writer per stage; diagnostic limits never control algorithm decisions.

    ponytail: at most 1 MiB of event JSON and 2 MiB of compressed mask samples per stage.
    Truncation is explicit; no random sampling or source array mutation is used.
    """

    def __init__(
        self, directory: Path | None, stage: str, *, event_budget: int = 1024**2, mask_budget: int = 2 * 1024**2
    ) -> None:
        self.directory = directory
        self.stage = stage
        self.event_budget = event_budget
        self.mask_budget = mask_budget
        self.written = 0
        self.dropped = 0
        self.mask_bytes = 0
        self.masks_dropped = 0
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / f"{stage}.jsonl"
            self.path.write_bytes(b"")
            self._coverage()

    @property
    def enabled(self) -> bool:
        return self.directory is not None

    def _coverage(self) -> None:
        if self.directory is not None:
            payload = json.dumps(
                dict(
                    stage=self.stage,
                    event_bytes=self.written,
                    events_dropped=self.dropped,
                    mask_bytes=self.mask_bytes,
                    masks_dropped=self.masks_dropped,
                    event_budget=self.event_budget,
                    mask_budget=self.mask_budget,
                ),
                sort_keys=True,
            )
            (self.directory / f"{self.stage}.coverage.json").write_text(payload)

    def emit(self, kind: str, **values: object) -> None:
        if self.directory is None:
            return
        payload = (
            json.dumps(dict(stage=self.stage, kind=kind, **values), sort_keys=True, allow_nan=False) + "\n"
        ).encode()
        if self.written + len(payload) > self.event_budget:
            self.dropped += 1
        else:
            with self.path.open("ab") as stream:
                stream.write(payload)
            self.written += len(payload)
        self._coverage()

    def mask(self, key: str, packed: bytes, shape: tuple[int, ...]) -> None:
        """Store losslessly packed bits, bounded independently from decision metadata."""
        if self.directory is None:
            return
        digest = hashlib.sha256(packed).hexdigest()
        payload = zlib.compress(packed)
        filename = f"{self.stage}-mask-{digest}.bits.zlib"
        path = self.directory / filename
        stored = path.exists()
        if not stored and self.mask_bytes + len(payload) <= self.mask_budget:
            path.write_bytes(payload)
            self.mask_bytes += len(payload)
            stored = True
        if not stored:
            self.masks_dropped += 1
        self.emit(
            "mask_sample",
            key=key,
            packed_checksum="sha256:" + digest,
            shape=list(shape),
            encoding="numpy.packbits-big,zlib",
            file=filename if stored else None,
            omitted_reason=None if stored else "mask_budget",
        )


def recorder(directory: str | Path | None, stage: str) -> EvidenceRecorder:
    return EvidenceRecorder(Path(directory) if directory else None, stage)
