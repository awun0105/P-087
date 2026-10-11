"""Strict parsers and unit conversion for user-supplied timestamp inventories."""

import math

from src.models.contracts.input_assembly import TimestampUnit


class TimestampRowFormatError(ValueError):
    """The text is not an unambiguous one-column timestamp inventory."""


class TimestampRowValueError(ValueError):
    """A timestamp inventory has values that cannot define an ordered clock."""


_SECONDS_PER_UNIT = {
    TimestampUnit.SECONDS: 1.0,
    TimestampUnit.MILLISECONDS: 1e-3,
    TimestampUnit.MICROSECONDS: 1e-6,
    TimestampUnit.NANOSECONDS: 1e-9,
}


def parse_timestamp_rows(text: str) -> tuple[float, ...]:
    """Parse one finite, strictly increasing numeric timestamp per non-comment row."""
    values: list[float] = []
    previous = -math.inf
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) != 1:
            raise TimestampRowFormatError("timestamp rows must contain one value each")
        try:
            value = float(parts[0])
        except ValueError as error:
            raise TimestampRowFormatError("timestamp rows must contain numeric values") from error
        if not math.isfinite(value):
            raise TimestampRowValueError("Timestamp rows must contain finite values.")
        if value <= previous:
            raise TimestampRowValueError("Timestamp rows must be strictly increasing.")
        values.append(value)
        previous = value
    if not values:
        raise TimestampRowFormatError("timestamp inventory is empty")
    return tuple(values)


def timestamps_in_seconds(values: tuple[float, ...], unit: TimestampUnit) -> tuple[float, ...]:
    """Convert exact scan timestamps to seconds without interpolation or clock shifts."""
    scale = _SECONDS_PER_UNIT[unit]
    seconds = tuple(value * scale for value in values)
    if not all(math.isfinite(value) for value in seconds):
        raise TimestampRowValueError("Converted timestamps must be finite.")
    if any(current <= previous for previous, current in zip(seconds, seconds[1:], strict=False)):
        raise TimestampRowValueError("Converted timestamps must remain strictly increasing.")
    return seconds
