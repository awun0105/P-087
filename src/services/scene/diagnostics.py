"""Bounded, append-only diagnostics shared with isolated Python runtimes (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
import zlib
from pathlib import Path


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "nonfinite"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return {"unsupported_type": type(value).__name__}


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
        self.mask_count = 0
        self.event_counts: dict[str, int] = {}
        self.reason_counts: dict[str, int] = {}
        self.masks_dropped = 0
        if directory is not None:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self.path = directory / f"{stage}.jsonl"
                self.path.write_bytes(b"")
                self._coverage()
            except OSError as error:
                self.directory = None
                logging.getLogger(__name__).warning("Diagnostic writer unavailable: %s", type(error).__name__)

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
                    masks_retained=self.mask_count,
                    max_mask_samples=32,
                    masks_dropped=self.masks_dropped,
                    event_budget=self.event_budget,
                    mask_budget=self.mask_budget,
                    event_counts=self.event_counts,
                    reason_counts=self.reason_counts,
                ),
                sort_keys=True,
            )
            (self.directory / f"{self.stage}.coverage.json").write_text(payload)

    def emit(self, kind: str, **values: object) -> None:
        try:
            self._emit(kind, **values)
        except OSError as error:
            self.directory = None
            logging.getLogger(__name__).warning("Diagnostic writer unavailable: %s", type(error).__name__)

    def _emit(self, kind: str, **values: object) -> None:
        if self.directory is None:
            return
        self.event_counts[kind] = self.event_counts.get(kind, 0) + 1
        reasons = list(values.get("reasons", []))
        if isinstance(values.get("reason"), str):
            reasons.append(values["reason"])
        for reason in reasons:
            if (
                isinstance(reason, str)
                and len(reason) <= 80
                and (reason in self.reason_counts or len(self.reason_counts) < 64)
            ):
                self.reason_counts[reason] = self.reason_counts.get(reason, 0) + 1
        payload = (
            json.dumps(
                _json_safe(dict(stage=self.stage, kind=kind, time_ns=time.monotonic_ns(), **values)),
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode()
        if self.written + len(payload) > self.event_budget:
            self.dropped += 1
        else:
            with self.path.open("ab") as stream:
                stream.write(payload)
            self.written += len(payload)
        self._coverage()

    def mask(self, key: str, packed: bytes, shape: tuple[int, ...]) -> None:
        try:
            self._mask(key, packed, shape)
        except OSError as error:
            self.directory = None
            logging.getLogger(__name__).warning("Diagnostic mask unavailable: %s", type(error).__name__)

    def _mask(self, key: str, packed: bytes, shape: tuple[int, ...]) -> None:
        """Store losslessly packed bits, bounded independently from decision metadata."""
        if self.directory is None:
            return
        digest = hashlib.sha256(packed).hexdigest()
        filename = f"{self.stage}-mask-{digest}.bits.zlib"
        path = self.directory / filename
        stored = path.exists()
        omitted_reason = "sample_limit" if self.mask_count >= 32 else "mask_budget"
        if not stored and self.mask_count < 32 and self.mask_bytes < self.mask_budget:
            payload = zlib.compress(packed)
            if self.mask_bytes + len(payload) <= self.mask_budget:
                path.write_bytes(payload)
                self.mask_bytes += len(payload)
                self.mask_count += 1
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
            omitted_reason=None if stored else omitted_reason,
        )


def recorder(directory: str | Path | None, stage: str) -> EvidenceRecorder:
    return EvidenceRecorder(Path(directory) if directory else None, stage)
