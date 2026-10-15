"""Isolated, revision-pinned ObjectGS dataset adapter and real train/export process runner."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np
import trimesh
import yaml
from PIL import Image
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel, Identifier
from src.models.contracts.coordinates import Transform
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.services.process_control import ProcessCancelledError, run_cancellable_process
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply
from src.services.scene.diagnostics import EvidenceRecorder
from src.services.scene.editing.membership import decode_gaussian_membership_labels
from src.services.simulation.colliders.carve import _rotation

OBJECTGS_COMMIT = "0f6842b0fa80b9bfe151c31b70c306cbc5eab788"
GSPLAT_COMMIT = "68a61a4485cfc2967703391a3e1cfb59981f8fc7"
GLM_COMMIT = "bf71a834948186f4097caa076cd2663c69a10e1e"


class ObjectGSView(ContractModel):
    image_path: Path
    mask_path: Path
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)
    camera_model: Literal["PINHOLE"] = "PINHOLE"
    parameters: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    center: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    rotation_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    coordinate_frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"


class ObjectGSRuntime(ContractModel):
    python: Path
    repository: Path
    gsplat_repository: Path
    cuda_home: Path | None = None
    cxx: Path | None = None
    glm_repository: Path | None = None
    extension_cache_dir: Path | None = None
    gpu_device: int = Field(default=0, ge=0, strict=True)
    iterations: int = Field(default=30000, ge=1, strict=True)
    timeout_seconds: FiniteFloat = Field(default=14400, gt=0)
    voxel_size_m: FiniteFloat = Field(default=0.01, gt=0)
    depth_trunc_m: FiniteFloat = Field(default=10, gt=0)


def prepare_dataset(
    rows: np.ndarray,
    labels: np.ndarray,
    label_to_object_id: dict[str, str],
    views: list[ObjectGSView],
    destination: Path,
) -> dict[str, int]:
    """Write canonical metre anchors and undistorted COLMAP cameras; mask IDs are explicit 0..N.

    Background is 0. Scene IDs are assigned 1..255 in sorted order, including merged source labels.
    Input masks must already use this exact mapping; unknown IDs are rejected, never relabelled silently.
    No metric rescaling or camera distortion correction is inferred here.
    """
    object_ids = sorted(set(label_to_object_id.values()))
    if not 1 <= len(object_ids) <= 255 or not views:
        raise ValueError("ObjectGS needs 1..255 objects and calibrated image/mask views")
    mapping = {object_id: index + 1 for index, object_id in enumerate(object_ids)}
    source_labels = np.asarray(labels)
    if source_labels.shape != (len(rows),) or not np.issubdtype(source_labels.dtype, np.integer):
        raise ValueError("Gaussian membership requires one integer label per source row")
    known = {-1, *(int(label) for label in label_to_object_id)}
    if not set(np.unique(source_labels)) <= known:
        raise ValueError("unknown Gaussian membership labels")
    xyz = positions(rows)
    if not np.isfinite(xyz).all():
        raise ValueError("ObjectGS anchors must be finite canonical metre points")
    encoded = np.zeros(len(rows), dtype=np.uint8)
    for label, object_id in label_to_object_id.items():
        encoded[source_labels == int(label)] = mapping[object_id]
    if not {0, *mapping.values()} <= set(np.unique(encoded)):
        raise ValueError("background and every ObjectGS object need source anchors")
    checked = []
    visible: set[int] = set()
    for view in views:
        with Image.open(view.image_path) as image, Image.open(view.mask_path) as mask:
            if image.size != (view.width, view.height) or mask.size != image.size or mask.mode != "L":
                raise ValueError("ObjectGS image/mask dimensions or categorical uint8 mask format differ")
            values = set(map(int, np.unique(np.asarray(mask))))
            if not values <= {0, *mapping.values()}:
                raise ValueError("mask label IDs do not match the explicit ObjectGS mapping")
            visible |= values
            checked.append((view, image.convert("RGB").copy(), mask.copy()))
        if view.parameters[0] <= 0 or view.parameters[1] <= 0:
            raise ValueError("camera focal lengths must be positive")
        if not np.isclose(np.linalg.norm(view.rotation_xyzw), 1, atol=1e-6):
            raise ValueError("camera quaternion must be normalized")
    if not set(mapping.values()) <= visible:
        raise ValueError("every ObjectGS object needs a labelled image observation")
    destination.mkdir(parents=True, exist_ok=False)
    sparse = destination / "sparse/0"
    sparse.mkdir(parents=True)
    (destination / "images").mkdir()
    (destination / "object_mask").mkdir()
    cameras, images = [], []
    for number, (view, image, mask) in enumerate(checked, 1):
        name = f"frame_{number:06d}.jpg"
        image.save(destination / "images" / name, quality=100, subsampling=0)
        mask.save(destination / "object_mask" / name.replace(".jpg", ".png"))
        cameras.append(f"{number} PINHOLE {view.width} {view.height} " + " ".join(map(str, view.parameters)))
        x, y, z, w = view.rotation_xyzw
        translation = -_rotation(view.rotation_xyzw).T @ np.asarray(view.center)
        pose = [w, -x, -y, -z, *translation]
        images.append(f"{number} " + " ".join(map(str, pose)) + f" {number} {name}\n")
    (sparse / "cameras.txt").write_text("\n".join(cameras) + "\n")
    (sparse / "images.txt").write_text("\n".join(images) + "\n")
    dtype = [(name, "<f4") for name in ["x", "y", "z", "nx", "ny", "nz"]] + [
        (name, "u1") for name in ["red", "green", "blue", "label"]
    ]
    anchors = np.zeros(len(rows), dtype=dtype)
    for axis, name in enumerate(["x", "y", "z"]):
        anchors[name] = xyz[:, axis]
    for axis, name in enumerate(["red", "green", "blue"]):
        values = rows[f"f_dc_{axis}"].astype(float)
        if not np.isfinite(values).all():
            raise ValueError("anchor colors must be finite")
        anchors[name] = np.round(np.clip(0.5 + 0.28209479177387814 * values, 0, 1) * 255).astype(np.uint8)
    anchors["label"] = encoded
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(rows)}"]
    header += [
        f"property {'float' if anchors.dtype[name].kind == 'f' else 'uchar'} {name}" for name in anchors.dtype.names
    ]
    (sparse / "points3D.ply").write_bytes(("\n".join([*header, "end_header"]) + "\n").encode() + anchors.tobytes())
    (destination / "label-map.json").write_text(json.dumps(mapping, sort_keys=True))
    return mapping


def _revision(repository: Path) -> str:
    if subprocess.check_output(
        ["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=no"], text=True
    ):
        raise ValueError("ObjectGS runtime checkouts must not contain tracked source modifications")
    return subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()


@contextmanager
def _extension_cache_lock(directory: Path | None) -> Iterator[None]:
    """Serialize optional shared compiler caches; pinned upstream removes JIT lock files itself."""
    if directory is None:
        yield
        return
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".p087-process.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("ObjectGS extension cache is in use by another process") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_objectgs(
    runtime: ObjectGSRuntime,
    dataset: Path,
    workspace: Path,
    *,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, object]:
    """Train a fresh upstream model and export each explicit object ID, with no legacy fallback.

    Resume is deliberately unsupported: pinned upstream capture/restore tuple layouts disagree.
    The caller must publish validated outputs transactionally against the source SceneIR revision.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelledError("ObjectGS operation cancelled before start")
    if _revision(runtime.repository) != OBJECTGS_COMMIT or _revision(runtime.gsplat_repository) != GSPLAT_COMMIT:
        raise ValueError("ObjectGS and custom gsplat checkouts must match pinned revisions")
    if runtime.glm_repository and _revision(runtime.glm_repository) != GLM_COMMIT:
        raise ValueError("GLM headers must match the pinned runtime revision")
    if not runtime.python.is_file():
        raise ValueError("isolated ObjectGS Python is missing")
    if runtime.python.absolute().parent.parent.resolve() == Path(sys.prefix).resolve():
        raise ValueError("ObjectGS must not run in the application Python environment")
    dataset = dataset.resolve()
    if any(token in str(dataset) for token in ["replica", "3dovs", "lerf_ovs", "scannet", "mipnerf360"]):
        raise ValueError("prepared dataset path triggers unsupported upstream dataset-name heuristics")
    # Pinned train.py indexes getTrainCameras()[10] for visualization at iteration 1.
    # Prepared images.txt has one pose row and an empty feature row per camera.
    camera_rows = (dataset / "sparse/0/images.txt").read_text().splitlines()
    if sum(bool(row.strip()) and not row.lstrip().startswith("#") for row in camera_rows) < 11:
        raise ValueError("pinned ObjectGS training requires at least 11 calibrated views")
    mapping = json.loads((dataset / "label-map.json").read_text())
    if not mapping or not set(mapping.values()) <= set(range(1, 256)):
        raise ValueError("invalid explicit object label mapping")
    workspace.mkdir(parents=True, exist_ok=False)
    workspace = workspace.resolve()
    trace = EvidenceRecorder(evidence_dir, "objectgs")
    trace.emit(
        "configured",
        label_to_object_id={str(label): object_id for object_id, label in mapping.items()},
        iterations=runtime.iterations,
        upstream_commit=OBJECTGS_COMMIT,
        gsplat_commit=GSPLAT_COMMIT,
        voxel_size_m=runtime.voxel_size_m,
        depth_trunc_m=runtime.depth_trunc_m,
    )
    # Upstream appends model_path.parent.name to source_path during export.
    scene_name = dataset.name
    config = yaml.safe_load((runtime.repository / "config/objectgs/2d/lerf_mask/config.yaml").read_text())
    config["model_params"].update(
        source_path=str(dataset.parent),
        dataset_name="p087",
        exp_name="objectgs",
        add_mask=False,
        add_depth=False,
        eval=False,
    )
    config["optim_params"]["iterations"] = runtime.iterations
    config_path = workspace / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    entry = Path(__file__).resolve().parents[3] / "scripts/scene/objectgs_entry.py"
    environment = {
        "CUDA_VISIBLE_DEVICES": str(runtime.gpu_device),
        "PYTHONPATH": str(runtime.gsplat_repository),
        "TORCH_EXTENSIONS_DIR": str((runtime.extension_cache_dir or workspace / "torch-extensions").resolve()),
        "MAX_JOBS": "2",
        # Python 3.8's Python.h includes crypt.h from the environment's include
        # root, which a separate Conda compiler sysroot does not search itself.
        "CPLUS_INCLUDE_PATH": str(runtime.python.absolute().parent.parent / "include"),
    }
    if runtime.cuda_home:
        environment.update(
            CUDA_HOME=str(runtime.cuda_home.resolve()),
            PATH=str(runtime.cuda_home.resolve() / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )
    if runtime.cxx:
        environment["CXX"] = str(runtime.cxx.absolute())
        environment["CC"] = str(runtime.cxx.absolute())
    if runtime.glm_repository:
        environment["CPLUS_INCLUDE_PATH"] += os.pathsep + str(runtime.glm_repository.resolve())

    def execute(command: list[str], stage: str) -> None:
        trace.emit("stage_started", phase=stage)
        if progress:
            progress(stage)
        with _extension_cache_lock(runtime.extension_cache_dir), (workspace / f"{stage}.log").open("w") as log:
            status = run_cancellable_process(
                [str(runtime.python.absolute()), *command[1:]],
                cwd=workspace,
                timeout_seconds=runtime.timeout_seconds,
                output=log,
                cancel_event=cancel_event,
                environment=environment,
            )
        if status:
            trace.emit("stage_failed", phase=stage, returncode=status)
            raise RuntimeError(f"ObjectGS {stage} failed (exit {status}); see {stage}.log")
        trace.emit("stage_completed", phase=stage)

    metadata_path = workspace / "runtime.json"
    probe = """import json, os, sys, torch, gsplat, open3d
if not torch.cuda.is_available(): raise RuntimeError('ObjectGS requires a usable CUDA GPU')
if os.path.commonpath([os.path.realpath(gsplat.__file__), os.path.realpath(sys.argv[2])]) != os.path.realpath(sys.argv[2]):
 raise RuntimeError('custom pinned gsplat was not imported from its isolated checkout')
with open(sys.argv[1], 'w') as f:
 json.dump(dict(python=sys.version,torch=torch.__version__,cuda=torch.version.cuda,gsplat=gsplat.__version__,open3d=open3d.__version__,gpu=torch.cuda.get_device_name(0)),f)
"""
    execute(
        [str(runtime.python), "-c", probe, str(metadata_path), str(runtime.gsplat_repository.resolve())],
        "runtime-check",
    )
    trace.emit("runtime_metadata", metadata=json.loads(metadata_path.read_text()))
    execute(
        [
            str(runtime.python),
            str(entry),
            "--upstream",
            str(runtime.repository.resolve()),
            "--config",
            str(config_path),
            "--scene-name",
            scene_name,
        ],
        "train",
    )
    models = list((workspace / "outputs/p087/objectgs" / scene_name).glob("*/config.yaml"))
    if len(models) != 1:
        raise RuntimeError("ObjectGS did not produce exactly one fresh model directory")
    model = models[0].parent
    checkpoint = model / f"point_cloud/iteration_{runtime.iterations}"
    checkpoint_files = [
        checkpoint / name for name in ["point_cloud.ply", "opacity_mlp.pt", "cov_mlp.pt", "color_mlp.pt"]
    ]
    if any(not path.is_file() or not path.stat().st_size for path in checkpoint_files):
        raise RuntimeError("ObjectGS model is missing Gaussian anchors or required MLP checkpoint files")
    surfaces = {}
    for object_id, label in mapping.items():
        execute(
            [
                str(runtime.python),
                str(entry.with_name("objectgs_export_entry.py")),
                "--upstream",
                str(runtime.repository.resolve()),
                "-m",
                str(model),
                "--query_label_id",
                str(label),
                "--iteration",
                str(runtime.iterations),
                "--num_cluster",
                "1",
                "--voxel_size",
                str(runtime.voxel_size_m),
                "--depth_trunc",
                str(runtime.depth_trunc_m),
            ],
            f"export-{label}",
        )
        # Raw export retains all connected components; upstream *_post.ply can drop small parts.
        path = model / f"train/id_{label}/mesh/fuse.ply"
        mesh = trimesh.load(path, force="mesh", process=False)
        trace.emit(
            "mesh_validation",
            object_id=object_id,
            label=label,
            vertices=len(mesh.vertices),
            triangles=len(mesh.faces),
            finite=bool(np.isfinite(mesh.vertices).all()),
            watertight=bool(mesh.is_watertight),
        )
        if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
            raise RuntimeError(f"ObjectGS exported an empty/nonfinite surface for {object_id}")
        surfaces[object_id] = {
            "label": label,
            "path": str(path),
            "checksum": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    receipt = {
        "model": str(model),
        "objects": surfaces,
        "upstream_commit": OBJECTGS_COMMIT,
        "gsplat_commit": GSPLAT_COMMIT,
        "glm_commit": GLM_COMMIT if runtime.glm_repository else None,
        "coordinate_frame": "world",
        "distance_unit": "m",
        "source_dataset": str(dataset),
        "runtime": json.loads(metadata_path.read_text()),
        "gpu_device": runtime.gpu_device,
        "export_config": {
            "voxel_size_m": runtime.voxel_size_m,
            "depth_trunc_m": runtime.depth_trunc_m,
            "num_cluster": 1,
            "mesh_variant": "raw_fuse",
            "depth_mask": "per_view_instance_label",
        },
        "config_checksum": "sha256:" + hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    (workspace / "result.json").write_text(json.dumps(receipt, sort_keys=True))
    return receipt


class PreparedObjectGSRequest(ContractModel):
    job_id: Identifier
    source_ply: Path
    source_labels: Path
    membership: ObjectMembershipArtifact
    source_poses: dict[str, Transform]
    views: list[ObjectGSView]
    runtime: ObjectGSRuntime
    workspace: Path


def run_prepared_objectgs(
    request: PreparedObjectGSRequest,
    *,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, object]:
    if Path(request.job_id).name != request.job_id or request.membership.source_visual_ref.job_id != request.job_id:
        raise ValueError("ObjectGS job ID and immutable membership source must agree")
    if set(request.source_poses) != set(request.membership.label_to_object_id.values()):
        raise ValueError("source poses must cover exactly the objects in immutable membership")
    for object_id, pose in request.source_poses.items():
        if pose.parent_frame != "world" or pose.local_frame != object_id:
            raise ValueError("source pose must explicitly map object-local coordinates to canonical world")
        if not np.isfinite(pose.translation_xyz).all():
            raise ValueError("source pose translation must be finite")
    payload = request.source_ply.read_bytes()
    if "sha256:" + hashlib.sha256(payload).hexdigest() != request.membership.source_visual_ref.artifact_checksum:
        raise ValueError("source Gaussian PLY checksum mismatch")
    rows = read_gaussian_ply(payload)
    labels = decode_gaussian_membership_labels(request.source_labels.read_bytes(), request.membership)
    request.workspace.mkdir(parents=True, exist_ok=False)
    dataset = request.workspace / "data" / request.job_id
    prepare_dataset(rows, labels, request.membership.label_to_object_id, request.views, dataset)
    receipt = run_objectgs(
        request.runtime,
        dataset,
        request.workspace / "runtime",
        progress=progress,
        cancel_event=cancel_event,
        **({"evidence_dir": evidence_dir} if evidence_dir is not None else {}),
    )
    model = Path(receipt["model"])
    checkpoint = request.workspace / "objectgs-checkpoint.tar.gz"
    with tarfile.open(checkpoint, "w:gz") as archive:
        archive.add(model / "config.yaml", arcname="config.yaml")
        archive.add(
            model / f"point_cloud/iteration_{request.runtime.iterations}",
            arcname=f"point_cloud/iteration_{request.runtime.iterations}",
        )
    dataset_archive = request.workspace / "objectgs-dataset.tar.gz"
    with tarfile.open(dataset_archive, "w:gz") as archive:
        archive.add(dataset, arcname=request.job_id)
    surface_dir = request.workspace / "surfaces"
    surface_dir.mkdir()
    for object_id, item in receipt["objects"].items():
        mesh = trimesh.load(item["path"], force="mesh", process=False)
        pose = request.source_poses[object_id]
        mesh.vertices = (np.asarray(mesh.vertices) - np.asarray(pose.translation_xyz)) @ _rotation(
            pose.rotation_quaternion_xyzw
        )
        path = surface_dir / f"label-{item['label']}.glb"
        payload = mesh.export(file_type="glb")
        path.write_bytes(payload)
        item.update(
            path=str(path),
            checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            vertex_count=len(mesh.vertices),
            triangle_count=len(mesh.faces),
            watertight=bool(mesh.is_watertight),
        )
    receipt.update(
        coordinate_frame="object_local",
        source_membership=request.membership.model_dump(mode="json"),
        source_poses={key: pose.model_dump(mode="json") for key, pose in request.source_poses.items()},
        checkpoint_path=str(checkpoint),
        checkpoint_checksum="sha256:" + hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        dataset_path=str(dataset_archive),
        dataset_checksum="sha256:" + hashlib.sha256(dataset_archive.read_bytes()).hexdigest(),
    )
    return receipt
