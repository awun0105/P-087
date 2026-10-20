"""Remote workers must have every input artifact the prepare subprocess reads (local-only resolver)."""

from types import SimpleNamespace

import pytest

from src.services.orchestration.jobs import runner


class RecordingResolver:
    def __init__(self) -> None:
        self.required: list[object] = []
        self.required_uris: list[tuple[str, str]] = []

    def require(self, reference):  # noqa: ANN001, ANN201
        self.required.append(reference)
        return SimpleNamespace(read_bytes=lambda: b"{}")

    def require_uri(self, uri: str, checksum: str) -> None:
        self.required_uris.append((uri, checksum))


@pytest.mark.parametrize("prepared", [True, False])
def test_pull_input_fetches_the_prepared_video_frame_map(monkeypatch: pytest.MonkeyPatch, prepared: bool) -> None:
    frame_map = SimpleNamespace(artifact_uri="artifact://jobs/upload-x/input/video_frame_map_abc.jsonl")
    manifest = SimpleNamespace(
        files=[
            SimpleNamespace(artifact_uri="artifact://jobs/upload-x/input/source.mp4", checksum="sha256:" + "1" * 64)
        ],
        video_preparation=SimpleNamespace(frame_map_ref=frame_map) if prepared else None,
    )
    monkeypatch.setattr(runner.InputManifest, "model_validate_json", staticmethod(lambda _: manifest))
    resolver = RecordingResolver()
    manifest_ref = object()
    assert runner._pull_input(resolver, manifest_ref) is manifest
    assert resolver.required_uris == [("artifact://jobs/upload-x/input/source.mp4", "sha256:" + "1" * 64)]
    assert resolver.required == ([manifest_ref, frame_map] if prepared else [manifest_ref])
