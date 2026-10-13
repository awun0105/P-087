"""Byte-bound SOURCE conservation fixtures; USD is structural proof, never Isaac acceptance."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.scene import SceneObjectState, SourceCollisionRegion
from src.services.orchestration.review import simulation_package
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply, write_gaussian_ply
from src.services.scene.editing.commands import confirm_object, delete_object, ignore_object, restore_object
from src.services.scene.representation_integrity import representation_issues
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.capabilities import assess_export_capabilities, export_requirements
from tests.test_orchestration.test_simulation_package import _scene_job


def _fixture(tmp_path: Path, count: int = 60):  # noqa: ANN202
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    template = scene.objects[0]
    fields = [
        "x",
        "y",
        "z",
        "opacity",
        *(f"scale_{i}" for i in range(3)),
        *(f"rot_{i}" for i in range(4)),
        *(f"f_dc_{i}" for i in range(3)),
        *(f"f_rest_{i}" for i in range(9)),
    ]
    rows = np.zeros(count + 1, dtype=[(field, "<f4") for field in fields])
    rows["x"] = np.arange(count + 1)
    rows["y"] = 0.3
    rows["z"] = 0.5
    for index, field in enumerate(fields[3:]):
        rows[field] = index * 0.01
    rows["rot_0"] = 1

    def publish(name: str, kind: str, payload: bytes):  # noqa: ANN202
        ref = scene.environment.geometry_ref.model_copy(
            update={
                "artifact_type": kind,
                "artifact_uri": f"artifact://jobs/{job.job_id}/scene/{name}",
                "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        )
        registry.scene.store.publish(ref, payload)
        return ref

    master = publish("source.ply", "ObjectGaussians", write_gaussian_ply(rows))
    background = publish("background.ply", "ObjectGaussians", write_gaussian_ply(rows[-1:]))
    labels = publish("labels.bin", "ObjectMembershipLabels", np.asarray([*range(count), -1], dtype="<i4").tobytes())
    objects = []
    for index in range(count):
        object_id = f"candidate-{index:03d}"
        pose = template.transform.model_copy(update={"local_frame": object_id, "translation_xyz": (float(index), 0, 0)})
        local = rows[index : index + 1].copy()
        local["x"] -= index
        visual = publish(f"{object_id}.ply", "ObjectGaussians", write_gaussian_ply(local))
        owner = SourceCollisionRegion(
            object_id=object_id,
            source_geometry_ref=scene.environment.geometry_ref,
            extraction_revision=scene.scene_revision,
            source_transform=pose,
            region_kind="source_obb",
            source_obb_dimensions_xyz_m=(1, 1, 1),
        )
        objects.append(
            template.model_copy(
                update={
                    "id": object_id,
                    "local_frame": object_id,
                    "transform": pose,
                    "source_collision": owner,
                    "visual_ref": visual,
                    "active": False,
                    "state": SceneObjectState.CANDIDATE,
                    "provenance": {},
                    "collider": None,
                    "physics": None,
                }
            )
        )
    membership = ObjectMembershipArtifact(
        source_visual_ref=master,
        source_geometry_ref=scene.environment.geometry_ref,
        extraction_revision=scene.scene_revision,
        coordinate_system=scene.coordinate_system,
        gaussian_count=count + 1,
        labels_ref=labels,
        label_to_object_id={str(index): item.id for index, item in enumerate(objects)},
    )
    scene = scene.model_copy(
        update={
            "objects": objects,
            "environment": scene.environment.model_copy(
                update={"membership": membership, "visual_master_ref": background}
            ),
        }
    )
    return registry, scene, rows


def _request(registry, scene, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN202
    captured = {}
    runtime = tmp_path / "python"
    runtime.touch()
    output = tmp_path / "output"
    output.mkdir()

    def run(command: list[str], **kwargs: object):  # noqa: ANN202
        request = json.loads(Path(command[command.index("--request") + 1]).read_bytes())
        captured.update(request)
        Path(request["output_dir"]).mkdir()
        Path(command[command.index("--result") + 1]).write_text(
            json.dumps({"root": "scene.usda", "objects": [], "external_assets": []})
        )
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(simulation_package.subprocess, "run", run)
    background = simulation_package._carved_environment(registry, scene)
    simulation_package._hybrid_layers(registry, scene, output, background, runtime)
    return captured


def test_sixty_inactive_candidates_conserve_source_rows_and_every_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, scene, master = _fixture(tmp_path)
    before = {
        ref.artifact_uri: registry.runtime_resolver.require(ref).read_bytes()
        for ref in [scene.environment.membership.source_visual_ref, scene.environment.membership.labels_ref]
    }
    assert not representation_issues(scene, registry.runtime_resolver.require)
    assert export_requirements(scene).hybrid_visuals
    request = _request(registry, scene, tmp_path, monkeypatch)
    assert not request["objects"]
    assert len(request["environment"]["extra_gaussians"]) == 60
    reconstructed = []
    for extra in request["environment"]["extra_gaussians"]:
        rows = read_gaussian_ply(Path(extra["ply"]).read_bytes()).copy()
        for axis, offset in zip(("x", "y", "z"), extra["translation"], strict=True):
            rows[axis] += offset
        reconstructed.append(rows)
    reconstructed.append(read_gaussian_ply(Path(request["environment"]["gaussians_ply"]).read_bytes()))
    assert np.array_equal(np.concatenate(reconstructed), master)
    for uri, payload in before.items():
        ref = next(
            ref
            for ref in [scene.environment.membership.source_visual_ref, scene.environment.membership.labels_ref]
            if ref.artifact_uri == uri
        )
        assert registry.runtime_resolver.require(ref).read_bytes() == payload


def test_move_then_ignore_retains_extraction_pose_and_delete_omits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, scene, _ = _fixture(tmp_path, 1)
    item = scene.objects[0]
    moved = item.model_copy(update={"transform": item.transform.model_copy(update={"translation_xyz": (9, 8, 7)})})
    ignored = ignore_object(scene.model_copy(update={"objects": [moved]}), item.id)
    request = _request(registry, ignored, tmp_path, monkeypatch)
    assert request["environment"]["extra_gaussians"][0]["translation"] == [0, 0, 0]
    assert not request["objects"]
    deleted = delete_object(ignored, item.id)
    assert not export_requirements(deleted).dynamic_physics
    from src.services.scene.representation_composition import scene_representations

    assert scene_representations(deleted)[0].visual_policy == "omit"
    assert scene_representations(restore_object(deleted, item.id))[0].visual_policy == "source"
    confirmed = confirm_object(scene, item.id)
    assert scene_representations(confirmed)[0].visual_policy == "object"
    assert (
        scene_representations(restore_object(delete_object(confirmed, item.id), item.id))[0].visual_policy == "object"
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "checksum",
        "pose",
        "rotation",
        "membership",
        "rows",
        "empty_claim",
        "labels_checksum",
        "attribute",
        "context",
        "stale_revision",
        "background",
        "background_checksum",
        "background_missing",
    ],
)
def test_bad_source_evidence_blocks_preflight_and_capability(tmp_path: Path, damage: str) -> None:
    registry, scene, _ = _fixture(tmp_path, 1)
    item = scene.objects[0]
    if damage == "missing":
        item = item.model_copy(update={"visual_ref": None})
    elif damage == "checksum":
        registry.runtime_resolver.require(item.visual_ref).write_bytes(b"tampered")
    elif damage == "pose":
        item = item.model_copy(update={"source_collision": None})
    elif damage == "rotation":
        item = item.model_copy(
            update={
                "source_collision": item.source_collision.model_copy(
                    update={
                        "source_transform": item.source_collision.source_transform.model_copy(
                            update={"rotation_quaternion_xyzw": (0, 0, 1, 0)}
                        )
                    }
                )
            }
        )
    elif damage == "membership":
        scene = scene.model_copy(update={"environment": scene.environment.model_copy(update={"membership": None})})
    elif damage == "rows":
        item = item.model_copy(
            update={
                "source_collision": item.source_collision.model_copy(
                    update={
                        "source_transform": item.source_collision.source_transform.model_copy(
                            update={"translation_xyz": (1, 0, 0)}
                        )
                    }
                )
            }
        )
    elif damage == "background_missing":
        scene = scene.model_copy(
            update={"environment": scene.environment.model_copy(update={"visual_master_ref": None})}
        )
    elif damage == "background_checksum":
        registry.runtime_resolver.require(scene.environment.visual_master_ref).write_bytes(b"bad background")
    elif damage == "background":
        scene = scene.model_copy(
            update={
                "environment": scene.environment.model_copy(
                    update={"visual_master_ref": scene.environment.membership.source_visual_ref}
                )
            }
        )
    elif damage == "labels_checksum":
        registry.runtime_resolver.require(scene.environment.membership.labels_ref).write_bytes(b"bad")
    elif damage == "attribute":
        rows = read_gaussian_ply(registry.runtime_resolver.require(item.visual_ref).read_bytes()).copy()
        rows["opacity"] += 1
        payload = write_gaussian_ply(rows)
        ref = item.visual_ref.model_copy(
            update={
                "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "artifact_uri": item.visual_ref.artifact_uri.replace(".ply", "-changed.ply"),
            }
        )
        registry.scene.store.publish(ref, payload)
        item = item.model_copy(update={"visual_ref": ref})
    elif damage == "context":
        item = item.model_copy(
            update={
                "source_collision": item.source_collision.model_copy(
                    update={
                        "source_geometry_ref": item.source_collision.source_geometry_ref.model_copy(
                            update={"artifact_checksum": "sha256:" + "f" * 64}
                        )
                    }
                )
            }
        )
    elif damage == "stale_revision":
        item = item.model_copy(
            update={"source_collision": item.source_collision.model_copy(update={"extraction_revision": "rev-stale"})}
        )
    else:
        item = item.model_copy(
            update={"visual_ref": None, "provenance": {"membership_reassign_blocker": "NO_SOURCE_GAUSSIANS"}}
        )
    scene = scene.model_copy(update={"objects": [item]})
    issues = representation_issues(scene, registry.runtime_resolver.require)
    assert issues
    preflight = run_preflight(scene, artifact_resolver=registry.runtime_resolver.require)
    assert preflight.blocking_result != "PASS"
    assert next(rule for rule in preflight.rules if rule.rule_id == "REPRESENTATION_INCOMPLETE").result == "FAIL"
    capability = assess_export_capabilities(
        scene, runtime_qualified=True, runtime_version="fixture", resolve_artifact=registry.runtime_resolver.require
    )
    assert capability.status == "blocked"
    assert any(issue.code.startswith("SOURCE_") for issue in capability.blockers)


@pytest.mark.skipif(not Path("data/scene_runtime/bin/python").is_file(), reason="USD runtime unavailable")
def test_actual_usd_runner_keeps_sixty_source_candidates(tmp_path: Path) -> None:
    registry, scene, master = _fixture(tmp_path)
    output = tmp_path / "actual-usd"
    output.mkdir()
    background = simulation_package._carved_environment(registry, scene)
    files = simulation_package._hybrid_layers(
        registry, scene, output, background, Path("data/scene_runtime/bin/python")
    )
    summary = json.loads(files["usd_export_summary.json"])
    assert summary["environment_gaussians"] == 61
    assert summary["objects"] == []
    # Read the generated ParticleField using the same real pxr runtime, outside pytest's CPU venv.
    import subprocess

    result = subprocess.run(
        [
            str(Path("data/scene_runtime/bin/python")),
            "-c",
            "import json,sys; from pxr import Usd,UsdVol; "
            "s=Usd.Stage.Open(sys.argv[1]); p=UsdVol.ParticleField3DGaussianSplat(s.GetPrimAtPath('/Root/Visual')); "
            "print(json.dumps({'positions':[list(v) for v in p.GetPositionsAttr().Get()], "
            "'count':len(p.GetOpacitiesAttr().Get()), 'degree':p.GetRadianceSphericalHarmonicsDegreeAttr().Get()}))",
            str(output / "hybrid/environment.usdc"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    actual = json.loads(result.stdout)
    # Background precedes source extras; compare by x rather than changing producer row order.
    expected = positions(master)
    actual_positions = np.asarray(actual["positions"])
    assert np.allclose(actual_positions[np.argsort(actual_positions[:, 0])], expected)
    assert actual["count"] == 61 and actual["degree"] == 1


def test_merged_membership_emits_primary_source_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, scene, master = _fixture(tmp_path, 2)
    primary, secondary = scene.objects
    payload = write_gaussian_ply(master[:2])  # Primary source origin is zero; world-aligned axes.
    visual = primary.visual_ref.model_copy(
        update={
            "artifact_uri": primary.visual_ref.artifact_uri.replace(".ply", "-merged.ply"),
            "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
    )
    registry.scene.store.publish(visual, payload)
    primary = primary.model_copy(update={"visual_ref": visual})
    secondary = secondary.model_copy(
        update={"visual_ref": None, "provenance": {"review": "MERGED", "merged_into": primary.id}}
    )
    membership = scene.environment.membership.model_copy(
        update={"label_to_object_id": {"0": primary.id, "1": primary.id}}
    )
    scene = scene.model_copy(
        update={
            "objects": [primary, secondary],
            "environment": scene.environment.model_copy(update={"membership": membership}),
        }
    )
    assert not representation_issues(scene, registry.runtime_resolver.require)
    request = _request(registry, scene, tmp_path, monkeypatch)
    assert len(request["environment"]["extra_gaussians"]) == 1
    assert not request["objects"]
    rows = read_gaussian_ply(Path(request["environment"]["extra_gaussians"][0]["ply"]).read_bytes())
    assert np.array_equal(rows, master[:2])


def test_verified_empty_membership_does_not_emit_phantom_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, scene, master = _fixture(tmp_path, 1)
    membership = scene.environment.membership
    payload = np.asarray([-1, -1], dtype="<i4").tobytes()
    labels = membership.labels_ref.model_copy(
        update={
            "artifact_uri": membership.labels_ref.artifact_uri.replace(".bin", "-empty.bin"),
            "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
    )
    registry.scene.store.publish(labels, payload)
    background_payload = write_gaussian_ply(master)
    background = scene.environment.visual_master_ref.model_copy(
        update={
            "artifact_uri": scene.environment.visual_master_ref.artifact_uri.replace(".ply", "-empty.ply"),
            "artifact_checksum": "sha256:" + hashlib.sha256(background_payload).hexdigest(),
        }
    )
    registry.scene.store.publish(background, background_payload)
    item = scene.objects[0].model_copy(
        update={"visual_ref": None, "provenance": {"membership_reassign_blocker": "NO_SOURCE_GAUSSIANS"}}
    )
    scene = scene.model_copy(
        update={
            "objects": [item],
            "environment": scene.environment.model_copy(
                update={
                    "membership": membership.model_copy(update={"labels_ref": labels}),
                    "visual_master_ref": background,
                }
            ),
        }
    )
    assert not representation_issues(scene, registry.runtime_resolver.require)
    request = _request(registry, scene, tmp_path, monkeypatch)
    assert not request["objects"] and not request["environment"]["extra_gaussians"]
