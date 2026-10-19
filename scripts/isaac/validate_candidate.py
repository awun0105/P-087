"""Run one immutable candidate through an isolated headless Isaac Sim process.

This script deliberately has no project imports: Isaac Sim runs from its own
Python environment, while the host validates this JSON protocol and all artifact
checksums before launch.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_SAMPLES_PER_PATH = 10_000
_CHECK_ALIASES = {
    "ISAAC_LOAD": "scene_load",
    "ISAAC_LOAD_ERROR": "scene_load",
    "scene_load": "scene_load",
    "COLLISION_SCENE_LOAD": "collision_scene_load",
    "collision_scene_load": "collision_scene_load",
    "ROBOT_SPAWN": "robot_spawn",
    "ROBOT_SPAWN_INVALID": "robot_spawn",
    "robot_spawn": "robot_spawn",
    "METRIC_SCALE": "metric_scale",
    "metric_scale": "metric_scale",
    "UP_AXIS": "up_axis",
    "up_axis": "up_axis",
    "COLLISION": "collision",
    "collision": "collision",
    "PENETRATION": "penetration",
    "PENETRATION_DEPTH": "penetration",
    "penetration": "penetration",
    "PATH_START_GOAL": "path_start_goal",
    "PATH_VALIDATION_ERROR": "path_start_goal",
    "path_start_goal": "path_start_goal",
    "REQUIRED_ROUTE_BLOCKED": "required_route_blocked",
}


def _record_check(checks: dict[str, tuple[str, str]], semantic_id: str, observation: tuple[str, str]) -> None:
    for check_id, mapped_id in _CHECK_ALIASES.items():
        if mapped_id == semantic_id:
            checks[check_id] = observation


def _read_request(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_REQUEST_BYTES:
        raise ValueError("request is missing, linked, or too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError("request schema is unsupported")
    required = {
        "run_id",
        "candidate_checksum",
        "config_checksum",
        "profile_checksum",
        "runtime_identity",
        "candidate_usd_path",
        "robot_asset_path",
        "required_check_ids",
        "warning_check_ids",
        "path_pairs",
        "robot_footprint_m",
        "spawn_position_xyz_m",
        "spawn_orientation_xyzw",
        "units",
        "up_axis",
        "physics_timestep_seconds",
        "collision_tolerance_m",
        "penetration_limit_m",
    }
    if set(value) != required | {"schema_version"}:
        raise ValueError("request fields differ from schema 1.0")
    for key in ("candidate_usd_path", "robot_asset_path"):
        artifact_path = Path(value[key])
        if not artifact_path.is_absolute() or artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError(f"{key} must be an existing absolute file")
    return value


def _path_points(start: list[float], goal: list[float], maximum_step_m: float) -> list[tuple[float, float, float]]:
    distance = math.dist(start, goal)
    steps = max(1, math.ceil(distance / maximum_step_m))
    if steps + 1 > _MAX_SAMPLES_PER_PATH:
        raise ValueError("configured path requires too many collision samples")
    return [
        tuple(start[axis] + (goal[axis] - start[axis]) * index / steps for axis in range(3))
        for index in range(steps + 1)
    ]


def _required_route_observation(
    path_pairs: list[dict[str, Any]], path_results: list[dict[str, Any]]
) -> tuple[str, str]:
    """Summarize configured required routes without treating optional routes as acceptance criteria."""
    required_ids = {pair["pair_id"] for pair in path_pairs if pair.get("required") is True}
    if not required_ids:
        return "ERROR", "REQUIRED_ROUTE_BLOCKED is configured but no required route pairs exist"
    observed = {result["pair_id"]: result["result"] for result in path_results}
    required_results = [observed.get(pair_id) for pair_id in required_ids]
    if any(result is None or result == "ERROR" for result in required_results):
        return "ERROR", "One or more required route pairs could not be observed"
    if any(result == "BLOCKED" for result in required_results):
        return "FAIL", "At least one configured required route is blocked"
    if all(result == "CLEAR" for result in required_results):
        return "PASS", "All configured required routes were observed clear"
    return "ERROR", "Required route result is unsupported by the configured policy"


def _path_execution_observation(
    path_pairs: list[dict[str, Any]], path_errors: int, check_requested: bool
) -> tuple[str, str]:
    if check_requested and not path_pairs:
        return "ERROR", "Path validation is configured but contains no Start–Goal pairs"
    if path_errors:
        return "ERROR", "One or more configured path queries failed"
    return "PASS", "All configured path queries completed"


def _result(
    request: dict[str, Any],
    runtime_version: str,
    checks: dict[str, tuple[str, str]],
    path_results: list[dict[str, Any]],
    max_penetration_m: float | None,
) -> dict[str, Any]:
    expected_ids = sorted(set(request["required_check_ids"]) | set(request["warning_check_ids"]))
    observations = []
    for check_id in expected_ids:
        mapped = checks.get(check_id)
        if mapped is None:
            message = (
                "Configured check could not be observed in this execution"
                if check_id in _CHECK_ALIASES
                else ("Isaac runner does not implement this configured check ID")
            )
            mapped = ("ERROR", message)
        observations.append({"check_id": check_id, "result": mapped[0], "message": mapped[1]})
    return {
        "schema_version": "1.0",
        "run_id": request["run_id"],
        "candidate_checksum": request["candidate_checksum"],
        "config_checksum": request["config_checksum"],
        "profile_checksum": request["profile_checksum"],
        "runtime_identity": request["runtime_identity"],
        "runtime_versions": {"isaac_sim": runtime_version},
        "checks": observations,
        "path_results": path_results,
        "max_penetration_m": max_penetration_m,
    }


def _error_result(request: dict[str, Any], runtime_version: str, message: str) -> dict[str, Any]:
    checks = {
        check_id: ("ERROR", message) for check_id in (*request["required_check_ids"], *request["warning_check_ids"])
    }
    paths = [
        {
            "pair_id": pair["pair_id"],
            "result": "ERROR",
            "message": message,
            "sample_count": 0,
            "collision_prim_paths": [],
        }
        for pair in request["path_pairs"]
    ]
    return _result(request, runtime_version, checks, paths, None)


def _version_string() -> str:
    from isaacsim.core.version import get_version

    version = get_version()
    return ".".join(version[index] for index in (2, 3, 4))


def _evaluate(request: dict[str, Any], simulation_app: Any, runtime_version: str) -> dict[str, Any]:
    import carb
    import omni.timeline
    import omni.usd
    from omni.physx import get_physx_scene_query_interface
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    checks: dict[str, tuple[str, str]] = {}
    path_results: list[dict[str, Any]] = []
    candidate_path = Path(request["candidate_usd_path"])
    if not omni.usd.get_context().open_stage(str(candidate_path)):
        return _error_result(request, runtime_version, "Isaac Sim could not open the candidate USD")
    simulation_app.update()
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return _error_result(request, runtime_version, "Isaac Sim opened no USD stage")
    if stage.GetCompositionErrors():
        return _error_result(request, runtime_version, "Candidate USD has unresolved composition dependencies")
    physics_scenes = [UsdPhysics.Scene(prim) for prim in stage.Traverse() if prim.IsA(UsdPhysics.Scene)]
    if not stage.GetDefaultPrim() or not physics_scenes:
        return _error_result(request, runtime_version, "Candidate stage requires a default prim and PhysicsScene")

    for source_id, semantic_id in _CHECK_ALIASES.items():
        if semantic_id == "scene_load":
            checks[source_id] = ("PASS", "Candidate USD loaded in the isolated Isaac Sim process")
        elif semantic_id == "collision_scene_load":
            checks[source_id] = ("PASS", "Candidate contains a USD PhysicsScene")
    meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
    up_axis = str(UsdGeom.GetStageUpAxis(stage))
    for source_id, semantic_id in _CHECK_ALIASES.items():
        if semantic_id == "metric_scale":
            passed = math.isclose(meters_per_unit, 1.0, rel_tol=0.0, abs_tol=1e-9)
            checks[source_id] = ("PASS" if passed else "FAIL", f"metersPerUnit={meters_per_unit}; expected 1.0")
        elif semantic_id == "up_axis":
            passed = up_axis == request["up_axis"]
            checks[source_id] = ("PASS" if passed else "FAIL", f"upAxis={up_axis}; expected {request['up_axis']}")

    timestep = float(request["physics_timestep_seconds"])
    if not math.isfinite(timestep) or timestep <= 0:
        return _error_result(request, runtime_version, "Physics timestep is invalid")
    physics_scenes[0].CreateTimeStepsPerSecondAttr().Set(1.0 / timestep)

    robot_prim_path = "/World/ValidationRobot"
    robot_path = Path(request["robot_asset_path"])
    try:
        if stage.GetPrimAtPath(robot_prim_path).IsValid():
            raise RuntimeError("candidate already defines the reserved validation robot path")
        robot_prim = stage.DefinePrim(robot_prim_path, "Xform")
        if not robot_prim.GetReferences().AddReference(str(robot_path)):
            raise RuntimeError("robot USD reference could not be added")
        xform = UsdGeom.Xformable(robot_prim)
        xform.AddTranslateOp().Set(Gf.Vec3d(*request["spawn_position_xyz_m"]))
        orientation = request["spawn_orientation_xyzw"]
        xform.AddOrientOp().Set(Gf.Quatd(orientation[3], Gf.Vec3d(*orientation[:3])))
        simulation_app.update()
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )
        bounds = bbox_cache.ComputeWorldBound(robot_prim).ComputeAlignedRange()
        robot_dimensions = bounds.GetSize()
        if any(not math.isfinite(float(value)) or float(value) <= 0 for value in robot_dimensions):
            raise RuntimeError("robot asset has no finite 3D bounds after spawn")
        center_offset = bounds.GetMidpoint() - Gf.Vec3d(*request["spawn_position_xyz_m"])
        _record_check(checks, "robot_spawn", ("PASS", "Configured robot USD resolved and has finite spawned bounds"))
    except (RuntimeError, ValueError, TypeError) as error:
        _record_check(checks, "robot_spawn", ("ERROR", f"Robot spawn observation failed: {type(error).__name__}"))
        return _result(
            request,
            runtime_version,
            checks,
            [
                {
                    "pair_id": pair["pair_id"],
                    "result": "ERROR",
                    "message": "Robot spawn failed; path query was not attempted",
                    "sample_count": 0,
                    "collision_prim_paths": [],
                }
                for pair in request["path_pairs"]
            ],
            None,
        )

    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(3):
        simulation_app.update()
    query = get_physx_scene_query_interface()
    footprint = request["robot_footprint_m"]
    tolerance = float(request["collision_tolerance_m"])
    half_extent = carb.Float3(
        footprint[0] / 2.0 + tolerance,
        footprint[1] / 2.0 + tolerance,
        float(robot_dimensions[2]) / 2.0,
    )
    orientation = carb.Float4(*request["spawn_orientation_xyzw"])

    def overlaps(position: tuple[float, float, float]) -> list[str]:
        center = Gf.Vec3d(*position) + center_offset
        paths: set[str] = set()

        def collect(hit: Any) -> bool:
            collider_path = getattr(hit, "collision", None) or getattr(hit, "rigid_body", None)
            if collider_path is not None:
                path = str(collider_path)
                if not path.startswith(robot_prim_path):
                    paths.add(path)
            return True

        query.overlap_box(
            half_extent,
            carb.Float3(float(center[0]), float(center[1]), float(center[2])),
            orientation,
            collect,
            False,
        )
        return sorted(paths)

    spawn_colliders = overlaps(tuple(request["spawn_position_xyz_m"]))
    _record_check(
        checks,
        "collision",
        (
            "FAIL" if spawn_colliders else "PASS",
            "Spawn footprint intersects candidate colliders"
            if spawn_colliders
            else "No spawn-footprint overlap observed",
        ),
    )
    penetration_message = (
        "PhysX overlap queries expose collider intersections but not penetration depth; no depth was inferred"
    )
    _record_check(checks, "penetration", ("ERROR", penetration_message))

    max_step = min(float(value) for value in footprint) / 4.0
    path_errors = 0
    for pair in request["path_pairs"]:
        try:
            points = _path_points(pair["start_xyz_m"], pair["goal_xyz_m"], max_step)
            path_colliders: set[str] = set()
            for point in points:
                path_colliders.update(overlaps(point))
            result = "BLOCKED" if path_colliders else "CLEAR"
            path_results.append(
                {
                    "pair_id": pair["pair_id"],
                    "result": result,
                    "message": "Straight-line footprint sweep using fixed configured orientation",
                    "sample_count": len(points),
                    "collision_prim_paths": sorted(path_colliders),
                }
            )
        except (RuntimeError, ValueError, TypeError) as error:
            path_errors += 1
            path_results.append(
                {
                    "pair_id": pair["pair_id"],
                    "result": "ERROR",
                    "message": f"Path query failed: {type(error).__name__}",
                    "sample_count": 0,
                    "collision_prim_paths": [],
                }
            )
    required_route = _required_route_observation(request["path_pairs"], path_results)
    _record_check(checks, "required_route_blocked", required_route)
    path_check_requested = any(
        _CHECK_ALIASES.get(check_id) == "path_start_goal"
        for check_id in (*request["required_check_ids"], *request["warning_check_ids"])
    )
    _record_check(
        checks,
        "path_start_goal",
        _path_execution_observation(request["path_pairs"], path_errors, path_check_requested),
    )
    timeline.stop()
    return _result(request, runtime_version, checks, path_results, None)


def _write_result(path: Path, result: dict[str, Any]) -> None:
    if path.is_symlink() or path.exists():
        raise ValueError("result path must not already exist or be a symbolic link")
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ValueError("result exceeds the size limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = _read_request(args.request)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"invalid Isaac validation request: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 2

    simulation_app = None
    runtime_version: str | None = None
    try:
        from isaacsim import SimulationApp

        simulation_app = SimulationApp({"headless": True, "disable_viewport_updates": True})
        runtime_version = _version_string()
        try:
            result = _evaluate(request, simulation_app, runtime_version)
        except Exception as error:  # Isaac/Kit extensions raise runtime-specific exception types.
            print(f"Isaac validation execution failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            result = _error_result(request, runtime_version, f"Isaac execution failed: {type(error).__name__}")
        _write_result(args.output, result)
        return 0
    except Exception as error:  # Startup/version/protocol failures are operational failures, never PASS.
        print(f"Isaac validation process failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        if simulation_app is not None:
            simulation_app.close()


if __name__ == "__main__":
    raise SystemExit(main())
