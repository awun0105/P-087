"""Reproducible REC-06 fixture handoff; không đọc Aisle_CW/GT hoặc xác nhận scale thật.

python -m tests.test_reconstruction.rec06_smoke --output data/rec06_smoke/<new-attempt>
Source reconstruction và review authority là fixture; resolver/store/math là code thật.
"""

import argparse
import json
from pathlib import Path

from src.services.reconstruction.rgb.metric_models import MetricConfirmation, independent_distance_error
from tests.test_reconstruction.rec06_fixtures import acceptance_for, metric_fixture


def fixture_error(record: MetricConfirmation) -> float:
    """Measurement riêng trong fixture, không áp tolerance acceptance chưa khóa."""
    data = record.preview.request.anchor.model_dump()
    data.update(anchor_id="independent-y", point_a=(0, 0, 3), point_b=(0, 0.25, 3), distance_m=0.51)
    sample = type(record.preview.request.anchor).model_validate(data)
    return independent_distance_error(record, sample)


def write_json(path: Path, payload: dict) -> None:
    """Attempt evidence không overwrite và không cho nonfinite JSON."""
    with path.open("x") as stream:
        stream.write(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n")


def main() -> None:
    """Lưu immutable confirmation + conversion plan và measured fixture evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    service, request = metric_fixture(args.output)
    preview = service.preview(request)
    record = service.confirm(preview, acceptance_for(service, preview))
    reference = service.publish(record, "rec06-fixture")
    if service.load(reference) != record:
        raise ValueError("confirmation roundtrip differs")
    plan = service.conversion_plan(reference, request.anchor.source_master)
    report = dict(
        evidence_kind="synthetic_fixture",
        product_metric_confirmed=False,
        source_reconstruction="fixture",
        acceptance_authority="fixture_verifier",
        confirmation_ref=reference.model_dump(mode="json"),
        record_checksum=record.record_checksum,
        preview_checksum=preview.checksum(),
        transform=plan.transform.model_dump(mode="json"),
        independent_distance_error_m=fixture_error(record),
        point_before=[1, 2, 3],
        point_after=list(plan.transform.apply_point((1, 2, 3))),
        payload_converted=plan.payload_converted,
    )
    write_json(args.output / "conversion-plan.json", plan.model_dump(mode="json"))
    write_json(args.output / "evidence.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
