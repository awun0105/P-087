"""CPU adapter/runner contract tests; these do not certify upstream ObjectGS training."""

import json
import sys
from pathlib import Path
from threading import Event

import numpy as np
import pytest
import trimesh
import yaml
from PIL import Image

from src.services.process_control import ProcessCancelledError
from src.services.scene import objectgs


def inputs(tmp_path):
    rows = np.zeros(6, dtype=[(name, "<f4") for name in ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2"]])
    rows["x"] = np.arange(6) + 10
    rows["y"] = 2
    rows["z"] = 3
    labels = np.array([-1, -1, 7, 7, 42, 42], dtype=np.int32)
    image = tmp_path / "rgb.png"
    mask = tmp_path / "mask.png"
    Image.new("RGB", (4, 3), (10, 20, 30)).save(image)
    Image.fromarray(np.array([[0, 1, 2, 0]] * 3, dtype=np.uint8)).save(mask)
    view = objectgs.ObjectGSView(
        image_path=image,
        mask_path=mask,
        width=4,
        height=3,
        parameters=(100, 110, 2, 1.5),
        center=(4, 5, 6),
        rotation_xyzw=(0, 0, np.sqrt(0.5), np.sqrt(0.5)),
    )
    return rows, labels, {"7": "chair", "42": "table"}, [view]


def test_dataset_keeps_metric_points_camera_pose_and_explicit_label_mapping(tmp_path):
    args = inputs(tmp_path)
    dest = tmp_path / "data/job-test"
    assert objectgs.prepare_dataset(*args, dest) == {"chair": 1, "table": 2}
    payload = (dest / "sparse/0/points3D.ply").read_bytes()
    end = payload.index(b"end_header\n") + len(b"end_header\n")
    dtype = [(name, "<f4") for name in ["x", "y", "z", "nx", "ny", "nz"]] + [
        (name, "u1") for name in ["red", "green", "blue", "label"]
    ]
    anchors = np.frombuffer(payload, dtype=dtype, offset=end)
    np.testing.assert_array_equal(anchors["x"], args[0]["x"])
    np.testing.assert_array_equal(anchors["label"], [0, 0, 1, 1, 2, 2])
    camera = (dest / "sparse/0/cameras.txt").read_text().split()
    assert camera[:4] == ["1", "PINHOLE", "4", "3"]
    np.testing.assert_allclose(list(map(float, camera[4:])), [100, 110, 2, 1.5])
    pose = (dest / "sparse/0/images.txt").read_text().splitlines()[0].split()
    np.testing.assert_allclose(list(map(float, pose[1:8])), [np.sqrt(0.5), 0, 0, -np.sqrt(0.5), -5, 4, -6], atol=1e-8)
    with Image.open(dest / "object_mask/frame_000001.png") as mask:
        assert set(np.unique(mask)) == {0, 1, 2}


@pytest.mark.parametrize("failure", ["unknown", "dimension", "quat", "empty", "background"])
def test_invalid_dataset_inputs_fail_before_creating_output(tmp_path, failure):
    rows, labels, mapping, views = inputs(tmp_path)
    if failure == "unknown":
        labels[0] = 999
    if failure == "dimension":
        views = [views[0].model_copy(update={"width": 5})]
    if failure == "quat":
        views = [views[0].model_copy(update={"rotation_xyzw": (0, 0, 0, 2)})]
    if failure == "empty":
        labels[labels == 42] = 7
    if failure == "background":
        labels[labels == -1] = 7
    dest = tmp_path / "bad"
    with pytest.raises(ValueError):
        objectgs.prepare_dataset(rows, labels, mapping, views, dest)
    assert not dest.exists()


def test_runner_requires_pinned_revisions_and_honors_cancellation(tmp_path, monkeypatch):
    runtime = objectgs.ObjectGSRuntime(python=Path(sys.executable), repository=tmp_path, gsplat_repository=tmp_path)
    monkeypatch.setattr(objectgs, "_revision", lambda _: "a" * 40)
    with pytest.raises(ValueError, match="pinned revisions"):
        objectgs.run_objectgs(runtime, tmp_path, tmp_path / "work")
    event = Event()
    event.set()
    with pytest.raises(ProcessCancelledError):
        objectgs.run_objectgs(runtime, tmp_path, tmp_path / "work", cancel_event=event)
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("shared_cache", [False, True])
def test_runner_contract_calls_train_then_each_numeric_label_never_minus_one(tmp_path, monkeypatch, shared_cache):
    repo = tmp_path / "upstream"
    template = repo / "config/objectgs/2d/lerf_mask/config.yaml"
    template.parent.mkdir(parents=True)
    template.write_text(yaml.safe_dump({"model_params": {}, "optim_params": {}, "pipeline_params": {}}))
    gsplat = tmp_path / "gsplat"
    gsplat.mkdir()
    python = tmp_path / "isolated/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    runtime = objectgs.ObjectGSRuntime(
        python=python,
        repository=repo,
        gsplat_repository=gsplat,
        iterations=2,
        gpu_device=3,
        extension_cache_dir=tmp_path / "compiler-cache" if shared_cache else None,
    )
    dataset = tmp_path / "data/job-test"
    rows, labels, mapping, views = inputs(tmp_path)
    objectgs.prepare_dataset(rows, labels, mapping, views * 11, dataset)
    monkeypatch.setattr(
        objectgs, "_revision", lambda p: objectgs.OBJECTGS_COMMIT if p == repo else objectgs.GSPLAT_COMMIT
    )
    calls = []

    def process(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "-c":
            Path(command[-2]).write_text(json.dumps({"fixture_runtime": True}))
            return 0
        model = kwargs["cwd"] / "outputs/p087/objectgs/job-test/run"
        if "--scene-name" in command:
            model.mkdir(parents=True)
            (model / "config.yaml").write_text("model_params: {}")
            checkpoint = model / "point_cloud/iteration_2"
            checkpoint.mkdir(parents=True)
            for name in ["point_cloud.ply", "opacity_mlp.pt", "cov_mlp.pt", "color_mlp.pt"]:
                (checkpoint / name).write_bytes(b"fixture checkpoint, not a real ObjectGS model")
        else:
            label = command[command.index("--query_label_id") + 1]
            path = model / f"train/id_{label}/mesh/fuse.ply"
            path.parent.mkdir(parents=True)
            path.write_bytes(trimesh.creation.box().export(file_type="ply"))
        return 0

    monkeypatch.setattr(objectgs, "run_cancellable_process", process)
    receipt = objectgs.run_objectgs(runtime, dataset, tmp_path / "work")
    assert [call[0][call[0].index("--query_label_id") + 1] for call in calls if "--query_label_id" in call[0]] == [
        "1",
        "2",
    ]
    assert all(call[1]["environment"]["CUDA_VISIBLE_DEVICES"] == "3" for call in calls)
    assert all(call[1]["environment"]["CPLUS_INCLUDE_PATH"] == str(python.parent.parent / "include") for call in calls)
    if shared_cache:
        assert all(call[1]["environment"]["TORCH_EXTENSIONS_DIR"] == str(tmp_path / "compiler-cache") for call in calls)
    assert set(receipt["objects"]) == {"chair", "table"}
    assert receipt["coordinate_frame"] == "world"
    assert receipt["export_config"] == {
        "voxel_size_m": 0.01,
        "depth_trunc_m": 10.0,
        "num_cluster": 1,
        "mesh_variant": "raw_fuse",
    }
    config = yaml.safe_load((tmp_path / "work/config.yaml").read_text())
    assert config["model_params"]["source_path"] == str(dataset.parent)
    assert config["optim_params"]["iterations"] == 2
    assert json.loads((tmp_path / "work/result.json").read_text())["upstream_commit"] == objectgs.OBJECTGS_COMMIT


def test_shared_extension_cache_rejects_concurrent_process_and_releases_after_failure(tmp_path):
    import fcntl

    cache = tmp_path / "cache"
    cache.mkdir()
    with (cache / ".p087-process.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="cache is in use"):
            with objectgs._extension_cache_lock(cache):
                pytest.fail("must not execute against another process's cache")
    with pytest.raises(ValueError):
        with objectgs._extension_cache_lock(cache):
            raise ValueError("fixture failure")
    with objectgs._extension_cache_lock(cache):
        pass


def test_prepared_stage_converts_world_mesh_to_rotated_object_local_once(tmp_path, monkeypatch):
    from scripts.scene import run_objectgs as cli
    from src.models.contracts.coordinates import Transform
    from src.services.scene.decomposition.gaussian_split import write_gaussian_ply
    from src.services.simulation.colliders.carve import _rotation
    from tests.test_contracts.test_object_geometry import membership, scene

    members = membership(scene())
    object_id = next(iter(members.label_to_object_id.values()))
    dtype = [(name, "<f4") for name in ["x", "y", "z", "opacity", "scale_0", "rot_0", "f_dc_0", "f_dc_1", "f_dc_2"]]
    rows = np.zeros(4, dtype=dtype)
    rows["x"] = [0, 1, 2, 3]
    ply = write_gaussian_ply(rows)
    source = tmp_path / "source.ply"
    source.write_bytes(ply)
    labels = np.array([-1, -1, 0, 0], dtype="<i4").tobytes()
    labels_path = tmp_path / "labels.bin"
    labels_path.write_bytes(labels)
    import hashlib

    members = members.model_copy(
        update={
            "gaussian_count": 4,
            "source_visual_ref": members.source_visual_ref.model_copy(
                update={"artifact_checksum": "sha256:" + hashlib.sha256(ply).hexdigest()}
            ),
            "labels_ref": members.labels_ref.model_copy(
                update={"artifact_checksum": "sha256:" + hashlib.sha256(labels).hexdigest()}
            ),
        }
    )
    pose = Transform(
        parent_frame="world",
        local_frame=object_id,
        translation_xyz=(4, 5, 6),
        rotation_quaternion_xyzw=(0, 0, np.sqrt(0.5), np.sqrt(0.5)),
    )
    _, _, _, views = inputs(tmp_path)
    Image.fromarray(np.array([[0, 1, 1, 0]] * 3, dtype=np.uint8)).save(views[0].mask_path)
    runtime = objectgs.ObjectGSRuntime(
        python=Path(sys.executable), repository=tmp_path, gsplat_repository=tmp_path, iterations=2
    )
    request = cli.Request(
        job_id=members.source_visual_ref.job_id,
        source_ply=source,
        source_labels=labels_path,
        membership=members,
        source_poses={object_id: pose},
        views=views,
        runtime=runtime,
        workspace=tmp_path / "stage",
    )

    def trained(*a, **kw):
        model = tmp_path / "fixture-model"
        model.mkdir()
        (model / "config.yaml").write_text("fixture: true")
        (model / "point_cloud/iteration_2").mkdir(parents=True)
        mesh = trimesh.creation.box(extents=[1, 2, 3])
        mesh.vertices = np.asarray(mesh.vertices) @ _rotation(pose.rotation_quaternion_xyzw).T + np.asarray(
            pose.translation_xyz
        )
        path = tmp_path / "world.ply"
        path.write_bytes(mesh.export(file_type="ply"))
        return {
            "model": str(model),
            "objects": {object_id: {"path": str(path), "label": 1}},
            "coordinate_frame": "world",
            "distance_unit": "m",
        }

    monkeypatch.setattr(objectgs, "run_objectgs", trained)
    result = cli.run(request)
    local = trimesh.load(result["objects"][object_id]["path"], force="mesh", process=False)
    np.testing.assert_allclose(local.bounds, [[-0.5, -1, -1.5], [0.5, 1, 1.5]], atol=1e-6)
    assert result["coordinate_frame"] == "object_local"
    assert Path(result["checkpoint_path"]).is_file()


def test_cancellation_kills_real_training_process_without_orphaning(tmp_path, monkeypatch):
    import os
    import threading
    import time

    from src.services.process_control import run_cancellable_process

    python = Path(__file__).parents[2] / "data/scene_runtime/bin/python"
    if not python.is_file():
        pytest.skip("isolated subprocess runtime is not installed")
    repo = tmp_path / "upstream"
    config = repo / "config/objectgs/2d/lerf_mask/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"model_params": {}, "optim_params": {}, "pipeline_params": {}}))
    marker = tmp_path / "training.pid"
    # Match only the import-time GPU prelude, then execute a genuine long-running child process.
    prelude = """import subprocess
cmd = 'nvidia-smi -q -d Memory |grep -A4 GPU|grep Used'
result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout.decode().split('\\n')
os.environ['CUDA_VISIBLE_DEVICES']=str(np.argmin([int(x.split()[2]) for x in result[:-1]]))"""
    (repo / "train.py").write_text(
        "import os,time\n" + prelude + f'\nopen({str(marker)!r},"w").write(str(os.getpid()))\ntime.sleep(60)\n'
    )
    gsplat = tmp_path / "gsplat"
    gsplat.mkdir()
    dataset = tmp_path / "data/job-test"
    rows, labels, mapping, views = inputs(tmp_path)
    objectgs.prepare_dataset(rows, labels, mapping, views * 11, dataset)
    runtime = objectgs.ObjectGSRuntime(python=python, repository=repo, gsplat_repository=gsplat, timeout_seconds=10)
    monkeypatch.setattr(
        objectgs, "_revision", lambda p: objectgs.OBJECTGS_COMMIT if p == repo else objectgs.GSPLAT_COMMIT
    )

    def process(command, **kwargs):
        if command[1] == "-c":
            Path(command[-2]).write_text("{}")
            return 0
        return run_cancellable_process(command, **kwargs)

    monkeypatch.setattr(objectgs, "run_cancellable_process", process)
    event = Event()

    def cancel_started_process():
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        event.set()

    thread = threading.Thread(target=cancel_started_process)
    thread.start()
    try:
        with pytest.raises(ProcessCancelledError):
            objectgs.run_objectgs(runtime, dataset, tmp_path / "work", cancel_event=event)
    finally:
        thread.join(timeout=6)
    assert marker.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert not (tmp_path / "work/result.json").exists()


@pytest.mark.parametrize("view_count", [1, 10])
def test_training_rejects_too_few_views_before_starting_upstream(tmp_path, monkeypatch, view_count):
    repo, gsplat = tmp_path / "repo", tmp_path / "gsplat"
    python = tmp_path / "isolated/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    runtime = objectgs.ObjectGSRuntime(python=python, repository=repo, gsplat_repository=gsplat)
    monkeypatch.setattr(
        objectgs, "_revision", lambda p: objectgs.OBJECTGS_COMMIT if p == repo else objectgs.GSPLAT_COMMIT
    )
    rows, labels, mapping, views = inputs(tmp_path)
    dataset = tmp_path / "data"
    objectgs.prepare_dataset(rows, labels, mapping, views * view_count, dataset)
    with pytest.raises(ValueError, match="at least 11 calibrated views"):
        objectgs.run_objectgs(runtime, dataset, tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()
