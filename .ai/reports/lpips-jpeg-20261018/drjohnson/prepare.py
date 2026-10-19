"""Reconstruct a private Brush input from checksum-verified drjohnson artifacts."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from dotenv import dotenv_values
from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.adapters.brush_input import BrushInputAdapter
from src.services.reconstruction.adapters.colmap_runtime import ColmapProcess, ColmapRuntimeSettings
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver

repo = Path.cwd()
root = repo / 'data/studio_local/artifacts'
out = repo / 'data/studio_local/evaluations/drjohnson-lpips-20261018'
out.mkdir(parents=True, exist_ok=False)
visual_path = root / 'jobs/job-f9f14e7fbfb1/attempts/preview-c7f1927a25d747d5912cb4e6cddf874a/rec04/visual.json'
visual = json.loads(visual_path.read_text())
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()
def resolve(ref):
    path = root / ref.artifact_uri.removeprefix('artifact://')
    assert path.is_file() and digest(path) == ref.artifact_checksum, ref.artifact_uri
    return path
pose_ref = ProductArtifactRef.model_validate(visual['source_camera_poses'])
poses = CameraPoseResolver(resolve, FrameSetResolver(resolve, resolve))
pose = poses.load(pose_ref)
source = out / 'source'
poses.materialize_sparse(pose, source / 'sparse/0')
images = source / 'images'
images.mkdir()
frames = poses.frames.load(pose.source_frame_set)
registered = {p.frame_id: p.image_name for p in pose.poses}
for frame in frames.frames:
    if frame.frame_id in registered:
        shutil.copyfile(resolve(frame.image), images / registered[frame.frame_id])
master_ref = ProductArtifactRef.model_validate(visual['master'])
master = resolve(master_ref)
metadata = {'job_id': 'job-f9f14e7fbfb1', 'source_visual_path': str(visual_path), 'source_visual_sha256': digest(visual_path), 'master_ref': visual['master'], 'camera_ref': visual['source_camera_poses'], 'held_out_frame_ids': visual['held_out_frame_ids'], 'original_quality': visual['holdout_quality'], 'original_bridge': visual['bridge']}
(out / 'source-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps({'stage': 'source_copied', 'frames': len(registered), 'workspace': str(out)}), flush=True)
