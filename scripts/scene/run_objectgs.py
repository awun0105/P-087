"""Run the prepared-input ObjectGS stage; no SceneIR publication or legacy fallback.

PYTHONPATH=. .venv/bin/python scripts/scene/run_objectgs.py --request request.json --result result.json
"""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

import numpy as np
import trimesh

from src.models.contracts.artifacts import ContractModel, Identifier
from src.models.contracts.coordinates import Transform
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.services.scene.decomposition.gaussian_split import read_gaussian_ply
from src.services.scene.editing.membership import decode_gaussian_membership_labels
from src.services.scene.objectgs import ObjectGSRuntime, ObjectGSView, prepare_dataset, run_objectgs
from src.services.simulation.colliders.carve import _rotation


class Request(ContractModel):
    job_id: Identifier
    source_ply: Path
    source_labels: Path
    membership: ObjectMembershipArtifact
    source_poses: dict[str, Transform]
    views: list[ObjectGSView]
    runtime: ObjectGSRuntime
    workspace: Path


def run(request: Request) -> dict[str, object]:
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
        progress=lambda stage: print(json.dumps({"stage": stage}), flush=True),
    )
    model = Path(receipt["model"])
    checkpoint = request.workspace / "objectgs-checkpoint.tar.gz"
    with tarfile.open(checkpoint, "w:gz") as archive:
        archive.add(model / "config.yaml", arcname="config.yaml")
        archive.add(
            model / f"point_cloud/iteration_{request.runtime.iterations}",
            arcname=f"point_cloud/iteration_{request.runtime.iterations}",
        )
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
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.result.resolve() == args.request.resolve():
        raise ValueError("request and result paths must differ")
    request = Request.model_validate_json(args.request.read_bytes())
    args.result.unlink(missing_ok=True)
    receipt = run(request)
    args.result.write_text(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
