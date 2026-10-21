"""T-070: bộ LOD của SOG lớn — tạo trên worker GPU lúc rảnh, lưu dưới thư mục job, file mục lục ghi sau cùng."""

import json
import zipfile
from pathlib import Path

import pytest

from src.services.orchestration.artifacts import lod

_CHECKSUM = "sha256:" + "a" * 64


def _sog(path: Path, count: int) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("meta.json", json.dumps({"version": 2, "count": count}))
    return path


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):  # noqa: ANN001, ANN201
    """splat-transform giả: ghi đúng đầu ra mà mỗi lệnh yêu cầu."""
    calls: list[tuple[str, ...]] = []

    def run(cli, *arguments, gpu=False):  # noqa: ANN001, ANN202
        calls.append(arguments)
        output = Path(next(a for a in reversed(arguments) if a.endswith((".ply", ".json"))))
        if output.name == "lod-meta.json":
            (output.parent / "0_0").mkdir(parents=True, exist_ok=True)
            (output.parent / "0_0" / "meta.json").write_text("{}")
            (output.parent / "0_0" / "means_l.webp").write_bytes(str(output).encode())  # khác nhau giữa hai lần tạo
            output.write_text(json.dumps({"lodLevels": 1, "filenames": ["0_0/meta.json"]}))
            return
        output.write_text("{}" if output.suffix == ".json" else "ply")

    monkeypatch.setattr(lod, "_run", run)
    return calls


def test_small_scene_needs_no_lod(tmp_path, fake_cli) -> None:  # noqa: ANN001
    assert lod.build_lod_bundle(tmp_path / "cli.mjs", _sog(tmp_path / "s.sog", 300_000), tmp_path / "work") is None
    assert fake_cli == []


def test_large_scene_builds_three_levels(tmp_path, fake_cli) -> None:  # noqa: ANN001
    out = lod.build_lod_bundle(tmp_path / "cli.mjs", _sog(tmp_path / "s.sog", 1_860_000), tmp_path / "work")
    assert out is not None and (out / "lod-meta.json").is_file()
    bundle_call = fake_cli[-1]
    assert bundle_call.count("-l") == 3 and bundle_call[-1].endswith("lod-meta.json")


def test_publish_writes_index_last_and_pushes_to_remote(tmp_path, fake_cli) -> None:  # noqa: ANN001
    out = lod.build_lod_bundle(tmp_path / "cli.mjs", _sog(tmp_path / "s.sog", 1_860_000), tmp_path / "work")
    pushed: list[str] = []

    class Remote:
        def push(self, relative, path):  # noqa: ANN001, ANN202
            pushed.append(relative)

    root = tmp_path / "artifacts"
    assert lod.lod_ready(root, None, "job-a", _CHECKSUM) is False
    lod.publish_lod_bundle(root, Remote(), "job-a", _CHECKSUM, out)
    assert lod.lod_ready(root, None, "job-a", _CHECKSUM) is True
    assert len(list((root / lod.lod_relative_dir("job-a", _CHECKSUM)).glob("b*/0_0/means_l.webp"))) == 1
    assert pushed[-1].endswith("/lod-meta.json")
    assert any(item.endswith("0_0/means_l.webp") for item in pushed[:-1])


def test_valid_bundle_paths_only() -> None:
    for good in ("lod-meta.json", "0_0/meta.json", "12_3/shN_labels.webp", "b0123456789ab/0_0/meta.json"):
        assert lod.valid_bundle_path(good)
    for bad in (
        "../x",
        "0_0/../../secret",
        "0_0/x.png",
        "/etc/passwd",
        "0_0/meta.json/..",
        "a_b/meta.json",
        "",
        "bxyz/0_0/meta.json",
        "b0123456789ab/lod-meta.json",
    ):
        assert not lod.valid_bundle_path(bad)


class _Registry:
    """Registry giả: một job với hai SOG trong allow-list."""

    def __init__(self, root: Path, sogs: dict[str, Path]) -> None:
        from types import SimpleNamespace

        self.runtime_resolver = SimpleNamespace(artifact_root=root, remote=None)
        self.sogs = sogs

    def lod_candidates(self):  # noqa: ANN201
        from types import SimpleNamespace

        return [
            ("job-a", SimpleNamespace(artifact_uri=f"artifact://jobs/job-a/{name}", artifact_checksum=checksum))
            for checksum, name in ((c, p.name) for c, p in self.sogs.items())
        ]

    def resolve_artifact(self, job_id, reference):  # noqa: ANN001, ANN201
        return self.sogs[reference.artifact_checksum]


def test_idle_builder_makes_one_bundle_per_tick_and_remembers_small_scenes(tmp_path, fake_cli) -> None:  # noqa: ANN001
    big, small = "sha256:" + "b" * 64, "sha256:" + "c" * 64
    registry = _Registry(
        tmp_path / "artifacts",
        {small: _sog(tmp_path / "small.sog", 200_000), big: _sog(tmp_path / "big.sog", 1_900_000)},
    )
    builder = lod.LodBuilder(registry, tmp_path / "cli.mjs", tmp_path / "work", tmp_path / "skip")
    assert builder.tick() is True  # small: marked, no build
    assert builder.tick() is True  # big: built
    assert lod.lod_ready(tmp_path / "artifacts", None, "job-a", big)
    assert builder.tick() is False  # nothing left
    assert sum(1 for call in fake_cli if call[-1].endswith("lod-meta.json")) == 1


def test_failed_build_is_retried_only_after_a_day(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    big = "sha256:" + "d" * 64
    registry = _Registry(tmp_path / "artifacts", {big: _sog(tmp_path / "big.sog", 1_900_000)})
    attempts = []

    def broken(cli, *arguments, gpu=False):  # noqa: ANN001, ANN202
        attempts.append(arguments)
        raise lod.LodBuildError("boom")

    monkeypatch.setattr(lod, "_run", broken)
    builder = lod.LodBuilder(registry, tmp_path / "cli.mjs", tmp_path / "work", tmp_path / "skip")
    assert builder.tick() is True
    assert builder.tick() is False
    assert len(attempts) == 1
    marker = next((tmp_path / "skip").iterdir())
    import os

    old = marker.stat().st_mtime - 2 * 86400
    os.utime(marker, (old, old))
    assert builder.tick() is True
    assert len(attempts) == 2


def test_registry_lists_viewable_sogs_and_authorizes_by_checksum(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from src.models.contracts.artifacts import ArtifactRef
    from src.services.orchestration.artifacts.store import ArtifactNotFoundError
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job_id = registry.list_jobs(registry.list_projects()[0].project_id)[0].job_id

    def ref(name: str, checksum: str) -> ArtifactRef:
        return ArtifactRef(
            artifact_type="GaussianSOG",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/{name}",
            artifact_checksum=checksum,
            data_class="derived",
            producer_stage="ST-VISUAL-RECON",
            job_id=job_id,
        )

    sog, ply = ref("scene.sog", "sha256:" + "1" * 64), ref("object.ply", "sha256:" + "2" * 64)
    monkeypatch.setattr(
        registry, "_product_visible_references", lambda job: {sog.artifact_uri: sog, ply.artifact_uri: ply}
    )
    assert [(job, item.artifact_uri) for job, item in registry.lod_candidates()] == [(job_id, sog.artifact_uri)]
    assert registry.authorized_sog_by_checksum(job_id, sog.artifact_checksum) == sog
    with pytest.raises(ArtifactNotFoundError):
        registry.authorized_sog_by_checksum(job_id, ply.artifact_checksum)
    with pytest.raises(ArtifactNotFoundError):
        registry.authorized_sog_by_checksum(job_id, "sha256:" + "9" * 64)


def test_idle_builder_only_on_a_gpu_worker_with_the_runtime(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    cli = tmp_path / "cli.mjs"
    cli.write_text("")
    registry = SimpleNamespace(runtime_resolver=SimpleNamespace(artifact_root=tmp_path / "artifacts"))
    monkeypatch.setenv("R2S_VOXEL_CLI", str(cli))
    monkeypatch.setattr(lod.shutil, "which", lambda name: None)
    assert lod.idle_lod_builder(registry, tmp_path / "worker") is None
    monkeypatch.setattr(lod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    assert isinstance(lod.idle_lod_builder(registry, tmp_path / "worker"), lod.LodBuilder)
    monkeypatch.delenv("R2S_VOXEL_CLI")
    assert lod.idle_lod_builder(registry, tmp_path / "worker") is None


def test_job_view_lods_builds_each_large_sog_once(tmp_path, fake_cli) -> None:  # noqa: ANN001
    """T-070 pipeline step: every large SOG of the finished job gets a bundle; small or ready ones are skipped."""
    from types import SimpleNamespace

    big, small = "sha256:" + "e" * 64, "sha256:" + "f" * 64
    paths = {big: _sog(tmp_path / "big.sog", 1_900_000), small: _sog(tmp_path / "small.sog", 100_000)}
    resolver = SimpleNamespace(
        artifact_root=tmp_path / "artifacts", remote=None, require=lambda ref: paths[ref.artifact_checksum]
    )
    refs = [
        SimpleNamespace(artifact_checksum=big),
        SimpleNamespace(artifact_checksum=small),
        SimpleNamespace(artifact_checksum=big),
    ]
    assert lod.build_job_view_lods(resolver, "job-a", refs, tmp_path / "cli.mjs", tmp_path / "work") == 1
    assert lod.lod_ready(tmp_path / "artifacts", None, "job-a", big)
    assert lod.build_job_view_lods(resolver, "job-a", refs, tmp_path / "cli.mjs", tmp_path / "work") == 0


def test_each_build_publishes_into_its_own_folder_and_the_first_index_wins(tmp_path, fake_cli) -> None:  # noqa: ANN001
    """Review fix: two builders of the same SOG never mix chunks; the index names the folder of one complete build."""
    from src.services.orchestration.artifacts.remote import ArtifactAlreadyExistsError

    stored: dict[str, bytes] = {}

    class Remote:
        def push(self, relative, path):  # noqa: ANN001, ANN202
            data = path.read_bytes()
            if relative in stored and stored[relative] != data:
                raise ArtifactAlreadyExistsError(relative)
            stored[relative] = data

    root_a, root_b = tmp_path / "pod-a", tmp_path / "pod-b"
    first = lod.build_lod_bundle(tmp_path / "cli.mjs", _sog(tmp_path / "s.sog", 1_860_000), tmp_path / "wa")
    second = lod.build_lod_bundle(tmp_path / "cli.mjs", _sog(tmp_path / "t.sog", 1_860_000), tmp_path / "wb")
    assert lod.publish_lod_bundle(root_a, Remote(), "job-a", _CHECKSUM, first) is True
    assert lod.publish_lod_bundle(root_b, Remote(), "job-a", _CHECKSUM, second) is False
    index_key = f"{lod.lod_relative_dir('job-a', _CHECKSUM)}/lod-meta.json"
    names = json.loads(stored[index_key])["filenames"]
    folders = {name.split("/")[0] for name in names}
    assert len(folders) == 1 and next(iter(folders)).startswith("b")
    for name in names:
        assert lod.valid_bundle_path(name)
        assert f"{lod.lod_relative_dir('job-a', _CHECKSUM)}/{name}" in stored


def test_idle_builder_skips_leased_jobs_and_reuses_its_candidate_list(tmp_path, fake_cli) -> None:  # noqa: ANN001
    """Review fix: the job being finished (live lease) is the runner's; the candidate walk is not redone every tick."""
    big = "sha256:" + "4" * 64
    registry = _Registry(tmp_path / "artifacts", {big: _sog(tmp_path / "big.sog", 1_900_000)})
    walks = []
    original = registry.lod_candidates
    registry.lod_candidates = lambda: walks.append(1) or original()
    busy = {"job-a"}
    builder = lod.LodBuilder(
        registry,
        tmp_path / "cli.mjs",
        tmp_path / "work",
        tmp_path / "skip",
        busy=lambda job: job in busy,
        now=lambda: 0.0,
    )
    assert builder.tick() is False
    busy.clear()
    assert builder.tick() is True
    assert builder.tick() is False
    assert len(walks) == 1


def test_small_scene_marker_is_shared_through_the_object_store(tmp_path, fake_cli) -> None:  # noqa: ANN001
    """Review fix: a fresh GPU pod must not re-download a small SOG another pod already checked."""
    small = "sha256:" + "5" * 64
    objects: dict[str, bytes] = {}

    class Remote:
        def push(self, relative, path):  # noqa: ANN001, ANN202
            objects[relative] = path.read_bytes()

        def head(self, relative):  # noqa: ANN001, ANN202
            return object() if relative in objects else None

    first = _Registry(tmp_path / "pod-a", {small: _sog(tmp_path / "small.sog", 100_000)})
    first.runtime_resolver.remote = Remote()
    assert lod.LodBuilder(first, tmp_path / "cli.mjs", tmp_path / "wa", tmp_path / "skip-a").tick() is True

    second = _Registry(tmp_path / "pod-b", {small: tmp_path / "missing.sog"})
    second.runtime_resolver.remote = first.runtime_resolver.remote
    assert lod.LodBuilder(second, tmp_path / "cli.mjs", tmp_path / "wb", tmp_path / "skip-b").tick() is False


def _bundle(root: Path, job_id: str, checksum: str, build: str = "b0123456789ab") -> Path:
    folder = root / lod.lod_relative_dir(job_id, checksum)
    for chunk in ("0_0", "1_0"):
        (folder / build / chunk).mkdir(parents=True)
        (folder / build / chunk / "meta.json").write_text("{}")
        (folder / build / chunk / "means_l.webp").write_bytes(chunk.encode())
    (folder / "bdeadbeef0000" / "0_0").mkdir(parents=True)  # lần tạo thua cuộc: mục lục không trỏ tới
    (folder / "bdeadbeef0000" / "0_0" / "meta.json").write_text("{}")
    (folder / lod.INDEX).write_text(json.dumps({"filenames": [f"{build}/0_0/meta.json", f"{build}/1_0/meta.json"]}))
    return folder


def test_copy_lod_bundle_takes_the_index_and_only_the_chunks_it_names(tmp_path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _bundle(source, "job-a", _CHECKSUM)
    assert lod.copy_lod_bundle(source, None, target, "job-a", _CHECKSUM) is True
    copied = target / lod.lod_relative_dir("job-a", _CHECKSUM)
    names = sorted(path.relative_to(copied).as_posix() for path in copied.rglob("*") if path.is_file())
    assert names == [
        "b0123456789ab/0_0/means_l.webp",
        "b0123456789ab/0_0/meta.json",
        "b0123456789ab/1_0/means_l.webp",
        "b0123456789ab/1_0/meta.json",
        "lod-meta.json",
    ]
    assert lod.lod_ready(target, None, "job-a", _CHECKSUM)


def test_copy_lod_bundle_without_a_complete_bundle_copies_nothing(tmp_path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    folder = _bundle(source, "job-a", _CHECKSUM)
    (folder / lod.INDEX).unlink()  # bộ đang tạo dở: chưa có mục lục
    assert lod.copy_lod_bundle(source, None, target, "job-a", _CHECKSUM) is False
    assert not target.exists()


def test_copy_lod_bundle_rejects_an_index_pointing_outside_the_bundle(tmp_path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    folder = _bundle(source, "job-a", _CHECKSUM)
    (folder / lod.INDEX).write_text(json.dumps({"filenames": ["../../secret/meta.json"]}))
    with pytest.raises(lod.LodBuildError):
        lod.copy_lod_bundle(source, None, target, "job-a", _CHECKSUM)


def test_copy_lod_bundle_pulls_a_bundle_kept_only_in_the_object_store(tmp_path) -> None:
    store, cache, target = tmp_path / "store", tmp_path / "cache", tmp_path / "target"
    _bundle(store, "job-a", _CHECKSUM)

    class Remote:
        def head(self, relative):  # noqa: ANN001, ANN202
            return object() if (store / relative).is_file() else None

        def fetch(self, relative, destination, expected_checksum=None):  # noqa: ANN001, ANN202
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((store / relative).read_bytes())

        def pull_tree(self, relative_dir, local_dir, *, skip_top=frozenset()):  # noqa: ANN001, ANN202
            for path in (store / relative_dir).rglob("*"):
                if path.is_file():
                    destination = local_dir / path.relative_to(store / relative_dir)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(path.read_bytes())

    assert lod.copy_lod_bundle(cache, Remote(), target, "job-a", _CHECKSUM) is True
    assert (target / lod.lod_relative_dir("job-a", _CHECKSUM) / "b0123456789ab/1_0/means_l.webp").read_bytes() == b"1_0"


def test_copy_view_lods_copies_each_sog_bundle_once_and_skips_sogs_without_one(tmp_path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    other = "sha256:" + "b" * 64
    _bundle(source, "job-a", _CHECKSUM)
    references = [
        {"artifact_uri": "artifact://jobs/job-a/scene/environment/x/background.sog", "artifact_checksum": _CHECKSUM},
        {"artifact_uri": "artifact://jobs/job-a/reconstruction/preview.sog", "artifact_checksum": _CHECKSUM},
        {"artifact_uri": "artifact://jobs/job-a/reconstruction/small.sog", "artifact_checksum": other},
        {"artifact_uri": "artifact://jobs/job-a/scene/scene_ir.json", "artifact_checksum": "sha256:" + "c" * 64},
    ]
    assert lod.copy_view_lods(source, None, target, "job-a", references) == 1
    assert lod.lod_ready(target, None, "job-a", _CHECKSUM)
    assert not (target / lod.lod_relative_dir("job-a", other)).exists()
