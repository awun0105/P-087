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
force_fused = False
class Predictor:
 def __init__(self, *a): pass
 def set_image(self, image): self.shape=image.shape[:2]
 def reset_predictor(self): pass
 def predict(self, point_coords, **kw):
  masks=[]; scores=[]
  for points in point_coords:
   mask=np.zeros(self.shape, dtype=bool)
   mask[:, 2:6] = True if force_fused else False
   if not force_fused: mask[:, :4] = True
   masks.append(mask); scores.append(.9 if force_fused or points[0, 0] < 4 else .2)
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
force_fused = True
fused = lift.run(dict(req,output_npz=str(work/'labels-fused.npz')))
refined = lift.run(dict(req,config=dict(req['config'], refinement='multiview_v1'),
 evidence_dir=str(work/'refined-evidence'), objectgs_observations_dir=str(work/'observations'),
 output_npz=str(work/'labels-refined.npz')))
expected=np.r_[np.zeros(10,dtype=np.int32),np.ones(10,dtype=np.int32)]
assert not np.array_equal(np.load(work/'labels-fused.npz')['labels'],expected)
assert np.array_equal(np.load(work/'labels-refined.npz')['labels'],expected)
assert set(np.unique(np.load(work/'observations/view-000000.labels.npy'))) <= {-1,0,1}
refined_events=[json.loads(line) for line in (work/'refined-evidence/lift.jsonl').read_text().splitlines()]
assert any(event['kind']=='overlap_refinement' and event['ambiguous_pixels']>0 for event in refined_events)
assert any(event['kind']=='ownership_refinement' and event['changed']>0 for event in refined_events)
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


def test_corrected_masks_follow_source_rows_across_channel_chunks_without_sam(tmp_path):
    script = r"""
import importlib.util,sys,types
from pathlib import Path
import numpy as np
import torch
from PIL import Image
torch.set_num_threads(1)
original_device=torch.device
torch.device=lambda *a,**kw: original_device('cpu')
calls=[]
def raster(means,quats,scales,opacity,colors,views,intrinsics,w,h,**kw):
 assert len(means)==70 and colors.shape[0]==70
 assert tuple(intrinsics[0].cpu().numpy()[0])==(50,0,20)
 calls.append(colors.shape[1])
 return colors.reshape(1,1,w,-1).expand(1,h,w,-1),None,None
sys.modules['gsplat']=types.SimpleNamespace(rasterization=raster)
sys.path.insert(0,str(Path('src/services/scene/association').resolve()))
import correction_observations as module
work=Path(sys.argv[1]);work.mkdir(exist_ok=True)
fields=['x','y','z','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']
rows=np.zeros(70,dtype=[(key,'<f4') for key in fields]);rows['rot_0']=1;rows['z']=1
header='ply\nformat binary_little_endian 1.0\nelement vertex 70\n'+''.join('property float '+key+'\n' for key in fields)+'end_header\n'
ply=work/'source.ply';ply.write_bytes(header.encode()+rows.tobytes())
image=work/'image.png';Image.new('RGB',(70,2)).save(image)
labels=np.repeat(np.array([-1,*range(34)],dtype='<i4'),2)
path=work/'labels.i32le';labels.tofile(path)
view=dict(model='PINHOLE',width=70,height=2,parameters=[50,60,20,1],center=[2,3,4],rotation_xyzw=[0,0,0,1],image_path=str(image))
request=dict(gaussians_ply=str(ply),labels_path=str(path),label_to_object_id={str(i):f'object-{i}' for i in range(34)},views=[view],output_dir=str(work/'before'))
before=module.run(request)
mask_before=np.load(before['objectgs_views'][0]['mask_path'])
np.testing.assert_array_equal(mask_before,np.tile(labels,(2,1)))
labels[4]=-1;labels.tofile(path)
after=module.run(dict(request,output_dir=str(work/'after')))
mask_after=np.load(after['objectgs_views'][0]['mask_path'])
np.testing.assert_array_equal(mask_after,np.tile(labels,(2,1)))
assert np.flatnonzero(mask_after[0]!=mask_before[0]).tolist()==[4]
assert calls==[31,4,31,4]
assert after['objectgs_views'][0]['parameters']==[50,60,20,1]
assert after['objectgs_views'][0]['center']==[2,3,4]
assert not torch.cuda.is_initialized()
print('CORRECTED_MASKS_SOURCE_ROWS_CPU')
"""
    result = subprocess.run(
        [str(RUNTIME), "-c", script, str(tmp_path / "work")],
        cwd=ROOT,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "CORRECTED_MASKS_SOURCE_ROWS_CPU" in result.stdout
