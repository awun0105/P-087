"""Real CPU Torch with fake SAM2/rasterization: instrumentation must preserve all arrays.

These tests never initialize CUDA and are not GPU segmentation acceptance.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
RUNTIME = ROOT / "data/scene_runtime/bin/python"
pytestmark = pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated scene runtime not installed")


def test_sam2_and_lift_arrays_are_identical_with_evidence(tmp_path):
    script = r"""
import contextlib, importlib.util, json, sys, types
from pathlib import Path
import numpy as np
import torch
from PIL import Image
torch.set_num_threads(1)
original_device = torch.device
torch.device = lambda *a, **kw: original_device('cpu')
torch.autocast = lambda *a, **kw: contextlib.nullcontext()
class Predictor:
 def __init__(self, *a): pass
 def set_image(self, image): self.shape=image.shape[:2]
 def reset_predictor(self): pass
 def predict(self, point_coords, **kw):
  masks=[]; scores=[]
  for points in point_coords:
   mask=np.zeros(self.shape, dtype=bool)
   mask[:, :4] = True
   masks.append(mask); scores.append(.9 if points[0, 0] < 4 else .2)
  return np.array(masks)[:,None], np.array(scores)[:,None], None
sys.modules['sam2.build_sam']=types.SimpleNamespace(build_sam2=lambda *a, **kw: object())
sys.modules['sam2.sam2_image_predictor']=types.SimpleNamespace(SAM2ImagePredictor=Predictor)
def raster(means, quats, scales, opacity, colors, views, intrinsics, w, h, **kw):
 if kw.get('render_mode')=='RGB+ED':
  return torch.full((1,h,w,2), 2.), None, None
 return colors.mean(dim=0).reshape(1,1,1,-1).expand(1,h,w,-1), None, None
sys.modules['gsplat']=types.SimpleNamespace(rasterization=raster)
def load(name, path):
 spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
work=Path(sys.argv[1]); work.mkdir(exist_ok=True)
sam=load('sam_runner','src/services/scene/sampro3d/sam2_runner.py')
lift=load('lift_runner','src/services/scene/association/lift_runner.py')
image=work/'view.png'; Image.new('RGB',(8,8)).save(image)
view=dict(model='PINHOLE', width=8,height=8,parameters=[4,4,4,4],center=[0,0,0],rotation_xyzw=[0,0,0,1],image_path=str(image))
points=np.array([[-.25,0,1],[.25,0,1]],dtype=np.float32)
np.savez(work/'points.npz',points=points,prompts=np.array([0,1]))
req=dict(points_npz=str(work/'points.npz'),config='fixture',checkpoint='fixture.pt',views=[view],batch=2,zbuffer_cell_px=1,depth_tolerance_m=.1)
sam.run(req,work/'baseline.npz')
sam.run(dict(req,evidence_dir=str(work/'evidence')),work/'observed.npz')
for key,value in np.load(work/'baseline.npz').items():
 assert np.array_equal(value,np.load(work/'observed.npz')[key]),key
fields=['x','y','z','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']
rows=np.zeros(20,dtype=[(k,'<f4') for k in fields]);rows['x'][:10]=-.25;rows['x'][10:]=.25
rows['z']=1;rows['opacity']=3;rows['rot_0']=1
for name in ['scale_0','scale_1','scale_2']:rows[name]=-4
header='ply\nformat binary_little_endian 1.0\nelement vertex 20\n'+''.join('property float '+k+'\n' for k in fields)+'end_header\n'
ply=work/'source.ply';ply.write_bytes(header.encode()+rows.tobytes())
np.savez(work/'seeds.npz',offsets=np.array([0,10,20]),members=np.arange(20))
req=dict(gaussians_ply=str(ply),seeds_npz=str(work/'seeds.npz'),sam2_config='fixture',sam2_checkpoint='fixture.pt',views=[view],config=dict(width=8,min_visible=1,max_area=.75,majority=.4),output_npz=str(work/'labels-before.npz'))
baseline=lift.run(req)
observed=lift.run(dict(req,evidence_dir=str(work/'evidence'),output_npz=str(work/'labels-after.npz')))
assert baseline==observed
assert np.array_equal(np.load(work/'labels-before.npz')['labels'],np.load(work/'labels-after.npz')['labels'])
events=[json.loads(line) for line in (work/'evidence/lift.jsonl').read_text().splitlines()]
assert any('low_score' in event.get('reasons',[]) for event in events)
assert any(event['kind']=='membership' for event in events)
print('CPU_RUNNERS_PRESERVED')
"""
    result = subprocess.run(
        [str(RUNTIME), "-c", script, str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CPU_RUNNERS_PRESERVED" in result.stdout
