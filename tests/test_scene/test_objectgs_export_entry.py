"""CPU API fixture for the per-view categorical-to-alpha mask export adapter."""

import json
import subprocess
import sys
from pathlib import Path


def test_export_binds_only_requested_label_without_modifying_categorical_masks(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "export_object_mesh.py").write_text("""
import argparse, json
from types import SimpleNamespace
import numpy as np
class Tensor:
    def __init__(self, array): self.array = np.asarray(array)
    def cpu(self): return self
    def __eq__(self, other): return Tensor(self.array == other)
    def unsqueeze(self, dimension): return Tensor(np.expand_dims(self.array, dimension))
    def float(self): return self.array.astype(np.float32)
class Extractor:
    def reconstruction(self, cameras):
        assert cameras[0].object_mask.array.tolist() == [[0, 1, 2, 2], [2, 0, 1, 0]]
        with open(args.result, 'w') as output:
            json.dump([camera.alpha_mask.tolist() for camera in cameras], output)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--query_label_id', type=int)
    parser.add_argument('--result')
    args = parser.parse_args()
    cameras = [SimpleNamespace(object_mask=Tensor([[0,1,2,2],[2,0,1,0]])),
               SimpleNamespace(object_mask=Tensor([[0,0,0,0],[0,0,0,0]]))]
    scene = SimpleNamespace(getTrainCameras=lambda: cameras)
    gaussExtractor = Extractor()
    gaussExtractor.reconstruction(scene.getTrainCameras())
""")
    result = tmp_path / "masks.json"
    subprocess.run(
        [
            sys.executable,
            str(Path("scripts/scene/objectgs_export_entry.py")),
            "--upstream",
            str(upstream),
            "--query_label_id",
            "2",
            "--result",
            str(result),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(result.read_text()) == [
        [[[0, 0, 1, 1], [1, 0, 0, 0]]],
        [[[0, 0, 0, 0], [0, 0, 0, 0]]],
    ]
